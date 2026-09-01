import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException
from pydantic import ValidationError

from database.models import Bot
from routes.public_routes import get_public_bot_or_404
from schemas.schemas import BotCreate, BotResponse, BotUpdate
from services.bot_service import create_bot, get_bot, update_bot
from services.bot_secret_service import decrypt_bot_provider_key, is_encrypted_bot_key


class _Query:
    def __init__(self, db):
        self.db = db

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.bot


class _MemoryDB:
    """Small deterministic service-boundary store; this is not a live database."""

    def __init__(self):
        self.bot = None

    def add(self, value):
        if isinstance(value, Bot):
            self.bot = value

    def query(self, model):
        return _Query(self)

    def flush(self):
        if self.bot and self.bot.id is None:
            self.bot.id = 91001
            self.bot.created_at = datetime(2026, 8, 20, 12, 0, 0)

    def commit(self):
        return None

    def refresh(self, value):
        return None


def _widget(**overrides):
    return {
        "welcome_message": "Welcome from widget",
        "primary_color": "#112233",
        "accent_color": "#445566",
        "launcher_text": "Ask us",
        "launcher_icon": "support",
        "position": "bottom-left",
        "placeholder_text": "Ask a question...",
        **overrides,
    }


def _create_payload(**overrides):
    values = {
        "organization_id": 81001,
        "name": "Complete contract bot",
        "description": "Original description",
        "category": "sales",
        "avatar_url": "https://example.test/original.png",
        "status": "draft",
        "provider": "claude",
        "model_name": "claude-3-5-sonnet",
        "provider_api_key": "sk-phase-b-original-secret",
        "system_prompt": "Use the approved business instructions.",
        "tone": "professional",
        "capabilities": {"web_search": True, "file_analysis": True, "temperature": 0.4},
        "welcome_message": "Welcome from bot",
        "widget_config": _widget(),
    }
    values.update(overrides)
    return BotCreate(**values)


class TestPhaseBBotContract(unittest.TestCase):
    def setUp(self):
        self.db = _MemoryDB()
        self.user = SimpleNamespace(id=71001, customer_id=61001, memberships=[])
        self.service_patches = (
            patch("services.bot_service.require_org_role"),
            patch("services.bot_service.ensure_can_create_bot"),
            patch("services.bot_service.refresh_resource_usage"),
            patch("services.bot_service.allocate_key_to_bot"),
            patch("services.bot_service.release_key_from_bot"),
        )
        for service_patch in self.service_patches:
            service_patch.start()

    def tearDown(self):
        for service_patch in reversed(self.service_patches):
            service_patch.stop()

    def test_a_b_create_and_fetch_round_trip_every_supported_field(self):
        created = create_bot(self.db, _create_payload(), user=self.user)
        fetched = get_bot(self.db, created["id"], user=self.user)

        for field in (
            "name", "description", "category", "avatar_url", "status", "provider",
            "model_name", "system_prompt", "tone", "capabilities", "welcome_message",
            "widget_config", "organization_id",
        ):
            self.assertEqual(fetched[field], created[field], field)
        self.assertEqual(fetched["ai_usage_mode"], "byo")
        self.assertIn("****", fetched["provider_api_key_masked"])
        self.assertNotIn("provider_api_key", fetched)
        response = BotResponse.model_validate(fetched).model_dump()
        self.assertNotIn("provider_api_key", response)

    def test_c_through_j_update_fetch_round_trip_every_editable_field(self):
        created = create_bot(self.db, _create_payload(), user=self.user)
        update_bot(
            self.db,
            created["id"],
            BotUpdate(
                name="Updated contract bot",
                description="Updated description",
                category="marketing",
                avatar_url="https://example.test/updated.png",
                status="active",
                provider="grok",
                model_name="grok-2",
                provider_api_key="sk-phase-b-updated-secret",
                system_prompt="Updated business instructions.",
                tone="empathetic",
                capabilities={"web_search": False, "file_analysis": True, "temperature": 0.9},
                welcome_message="Updated welcome",
                widget_config=_widget(
                    primary_color="#abcdef",
                    launcher_text="Talk now",
                    position="bottom-right",
                ),
            ),
            user=self.user,
        )
        fetched = get_bot(self.db, created["id"], user=self.user)

        self.assertEqual(fetched["name"], "Updated contract bot")
        self.assertEqual(fetched["description"], "Updated description")
        self.assertEqual(fetched["category"], "marketing")
        self.assertEqual(fetched["avatar_url"], "https://example.test/updated.png")
        self.assertEqual(fetched["status"], "active")
        self.assertEqual((fetched["provider"], fetched["model_name"]), ("grok", "grok-2"))
        self.assertEqual(fetched["system_prompt"], "Updated business instructions.")
        self.assertEqual(fetched["tone"], "empathetic")
        self.assertEqual(fetched["capabilities"]["temperature"], 0.9)
        self.assertEqual(fetched["welcome_message"], "Updated welcome")
        self.assertEqual(fetched["widget_config"]["primary_color"], "#abcdef")
        self.assertEqual(fetched["widget_config"]["position"], "bottom-right")

    def test_k_l_explicit_byok_clear_and_omitted_key_semantics(self):
        created = create_bot(self.db, _create_payload(), user=self.user)
        update_bot(self.db, created["id"], BotUpdate(name="Key unchanged"), user=self.user)
        self.assertTrue(is_encrypted_bot_key(self.db.bot.provider_api_key))
        self.assertEqual(
            decrypt_bot_provider_key(self.db.bot.provider_api_key, allow_legacy=False),
            "sk-phase-b-original-secret",
        )

        cleared = update_bot(self.db, created["id"], BotUpdate(provider_api_key=None), user=self.user)
        self.assertIsNone(self.db.bot.provider_api_key)
        self.assertIsNone(cleared["provider_api_key_masked"])
        self.assertEqual(cleared["ai_usage_mode"], "platform")

    def test_n_invalid_contract_values_are_rejected_before_service_work(self):
        with self.assertRaises(ValidationError):
            BotCreate(name="Missing organization")
        with self.assertRaises(ValidationError):
            _create_payload(status="inactive")
        with self.assertRaises(ValidationError):
            _create_payload(widget_config=_widget(position="top-right"))
        with self.assertRaises(ValidationError):
            _create_payload(widget_config=_widget(primary_color="blue"))
        with self.assertRaises(ValidationError):
            BotUpdate(status=None)

    def test_provider_model_pair_is_rejected_actionably(self):
        with self.assertRaises(HTTPException) as context:
            create_bot(self.db, _create_payload(provider="claude", model_name="gpt-4.1-mini"), user=self.user)
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("Unsupported model", context.exception.detail)

    def test_o_status_round_trip_matches_public_access_enforcement(self):
        created = create_bot(self.db, _create_payload(status="draft"), user=self.user)
        with self.assertRaises(HTTPException) as draft_context:
            get_public_bot_or_404(self.db, created["id"])
        self.assertEqual(draft_context.exception.status_code, 404)

        update_bot(self.db, created["id"], BotUpdate(status="active"), user=self.user)
        self.assertIs(get_public_bot_or_404(self.db, created["id"]), self.db.bot)

        update_bot(self.db, created["id"], BotUpdate(status="disabled"), user=self.user)
        with self.assertRaises(HTTPException) as disabled_context:
            get_public_bot_or_404(self.db, created["id"])
        self.assertEqual(disabled_context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
