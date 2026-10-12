"""Request-scoped message and output contracts; never stored on provider clients."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class GenerationInput:
    messages: tuple[tuple[str, str], ...] = ()
    schema_json: str | None = None

    @property
    def schema(self):
        return json.loads(self.schema_json) if self.schema_json else None


_INPUT: ContextVar[GenerationInput] = ContextVar('generation_input', default=GenerationInput())


def current_input():
    return _INPUT.get()


@contextmanager
def generation_input(messages=(), schema=None):
    values = tuple((item['role'], item['content']) for item in messages)
    if any(role not in ('user', 'assistant') or not isinstance(content, str) for role, content in values):
        raise ValueError('invalid_generation_messages')
    token = _INPUT.set(GenerationInput(values, json.dumps(schema) if schema is not None else None))
    try:
        yield
    finally:
        _INPUT.reset(token)


def openai_messages(prompt, system_instruction=None):
    messages = [{'role': 'developer', 'content': system_instruction}] if system_instruction else []
    messages.extend({'role': role, 'content': content} for role, content in current_input().messages)
    if not current_input().messages:
        messages.append({'role': 'user', 'content': prompt})
    return messages


def openai_output_options():
    schema = current_input().schema
    return {'text': {'format': {'type': 'json_schema', 'name': 'evidence_answer',
                               'strict': True, 'schema': schema}}} if schema else {}


def gemini_contents(prompt, config):
    # Text-only adaptation of Dify's Gemini plugin message conversion and
    # _set_chat_parameters. See third_party/answer-layer/manifest.json.
    from google.genai import types
    request = current_input()
    if request.schema is not None:
        config.response_mime_type = 'application/json'
        config.response_json_schema = request.schema
    if not request.messages:
        return prompt
    contents = []
    for role, text in request.messages:
        content = types.Content(role='model' if role == 'assistant' else 'user',
                                parts=[types.Part.from_text(text=text)])
        if contents and contents[-1].role == content.role:
            contents[-1].parts.extend(content.parts)
        else:
            contents.append(content)
    return contents


def admission_text(prompt):
    """Reserve for the actual message body, role overhead and response schema."""
    request = current_input()
    if request.messages:
        prompt = '\n'.join(f'{role}: {content}' for role, content in request.messages)
    return prompt + ('\n' + request.schema_json if request.schema_json else '')
