# Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# http://www.apache.org/licenses/LICENSE-2.0
# Modified for Chatbot-SaaS: selected GoogleChat Gemini-only provider mapping;
# injected client replaces Vertex/product configuration. No retrieval/prompt changes.
from .runtime import num_tokens_from_string


class GeminiProvider:
    def __init__(self, client, model_name):
        self.client, self.model_name = client, model_name

    def _clean_conf(self, gen_conf):
        if "max_tokens" in gen_conf:
            gen_conf["max_output_tokens"] = gen_conf["max_tokens"]
            del gen_conf["max_tokens"]
        for k in list(gen_conf.keys()):
            if k not in ["temperature", "top_p", "max_output_tokens"]:
                del gen_conf[k]
        return gen_conf

    async def _async_chat(self, history, gen_conf, **kwargs):
        gen_conf = dict(gen_conf or {})
        system = history[0]["content"] if history and history[0]["role"] == "system" else ""
        history = [h for h in history if h["role"] != "system"]
        if "thinking_budget" not in gen_conf:
            gen_conf["thinking_budget"] = 0
        thinking_budget = gen_conf.pop("thinking_budget", 0)
        gen_conf = self._clean_conf(gen_conf)
        from google.genai.types import Content, GenerateContentConfig, Part, ThinkingConfig
        config_dict = {}
        if system:
            config_dict["system_instruction"] = system
        if "temperature" in gen_conf:
            config_dict["temperature"] = gen_conf["temperature"]
        if "top_p" in gen_conf:
            config_dict["top_p"] = gen_conf["top_p"]
        if "max_output_tokens" in gen_conf:
            config_dict["max_output_tokens"] = gen_conf["max_output_tokens"]
        config_dict["thinking_config"] = ThinkingConfig(thinking_budget=thinking_budget)
        config = GenerateContentConfig(**config_dict)
        contents = []
        for item in history:
            role = "model" if item["role"] == "assistant" else item["role"]
            contents.append(Content(role=role, parts=[Part(text=item["content"])]))
        response = await self.client.aio.models.generate_content(model=self.model_name, contents=contents, config=config)
        ans = response.text or ""
        try:
            total_tokens = response.usage_metadata.total_token_count
        except Exception:
            total_tokens = num_tokens_from_string(ans)
        return ans, total_tokens
