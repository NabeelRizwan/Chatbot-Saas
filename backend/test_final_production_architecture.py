"""Deterministic tests for provider, crawler, storage, and embedding ports."""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.crawler_service import CrawlPage, FirecrawlCrawlerProvider, get_crawler_provider
from services.embedding_service import (
    EMBEDDING_DIMENSIONS,
    EmbeddingProfile,
    IncompatibleEmbeddingProfile,
    resolve_active_embedding_profile,
)
from services.firecrawl_service import CrawlAuditReport, Page
from services.llm_client import LLMErrorCode, classify_exception
from services.llm_router import LLMRouterError, generate, get_last_generation_metadata
from services.object_storage import (
    LocalObjectStorage,
    ObjectStorageError,
    build_source_object_key,
    get_object_storage,
    normalize_object_key,
    validate_source_object_ownership,
    validate_object_storage_config,
)
from services.providers.base_provider import (
    BaseProvider,
    GenerationResult,
    ProviderError,
    ProviderErrorKind,
    ProviderUsage,
)


class _FakeProvider(BaseProvider):
    capabilities = SimpleNamespace(streaming=True, usage_reporting=True)

    def __init__(self, name: str):
        self.provider_name = name

    def generate(self, api_key, model_name, prompt, system_instruction=None, temperature=0.2):
        return f"{self.provider_name}:{model_name}:{prompt}"

    def generate_with_metadata(self, api_key, model_name, prompt, system_instruction=None, temperature=0.2):
        return GenerationResult(
            text=self.generate(api_key, model_name, prompt, system_instruction, temperature),
            provider=self.provider_name,
            model=model_name,
            usage=ProviderUsage(input_tokens=3, output_tokens=2),
        )


class _RowsQuery:
    def __init__(self, rows):
        self.rows = rows

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def all(self):
        return self.rows


class _RowsDB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *args, **kwargs):
        return _RowsQuery(self.rows)


class ProductionProviderContractTests(unittest.TestCase):
    def _bot(self, provider: str, model: str, bot_id: int):
        return SimpleNamespace(
            id=bot_id,
            name=f"bot-{bot_id}",
            organization_id=bot_id * 10,
            provider=provider,
            model_name=model,
            provider_api_key=None,
            platform_credential_id=None,
            capabilities={"temperature": 0.2},
        )

    @contextmanager
    def _permit(self, *args, **kwargs):
        yield True

    def test_per_bot_generation_selection_does_not_leak_and_usage_is_not_estimated(self):
        bot_a = self._bot("provider-a", "model-a", 1)
        bot_b = self._bot("provider-b", "model-b", 2)
        providers = {"provider-a": _FakeProvider("provider-a"), "provider-b": _FakeProvider("provider-b")}
        with patch("services.llm_router.PROVIDERS", providers), patch(
            "services.llm_router._resolve_api_key", return_value=("secret", True)
        ), patch("services.llm_client.distributed_concurrency_guard", self._permit), patch(
            "services.llm_router._track_usage"
        ) as usage:
            self.assertEqual(generate(bot_a, "hello"), "provider-a:model-a:hello")
            self.assertEqual(generate(bot_b, "hello"), "provider-b:model-b:hello")

        self.assertEqual([call.args for call in usage.call_args_list], [(1, 5), (2, 5)])
        self.assertEqual(get_last_generation_metadata()["provider"], "provider-b")
        self.assertEqual(get_last_generation_metadata()["total_tokens"], 5)

    def test_environment_keys_cannot_bypass_managed_bot_capacity(self):
        from services import llm_router

        bot_a = self._bot("openai", "gpt-4.1-mini", 1)
        bot_b = self._bot("claude", "claude-3-5-sonnet", 2)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "platform-openai-test", "ANTHROPIC_API_KEY": ""}, clear=False), patch(
            "services.platform_key_service.get_decrypted_key_for_bot", return_value=None
        ):
            with self.assertRaises(LLMRouterError):
                llm_router._resolve_api_key(bot_a)
            with self.assertRaises(LLMRouterError):
                llm_router._resolve_api_key(bot_b)

    def test_byok_then_assigned_profile_precedence_without_environment_fallback(self):
        from services import llm_router

        byok_bot = self._bot("openai", "gpt-4.1-mini", 1)
        byok_bot.provider_api_key = "encrypted-byok"
        with patch("services.bot_secret_service.decrypt_bot_provider_key", return_value="byok-secret"), patch(
            "services.platform_key_service.get_decrypted_key_for_bot"
        ) as platform_lookup:
            self.assertEqual(llm_router._resolve_api_key(byok_bot), ("byok-secret", False))
            platform_lookup.assert_not_called()

        profile_bot = self._bot("openai", "gpt-4.1-mini", 2)
        fake_session = MagicMock()
        fake_session.__enter__.return_value = MagicMock()
        with patch("database.connection.SessionLocal", return_value=fake_session), patch(
            "services.platform_key_service.get_decrypted_key_for_bot",
            return_value="profile-secret",
        ), patch.dict(os.environ, {"OPENAI_API_KEY": "environment-secret"}, clear=False):
            self.assertEqual(llm_router._resolve_api_key(profile_bot), ("profile-secret", True))

    def test_provider_error_kinds_are_classified_without_string_guessing(self):
        cases = (
            (ProviderErrorKind.RATE_LIMIT, LLMErrorCode.LLM_RATE_LIMITED, True),
            (ProviderErrorKind.QUOTA_EXHAUSTED, LLMErrorCode.LLM_RATE_LIMITED, False),
            (ProviderErrorKind.AUTHENTICATION, LLMErrorCode.LLM_AUTH_ERROR, False),
            (ProviderErrorKind.BILLING_RESTRICTION, LLMErrorCode.LLM_AUTH_ERROR, False),
            (ProviderErrorKind.TIMEOUT, LLMErrorCode.LLM_TIMEOUT, True),
            (ProviderErrorKind.TEMPORARY, LLMErrorCode.LLM_PROVIDER_UNAVAILABLE, True),
            (ProviderErrorKind.INVALID_MODEL, LLMErrorCode.LLM_MODEL_UNAVAILABLE, False),
            (ProviderErrorKind.UNAVAILABLE, LLMErrorCode.LLM_PROVIDER_UNAVAILABLE, True),
        )
        for kind, expected_code, expected_retryable in cases:
            code, retryable, status, retry_after = classify_exception(
                ProviderError(
                    "safe classified failure",
                    status_code=429 if kind == ProviderErrorKind.RATE_LIMIT else 502,
                    kind=kind,
                    retry_after_seconds=2.0,
                )
            )
            self.assertEqual(code, expected_code)
            self.assertEqual(retryable, expected_retryable)
            self.assertGreaterEqual(status, 400)
            self.assertEqual(retry_after, 2)

    def test_generation_provider_is_independent_from_embedding_profile(self):
        profile = resolve_active_embedding_profile(
            _RowsDB([("gemini", "gemini-embedding-001", 1, EMBEDDING_DIMENSIONS)]),
            bot_id=1,
            organization_id=10,
        )
        self.assertEqual(profile, EmbeddingProfile("gemini", "gemini-embedding-001", 1, 768))
        for generation_provider in ("gemini", "openai", "claude", "grok"):
            self.assertEqual(profile.provider, "gemini", generation_provider)

    def test_mixed_active_embedding_spaces_fail_closed(self):
        rows = [
            ("gemini", "gemini-embedding-001", 1, 768),
            ("openai", "text-embedding-3-small", 1, 768),
        ]
        with self.assertRaises(IncompatibleEmbeddingProfile):
            resolve_active_embedding_profile(_RowsDB(rows), bot_id=1, organization_id=10)


class ProductionObjectStorageTests(unittest.TestCase):
    def test_pdf_txt_docx_survive_api_worker_filesystem_separation_and_cleanup(self):
        samples = {
            ".pdf": b"%PDF-1.7\nexample",
            ".txt": b"durable text source",
            ".docx": b"PK\x03\x04example",
        }
        with tempfile.TemporaryDirectory() as root:
            storage = LocalObjectStorage(root)
            for suffix, payload in samples.items():
                key = build_source_object_key(7, 11, suffix)
                storage.put(key, payload, content_type="application/octet-stream")
                with storage.download_to_temp(key) as worker_path:
                    self.assertNotEqual(Path(worker_path).resolve(), (Path(root) / key).resolve())
                    self.assertEqual(Path(worker_path).read_bytes(), payload)
                    temporary_copy = worker_path
                self.assertFalse(Path(temporary_copy).exists())
                self.assertEqual(storage.metadata(key).size, len(payload))
                self.assertTrue(storage.delete(key))
                self.assertFalse(storage.exists(key))

    def test_generated_keys_isolate_tenants_and_duplicate_names(self):
        first = build_source_object_key(1, 10, ".pdf")
        second = build_source_object_key(1, 10, ".pdf")
        other_tenant = build_source_object_key(2, 10, ".pdf")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("organizations/1/bots/10/"))
        self.assertTrue(other_tenant.startswith("organizations/2/bots/10/"))

    def test_retry_is_idempotent_and_temp_cleanup_survives_extractor_failure(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalObjectStorage(root)
            key = build_source_object_key(4, 8, ".txt", document_token="stable-operation")
            storage.put(key, b"first")
            storage.put(key, b"replacement")
            self.assertEqual(storage.metadata(key).size, len(b"replacement"))
            temporary_copy = None
            with self.assertRaisesRegex(RuntimeError, "extractor failed"):
                with storage.download_to_temp(key) as worker_path:
                    temporary_copy = worker_path
                    raise RuntimeError("extractor failed")
            self.assertIsNotNone(temporary_copy)
            self.assertFalse(Path(temporary_copy).exists())
            self.assertTrue(storage.delete(key))
            self.assertFalse(storage.delete(key))

    def test_unsafe_keys_are_rejected(self):
        for key in ("../secret", "/absolute/path", "organizations/1/../../secret"):
            with self.assertRaises(ObjectStorageError):
                normalize_object_key(key)

    def test_source_object_reference_is_bound_to_organization_and_bot(self):
        key = build_source_object_key(7, 11, ".txt")
        self.assertEqual(validate_source_object_ownership(key, 7, 11), key)
        for organization_id, bot_id in ((8, 11), (7, 12)):
            with self.assertRaises(ObjectStorageError):
                validate_source_object_ownership(key, organization_id, bot_id)

    def test_local_adapter_is_development_only_and_s3_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"APP_ENV": "development", "OBJECT_STORAGE_PROVIDER": "local", "OBJECT_STORAGE_LOCAL_DIR": root},
            clear=False,
        ):
            self.assertEqual(get_object_storage().provider_name, "local")

        with self.assertRaises(RuntimeError):
            validate_object_storage_config({"APP_ENV": "production", "OBJECT_STORAGE_PROVIDER": "local"})
        with self.assertRaises(RuntimeError):
            validate_object_storage_config({"APP_ENV": "production", "OBJECT_STORAGE_PROVIDER": "s3"})


class ProductionCrawlerPortTests(unittest.TestCase):
    def test_firecrawl_is_active_and_exact_page_normalizes_generic_output(self):
        self.assertIsInstance(get_crawler_provider(), FirecrawlCrawlerProvider)
        audit = CrawlAuditReport(seed_url="https://example.com/product", crawled_urls=1)
        firecrawl_page = Page(
            url="https://example.com/product",
            title="Product",
            markdown="# Product\nUseful details",
            metadata={"canonicalURL": "https://example.com/product"},
            links=["https://example.com/child"],
        )
        with patch(
            "services.firecrawl_service.scrape_single_page_with_audit",
            return_value=([firecrawl_page], audit),
        ):
            pages, result_audit = get_crawler_provider().fetch_exact_page("https://example.com/product")
        self.assertEqual(len(pages), 1)
        self.assertIsInstance(pages[0], CrawlPage)
        self.assertEqual(pages[0].requested_url, "https://example.com/product")
        self.assertEqual(pages[0].canonical_url, "https://example.com/product")
        self.assertEqual(result_audit.provider, "firecrawl")

    def test_website_crawl_uses_same_generic_contract_without_global_tenant_state(self):
        provider_a = get_crawler_provider()
        provider_b = get_crawler_provider()
        self.assertIsNot(provider_a, provider_b)
        audit = CrawlAuditReport(seed_url="https://example.com", crawled_urls=1)
        page = Page(url="https://example.com", title="Home", markdown="# Home")
        with patch("services.firecrawl_service.crawl_website_with_audit", return_value=([page], audit)):
            pages, result_audit = provider_a.crawl_site("https://example.com")
        self.assertIsInstance(pages[0], CrawlPage)
        self.assertEqual(result_audit.provider, "firecrawl")
        crawler_source = Path(__file__).parent / "services" / "crawler_service.py"
        self.assertNotIn("crawl4ai", crawler_source.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
