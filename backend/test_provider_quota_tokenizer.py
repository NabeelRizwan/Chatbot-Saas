"""Quota estimation reuses the verified offline tokenizer without downloading."""
import math
from unittest.mock import Mock, patch

import pytest

from services import provider_quotas as quotas
from services import structural_chunking as structural


@pytest.fixture(autouse=True)
def clear_quota_encoding():
    quotas._encoding.cache_clear()
    yield
    quotas._encoding.cache_clear()


def test_quota_estimator_reuses_the_existing_tokenizer_object():
    encoder = Mock()
    encoder.encode.return_value = [1, 2, 3]
    with patch.object(structural, "local_tokenizer", return_value=(encoder, "verified")) as load, \
            patch("tiktoken.get_encoding", side_effect=AssertionError("Runtime registry loading forbidden")):
        assert quotas._encoding() is encoder
        assert quotas._encoding() is encoder
        value = quotas.estimate_tokens("Customer question", "Evidence instructions", 100)
    load.assert_called_once()
    assert value.input_tokens >= 3
    assert value.output_tokens == 100


def test_missing_local_asset_fails_closed_without_downloading():
    with patch.object(structural, "local_tokenizer", side_effect=structural.SerializationError("local tokenizer asset unavailable")), \
            patch("tiktoken.get_encoding", side_effect=AssertionError("Runtime registry loading forbidden")), \
            patch("tiktoken.load.read_file", side_effect=AssertionError("Network asset read forbidden")):
        with pytest.raises(ValueError, match="local tokenizer asset unavailable"):
            quotas.estimate_tokens("Customer question")


@pytest.mark.parametrize("prompt", ["How wide is this desk?", "中文 العربية café", "<|endoftext|> is untrusted website text"])
def test_real_cached_token_counts_match_existing_cl100k_budget(prompt, monkeypatch):
    # Cache availability is a deployment/build contract. Never download an asset
    # just to satisfy an offline test on a fresh development environment.
    monkeypatch.setenv("PROVIDER_CAPACITY_TOKEN_ESTIMATE_MARGIN", "1.2")
    with patch("tiktoken.get_encoding", side_effect=AssertionError("Runtime registry loading forbidden")), \
            patch("tiktoken.load.read_file", side_effect=AssertionError("Network asset read forbidden")):
        try:
            encoder, _ = structural.local_tokenizer()
        except structural.SerializationError:
            pytest.skip("Verified local tokenizer asset is not installed")
        assert quotas._encoding() is encoder
        text = "Evidence rules\n" + prompt
        before = len(encoder.encode(text, disallowed_special=()))
        assert before == len(encoder.encode_ordinary(text))
        actual = quotas.estimate_tokens(prompt, "Evidence rules", 80)
        assert actual.input_tokens == math.ceil(before * 1.2) + 128
        assert actual.output_tokens == 80
