"""Offline generation defaults: no database, credential, or provider calls."""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import os
import re
import unittest
from unittest.mock import Mock, patch

from database.models import Bot, EMBEDDING_DIMENSIONS
from schemas.schemas import BotCreate
from services import llm_router as router
from services.bot_service import SUPPORTED_MODELS, validate_provider_model
from services.embedding_service import GEMINI_EMBEDDING_MODEL, OPENAI_EMBEDDING_MODEL
from services.providers.base_provider import GenerationResult

DEFAULT = "models/gemini-3.5-flash-lite"


class GenerationModelDefaults(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(router, "_resolve_api_key", return_value=("synthetic-placeholder", False)))
        self.stack.enter_context(patch.object(router, "_track_usage", side_effect=AssertionError("Unexpected usage write")))
        self.stack.enter_context(patch.object(router, "execute_with_resilience",
            side_effect=lambda generate_fn, *args, **kwargs: generate_fn()))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.providers = {}
        for name in ("gemini", "openai", "claude", "grok"):
            fake = Mock()
            fake.generate_with_metadata.side_effect = lambda _name=name, **kw: GenerationResult(
                "Synthetic response", _name, kw["model_name"])
            fake.generate_stream.side_effect = lambda **kw: iter(["Synthetic response"])
            self.providers[name] = fake
        self.stack.enter_context(patch.dict(router.PROVIDERS, self.providers))

    def bot(self, provider="gemini", model=None, identity=17):
        return SimpleNamespace(id=identity, organization_id=identity + 100,
            provider=provider, model_name=model, provider_api_key=None, capabilities={})

    def assert_generate_model(self, bot, expected):
        before = dict(vars(bot))
        self.assertEqual(router.generate(bot, "Synthetic prompt"), "Synthetic response")
        call = self.providers[bot.provider].generate_with_metadata.call_args.kwargs
        self.assertEqual(call["model_name"], expected)
        if not router.verification_mode.get():
            self.assertEqual(router.get_last_generation_metadata()["model"], expected)
        self.assertEqual(vars(bot), before)

    def test_gemini_missing_model(self):
        self.assert_generate_model(self.bot(), DEFAULT)

    def test_gemini_empty_model(self):
        self.assert_generate_model(self.bot(model=""), DEFAULT)

    def test_gemini_missing_attribute(self):
        bot = self.bot()
        del bot.model_name
        self.assert_generate_model(bot, DEFAULT)

    def test_explicit_gemini_choices_win(self):
        for model in ("gemini-2.5-flash", "gemini-1.5-pro", "models/explicit-configured-model"):
            with self.subTest(model=model):
                self.assert_generate_model(self.bot(model=model), model)

    def test_other_provider_selection_unchanged(self):
        for provider, model in (("openai", "gpt-4.1"), ("claude", "claude-3-opus"), ("grok", "grok-2")):
            with self.subTest(provider=provider):
                self.assert_generate_model(self.bot(provider, model), model)
                self.assertEqual(list(router.generate_stream(self.bot(provider, model), "Synthetic prompt")),
                                 ["Synthetic response"])
                self.assertEqual(self.providers[provider].generate_stream.call_args.kwargs["model_name"], model)

    def test_other_providers_do_not_acquire_a_gemini_fallback(self):
        for provider in ("openai", "claude", "grok"):
            with self.subTest(provider=provider):
                self.assertIsNone(router._generation_model(self.bot(provider)))

    def test_per_bot_models_and_organizations_remain_independent(self):
        for identity, model in ((21, "gemini-2.5-flash"), (39, None), (80, "gemini-1.5-pro")):
            with self.subTest(identity=identity):
                self.assert_generate_model(self.bot(model=model, identity=identity), model or DEFAULT)

    def test_stream_uses_fallback_and_preserves_override(self):
        for model in (None, "gemini-2.5-flash"):
            with self.subTest(model=model):
                list(router.generate_stream(self.bot(model=model), "Synthetic prompt"))
                self.assertEqual(self.providers["gemini"].generate_stream.call_args.kwargs["model_name"], model or DEFAULT)
                self.assertEqual(router.get_last_generation_metadata()["model"], model or DEFAULT)

    def test_auxiliary_fallback_and_explicit_bot_model(self):
        for model in (None, "gemini-2.5-flash"):
            with self.subTest(model=model):
                self.assertEqual(router.generate_auxiliary(self.bot(model=model), "Synthetic prompt", ""), "Synthetic response")
                self.assertEqual(self.providers["gemini"].generate_with_metadata.call_args.kwargs["model_name"], model or DEFAULT)

    def test_explicit_auxiliary_override_preserved(self):
        with patch.dict(os.environ, RAG_AUX_MODEL_GEMINI="explicit-auxiliary-model"):
            router.generate_auxiliary(self.bot(model="gemini-2.5-flash"), "Synthetic prompt", "")
        self.assertEqual(self.providers["gemini"].generate_with_metadata.call_args.kwargs["model_name"],
                         "explicit-auxiliary-model")

    def test_verifier_uses_bot_model_not_auxiliary_override(self):
        token = router.verification_mode.set(True)
        try:
            with patch.dict(os.environ, RAG_AUX_MODEL_GEMINI="explicit-auxiliary-model"):
                self.assert_generate_model(self.bot(model="gemini-2.5-flash"), "gemini-2.5-flash")
        finally:
            router.verification_mode.reset(token)

    def test_creation_defaults_and_explicit_models(self):
        self.assertEqual(BotCreate(name="Synthetic bot", organization_id=17).model_name, DEFAULT)
        self.assertEqual(Bot.__table__.c.model_name.default.arg, DEFAULT)
        for provider, models in SUPPORTED_MODELS.items():
            for model in models:
                with self.subTest(provider=provider, model=model):
                    value = BotCreate(name="Synthetic bot", organization_id=17, provider=provider, model_name=model)
                    self.assertEqual(value.model_name, model)
                    validate_provider_model(provider, model)

    def test_frontend_default_preserves_all_existing_choices(self):
        source = (Path(__file__).parents[1] / "frontend/types/bot.ts").read_text(encoding="utf-8")
        expected = {"gemini": [DEFAULT, "gemini-2.5-flash", "gemini-1.5-pro"],
                    "openai": ["gpt-4.1-mini", "gpt-4.1"], "claude": ["claude-3-5-sonnet", "claude-3-opus"],
                    "grok": ["grok-2", "grok-beta"]}
        for provider, models in expected.items():
            listed = re.search(r"  " + provider + r": \[([^\]]+)\]", source)[1]
            self.assertEqual(re.findall(r'"([^"]+)"', listed), models)
            self.assertEqual(set(models), SUPPORTED_MODELS[provider])

    def test_embedding_defaults_unchanged(self):
        self.assertEqual(GEMINI_EMBEDDING_MODEL, "gemini-embedding-001")
        self.assertEqual(OPENAI_EMBEDDING_MODEL, "text-embedding-3-small")
        self.assertEqual(EMBEDDING_DIMENSIONS, 768)


if __name__ == "__main__":
    unittest.main()
