"""Verify uncrawled linked-heading subjects using the cited source document."""
import hashlib
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt('commonmark', {'html': False})


def canonical_url(value, base=''):
    try:
        parts = urlsplit(urljoin(base, value))
        scheme = parts.scheme.lower()
        if scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            host = '[' + host + ']'
        if parts.port is not None and parts.port != {'http': 80, 'https': 443}[scheme]:
            host += ':' + str(parts.port)
        unreserved = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
        path = re.sub(r'%([0-9a-fA-F]{2})', lambda match: (
            chr(int(match[1], 16)) if chr(int(match[1], 16)) in unreserved else '%' + match[1].upper()
        ), parts.path or '/')
        return urlunsplit((scheme, host, path, parts.query, ''))
    except (ValueError, TypeError, UnicodeError):
        return None


def heading_link(children):
    destinations, inside, label, prefix = [], False, [], []
    for child in children:
        if child.type == 'link_open':
            destinations.append(child.attrGet('href') or '')
            inside = True
        elif child.type == 'link_close':
            inside = False
        elif child.type in {'text', 'code_inline', 'html_inline', 'image'}:
            if inside and child.type != 'image':
                label.append(child.content)
            elif not inside and not destinations:
                prefix.append(child.content)
    if len(destinations) != 1 or re.search(r'\w', ''.join(prefix)) or not re.search(r'\w', ''.join(label)):
        return None
    return destinations[0], ''.join(label).strip()


def linked_subjects(source, records):
    origins = {urlsplit(value)[:2] for record in records
               if (value := canonical_url(record['url']))}
    environment, candidates = {}, []
    tokens = _MARKDOWN.parse(source['text'], environment)
    lines = source['text'].splitlines()
    for index, token in enumerate(tokens):
        if token.level != 0 or token.map is None:
            continue
        if token.type == 'heading_open' and tokens[index + 1].type == 'inline':
            candidates.append(tokens[index + 1])
        elif token.type == 'paragraph_open':
            for number in range(*token.map):
                wrapped = re.fullmatch(r'\s*(\*\*|__)(#{1,6})[ \t]+(.+?)\1\s*', lines[number])
                if wrapped:
                    candidates.append(_MARKDOWN.parseInline(wrapped[3], environment)[0])
    subjects = set()
    for inline in candidates:
        linked = heading_link(inline.children or [])
        url = canonical_url(linked[0], source['url']) if linked else None
        if url and urlsplit(url)[:2] in origins:
            subjects.add(('linked:' + hashlib.sha256(url.encode()).hexdigest(), linked[1]))
    return subjects
