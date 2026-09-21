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

    async def native_completion(self, messages, tools, state):
        """Provider transport for upstream OpenAI-shaped native tool exchanges.
        Tool names, arguments and prompts are not rewritten. Gemini thought
        signatures are kept request-locally because LangGraph normalizes away
        provider extension fields while carrying tool call IDs unchanged.
        """
        import copy
        import json
        from uuid import uuid4
        from types import SimpleNamespace
        from google.genai.types import (Content, GenerateContentConfig, Part, Tool,
            FunctionDeclaration, FunctionCall, FunctionResponse, AutomaticFunctionCallingConfig)
        systems, contents, names = [], [], {}
        for message in messages:
            role, content = message['role'], message.get('content') or ''
            if not isinstance(content, str):
                raise ValueError('TEXT_TOOL_HISTORY_REQUIRED')
            if role == 'system':
                systems.append(content)
                continue
            parts = [Part(text=content)] if content else []
            if role == 'assistant':
                for call in message.get('tool_calls') or []:
                    cid, fn = call['id'], call['function']
                    args = json.loads(fn['arguments']) if isinstance(fn['arguments'], str) else fn['arguments']
                    names[cid] = fn['name']
                    if cid in state:
                        part = copy.deepcopy(state[cid])
                        if part.function_call.name != fn['name'] or part.function_call.args != args:
                            raise ValueError('TOOL_HISTORY_IDENTITY_MISMATCH')
                    else:
                        # Upstream may itself append a synthetic tool exchange.
                        part = Part(function_call=FunctionCall(name=fn['name'], args=args))
                    parts.append(part)
                role = 'model'
            elif role == 'tool':
                cid = message['tool_call_id']
                if cid not in names:
                    raise ValueError('UNPAIRED_TOOL_RESULT')
                parts = [Part(function_response=FunctionResponse(name=names[cid], response={'result': content}))]
                role = 'user'
            elif role != 'user':
                raise ValueError('INVALID_TOOL_HISTORY_ROLE')
            if parts:
                if contents and contents[-1].role == role:
                    contents[-1].parts.extend(parts)
                else:
                    contents.append(Content(role=role, parts=parts))
        declarations = []
        for spec in tools or []:
            fn = spec['function']
            declarations.append(FunctionDeclaration(name=fn['name'], description=fn.get('description'),
                                                    parameters_json_schema=fn.get('parameters')))
        config = {'automatic_function_calling': AutomaticFunctionCallingConfig(disable=True)}
        if systems:
            config['system_instruction'] = '\n\n'.join(systems)
        if declarations:
            config['tools'] = [Tool(function_declarations=declarations)]
        # Same validated Gemini 3.5 defaults as the text callback: no legacy
        # thinking_budget or unsupported custom sampling controls.
        response = await self.client.aio.models.generate_content(
            model=self.model_name, contents=contents, config=GenerateContentConfig(**config))
        candidates = response.candidates or []
        if not candidates or not candidates[0].content:
            raise ValueError('EMPTY_PROVIDER_CANDIDATE')
        calls, answer = [], []
        for part in candidates[0].content.parts or []:
            if part.function_call:
                cid = 'call_' + uuid4().hex
                state[cid] = copy.deepcopy(part)
                calls.append(SimpleNamespace(id=cid, type='function', function=SimpleNamespace(
                    name=part.function_call.name, arguments=json.dumps(part.function_call.args or {}, ensure_ascii=False))))
            elif part.text and not part.thought:
                answer.append(part.text)
        usage = response.usage_metadata
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=''.join(answer), tool_calls=calls))], usage=SimpleNamespace(
            prompt_tokens=getattr(usage, 'prompt_token_count', 0) or 0,
            completion_tokens=getattr(usage, 'candidates_token_count', 0) or 0,
            total_tokens=getattr(usage, 'total_token_count', 0) or 0))
