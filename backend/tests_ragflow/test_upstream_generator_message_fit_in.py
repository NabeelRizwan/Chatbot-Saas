# Modified for Chatbot-SaaS: namespace/loader only; upstream fixtures and assertions unchanged.
#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class _CharEncoder:
    @staticmethod
    def encode(text):
        return list(text)

    @staticmethod
    def decode(tokens):
        return "".join(tokens)


def _load_generator_module(monkeypatch):
    from ragflow_derived.upstream.prompts import generator
    return generator


@pytest.mark.p1
def test_message_fit_in_truncates_user_message_by_system_token_budget(monkeypatch):
    generator = _load_generator_module(monkeypatch)
    monkeypatch.setattr(generator, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(generator, "get_encoder", lambda: _CharEncoder())

    messages = [
        {"role": "system", "content": "1234"},
        {"role": "user", "content": "abcdefghij"},
    ]

    used_tokens, trimmed = generator.message_fit_in(messages, max_length=8)

    assert used_tokens == 8
    assert trimmed[0]["content"] == "1234"
    assert trimmed[-1]["content"] == "abcd"


@pytest.mark.p1
def test_message_fit_in_handles_zero_token_messages(monkeypatch):
    generator = _load_generator_module(monkeypatch)
    monkeypatch.setattr(generator, "num_tokens_from_string", lambda _text: 0)
    monkeypatch.setattr(generator, "get_encoder", lambda: _CharEncoder())

    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": ""},
    ]

    used_tokens, trimmed = generator.message_fit_in(messages, max_length=0)

    assert used_tokens == 0
    assert trimmed == messages


@pytest.mark.p1
def test_message_fit_in_clamps_negative_slice_lengths(monkeypatch):
    generator = _load_generator_module(monkeypatch)
    monkeypatch.setattr(generator, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(generator, "get_encoder", lambda: _CharEncoder())

    messages = [
        {"role": "system", "content": "1234"},
        {"role": "user", "content": "abcdefghij"},
    ]

    used_tokens, trimmed = generator.message_fit_in(messages, max_length=2)

    assert used_tokens == 2
    assert trimmed[0]["content"] == "12"
    assert trimmed[-1]["content"] == ""


@pytest.mark.p1
def test_message_fit_in_clamps_dominant_last_message_to_budget(monkeypatch):
    generator = _load_generator_module(monkeypatch)
    monkeypatch.setattr(generator, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(generator, "get_encoder", lambda: _CharEncoder())

    messages = [
        {"role": "system", "content": "s" * 41},
        {"role": "user", "content": "abcdefghij"},
    ]

    used_tokens, trimmed = generator.message_fit_in(messages, max_length=8)

    assert used_tokens == 8
    assert trimmed[0]["content"] == ""
    assert trimmed[-1]["content"] == "abcdefgh"


@pytest.mark.p1
def test_message_fit_in_zero_budget_preserves_non_empty_messages(monkeypatch):
    generator = _load_generator_module(monkeypatch)
    monkeypatch.setattr(generator, "num_tokens_from_string", lambda text: len(text))
    monkeypatch.setattr(generator, "get_encoder", lambda: _CharEncoder())

    system_len = 8100
    user_content = "User query: test"
    messages = [
        {"role": "system", "content": "s" * system_len},
        {"role": "user", "content": user_content},
    ]
    expected_total = system_len + len(user_content)

    used_tokens, trimmed = generator.message_fit_in(messages, max_length=0)

    assert expected_total > 861
    assert expected_total < 8192
    assert used_tokens == expected_total
    assert trimmed[0]["content"] == "s" * system_len
    assert trimmed[-1]["content"] == user_content
