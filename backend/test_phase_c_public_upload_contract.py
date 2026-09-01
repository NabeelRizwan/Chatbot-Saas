import os
import sys
import unittest
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from database.models import ConversationMessage, ConversationSession
from routes.public_routes import get_shared_transcript
from services.document_processing_service import SUPPORTED_EXTENSIONS, validate_upload


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(b"phase-c"),
        headers=Headers({"content-type": content_type}),
    )


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.value

    def all(self):
        return self.value


class _DB:
    def __init__(self, session=None, messages=None):
        self.session = session
        self.messages = messages or []

    def query(self, model):
        if model is ConversationSession:
            return _Query(self.session)
        if model is ConversationMessage:
            return _Query(self.messages)
        raise AssertionError(f"Unexpected model query: {model}")


class TestPhaseCPublicUploadContract(unittest.TestCase):
    def test_backend_upload_allowlist_is_pdf_txt_docx_only(self):
        self.assertEqual(SUPPORTED_EXTENSIONS, {".pdf", ".txt", ".docx"})
        supported = (
            ("guide.pdf", "application/pdf"),
            ("notes.txt", "text/plain"),
            ("manual.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )
        for filename, content_type in supported:
            with self.subTest(filename=filename):
                self.assertEqual(validate_upload(_upload(filename, content_type)), filename)

    def test_backend_rejects_unadvertised_csv_xlsx_and_markdown(self):
        unsupported = (
            ("data.csv", "text/csv"),
            ("sheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("readme.md", "text/markdown"),
        )
        for filename, content_type in unsupported:
            with self.subTest(filename=filename):
                with self.assertRaises(HTTPException) as context:
                    validate_upload(_upload(filename, content_type))
                self.assertEqual(context.exception.status_code, 400)
                self.assertEqual(context.exception.detail, "Supported file types are PDF, TXT, and DOCX.")

    def test_valid_shared_transcript_returns_only_public_snapshot_fields(self):
        session = SimpleNamespace(
            id=10,
            session_id="private-session-id",
            organization_id=99,
            title="Shared support chat",
            created_at=datetime(2026, 8, 20, 12, 0, 0),
            bot=SimpleNamespace(id=20, name="Support bot", provider_api_key="never-return-this"),
        )
        message = SimpleNamespace(
            id=30,
            user_message="Question",
            assistant_response="Answer",
            created_at=datetime(2026, 8, 20, 12, 1, 0),
        )
        result = get_shared_transcript("valid-token", db=_DB(session, [message]))

        self.assertEqual(set(result), {"session", "messages"})
        self.assertEqual(set(result["session"]), {"title", "bot_name", "created_at"})
        self.assertEqual(
            set(result["messages"][0]),
            {"id", "user_message", "assistant_response", "created_at"},
        )
        serialized = repr(result)
        self.assertNotIn("private-session-id", serialized)
        self.assertNotIn("never-return-this", serialized)
        self.assertNotIn("organization_id", serialized)

    def test_invalid_or_unshared_token_fails_safely(self):
        with self.assertRaises(HTTPException) as context:
            get_shared_transcript("missing-token", db=_DB())
        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.detail, "Shared transcript not found")


if __name__ == "__main__":
    unittest.main()
