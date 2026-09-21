"""Gemini wire compatibility only; no tools, prompts or retrieval policy here."""
import copy
import json
import re
from types import SimpleNamespace
from uuid import uuid4
from google.genai.types import Content, Part, FunctionCall, FunctionResponse, FunctionDeclaration

# Google's documented marker for client-executed, non-model tool history.
# Never used to replace a signature returned by Gemini.
CLIENT_HISTORY_SIGNATURE = b'skip_thought_signature_validator'


def declarations_for(tools):
    """Validate our exercised JSON-schema subset without deleting semantics.

    Unvalidated schema features fail locally, rather than silently weakening a
    tool. Current upstream schemas need no conversion at all.
    """
    def schema(value, root=False):
        if not isinstance(value, dict):
            raise ValueError('INVALID_TOOL_SCHEMA')
        allowed = {'type', 'properties', 'required', 'items', 'minItems', 'maxItems',
                   'description', 'enum'}
        if set(value) - allowed:
            raise ValueError('UNVALIDATED_TOOL_SCHEMA_FEATURE')
        kind = value.get('type')
        if kind not in ('object', 'array', 'string', 'integer', 'number', 'boolean') or (root and kind != 'object'):
            raise ValueError('INVALID_TOOL_SCHEMA_TYPE')
        if 'description' in value and not isinstance(value['description'], str):
            raise ValueError('INVALID_TOOL_DESCRIPTION')
        if 'enum' in value:
            if kind != 'string' or not isinstance(value['enum'], list) or not value['enum'] or not all(isinstance(x, str) for x in value['enum']):
                raise ValueError('INVALID_TOOL_ENUM')
        if kind == 'object':
            props, required = value.get('properties', {}), value.get('required', [])
            if not isinstance(props, dict) or not isinstance(required, list) or not all(isinstance(x, str) for x in required):
                raise ValueError('INVALID_TOOL_PROPERTIES')
            if len(set(required)) != len(required) or not set(required) <= props.keys():
                raise ValueError('INVALID_TOOL_REQUIRED')
            for key, child in props.items():
                if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key):
                    raise ValueError('INVALID_TOOL_PARAMETER_NAME')
                schema(child)
        elif 'properties' in value or 'required' in value:
            raise ValueError('INVALID_TOOL_OBJECT_KEYWORD')
        if kind == 'array':
            schema(value.get('items'))
            for key in ('minItems', 'maxItems'):
                if key in value and (type(value[key]) is not int or value[key] < 0):
                    raise ValueError('INVALID_TOOL_ARRAY_BOUND')
            if value.get('minItems', 0) > value.get('maxItems', float('inf')):
                raise ValueError('INVALID_TOOL_ARRAY_BOUND')
        elif any(key in value for key in ('items', 'minItems', 'maxItems')):
            raise ValueError('INVALID_TOOL_ARRAY_KEYWORD')
    result, names = [], set()
    for spec in tools or []:
        if not isinstance(spec, dict) or spec.get('type') != 'function' or not isinstance(spec.get('function'), dict):
            raise ValueError('INVALID_TOOL_DECLARATION')
        fn = spec['function']
        name = fn.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', name) or name in names:
            raise ValueError('INVALID_OR_DUPLICATE_TOOL_NAME')
        if set(fn) - {'name', 'description', 'parameters'} or not isinstance(fn.get('description', ''), str):
            raise ValueError('INVALID_TOOL_DECLARATION')
        parameters = fn.get('parameters', {'type': 'object', 'properties': {}})
        schema(parameters, root=True)
        result.append(FunctionDeclaration(name=name, description=fn.get('description'), parameters_json_schema=copy.deepcopy(parameters)))
        names.add(name)
    return result


def history_contents(messages, state, declared_names):
    """Keep complete provider Content out-of-band, including part ordering."""
    systems, contents, pending, seen = [], [], {}, set()
    records = state.setdefault('calls', {})
    for message in messages:
        role, content = message['role'], message.get('content') or ''
        if not isinstance(content, str):
            raise ValueError('TEXT_TOOL_HISTORY_REQUIRED')
        if role != 'tool' and pending:
            raise ValueError('MISSING_TOOL_RESPONSES')
        if role == 'system':
            systems.append(content)
            continue
        parts = [Part(text=content)] if content else []
        if role == 'assistant':
            calls = message.get('tool_calls') or []
            ids = [c['id'] for c in calls]
            if len(set(ids)) != len(ids) or any(not isinstance(cid, str) or not cid or cid in seen for cid in ids):
                raise ValueError('INVALID_TOOL_HISTORY_IDS')
            parsed = []
            for call in calls:
                cid, fn = call['id'], call['function']
                args = json.loads(fn['arguments']) if isinstance(fn['arguments'], str) else fn['arguments']
                if not isinstance(args, dict):
                    raise ValueError('INVALID_TOOL_ARGUMENTS')
                if cid in records:
                    record = records[cid]
                    if record['name'] != fn['name'] or record['args'] != args:
                        raise ValueError('TOOL_HISTORY_IDENTITY_MISMATCH')
                    wire_id = record['provider_id']
                else:
                    if fn['name'] not in declared_names:
                        raise ValueError('UNKNOWN_HISTORY_TOOL')
                    wire_id = cid
                parsed.append((cid, fn['name'], args, wire_id))
                pending[cid] = (fn['name'], wire_id)
                seen.add(cid)
            provider_records = [records[cid] for cid in ids if cid in records]
            if provider_records:
                first = provider_records[0]
                if len(provider_records) != len(ids) or first['ids'] != ids or first['text'] != content:
                    raise ValueError('PROVIDER_TURN_CHANGED')
                parts = copy.deepcopy(first['content'].parts)
            elif calls:
                # These are already-executed upstream synthetic exchanges, not
                # fabricated provider history. The documented Gemini marker is
                # the only wire adaptation; args/results remain exact.
                parts.extend(Part(function_call=FunctionCall(id=cid, name=name, args=args),
                                  thought_signature=CLIENT_HISTORY_SIGNATURE)
                             for cid, name, args, _ in parsed)
            else:
                previous = state.get('text_turns', {}).get(content)
                if previous is not None:
                    parts = copy.deepcopy(previous.parts)
            role = 'model'
        elif role == 'tool':
            cid = message['tool_call_id']
            if cid not in pending:
                raise ValueError('UNPAIRED_TOOL_RESULT')
            name, wire_id = pending.pop(cid)
            if message.get('name', name) != name:
                raise ValueError('TOOL_RESULT_NAME_MISMATCH')
            parts = [Part(function_response=FunctionResponse(id=wire_id, name=name, response={'result': content}))]
            role = 'user'
        elif role != 'user':
            raise ValueError('INVALID_TOOL_HISTORY_ROLE')
        if parts:
            # Parallel tool responses share a user content, but never merge
            # distinct provider model contents or reorder signed parts.
            if role == 'user' and contents and contents[-1].role == role and message['role'] == 'tool':
                contents[-1].parts.extend(parts)
            else:
                contents.append(Content(role=role, parts=parts))
    if pending:
        raise ValueError('MISSING_TOOL_RESPONSES')
    return systems, contents


def parse_native_response(response, state, declared_names):
    candidates = response.candidates or []
    if not candidates or not candidates[0].content:
        raise ValueError('EMPTY_PROVIDER_CANDIDATE')
    original = candidates[0].content
    calls, answer, saved = [], [], {}
    for part in original.parts or []:
        if part.function_call:
            fc = part.function_call
            if fc.name not in declared_names:
                raise ValueError('UNKNOWN_PROVIDER_TOOL')
            cid = fc.id or 'call_' + uuid4().hex
            if cid in saved or cid in state.get('calls', {}):
                raise ValueError('DUPLICATE_PROVIDER_CALL_ID')
            args = fc.args or {}
            if not isinstance(args, dict):
                raise ValueError('INVALID_PROVIDER_ARGUMENTS')
            saved[cid] = {'name': fc.name, 'args': copy.deepcopy(args), 'provider_id': fc.id}
            calls.append(SimpleNamespace(id=cid, type='function', function=SimpleNamespace(
                name=fc.name, arguments=json.dumps(args, ensure_ascii=False))))
        elif part.text and not part.thought:
            answer.append(part.text)
    text = ''.join(answer)
    for cid, record in saved.items():
        record.update(content=copy.deepcopy(original), ids=list(saved), text=text)
    state.setdefault('calls', {}).update(saved)
    if not calls:
        state.setdefault('text_turns', {})[text] = copy.deepcopy(original)
    usage = response.usage_metadata
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls))],
        usage=SimpleNamespace(prompt_tokens=getattr(usage, 'prompt_token_count', 0) or 0,
            completion_tokens=getattr(usage, 'candidates_token_count', 0) or 0,
            total_tokens=getattr(usage, 'total_token_count', 0) or 0))
