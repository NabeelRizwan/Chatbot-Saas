# Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Development-only Gemini 3.5 transport compatibility. Message/usage mapping
# derives from ragflow_derived.upstream.gemini; upstream prompts remain unchanged.
from ragflow_derived.upstream.gemini import GeminiProvider
from ragflow_derived.upstream.runtime import num_tokens_from_string


class Gemini35Provider(GeminiProvider):
    """Text callback with model defaults, not legacy 2.5 generation controls."""

    async def _async_chat(self, history, gen_conf, **kwargs):
        from google.genai.types import Content, GenerateContentConfig, Part

        system = history[0]["content"] if history and history[0]["role"] == "system" else ""
        turns = [item for item in history if item["role"] != "system"]
        if not turns or turns[-1]["role"] != "user":
            raise ValueError("NONEMPTY_FINAL_USER_TURN_REQUIRED")
        if any(item["role"] not in ("user", "assistant", "model") or
                not isinstance(item["content"], str) or not item["content"].strip() for item in turns):
            raise ValueError("INVALID_TEXT_TURN")
        contents = [Content(role="model" if item["role"] == "assistant" else item["role"],
            parts=[Part(text=item["content"])]) for item in turns]
        config_dict = {"system_instruction": system} if system else {}
        conf = self._clean_conf(dict(gen_conf or {}))
        # Preserve a caller's explicit output bound; no new application limit.
        if "max_output_tokens" in conf:
            config_dict["max_output_tokens"] = conf["max_output_tokens"]
        # Omit thinking (Flash-Lite defaults to minimal), custom sampling,
        # candidate_count and all other optional legacy controls.
        request = {"model": self.model_name, "contents": contents}
        if config_dict:
            request["config"] = GenerateContentConfig(**config_dict)
        response = await self.client.aio.models.generate_content(**request)
        answer = response.text or ""
        try:
            tokens = response.usage_metadata.total_token_count
        except (AttributeError, TypeError):
            tokens = num_tokens_from_string(answer)
        return answer, tokens
