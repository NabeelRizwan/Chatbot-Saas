"""Phase L.4 — approved-answer delivery must not add artificial latency."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routes import public_routes
from schemas.schemas import PublicChatRequest
from services.rag_service import APPROVED_ANSWER_SSE_CHUNK_CHARS, iter_approved_answer_chunks, stream_answer_question


class _DB:
    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def close(self):
        return None


def _bot(origins=None):
    return SimpleNamespace(
        id=91,
        organization_id=44,
        name="Latency Bot",
        status="active",
        allowed_origins=origins or ["http://127.0.0.1:4173"],
        provider="gemini",
        model_name="gemini-2.5-flash",
        capabilities={},
        system_prompt=None,
        tone="neutral",
    )


async def _body(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _events(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        line = next((ln for ln in block.split("\n") if ln.startswith("data: ")), None)
        if not line:
            continue
        events.append(json.loads(line[6:]))
    return events


class ApprovedAnswerDeliveryTests(unittest.TestCase):
    def test_a_approved_answer_chunking_has_no_tiny_pacing(self):
        reply = "A" * 5000
        chunks = iter_approved_answer_chunks(reply)
        self.assertEqual("".join(chunks), reply)
        self.assertLessEqual(len(chunks), 2)
        self.assertGreaterEqual(APPROVED_ANSWER_SSE_CHUNK_CHARS, 1024)
        self.assertTrue(all(len(chunk) >= 1024 or chunk == reply[-len(chunk):] for chunk in chunks))

    def test_b_stream_answer_buffers_quality_pipeline_then_emits_approved_text(self):
        bot = _bot()
        with patch(
            "services.rag_service.answer_question",
            return_value=("Approved final answer " + ("x" * 100), [{"title": "Docs"}], []),
        ) as canonical, patch("services.llm_router.generate_stream") as direct_stream:
            result = list(
                stream_answer_question(
                    db=_DB(), bot=bot, question="Question", history=[], include_metadata=True
                )
            )
        canonical.assert_called_once()
        direct_stream.assert_not_called()
        self.assertEqual(result[0]["reply"][:22], "Approved final answer ")

    def test_c_public_stream_emits_large_chunks_without_sleep(self):
        bot = _bot()
        long_answer = ("Approved multi-entity answer. " * 80).strip()
        with patch("routes.public_routes.get_public_bot_or_404", return_value=bot), patch(
            "routes.public_routes._enforce_public_turn_access", return_value="usage-key"
        ), patch("routes.public_routes._existing_public_turn", return_value=None), patch(
            "routes.public_routes.stream_answer_question",
            return_value=iter(
                [
                    {
                        "reply": long_answer,
                        "sources": [
                            {
                                "title": "Product A",
                                "source_url": "https://example.com/a",
                                "cta_links": [{"label": "Product A", "url": "https://example.com/a"}],
                            },
                            {
                                "title": "Product B",
                                "source_url": "https://example.com/b",
                                "cta_links": [{"label": "Product B", "url": "https://example.com/b"}],
                            },
                        ],
                        "retrieved_chunks": [],
                    }
                ]
            ),
        ), patch("routes.public_routes.track_widget_chat_message") as persist, patch(
            "routes.public_routes.track_chat_completion"
        ), patch("routes.public_routes.heartbeat_message_quota"):
            started = time.perf_counter()
            response = public_routes.public_chat_stream(
                PublicChatRequest(
                    session_id="s1",
                    session_token="token",
                    turn_id="t1",
                    message="Compare A and B",
                ),
                bot_id=bot.id,
                db=_DB(),
            )
            body = asyncio.run(_body(response))
            elapsed_ms = (time.perf_counter() - started) * 1000
        events = _events(body)
        types = [event.get("type") for event in events]
        token_events = [event for event in events if event.get("type") == "token"]
        self.assertIn("meta", types)
        self.assertIn("token", types)
        self.assertIn("sources", types)
        self.assertIn("done", types)
        self.assertLess(len(token_events), 20)
        self.assertEqual("".join(event["token"] for event in token_events), long_answer)
        self.assertLess(elapsed_ms, 250, msg=f"artificial delivery delay detected: {elapsed_ms:.1f}ms")
        persist.assert_called_once()
        # Persistence happens after delivery in the generator; call order is still once.

    def test_d_done_follows_approved_answer_promptly(self):
        bot = _bot()
        with patch("routes.public_routes.get_public_bot_or_404", return_value=bot), patch(
            "routes.public_routes._enforce_public_turn_access", return_value="usage-key"
        ), patch("routes.public_routes._existing_public_turn", return_value=None), patch(
            "routes.public_routes.stream_answer_question",
            return_value=iter([{"reply": "Short approved answer.", "sources": [], "retrieved_chunks": []}]),
        ), patch("routes.public_routes.track_widget_chat_message"), patch(
            "routes.public_routes.track_chat_completion"
        ):
            body = asyncio.run(
                _body(
                    public_routes.public_chat_stream(
                        PublicChatRequest(
                            session_id="s1",
                            session_token="token",
                            turn_id="t2",
                            message="Hello",
                        ),
                        bot_id=bot.id,
                        db=_DB(),
                    )
                )
            )
        events = _events(body)
        types = [event.get("type") for event in events]
        self.assertEqual(types[-1], "done")
        self.assertLess(types.index("done") - types.index("token"), 3)

    def test_e_sources_remain_on_successful_comparison_delivery(self):
        bot = _bot()
        sources = [
            {
                "title": "Product A",
                "source_url": "https://example.com/a",
                "cta_links": [{"label": "Product A", "url": "https://example.com/a"}],
            },
            {
                "title": "Product B",
                "source_url": "https://example.com/b",
                "cta_links": [{"label": "Product B", "url": "https://example.com/b"}],
            },
        ]
        with patch("routes.public_routes.get_public_bot_or_404", return_value=bot), patch(
            "routes.public_routes._enforce_public_turn_access", return_value="usage-key"
        ), patch("routes.public_routes._existing_public_turn", return_value=None), patch(
            "routes.public_routes.stream_answer_question",
            return_value=iter(
                [{"reply": "A is cheaper than B.", "sources": sources, "retrieved_chunks": []}]
            ),
        ), patch("routes.public_routes.track_widget_chat_message"), patch(
            "routes.public_routes.track_chat_completion"
        ):
            body = asyncio.run(
                _body(
                    public_routes.public_chat_stream(
                        PublicChatRequest(
                            session_id="s1",
                            session_token="token",
                            turn_id="t3",
                            message="Which one is cheaper?",
                        ),
                        bot_id=bot.id,
                        db=_DB(),
                    )
                )
            )
        events = _events(body)
        source_event = next(event for event in events if event.get("type") == "sources")
        labels = {
            (link.get("label") or source.get("title"))
            for source in source_event["sources"]
            for link in (source.get("cta_links") or [{}])
        }
        self.assertIn("Product A", labels)
        self.assertIn("Product B", labels)

    def test_f_no_raw_provider_stream_before_approval(self):
        bot = _bot()
        with patch(
            "services.rag_service.answer_question",
            return_value=("Approved only", [], []),
        ), patch("services.llm_router.generate_stream") as direct_stream:
            list(stream_answer_question(db=_DB(), bot=bot, question="Q", include_metadata=True))
        direct_stream.assert_not_called()

    def test_g_cache_hit_identity_helpers_unchanged(self):
        from services.query_contract import QueryContract

        left = QueryContract(
            original_query="which one is cheaper?",
            normalized_query="which one is cheaper",
            resolved_query="a and b which one is cheaper",
            intent="comparison",
            mode="comparison",
            comparison_entities=["A", "B"],
        )
        right = QueryContract(
            original_query="which one is cheaper?",
            normalized_query="which one is cheaper",
            resolved_query="c and d which one is cheaper",
            intent="comparison",
            mode="comparison",
            comparison_entities=["C", "D"],
        )
        self.assertNotEqual(left.cache_fragment(), right.cache_fragment())

    def test_h_stream_nonstream_chunk_helper_preserves_full_text(self):
        text = "One-time: $33.00\nSubscribe & Save: $31.35"
        self.assertEqual("".join(iter_approved_answer_chunks(text)), text)


if __name__ == "__main__":
    unittest.main()
