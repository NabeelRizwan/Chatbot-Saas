"""Exact source and rendering contract for optional context supplements."""
from collections.abc import Mapping

def _field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)

def _encode(tokenizer, text):
    if callable(tokenizer):
        return tokenizer(text)
    try:
        return tokenizer.encode(text, disallowed_special=())
    except TypeError:
        return tokenizer.encode(text)

def _subject(node):
    return str(node.metadata.get('subject_source_id') or node.metadata['source_id'])

def _checked(node, documents):
    source = str(node.metadata['source_id'])
    if source not in documents:
        raise ValueError('Unknown source.')
    document = documents[source]
    text = _field(document, 'text')
    a, b = node.start_char_idx, node.end_char_idx
    if (not isinstance(text, str) or type(a) is not int or type(b) is not int
            or not 0 <= a < b <= len(text) or text[a:b] != node.text
            or node.metadata.get('url', '') != _field(document, 'url', '')):
        raise ValueError('Source text, offset, or URL mismatch.')
    return source, document, text, a, b

def _covered(a, b, intervals, text):
    """Only source interval coverage counts; no semantic/text deduplication."""
    cursor = a
    for left, right in sorted(intervals):
        if right <= cursor or left >= b:
            continue
        if left > cursor and text[cursor:left].strip():
            return False
        cursor = max(cursor, right)
        if cursor >= b:
            return True
    return not text[cursor:b].strip()

def _headers(node, source, document, text, a, b):
    m = node.metadata
    keys = ('table_header', 'table_header_start_char_idx', 'table_header_end_char_idx',
            'table_start_char_idx', 'table_end_char_idx')
    if not any(key in m for key in keys):
        return []
    header, start, end, table_start, table_end = [m.get(key) for key in keys]
    if (not isinstance(header, str) or not header.strip()
            or any(type(value) is not int for value in (start, end, table_start, table_end))
            or not 0 <= table_start == start < end <= table_end <= len(text)
            or text[start:end] != header
            or not table_start <= node.start_char_idx < node.end_char_idx <= table_end):
        raise ValueError('Table header provenance mismatch.')
    included = not (a <= start + len(header) - len(header.lstrip())
                    and end - len(header) + len(header.rstrip()) <= b)
    return [{'text': header, 'start_char': start, 'end_char': end,
             'source_id': source, 'url': _field(document, 'url', ''),
             'included_in_context': included}]

def _header_text(item):
    return ''.join(f"Table header (source characters {h['start_char']}–{h['end_char']}):\n{h['text'].rstrip()}\n"
                   for h in item['table_headers'] if h['included_in_context'])

def render_item(item):
    subject = (f"Subject: {item['subject_title']}\n"
               if item['subject_source_id'] != item['source_id'] else '')
    roles = ', '.join(item['evidence_roles'])
    role = f'Structural evidence roles: {roles}\n' if roles else ''
    return (f"[Source {item['citation_id']}] {item['title']}\n{subject}"
            f"Section: {item['section']}\n{role}URL: {item['url']}\n"
            f"{_header_text(item)}{item['text']}")
