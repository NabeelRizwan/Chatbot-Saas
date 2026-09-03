import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from database.models import Bot, Plan, PlatformApiKey
from routes import billing_routes, public_routes
from schemas.schemas import BotUpdate, PublicChatRequest
from services.bot_service import get_bot_or_404, update_bot


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.value[0] if isinstance(self.value, list) and self.value else self.value

    def all(self):
        if self.value is None:
            return []
        return self.value if isinstance(self.value, list) else [self.value]


class _DB:
    def __init__(self, values=None):
        self.values = values or {}

    def query(self, model):
        return _Query(self.values.get(model))

    def flush(self):
        return None

    def commit(self):
        return None

    def refresh(self, value):
        return None


def _bot(status="active"):
    return Bot(
        id=401,
        customer_id=501,
        organization_id=601,
        name="Phase A2 Bot",
        provider="gemini",
        model_name="gemini-2.5-flash",
        provider_api_key="private-test-key",
        status=status,
        welcome_message="Welcome",
        widget_config={"primary_color": "#123456"},
    )


class TestPhaseA2StopShipSecurity(unittest.TestCase):
    def test_a_active_bot_widget_config_works(self):
        bot = _bot("active")
        result = public_routes.get_widget_config(bot_id=bot.id, db=_DB({Bot: bot}))
        self.assertEqual(result["bot_id"], bot.id)
        self.assertEqual(result["primary_color"], "#123456")

    def test_b_active_bot_public_non_stream_chat_works(self):
        bot = _bot("active")
        request = PublicChatRequest(message="Hello")
        with patch("routes.public_routes.enforce_rate_limit") as limiter, patch(
            "routes.public_routes.ensure_can_send_message"
        ) as quota, patch(
            "routes.public_routes.answer_question", return_value=("Hello back", [], [])
        ), patch("routes.public_routes.track_chat_completion"):
            result = public_routes.public_chat(
                data=request,
                background_tasks=BackgroundTasks(),
                bot_id=bot.id,
                db=_DB({Bot: bot}),
            )
        self.assertEqual(result["reply"], "Hello back")
        limiter.assert_called_once()
        quota.assert_called_once_with(ANY, bot.organization_id)

    def test_c_active_bot_public_streaming_chat_works(self):
        bot = _bot("active")
        request = PublicChatRequest(message="Stream")
        with patch("routes.public_routes.ensure_can_send_message") as quota, patch(
            "routes.public_routes.stream_answer_question", return_value=iter(["Hello", " back"])
        ), patch("routes.public_routes.track_chat_completion"):
            response = public_routes.public_chat_stream(data=request, bot_id=bot.id, db=_DB({Bot: bot}))

            async def collect_body():
                chunks = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
                return "".join(chunks)

            body = asyncio.run(collect_body())
        self.assertIn('"token": "Hello"', body)
        self.assertIn('"done": true', body)
        quota.assert_called_once()

    def test_d_e_f_draft_bot_is_denied_by_every_public_bot_route(self):
        bot = _bot("draft")
        db = _DB({Bot: bot})
        request = PublicChatRequest(message="Blocked")

        calls = (
            lambda: public_routes.get_widget_config(bot_id=bot.id, db=db),
            lambda: public_routes.public_chat(
                data=request, background_tasks=BackgroundTasks(), bot_id=bot.id, db=db
            ),
            lambda: public_routes.public_chat_stream(data=request, bot_id=bot.id, db=db),
        )
        with patch("routes.public_routes.answer_question") as answer, patch(
            "routes.public_routes.stream_answer_question"
        ) as stream:
            for call in calls:
                with self.subTest(route=call):
                    with self.assertRaises(HTTPException) as ctx:
                        call()
                    self.assertEqual(ctx.exception.status_code, 404)
                    self.assertEqual(ctx.exception.detail, "Bot not found")
        answer.assert_not_called()
        stream.assert_not_called()

    def test_g_every_non_active_or_unknown_status_has_same_safe_denial(self):
        for status in ("disabled", "inactive", "archived", None):
            with self.subTest(status=status):
                bot = _bot(status)
                with self.assertRaises(HTTPException) as ctx:
                    public_routes.get_public_bot_or_404(_DB({Bot: bot}), bot.id)
                self.assertEqual(ctx.exception.status_code, 404)
                self.assertEqual(ctx.exception.detail, "Bot not found")

    def test_h_private_owner_can_read_and_edit_an_inactive_bot(self):
        bot = _bot("disabled")
        db = _DB({Bot: bot, PlatformApiKey: None})
        owner = SimpleNamespace(id=701)
        with patch("services.bot_service.require_org_role") as require_role, patch("services.bot_service.lock_credential_lifecycle"):
            self.assertIs(get_bot_or_404(db, bot.id, user=owner), bot)
            result = update_bot(db, bot.id, BotUpdate(name="Renamed privately"), user=owner)
        self.assertEqual(result["name"], "Renamed privately")
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(require_role.call_count, 2)

    def test_unsigned_webhook_is_disabled_and_does_not_reflect_payload(self):
        app = FastAPI()
        app.include_router(billing_routes.router, prefix="/billing")
        client = TestClient(app)
        marker = "arbitrary-secret-payment-payload"

        response = client.post(
            "/billing/webhooks/fake-provider",
            json={"event": "subscription.active", "secret": marker},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Billing webhook is not configured"})
        self.assertNotIn(marker, response.text)
        self.assertNotIn("subscription.active", response.text)

    def test_plan_and_usage_reads_remain_available_without_checkout(self):
        plan = SimpleNamespace(
            code="free", name="Free", monthly_price_cents=0, limits_json={"max_bots": 2}
        )
        with patch("routes.billing_routes.ensure_default_plans"), patch(
            "routes.billing_routes.require_org_role"
        ) as require_role, patch(
            "routes.billing_routes.serialize_subscription",
            return_value={"organization_id": 601, "status": "active", "plan": {"code": "free"}},
        ), patch(
            "routes.billing_routes.get_usage_summary",
            return_value={"organization_id": 601, "usage": {}, "limits": {}},
        ):
            require_role.return_value = SimpleNamespace(organization=SimpleNamespace(id=601))
            plans = billing_routes.plans(db=_DB({Plan: [plan]}))
            subscription = billing_routes.subscription(601, current_user=SimpleNamespace(id=701), db=_DB())
            usage = billing_routes.usage(601, current_user=SimpleNamespace(id=701), db=_DB())

        self.assertEqual(plans[0]["code"], "free")
        self.assertEqual(subscription["status"], "active")
        self.assertEqual(usage["subscription_status"], "active")
        route_paths = {route.path for route in billing_routes.router.routes}
        self.assertFalse(any("checkout" in path for path in route_paths))


if __name__ == "__main__":
    unittest.main()
