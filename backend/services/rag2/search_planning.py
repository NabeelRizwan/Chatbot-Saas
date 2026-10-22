"""Bounded search decomposition for the isolated planned deployment variant.

The prompt is the exact tested query planner, without saved questions/answers.
Credentials, tenant ownership, quotas and usage stay in the existing LLM router.
"""
import json
import os
from hashlib import sha256
from pathlib import Path

from services.llm_router import generate_auxiliary, get_last_auxiliary_metadata
from services.providers.generation_input import generation_input
from services.llama_rag.client_runtime import RetrievalError, enabled, setting

PROMPT = Path(__file__).with_name('search_planner_prompt.txt').read_text(encoding='utf-8')
SCHEMA = {'type': 'object', 'properties': {'queries': {'type': 'array',
    'minItems': 1, 'maxItems': 6, 'items': {'type': 'string'}}}, 'required': ['queries']}


def validate_queries(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 6
            or any(not isinstance(q, str) or not q.strip() or len(q) > 420
                   or len(q.split()) > 65 for q in value)
            or len(set(value)) != len(value)):
        raise RetrievalError('search_plan_invalid')
    return list(value)


def plan_searches(bot, question):
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise RetrievalError('question_invalid')
    # Follow-up resolution has already produced this question. Source documents,
    # prior benchmark answers and expected facts never enter the planner prompt.
    with generation_input(schema=SCHEMA, transport_timeout_seconds=60, generation_timeout_seconds=60):
        raw = generate_auxiliary(bot, question, PROMPT,
            timeout=setting('LLAMA_SEARCH_PLANNER_TIMEOUT', 60, 10, 120),
            tokens=4096, json_mode=True, use_auxiliary_model=True)
    try:
        def pairs(entries):
            obj = {}
            for key, value in entries:
                if key in obj:
                    raise ValueError('duplicate_field')
                obj[key] = value
            return obj
        payload = json.loads(raw, object_pairs_hook=pairs)
        if not isinstance(payload, dict) or set(payload) != {'queries'}:
            raise ValueError('unexpected_fields')
        queries = validate_queries(payload['queries'])
    except (ValueError, TypeError):
        raise RetrievalError('search_plan_invalid') from None
    return queries, {'status': 'validated', 'focused_searches': len(queries),
        'prompt_sha256': sha256(PROMPT.encode()).hexdigest(),
        'provider': bot.provider,
        'model': os.getenv(f'RAG_AUX_MODEL_{bot.provider.upper()}') or getattr(bot, 'model_name', None),
        'generation': get_last_auxiliary_metadata()}
