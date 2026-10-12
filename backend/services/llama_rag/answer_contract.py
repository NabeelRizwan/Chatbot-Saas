"""Provider-native answer metadata with ordinary prose for the widget."""

import json
import os
import re
import unicodedata
from html.parser import HTMLParser

from markdown_it import MarkdownIt
from markdown_it.common.html_re import HTML_TAG_RE
from markdown_it.common.utils import normalizeReference
from markdown_it.helpers import parseLinkDestination, parseLinkLabel
from markdown_it.rules_inline import StateInline, autolink, image, link
from pydantic_core import from_json

from .citations import select_sources, AttributionStream
from .client import RetrievalError


STRUCTURED_REFERENCE_RULES = (
    'Return the customer answer in the answer field of the required JSON object. '
    'That string may use natural paragraphs, lists and Markdown as appropriate; '
    'no fixed visible template is required. Put the supplied passage IDs actually '
    'used to support the answer in source_ids. Cite both sides of a conflict. '
    'Do not include retrieved but unused passages. Use [] if no passage supports '
    'an answered fact. Do not write a bibliography, private tags or raw source '
    'markers in the answer string. Useful user-requested links are allowed.'
)


def enabled(name):
    return os.getenv(name, '0').lower() in ('1', 'true', 'yes')


def native_schema_supported(bot):
    provider = str(getattr(bot, 'provider', '')).lower()
    model = str(getattr(bot, 'model_name', '') or '').removeprefix('models/')
    if provider == 'gemini':
        return model.startswith(('gemini-2.', 'gemini-3.')) and not any(
            name in model for name in ('image', 'tts', 'live', 'audio'))
    if provider == 'openai':
        # Specialty/search/audio models and the first 4o snapshot do not share
        # the text models' strict-schema contract. Unknown IDs keep legacy output.
        if model == 'gpt-4o-2024-05-13':
            return False
        return bool(re.fullmatch(
            r'(?:gpt-4o(?:-mini)?|gpt-4\.1(?:-mini|-nano)?|'
            r'gpt-5(?:\.\d+)?(?:-mini|-nano)?|gpt-6(?:\.\d+)?-(?:sol|astra|luna)|'
            r'o3(?:-mini)?|o4-mini)(?:-\d{4}-\d{2}-\d{2})?', model))
    return False


def answer_schema(items):
    ids = list(dict.fromkeys(str(item['chunk'].metadata_json['citation_id']) for item in items))
    return {'type': 'object', 'properties': {
        'answer': {'type': 'string'},
        'source_ids': {'type': 'array', 'items': {'type': 'string', 'enum': ids}}},
        'required': ['answer', 'source_ids'], 'additionalProperties': False}


def answer_messages(history, current_prompt):
    # Adapted from LlamaIndex get_prefix_messages_with_context (MIT).
    # Instructions remain in the provider's system/developer field; retrieved
    # website text stays in the lower-trust current user message.
    return [*({'role': item['role'], 'content': item['content']} for item in history),
            {'role': 'user', 'content': current_prompt}]


_LABEL = r'(?:Source(?:[ \t]+|_)|ID:[ \t]*)'
_NUMBER = r'[1-9][0-9]{0,8}'
_INLINE = re.compile(r'\[(' + _LABEL + _NUMBER
    + r'(?:[ \t]*,[ \t]*(?:' + _LABEL + r')?' + _NUMBER + r')*[ \t]*)\]', re.IGNORECASE)
_MARKUP = re.compile(r'`+|~{3,}|\\.|\[|<|https?://', re.IGNORECASE)
_MAX_INLINE_MARKER = 4096
_MAX_INLINE_REFERENCES = 64
_MARKDOWN = MarkdownIt('commonmark').disable('inline')


class _CitationSpanAttributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes = None

    def handle_starttag(self, tag, attrs):
        if tag == 'span' and len(attrs) == 2 and {name for name, _ in attrs} == {'class', 'data-citation'}:
            self.attributes = dict(attrs)


def _citation_span_ids(opening, available):
    if len(opening) > _MAX_INLINE_MARKER or opening.endswith('/>'):
        return None
    parser = _CitationSpanAttributes()
    parser.feed(opening)
    attrs = parser.attributes
    if not attrs or attrs['class'] != 'citation' or not isinstance(attrs['data-citation'], str):
        return None
    value = attrs['data-citation']
    parts = value.split(',')
    if (len(parts) > _MAX_INLINE_REFERENCES
            or not re.fullmatch(_NUMBER + r'(?:[ \t]*,[ \t]*' + _NUMBER + r')*', value)):
        return None
    references = list(dict.fromkeys(part.strip() for part in parts))
    return references if set(references) <= available else None


def _possible_span_opening(tail):
    if len(tail) > _MAX_INLINE_MARKER:
        return False
    prefix = '<span'
    return (prefix.startswith(tail.lower())
            or bool(re.fullmatch(r'<span[ \t\r\n][^<>]*', tail, re.IGNORECASE)))


def _possible_span_closing(tail):
    return ('</span>'.startswith(tail.lower())
            or bool(re.fullmatch(r'</span[ \t]*', tail, re.IGNORECASE)))


def _inline_ids(marker):
    # Adapted from Haystack AnswerBuilder._extract_reference_idxs (Apache-2.0).
    # Keep its comma-list extraction; do not expand ranges or map sparse IDs
    # by document position. The caller checks every ID against scoped evidence.
    matches = re.findall(_INLINE, marker)
    idxs: set[int] = set()
    for match in matches:
        for part in match.split(','):
            part = re.sub(r'^' + _LABEL, '', part.strip(), flags=re.IGNORECASE)
            idxs.add(int(part) - 1)
    return [str(index + 1) for index in sorted(idxs)]


def _possible_marker(tail):
    parts = tail[1:].split(',')
    if len(tail) > _MAX_INLINE_MARKER or len(parts) > _MAX_INLINE_REFERENCES:
        return False
    for index, part in enumerate(parts):
        part = part.lstrip(' \t') if index else part
        pattern = (_LABEL if not index else '(?:' + _LABEL + ')?') + _NUMBER + '[ \t]*'
        if re.fullmatch(pattern, part, re.IGNORECASE):
            continue
        if index == len(parts) - 1:
            return (any(label.startswith(part.lower()) for label in ('source ', 'source_', 'id:'))
                    or bool(re.fullmatch(_LABEL, part, re.IGNORECASE)))
        return False
    return True


def _literal_blocks(text, env):
    # Use the existing CommonMark parser's line maps, including code nested in
    # lists/quotes. Rendering and the original customer text remain unchanged.
    offsets = [0, *(match.end() for match in re.finditer(r'\r\n|\r|\n', text))]
    if offsets[-1] != len(text):
        offsets.append(len(text))
    tokens = _MARKDOWN.parse(text, env)
    maps = [token.map for token in tokens
            if token.type in {'code_block', 'fence', 'html_block'} and token.map]
    maps.extend(reference['map'] for reference in env.get('references', {}).values()
                if reference.get('map'))
    return sorted((offsets[start], offsets[end]) for start, end in maps)


def _quoted_marker(text, start):
    if not start:
        return False
    previous = text[start - 1]
    return (previous in '[\'"' or unicodedata.category(previous) in {'Pi', 'Pf', 'Ps'}
            or 'QUOTATION' in unicodedata.name(previous, ''))


def _marker_spans(text, available, *, partial=False):
    """Conservative labelled markers only; code, links and unknown IDs stay prose."""
    if '[' not in text and '<' not in text:
        return [], [], None
    spans, ids, code = [], [], None
    env = {}
    blocks = _literal_blocks(text, env)
    inline = StateInline(text, _MARKDOWN, env, [])
    position, block_index, html_code = 0, 0, []
    while token := _MARKUP.search(text, position):
        start, position = token.start(), token.end()
        value = token.group()
        while block_index < len(blocks) and blocks[block_index][1] <= start:
            block_index += 1
        if block_index < len(blocks) and blocks[block_index][0] <= start:
            # A streamed opening span alone can initially look like an HTML
            # block. Its immediate closing tag changes CommonMark's parse.
            # Hold only that bounded, scoped candidate until it is decidable.
            tag = HTML_TAG_RE.match(text[start:]) if partial and value == '<' else None
            if (tag and len(text) - start <= _MAX_INLINE_MARKER
                    and _citation_span_ids(tag.group(), available)
                    and _possible_span_closing(text[start + tag.end():])):
                return spans, ids, start
            position = blocks[block_index][1]
            continue
        if value.lower().startswith(('http://', 'https://')):
            boundary = re.search(r'[\s<>"\x27`]', text[position:])
            maximum = position + boundary.start() if boundary else len(text)
            destination = parseLinkDestination(text, start, maximum)
            position = destination.pos if destination.ok else maximum
            continue
        if value == '<':
            inline.pos = start
            if autolink(inline, True):
                position = inline.pos
                continue
            tag = HTML_TAG_RE.match(text[start:])
            literal = code or html_code or _quoted_marker(text, start)
            if tag:
                position = start + tag.end()
                references = None if literal else _citation_span_ids(tag.group(), available)
                if references:
                    closing = re.match(r'</span[ \t]*>', text[position:], re.IGNORECASE)
                    if closing and tag.end() + closing.end() <= _MAX_INLINE_MARKER:
                        end = position + closing.end()
                        spans.append((start, end))
                        ids.extend(references)
                        position = end
                        continue
                    if (partial and len(text) - start <= _MAX_INLINE_MARKER
                            and _possible_span_closing(text[position:])):
                        return spans, ids, start
                named = re.match(r'</?(code|pre|a)\b', tag.group(), re.IGNORECASE)
                if named and not code:
                    if tag.group().startswith('</'):
                        if html_code and html_code[-1] == named[1].lower():
                            html_code.pop()
                    elif not tag.group().endswith('/>'):
                        html_code.append(named[1].lower())
            elif partial and not literal and _possible_span_opening(text[start:]):
                return spans, ids, start
            continue
        if html_code:
            continue
        if value[0] in '`~':
            if code is None:
                code = value
            elif value == code or (len(code) >= 3 and value[0] == code[0] and len(value) >= len(code)):
                code = None
            continue
        if code or value != '[':
            continue
        match = _INLINE.match(text, start)
        if not match or (match.end() < len(text) and text[match.end()] == '('):
            inline.pos = start - 1 if start and text[start - 1] == '!' else start
            parser = image if inline.pos != start else link
            if parser(inline, True):
                position = inline.pos
                continue
        if _quoted_marker(text, start):
            # A quoted chain is one literal example, not independent markers.
            while match:
                position = match.end()
                match = _INLINE.match(text, position)
            continue
        if match:
            end = match.end()
            chain = [match]
            while adjacent := _INLINE.match(text, end):
                chain.append(adjacent)
                end = adjacent.end()
            if len(chain) > 1:
                references = list(dict.fromkeys(
                    reference for marker in chain for reference in _inline_ids(marker.group())))
                bounded = (end - start <= _MAX_INLINE_MARKER
                           and sum(marker.group().count(',') + 1 for marker in chain)
                           <= _MAX_INLINE_REFERENCES)
                scoped = bounded and set(references) <= available
                if partial and scoped:
                    # A reference definition may arrive later in the answer.
                    # Keep this ambiguous suffix until final CommonMark parsing.
                    return spans, ids, start
                defined = any(normalizeReference(marker.group()[1:-1])
                              in env.get('references', {}) for marker in chain)
                if scoped and not defined and (end == len(text) or text[end] not in '([:'):
                    if end == len(text) or text[end].isspace() or text[end] in '.,;:!?':
                        while start and text[start - 1] in ' \t':
                            start -= 1
                    spans.append((start, end))
                    ids.extend(references)
                position = end
                continue
            # Preserve Markdown links/reference labels instead of guessing that
            # a user-visible link label is private citation metadata.
            if end < len(text) and text[end] in '([:':
                if partial and text[end] == '[' and _possible_marker(text[end:]):
                    return spans, ids, start
                if text[end] in '([':
                    closing = ')' if text[end] == '(' else ']'
                    close = text.find(closing, end + 1)
                    position = close + 1 if close >= 0 else len(text)
                continue
            references = _inline_ids(match.group())
            # Apply the same raw-part and length bounds before deduplication
            # that the partial parser uses; emitted text cannot be retracted.
            bounded = (len(match.group()) <= _MAX_INLINE_MARKER
                       and match.group().count(',') < _MAX_INLINE_REFERENCES)
            if bounded and set(references) <= available:
                if normalizeReference(match.group()[1:-1]) in env.get('references', {}):
                    position = end
                    continue
                if partial:
                    # This label may become a shortcut link when its definition
                    # arrives later. Do not emit text that would need restoring.
                    return spans, ids, start
                if end == len(text) or text[end].isspace() or text[end] in '.,;:!?':
                    while start and text[start - 1] in ' \t':
                        start -= 1
                spans.append((start, end))
                ids.extend(references)
            position = end
        elif partial and _possible_marker(text[start:]):
            return spans, ids, start
        else:
            # A nested marker in a bracketed label is literal text. The upstream
            # helper handles escaped brackets and nested Markdown tokens.
            label_end = parseLinkLabel(inline, start)
            position = label_end + 1 if label_end >= 0 else len(text)
    return spans, ids, None


def clean_markers(text, *, partial=False, available=()):
    spans, _, pending = _marker_spans(text, set(available), partial=partial)
    if pending is not None:
        text = text[:pending]
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text


def _available_ids(items):
    return {citation_id for item in items
            if isinstance(citation_id := (getattr(item['chunk'], 'metadata_json', None) or {}).get('citation_id'), str)}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_answer_field')
        result[key] = value
    return result


def decode_answer(response, items, *, structured=False, normalize=False):
    if len(response) > 200_000:
        raise RetrievalError('generation_response_too_large')
    if structured:
        try:
            obj = json.loads(response, object_pairs_hook=_unique_object)
            if (not isinstance(obj, dict) or set(obj) != {'answer', 'source_ids'}
                    or not isinstance(obj['answer'], str) or not isinstance(obj['source_ids'], list)
                    or len(obj['source_ids']) > 64 or any(type(v) is not str for v in obj['source_ids'])):
                raise ValueError('invalid_answer_schema')
            response = obj['answer'] + '\n<source_refs>' + json.dumps(obj['source_ids']) + '</source_refs>'
        except (ValueError, TypeError):
            raise RetrievalError('invalid_answer_schema') from None
    answer, selected, audit = select_sources(response, items)
    if normalize:
        available = _available_ids(items)
        spans, inline_ids, _ = _marker_spans(answer, available)
        refs = list(dict.fromkeys(audit['selected_ids'] + inline_ids))
        if refs:
            answer, selected, normalized = select_sources(answer + '\n<source_refs>' + json.dumps(refs) + '</source_refs>', items)
            normalized['metadata_status'] = audit['status']
            normalized['invalid_count'] += audit['invalid_count']
            if normalized['invalid_count']:
                normalized['status'] = 'invalid_ids'
            audit = normalized
        answer = clean_markers(answer, available=available)
        audit['inline_markers_removed'] = len(spans)
    audit['structured_output'] = structured
    return answer, selected, audit


class AnswerContractStream:
    """Decode partial JSON using pydantic-core; metadata is never sent to users."""

    def __init__(self, on_delta, *, structured=False, normalize=False, items=()):
        self.on_delta, self.structured, self.normalize = on_delta, structured, normalize
        self.available = _available_ids(items)
        self.raw, self.forwarded = '', ''
        self.legacy = AttributionStream(self._publish)

    def _publish(self, delta):
        self.raw += delta
        self._send(clean_markers(self.raw, partial=True, available=self.available) if self.normalize else self.raw)

    def _send(self, visible):
        visible = visible.rstrip()
        if not visible.startswith(self.forwarded):
            raise RetrievalError('stream_prefix_changed')
        delta = visible[len(self.forwarded):]
        if delta:
            self.on_delta(delta)
            self.forwarded = visible

    def feed(self, delta):
        if not self.structured:
            self.legacy.feed(delta)
            return
        self.raw += delta
        if len(self.raw) > 200_000:
            raise RetrievalError('generation_response_too_large')
        try:
            obj = from_json(self.raw, allow_partial='trailing-strings')
        except ValueError:
            return
        visible = obj.get('answer', '') if isinstance(obj, dict) else ''
        if not isinstance(visible, str):
            return
        self._send(clean_markers(visible, partial=True, available=self.available) if self.normalize else visible)
