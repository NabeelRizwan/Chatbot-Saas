"""Request-scoped citation provenance with conservative formatting equivalence.

This verifies quotation presence, NOT that surrounding claims follow from it.
Raw answers, evidence, numbers and instruction prompts are never rewritten.
No fuzzy matching, corpus search or ellipsis/wildcard expansion is performed.
"""
import hashlib
import re
import unicodedata
import regex
from markdown_it import MarkdownIt

PARSER = MarkdownIt('commonmark', {'html': False, 'typographer': False,
                                 'linkify': False})
WORD_BOUNDARY = regex.compile(r'\b', regex.WORD | regex.VERSION1)
WORD_CHARACTER = regex.compile(r'\w', regex.VERSION1)
GRAPHEME = regex.compile(r'\X', regex.VERSION1)

# Bound optional parsing work, never the answer or source evidence. Exact
# and NFC/whitespace matching remain available if this projection is skipped.
MAX_MARKDOWN_SOURCE_CHARS = 32768
MAX_MARKDOWN_REQUEST_CHARS = 262144

def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())

def visible_markdown(text):
    """Extract parsed text, preserving code and literal punctuation.

    Links contribute their label; targets remain in trusted metadata, not in
    the quotation. Block boundaries become whitespace. HTML is not executed.
    Returned offsets are in this projection, never claimed as raw offsets.
    """
    blocks = []
    for token in PARSER.parse(text):
        if token.type == 'inline':
            parts = []
            for child in token.children or []:
                if child.type in ('text', 'code_inline', 'html_inline'):
                    parts.append(child.content)
                elif child.type in ('softbreak', 'hardbreak'):
                    parts.append(' ')
                elif child.type == 'image':
                    # Image alt text may contain emphasis tokens. Preserve
                    # every literal label while removing only source markup.
                    parts.append(inline_text(child.children or []))
            blocks.append(''.join(parts))
        elif token.type in ('fence', 'code_block', 'html_block'):
            blocks.append(token.content)
    return normalized(' '.join(blocks))

def inline_text(children):
    parts = []
    for child in children:
        if child.type in ('text', 'code_inline', 'html_inline'):
            parts.append(child.content)
        elif child.type in ('softbreak', 'hardbreak'):
            parts.append(' ')
        elif child.type == 'image':
            parts.append(inline_text(child.children or []))
    return ''.join(parts)

def label_keys(value, allow_underscore=True):
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        value = value[1:-1].strip()
    match = re.fullmatch(r'(?i:source)(.+)', value, re.DOTALL)
    if not match:
        return set()
    suffix = match.group(1).strip()
    keys = {suffix} if suffix else set()
    if allow_underscore and suffix.startswith('_') and suffix[1:].strip():
        keys.add(suffix[1:].strip())
    return keys

def whole_graphemes(text, start, end, cache):
    """Quote endpoints must not split a Unicode grapheme cluster.

    ASCII boundaries are already separate clusters except CRLF. Only build
    the per-projection boundary cache when a Unicode endpoint needs it.
    """
    edge_chars = text[max(0, start-1):start+1] + text[max(0, end-1):end+1]
    if edge_chars.isascii() and '\r\n' not in edge_chars:
        return True
    boundaries = cache.get(text)
    if boundaries is None:
        boundaries = {0}
        boundaries.update(match.end() for match in GRAPHEME.finditer(text))
        cache[text] = boundaries
    return start in boundaries and end in boundaries

def bounded_span(haystack, needle, grapheme_cache=None):
    """Avoid matching fragments of another word/number; no semantic inference."""
    start = 0
    while needle:
        pos = haystack.find(needle, start)
        if pos < 0:
            return None
        end = pos + len(needle)
        before = haystack[pos - 1] if pos else ''
        after = haystack[end] if end < len(haystack) else ''
        # Unicode word boundaries include combining marks and allow scripts
        # whose words are not separated by ASCII spaces. No accent folding.
        left_ok = not WORD_CHARACTER.fullmatch(needle[0]) or WORD_BOUNDARY.match(haystack, pos) is not None
        right_ok = not WORD_CHARACTER.fullmatch(needle[-1]) or WORD_BOUNDARY.match(haystack, end) is not None
        # Preserve mathematical/full-width signs as well as ASCII signs.
        # This is a boundary check, not replacement or numeric coercion.
        if needle[0].isdigit() and before in ('-', '+', '\u2212', '\uff0d', '\uff0b', '\u00b1', '.', ','):
            left_ok = False
        if needle[-1].isdigit() and after in ('.', ',') and end + 1 < len(haystack) and haystack[end + 1].isdigit():
            right_ok = False
        if left_ok and right_ok and whole_graphemes(haystack, pos, end, grapheme_cache if grapheme_cache is not None else {}):
            return pos, end
        start = pos + 1
    return None

class CitationRegistry:
    allow_markdown = True
    allow_underscore = True

    def __init__(self, available, context):
        self.available = available
        self._context = context
        self._aliases = {cid: {cid} for cid in available}
        self._normalized = {}
        self._visible = {}
        self._source_hashes = {}
        self._normalized_context = None
        self._grapheme_boundaries = {}
        self._markdown_chars = 0
        self.diagnostics = []
        self.matches = {}
        # A real ID that resembles a display alias blocks ambiguous variants.
        # Exact literal IDs always win before alias resolution.
        for cid in available:
            for key in label_keys(cid, self.allow_underscore):
                if key in self._aliases:
                    self._aliases[key].add(cid)

    def resolve(self, value):
        if not isinstance(value, str):
            return None
        if value in self.available:
            return value
        matches = set()
        for key in label_keys(value, self.allow_underscore):
            matches.update(self._aliases.get(key, ()))
        return next(iter(matches)) if len(matches) == 1 else None

    def quote_match(self, cid, quote):
        if cid not in self.available or not isinstance(quote, str) or not quote.strip():
            return None
        text = self.available[cid]['text']
        span = bounded_span(text, quote, self._grapheme_boundaries)
        if span is not None:
            return self._record(cid, quote, text, 'exact', span)
        if cid not in self._normalized:
            self._normalized[cid] = normalized(text)
        # Avoid Markdown parsing for the common exact-match path.
        span = bounded_span(self._normalized[cid], normalized(quote), self._grapheme_boundaries)
        if span is not None:
            return self._record(cid, quote, text, 'nfc_whitespace', span)
        if self.allow_markdown:
            if cid not in self._visible:
                if len(text) > MAX_MARKDOWN_SOURCE_CHARS or self._markdown_chars + len(text) > MAX_MARKDOWN_REQUEST_CHARS:
                    self.diagnostics.append({'source_id': cid, 'code': 'markdown_projection_budget_exceeded'})
                    self._visible[cid] = None
                    return None
                self._markdown_chars += len(text)
                self._visible[cid] = visible_markdown(text)
            # Never parse away details from the claimed quote: doing so can
            # erase a changed URL or list ordinal and create false provenance.
            excerpt = normalized(quote)
            if self._visible[cid] is not None and excerpt:
                span = bounded_span(self._visible[cid], excerpt, self._grapheme_boundaries)
                if span is not None:
                    return self._record(cid, quote, text, 'markdown_source_visible_literal_quote', span)
        return None

    def _record(self, cid, quote, text, mode, span):
        quote_hash = hashlib.sha256(quote.encode()).hexdigest()
        cached_hash = self._source_hashes.get(cid)
        if cached_hash is None or cached_hash[0] != text:
            cached_hash = (text, hashlib.sha256(text.encode()).hexdigest())
            self._source_hashes[cid] = cached_hash
        key = cid + ':' + quote_hash
        self.matches[key] = {'source_id': cid, 'mode': mode,
            'source_sha256': cached_hash[1],
            'quote_sha256': quote_hash,
            'match_start': span[0], 'match_end': span[1],
            'offset_coordinates': 'raw_source' if mode == 'exact' else mode + '_projection'}
        return mode

    def context_contains_quote(self, quote):
        # Diagnostic only. Source attachment ALWAYS requires quote_match on
        # its own authorised passage, not a match elsewhere in the context.
        if not quote:
            return False
        if quote in self._context:
            return True
        if self._normalized_context is None:
            self._normalized_context = normalized(self._context)
        return normalized(quote) in self._normalized_context
