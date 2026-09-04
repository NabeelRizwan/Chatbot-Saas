"""Deterministic presentation contracts; no model, network or database calls."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from routes.public_routes import get_widget_config
from services.conversational_engine import polish_answer, verify_answer
from services.rag_service import (
    DEFAULT_SUPPORT_PROMPT, NATURAL_ANSWER_STYLE, STRICT_GROUNDING_INSTRUCTION,
    _get_system_instruction,
)


class HumanAnswerStyleTests(unittest.TestCase):
    def polish(self, answer, question="How do these options compare?"):
        with patch("services.conversational_engine.generate") as generate:
            result = polish_answer(SimpleNamespace(), question, answer, "system", was_verified=True)
        generate.assert_not_called()
        return result

    def test_custom_bot_prompt_keeps_shared_style_and_grounding(self):
        bot = SimpleNamespace(system_prompt="Our business instructions.", tone="friendly")
        instruction = _get_system_instruction(bot, DEFAULT_SUPPORT_PROMPT, strict_grounding=True)
        self.assertIn(bot.system_prompt, instruction)
        self.assertIn(NATURAL_ANSWER_STYLE, instruction)
        self.assertIn(STRICT_GROUNDING_INSTRUCTION, instruction)

    def test_style_is_compact_domain_independent_and_explicit(self):
        self.assertLess(len(NATURAL_ANSWER_STYLE.split()), 150)
        for phrase in ("according to the provided context", "based on the knowledge base",
                       "the retrieved chunks", "the supplied documents"):
            self.assertIn(phrase, NATURAL_ANSWER_STYLE)
        for requirement in ("one or two sentences", "structured comparison", "qualifications",
                            "uncertainty", "canonical citations/links", "live access"):
            self.assertIn(requirement, NATURAL_ANSWER_STYLE)
        for customer in ("wowmd", "turmeric", "supplement", "hotel", "ecommerce"):
            self.assertNotIn(customer, NATURAL_ANSWER_STYLE.lower())

    def test_verification_still_receives_style_evidence_and_required_fields(self):
        with patch("services.conversational_engine.generate", return_value="Approved answer") as generate:
            answer = verify_answer(SimpleNamespace(), "Compare the options", "Draft", "Evidence",
                                   NATURAL_ANSWER_STYLE, strict_grounding=True,
                                   required_fields=["Option A: renewal terms"])
        self.assertEqual(answer, "Approved answer")
        self.assertIn("Evidence", generate.call_args.kwargs["prompt"])
        self.assertIn("Option A: renewal terms", generate.call_args.kwargs["prompt"])
        self.assertEqual(generate.call_args.kwargs["system_instruction"], NATURAL_ANSWER_STYLE)

    def test_meta_openings_are_removed_without_changing_the_answer(self):
        body = "It's $33 per bottle."
        for prefix in ("According to the provided context, ", "Based on the knowledge base, ",
                       "The retrieved chunks state that ", "The supplied documents indicate that "):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.polish(prefix + body), body)

    def test_numbers_units_and_qualifications_survive(self):
        body = "Take 2 capsules with 6–8 oz of water. Results may take 4–8 weeks; experiences vary."
        self.assertEqual(self.polish("Certainly! " + body), body)

    def test_missing_information_stays_missing(self):
        body = "I don't have a confirmed timeline for Option B; it isn't guaranteed for Option A."
        self.assertEqual(self.polish("Based on the knowledge base, " + body), body)

    def test_citations_and_named_attribution_are_preserved(self):
        body = "According to the manufacturer, results vary. [Details](https://example.test/a#results) [1]"
        self.assertEqual(self.polish(body), body)

    def test_simple_answer_stays_concise(self):
        body = "It's $33 per bottle."
        self.assertEqual(self.polish(body, "How much is it?"), body)

    def test_comparison_structure_and_every_field_survive(self):
        body = "| Option | Price | Duration |\n| --- | --- | --- |\n| A | $33 | 4–8 weeks, may vary |\n| B | $49 | Not confirmed |"
        self.assertEqual(self.polish(body), body)
        self.assertEqual(self.polish("*   A costs $33.\n*   B costs $49."),
                         "* A costs $33.\n* B costs $49.")

    def test_explicit_quotes_are_untouched(self):
        body = "Based on the knowledge base, something was reported."
        self.assertEqual(self.polish(body, "Quote the exact wording verbatim."), body)

    def test_non_preamble_facts_and_quoted_blocks_are_untouched(self):
        for body in ("According to the provided context, prices increased 5%, so check your quote.",
                     "> Certainly! Results may vary.", "```text\n  2  4  8\n```"):
            with self.subTest(body=body):
                if body.startswith("According"):
                    self.assertEqual(self.polish(body), "prices increased 5%, so check your quote.")
                else:
                    self.assertEqual(self.polish(body), body)

    def test_no_new_facts_from_a_style_model(self):
        with patch("services.conversational_engine.generate", return_value="Guaranteed in 1 day for $9") as generate:
            result = polish_answer(SimpleNamespace(), "When?", "Sure, Timing isn't confirmed.", "system")
        generate.assert_not_called()
        self.assertEqual(result, "Timing isn't confirmed.")


class PerBotWelcomeTests(unittest.TestCase):
    def config(self, welcome=None, widget=None):
        bot = SimpleNamespace(id=7, name="Assistant", avatar_url=None,
                              welcome_message=welcome, widget_config=widget)
        with patch("routes.public_routes.get_public_bot_or_404", return_value=bot), \
             patch("routes.public_routes.enforce_public_origin"):
            return get_widget_config(bot_id=7, db=object())["welcome_message"]

    def test_primary_bot_welcome_wins_over_legacy_config(self):
        self.assertEqual(self.config("Welcome to A!", {"welcome_message": "Old greeting"}), "Welcome to A!")

    def test_different_bots_keep_their_own_greeting(self):
        for greeting in ("Welcome to A!", "Hello from B!", "What can I help you with today?"):
            self.assertEqual(self.config(greeting), greeting)

    def test_legacy_widget_greeting_is_preserved(self):
        self.assertEqual(self.config(None, {"welcome_message": "Legacy greeting"}), "Legacy greeting")
        self.assertEqual(self.config(None, '{"welcome_message": "Stored JSON greeting"}'), "Stored JSON greeting")

    def test_unconfigured_greeting_is_neutral(self):
        self.assertEqual(self.config(), "Hi, how can I help you today?")

    def test_empty_and_whitespace_greetings_fall_back(self):
        for value in (None, "", "   "):
            self.assertEqual(self.config(value, {"welcome_message": value}), "Hi, how can I help you today?")


if __name__ == "__main__":
    unittest.main()
