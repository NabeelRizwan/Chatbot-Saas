# Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# http://www.apache.org/licenses/LICENSE-2.0
# Modified for Chatbot-SaaS: extract dialog_service.async_chat query preparation,
# inject authorized model rather than tenant/model database globals.
from dataclasses import dataclass
from .upstream.prompts.generator import full_question, cross_languages, keyword_extraction
from .contracts import EngineError


@dataclass(frozen=True)
class QueryOptions:
    refine_multiturn: bool = False
    cross_languages: tuple[str, ...] = ()
    keyword: bool = False
    toc_enhance: bool = False


async def prepare_query(query, messages, options, chat_mdl):
    messages = list(messages or []) + [{"role": "user", "content": query}]
    if len(messages) > 64 or any(m.get("role") not in ("user", "assistant")
            or not isinstance(m.get("content"), str) or len(m["content"]) > 16384 for m in messages):
        raise EngineError("RETRIEVAL_FAILED", "history bounds")
    questions = [m["content"] for m in messages if m["role"] == "user"][-3:]
    if len(questions) > 1 and options.refine_multiturn:
        questions = [await full_question(messages=messages, chat_mdl=chat_mdl)]
    else:
        questions = questions[-1:]
    if options.cross_languages:
        questions = [await cross_languages(None, None, questions[0], options.cross_languages, chat_mdl=chat_mdl)]
    if options.keyword:
        questions[-1] = questions[-1] + "," + await keyword_extraction(chat_mdl, questions[-1])
    return " ".join(questions)
