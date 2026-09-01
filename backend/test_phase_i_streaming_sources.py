import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from routes import chat_routes
from schemas.schemas import ChatRequest, PublicChatRequest


async def _response_body(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _stream_result():
    yield {
        "reply": "Grounded answer",
        "sources": [
            {
                "document_id": 4,
                "filename": "Launch guide",
                "source_url": "https://docs.example/launch",
                "chunk_refs": [2],
                "cta_links": [
                    {"label": "Start trial", "url": "https://docs.example/trial"}
                ],
            }
        ],
        "retrieved_chunks": [
            {
                "chunk_id": 8,
                "document_id": 4,
                "chunk_index": 2,
                "content": "Evidence",
                "token_count": 1,
                "score": 0.9,
                "source_filename": "Launch guide",
                "source_url": "https://docs.example/launch",
                "metadata": {},
            }
        ],
    }


class TestPhaseIStreamingSources(unittest.TestCase):
    def test_api_stream_emits_answer_sources_chunks_and_cta(self):
        bot = SimpleNamespace(id=91, organization_id=17)
        with patch("routes.chat_routes.get_owned_bot", return_value=(None, bot)), patch(
            "routes.chat_routes.ensure_can_send_message", return_value="reservation"
        ), patch("routes.chat_routes.consume_message_quota"), patch(
            "routes.chat_routes.stream_answer_question", side_effect=lambda **_: _stream_result()
        ), patch("routes.chat_routes.track_chat_completion"):
            response = chat_routes.chat_stream(
                ChatRequest(api_key="test", bot_id=91, message="Question"), db=SimpleNamespace()
            )
            body = asyncio.run(_response_body(response))

        payloads = [
            json.loads(line[6:])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(payloads[0]["token"], "Grounded answer")
        self.assertEqual(payloads[1]["sources"][0]["cta_links"][0]["label"], "Start trial")
        self.assertEqual(payloads[1]["retrieved_chunks"][0]["chunk_id"], 8)
        self.assertTrue(payloads[-1]["done"])

    def test_dashboard_stream_records_real_knowledge_hit(self):
        bot = SimpleNamespace(id=92, organization_id=18)
        user = SimpleNamespace(id=6)
        with patch("services.bot_service.get_bot_or_404", return_value=bot), patch(
            "routes.chat_routes.ensure_can_send_message", return_value="reservation"
        ), patch(
            "routes.chat_routes.stream_answer_question", side_effect=lambda **_: _stream_result()
        ), patch("routes.chat_routes.record_widget_chat_message") as record, patch(
            "routes.chat_routes.track_chat_completion"
        ):
            response = chat_routes.dashboard_playground_chat_stream(
                92, PublicChatRequest(message="Question"), current_user=user, db=SimpleNamespace()
            )
            body = asyncio.run(_response_body(response))

        self.assertIn('"retrieved_chunks"', body)
        self.assertIn('"cta_links"', body)
        self.assertTrue(record.call_args.kwargs["had_knowledge_hit"])
        self.assertTrue(record.call_args.kwargs["retrieval_attempted"] is False)


if __name__ == "__main__":
    unittest.main()
