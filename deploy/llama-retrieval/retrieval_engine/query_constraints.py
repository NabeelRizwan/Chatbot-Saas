"""Conservative query hints derived from corpus titles, without an LLM.

This is application routing glue, not a learned relevance model. Uncertain queries
retain the global hybrid search. No product names or benchmark questions live here.
"""
from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from urllib.parse import urlparse


def words(text):
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


def folded_word(text):
    return ''.join(char for char in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(char))


@dataclass(frozen=True)
class QueryHints:
    retrieval_query: str
    comparison_source_ids: tuple[str, ...]
    excluded_title_terms: tuple[str, ...]
    broad_discovery: bool


def _plural_form(term):
    if len(term) > 2 and term.endswith('y') and term[-2] not in 'aeiou':
        return term[:-1] + 'ies'
    if term.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return term + 'es'
    return term + 's'


def _literal_title_spans(text, full_titles):
    spans = []
    for title in full_titles:
        pattern = r'\b' + r'[\W_]+'.join(re.escape(token) for token in title) + r'\b'
        spans.extend(match.span() for match in re.finditer(pattern, text, re.I))
    return spans


def _asks_for_alternative_items(prefix):
    modifiers = r"(?:[^\W_]+(?:[-–][^\W_]+)*\s+){0,6}"
    return bool(re.search(
        rf'\b(?:(?:other|additional|alternative|different)\s+{modifiers}'
        r'(?:products|options|items|choices|models)|'
        rf'(?:what|which)\s+{modifiers}(?:products|options|items|choices|models)|'
        r'(?:what|anything|something)\s+else|suggest|recommend|'
        r'(?:can|could|should)\s+(?:I|we)\s+(?:consider|choose|try|buy))\b',
        prefix, re.I))


def _exclusion_parts(question, title_terms, full_titles=(), title_aliases=None):
    """Extract bounded noun lists without deleting their remaining grammar.

    Unknown list items or predicates remain verbatim. A regular plural may map
    to corpus title vocabulary; no synonym or product list is generated.
    """
    starter = re.compile(
        r"\b(?:(?:(?:I|we)\s+)?(?:don't|don’t|do\s+not)\s+want|"
        r"without\s+being|excluding|exclude|avoid|besides|no|not)\s+", re.I)
    boundary = re.compile(
        r"[.!?;:]|\b(?:but|however|instead|rather|except|although|yet)\b|"
        r",\s*(?=(?:compare|suggest|recommend|tell|show|find|which|what|how|where|when|why|can|could|would|I|we)\b)|"
        r"\b(?:and|or)\s+(?=(?:I|we|please|recommend|show|compare|tell|find|prefer|want|need)\b)", re.I)
    predicates = {'i','we','you','he','she','it','they','me','my','our','your','for',
                  'with','to','from','of','that','which','who','if','unless','because',
                  'is','are','be','being','was','were','can','could','would','should',
                  'has','have','does','do','need','want','prefer','like','recommend',
                  'find','show','compare','tell','use','wear','take'}

    def canonical(term):
        if term in title_terms:
            return term
        alternatives = [candidate for candidate in title_terms
                        if term == _plural_form(candidate) or _plural_form(term) == candidate]
        return alternatives[0] if len(alternatives) == 1 else None

    full_titles = {tuple(words(title)) for title in full_titles if words(title)}
    aliases = title_aliases or {}
    known_titles = full_titles | set(aliases)
    known_spans = _literal_title_spans(question, known_titles)

    def noun_phrase(text, exact_only=False):
        tokens = words(text)
        if tuple(tokens) in full_titles:
            return ' '.join(tokens)
        if tuple(tokens) in aliases:
            return ' '.join(aliases[tuple(tokens)])
        while tokens and tokens[0] in {'a','an','the','any','these','those','no'}:
            tokens.pop(0)
        if tuple(tokens) in full_titles:
            return ' '.join(tokens)
        if tuple(tokens) in aliases:
            return ' '.join(aliases[tuple(tokens)])
        if exact_only:
            # Resolve a shortened or reordered name only when every word
            # belongs to one known title. Unknown modifiers and shared model
            # names stay unresolved rather than excluding a whole family.
            if len(tokens) < 2 or set(tokens) & predicates:
                return None
            matches = [title for title in full_titles if set(tokens) <= set(title)]
            return ' '.join(matches[0]) if len(matches) == 1 else None
        if not tokens or len(tokens) > 4 or set(tokens) & predicates:
            return None
        resolved = [canonical(token) for token in tokens]
        if not resolved[-1]:
            return None
        # Drink/drinking can identify a consumable form rather than an entity.
        # Other unknown modifiers (e.g. a colour absent from titles) cannot be
        # discarded: "red shoes" must not exclude every shoe.
        if any(value is None and token not in {'drink','drinking'}
               for token,value in zip(tokens,resolved)):
            return None
        return ' '.join(value for value in resolved if value)

    excluded, removals, scanned_until = [], [], 0
    for match in starter.finditer(question):
        if match.start() < scanned_until or any(start <= match.start() < end for start,end in known_spans):
            continue
        ending = next((candidate for candidate in boundary.finditer(question, match.end())
                       if not any(start <= candidate.start() < end for start,end in known_spans)), None)
        end = ending.start() if ending else len(question)
        scanned_until = end
        kind = match.group().strip().casefold()
        if kind == 'besides' and not _asks_for_alternative_items(question[:match.start()]):
            # "What does this support besides joints?" asks for additional
            # benefits, not exclusion of a product named Joints.
            continue
        if kind == 'not':
            # A bare "not" is only a short explicit contrast, not a property
            # question such as "Is this not durable?".
            prefix = question[:match.start()].rstrip()
            if (prefix and prefix[-1] not in ',;:.?!') or not ending or ending.group().casefold() != 'but':
                continue
        body = question[match.end():end].strip(' ,')
        body = re.sub(r'\s+for\s+me\s*$', '', body, flags=re.I)
        # A comma or conjunction inside a verified full title is not a list
        # separator, including quoted titles and names longer than four words.
        title_spans = _literal_title_spans(body, known_titles)
        separators = [separator for separator in re.finditer(
            r'\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+', body, re.I)
            if not any(start <= separator.start() < finish for start,finish in title_spans)]
        items, previous = [], 0
        for separator in separators:
            items.append(body[previous:separator.start()])
            previous = separator.end()
        items.append(body[previous:])
        resolved = [noun_phrase(item, exact_only=kind == 'besides') for item in items]
        excluded.extend(value for value in resolved if value)
        if not resolved or any(value is None for value in resolved):
            continue
        remove_end = end
        if ending:
            marker = ending.group().strip().casefold()
            if marker in {'but','however','instead','rather','except','although','yet'}:
                # Keep the contrast: dropping "but not" could turn a second
                # negative into a positive. Only the noun exclusion is removed.
                pass
            elif marker in {',',':',';'} or re.match(r'^(?:and|or)\b', marker):
                remove_end = ending.end()
            elif marker in {'.','?','!'}:
                prefix = re.split(r'[.!?;:]', question[:match.start()])[-1]
                if not prefix.strip():
                    remove_end = ending.end()
        removals.append((match.start(), remove_end))
    retrieval = _replace_spans(question, removals, '')
    retrieval = re.sub(r'\s+([,.;:?!])', r'\1', ' '.join(retrieval.split()))
    retrieval = re.sub(r'^[,;:.!?\s]*(?:but|however|yet)\s+', '', retrieval, flags=re.I)
    retrieval = retrieval.strip(' ,:;') or question
    return tuple(dict.fromkeys(excluded)), retrieval


def _literal_catalog_subjects(question, documents, excluded):
    """Prefer non-overlapping catalog names over loose word overlap.

    A frequently repeated leading title prefix may be omitted by a customer.
    All aliases still consist of original, contiguous title words. Numeric
    variants retain their numbers; no query facts or learned aliases enter here.
    """
    catalog = {d['source_id']: tuple(words(d['title'])) for d in documents}
    counts = Counter(word for title in catalog.values() for word in set(title))
    from ._vendor_flashtext import KeywordProcessor
    owners = {}
    for doc in documents:
        if title_is_excluded(doc['title'], QueryHints('', (), excluded, False)):
            continue
        title = catalog[doc['source_id']]
        shortened = list(title)
        while len(shortened) > 1 and counts[shortened[0]] >= max(3, len(catalog) * .6):
            shortened.pop(0)
        aliases = {title, tuple(shortened)}
        # Website titles sometimes repeat the site's own brand after a common
        # catalog qualifier. An exact hostname label is metadata, not a synonym.
        # Only a leading label may be omitted; the remaining title stays intact.
        try:
            host = (urlparse(doc.get('url', '')).hostname or '').casefold()
        except (TypeError, ValueError):
            host = ''
        host_labels = {label for label in host.split('.')[:-1] if len(label) >= 4} - {'shop', 'store'}
        if len(shortened) > 1 and shortened[0] in host_labels:
            aliases.add(tuple(shortened[1:]))
        for alias in aliases:
            if not alias or (len(alias) == 1 and len(alias[0]) < 5):
                continue
            owners.setdefault(' '.join(alias), set()).add(doc['source_id'])
    processor = KeywordProcessor(case_sensitive=True)
    for character in set(' '.join(owners) + question.casefold()):
        if character.isalnum():
            processor.add_non_word_boundary(character)
    for alias, sources in owners.items():
        processor.add_keyword(alias, tuple(sorted(sources)))
    matches = processor.extract_keywords(' '.join(words(question)))
    if any(len(sources) != 1 for sources in matches):
        return ()
    return tuple(dict.fromkeys(sources[0] for sources in matches))


def query_hints(question, documents, exclusion_titles=()):
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    documents = list(documents)
    stop = ENGLISH_STOP_WORDS | {'product', 'products', 'supplement', 'supplements'}
    titles = {d['source_id']: [w for w in words(d['title']) if w not in stop and not w.isdigit()]
              for d in documents}
    # Numbers distinguish model variants only when the corpus has sibling titles
    # differing by those numbers. A unique title may still have a common alias
    # that omits its number (for example an omega-3 product).
    variants = {}
    for doc in documents:
        parts = tuple(words(doc['title']))
        family = tuple(w for w in parts if not w.isdigit())
        variants.setdefault(family, set()).add(tuple(w for w in parts if w.isdigit()))
    counts = Counter(t for title in titles.values() for t in set(title))
    query_words = set(words(question))
    # Parser-verified linked subjects may be excluded but must never become
    # comparison scopes: only actual documents participate in matching below.
    additional_titles = [title for title in exclusion_titles if isinstance(title,str) and title.strip()]
    exclusion_counts = counts.copy()
    exclusion_counts.update(word for title in additional_titles for word in set(words(title))
                            if word not in stop and not word.isdigit())
    excluded, retrieval_query = _exclusion_parts(question, exclusion_counts,
        [document['title'] for document in documents] + additional_titles,
        _site_prefixed_exclusion_aliases(documents))
    broad = bool(re.search(r'\b(?:options|products|suggest|recommend|which\s+\w+s)\b', question, re.I))
    besides = re.search(r'\bbesides\s+', question, re.I)
    if excluded and besides and _asks_for_alternative_items(question[:besides.start()]):
        broad = True
    comparison = bool(re.search(r'\b(?:compar(?:e[ds]?|ing|ison)|versus|vs|between|different|difference|than|or|both|either)\b', question, re.I))
    if comparison:
        literal = _literal_catalog_subjects(question, documents, excluded)
        if 2 <= len(literal) <= 4:
            return QueryHints(retrieval_query, literal, excluded, False)
    matched = []
    if comparison:
        for source_id, title in titles.items():
            full_title_text = next(d['title'] for d in documents if d['source_id'] == source_id)
            if not title or title_is_excluded(full_title_text, QueryHints('', (), excluded, False)):
                continue
            shared = set(title) & query_words
            full_title = words(full_title_text)
            family = tuple(w for w in full_title if not w.isdigit())
            numbers = {w for w in full_title if w.isdigit()}
            if len(variants.get(family, ())) > 1 and not numbers.issubset(query_words):
                continue
            query_sequence = words(question)
            exact = any(query_sequence[i:i+len(full_title)] == full_title
                        for i in range(len(query_sequence)-len(full_title)+1))
            if len(variants.get(family, ())) > 1 and not exact:
                # A number elsewhere in the question may be a requested
                # measurement, not a mention of this other model variant.
                continue
            prefix = len(title) >= 2 and all(w in query_words for w in title[:2])
            unique_lead = counts[title[0]] == 1 and title[0] in query_words and len(title[0]) >= 5
            weight = lambda w: 1 + math.log((1 + len(titles))/(1 + counts[w]))
            coverage = sum(weight(w) for w in shared) / sum(weight(w) for w in set(title))
            distinctive = len(shared) >= 2 and any(counts[w] == 1 for w in shared)
            if exact or prefix or unique_lead or distinctive or (len(shared) >= 2 and coverage >= .5):
                matched.append((source_id, coverage, len(shared)))
    # Broad single-name collisions never constrain discovery. More than four
    # matches is ambiguous, so leave the full search available.
    ids = tuple(s for s, _, _ in sorted(matched, key=lambda v:(-v[1], -v[2], v[0]))) if 2 <= len(matched) <= 4 else ()
    return QueryHints(retrieval_query, ids, excluded, broad and not ids)


def _site_prefixed_exclusion_aliases(documents):
    """Resolve a site's decorative prefix only for a complete, unique title."""
    titles = {tuple(words(doc['title'])) for doc in documents}
    owners = {}
    for doc in documents:
        title = tuple(words(doc['title']))
        try:
            host = (urlparse(doc.get('url', '')).hostname or '').casefold()
        except (TypeError, ValueError):
            continue
        for label in host.split('.')[:-1]:
            if len(label) < 4 or label in {'www', 'shop', 'store'} or len(words(label)) != 1:
                continue
            if title and title[0] != label:
                owners.setdefault((label, *title), set()).add(title)
    # Never let an inferred alias shadow a real named variant in the corpus.
    return {alias: next(iter(matches)) for alias, matches in owners.items()
            if len(matches) == 1 and alias not in titles}


def title_is_excluded(title, hints):
    normalized = words(title)
    for term in hints.excluded_title_terms:
        phrase = words(term)
        for start in range(len(normalized) - len(phrase) + 1):
            found = normalized[start:start + len(phrase)]
            if not all(left == right or _plural_form(left) == right or _plural_form(right) == left
                       for left,right in zip(found,phrase)):
                continue
            before, after = normalized[:start], normalized[start + len(phrase):]
            absent = (after[:1] == ['free'] or before[-1:] in [['free'],['without'],['no']]
                      or before[-2:] in [['free','of'],['free','from']])
            if not absent:
                return True
    return False


_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_COMPARISON = re.compile(r"\b(?:compare|comparison|versus|vs|between|different|differences?|than|or)\b", re.I)
_ASPECT_INTRO = re.compile(r"\b(?:on|in|for|by)\b", re.I)
_ALIAS_FUNCTION_WORDS = frozenset({'a', 'an', 'the', 'and', 'or', 'of', 'for', 'in', 'on', 'by', 'with', 'to'})


def _title_mentions(question, compared_titles):
    """Find one literal mention per title without consuming task properties.

    Exact token sequences take precedence. A shortened name must be a contiguous
    query phrase made of title terms with a term distinctive among the compared
    titles. Ambiguous aliases are deliberately left in the query.
    """
    compared_titles = list(compared_titles)
    model_heads = {folded_word(match.group()) for title in compared_titles
                   if (match := _WORD.search(title)) and match.group().isupper() and len(match.group()) >= 4}
    titles = list(dict.fromkeys(tuple(folded_word(w) for w in words(title)) for title in compared_titles))
    titles = [title for title in titles if title]
    tokens = [(folded_word(match.group()), match.start(), match.end())
              for match in _WORD.finditer(question)]
    counts = Counter(term for title in titles for term in set(title))
    exact = {}
    for index, title in enumerate(titles):
        exact[index] = [(tokens[start][1], tokens[start + len(title) - 1][2])
                        for start in range(len(tokens) - len(title) + 1)
                        if tuple(token[0] for token in tokens[start:start + len(title)]) == title]

    # A property introducer inside an actual full title ("Kit for Travel") is
    # not a task boundary. Names repeated after the boundary are task text.
    marker = _COMPARISON.search(question)
    boundary = len(question)
    if marker:
        full_spans = [span for spans in exact.values() for span in spans]
        boundary = next((match.start() for match in _ASPECT_INTRO.finditer(question, marker.end())
                         if not any(start <= match.start() < end for start, end in full_spans)), boundary)

    chosen = {}

    def free(span):
        return not any(span[0] < end and start < span[1] for start, end in chosen.values())

    # Longest titles win overlapping mentions, and only their first usable
    # occurrence is removed. Repeated names in a later predicate survive.
    order = sorted(range(len(titles)), key=lambda index: -len(titles[index]))
    for index in order:
        span = next((span for span in exact[index] if span[1] <= boundary and free(span)), None)
        if span:
            chosen[index] = span

    for index in order:
        if index in chosen:
            continue
        title, candidates = titles[index], []
        content = [term for term in title if term not in _ALIAS_FUNCTION_WORDS]
        # One shared leading catalog qualifier may be omitted. Do not strip
        # an entire shared product family down to a colour or other attribute.
        if len(content) > 1 and counts[content[0]] == len(titles):
            content.pop(0)
            if len(content) > 1 and content[0] == 's' and counts['s'] == len(titles):
                content.pop(0)
        for start in range(len(tokens)):
            if tokens[start][1] >= boundary or tokens[start][0] not in title:
                continue
            end = start
            while end < len(tokens) and tokens[end][2] <= boundary and tokens[end][0] in title:
                # Punctuation may separate words in a name, but a clause
                # boundary is not evidence of a contiguous title alias.
                if end > start and re.search(r"[,;:?!]", question[tokens[end - 1][2]:tokens[end][1]]):
                    break
                end += 1
            alias = [token[0] for token in tokens[start:end]]
            meaningful = [term for term in alias if term not in _ALIAS_FUNCTION_WORDS]
            distinctive = any(counts[term] == 1 for term in meaningful)
            multiword = len(meaningful) >= 2 and distinctive
            unique_lead = (len(alias) == 1 and content and alias[0] == content[0]
                           and (len(alias[0]) >= 5 or alias[0] in model_heads) and counts[alias[0]] == 1)
            if (multiword or unique_lead) and end > start:
                span = (tokens[start][1], tokens[end - 1][2])
                if free(span):
                    candidates.append((len(alias), span))
        if candidates:
            chosen[index] = min(candidates, key=lambda candidate: (-candidate[0], candidate[1][0]))[1]
    return sorted(chosen.values())


def _replace_spans(text, spans, replacement=' '):
    parts, previous = [], 0
    for start, end in sorted(spans):
        if start < previous:
            continue
        parts.extend((text[previous:start], replacement))
        previous = end
    parts.append(text[previous:])
    return ''.join(parts)


def focused_query(question, target_title, compared_titles):
    """Keep the requested task/constraints, evaluating one explicit subject.

    Surface terms come only from matched corpus titles. This deterministic
    query decomposition does not generate facts, synonyms or answers.
    """
    mentions = _title_mentions(question, compared_titles)
    removals = list(mentions)
    for left, right in zip(mentions, mentions[1:]):
        between = question[left[1]:right[0]]
        if re.fullmatch(r"\s*(?:(?:and|or|versus|vs|than|with)\b\.?|[,/&]|\s)+(?:the\s+)?", between, re.I):
            removals.append((left[1], right[0]))
    if mentions:
        leading_compare = re.search(r'\bcompare\s+(?:the\s+)?$', question[:mentions[0][0]], re.I)
        if leading_compare:
            removals.append(leading_compare.span())
    residual = _replace_spans(question, removals)
    residual = ' '.join(residual.split()).strip(' ,:;')
    return f'{target_title}. {residual}' if residual else target_title


def explicit_query_aspects(question, compared_titles):
    """Return two or three literal property spans in an explicit comparison.

    This intentionally declines negative constraints, extra predicates and
    ambiguous clauses. An empty tuple means callers must keep the full task;
    it does not mean that an ignored property has been satisfied.
    """
    titles = list(compared_titles)
    if len({tuple(words(title)) for title in titles}) < 2:
        return ()
    mentions = _title_mentions(question, titles)
    if len(mentions) < 2:
        return ()
    masked = _replace_spans(question, mentions, '@')
    # Negation in a matched product name is not a user constraint. Everywhere
    # else it stays with the original task instead of being lost in splitting.
    if re.search(r"\b(?:no|not|never|without|except|excluding|avoid|only|unless|rather)\b|n['’]t\b", masked, re.I):
        return ()
    entity = r'(?:the\s+)?@'
    subjects = rf'{entity}(?:\s*(?:,\s*(?:and\s+)?|and\s+|or\s+|with\s+|versus\s+|vs\.?\s+|&\s*){entity}){{1,3}}'
    safe_prefix = re.compile(
        rf'(?:compare\s+{subjects}|'
        rf'how\s+(?:are|is)\s+{subjects}\s+different|'
        rf'how\s+(?:do|does)\s+{subjects}\s+differ|'
        rf'(?:what\s+(?:is|are)\s+(?:the\s+)?)?differences?\s+between\s+{subjects}|'
        rf'{entity}\s+(?:versus|vs\.?)\s+{entity})', re.I)
    for intro in _ASPECT_INTRO.finditer(question, mentions[-1][1]):
        prefix_mentions = [span for span in mentions if span[1] <= intro.start()]
        prefix = _replace_spans(question[:intro.start()], prefix_mentions, '@').strip()
        prefix = re.sub(r'^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?', '', prefix, flags=re.I)
        if not safe_prefix.fullmatch(prefix):
            continue
        requested = question[intro.end():].strip().rstrip('.?!').strip()
        if re.search(r'[;:?!()]|\bor\b', requested, re.I):
            return ()
        pieces = tuple(piece.strip() for piece in re.split(r'\s*,\s*(?:and\s+)?|\s+and\s+', requested, flags=re.I))
        if not 2 <= len(pieces) <= 3 or any(not piece for piece in pieces):
            return ()
        if any(not 1 <= len(words(piece)) <= 8 for piece in pieces):
            return ()
        # A literal short noun phrase is sufficient; a new question, condition
        # or verbal clause must remain part of the complete original query.
        unsafe = r'\b(?:whether|which|what|when|where|why|how|if|because|that|who|whose|is|are|was|were|be|can|could|will|would|should|must|has|have|does|do|it|they|them|me|my|your)\b'
        if any(re.search(unsafe, piece, re.I) for piece in pieces):
            return ()
        if len({tuple(words(piece)) for piece in pieces}) != len(pieces):
            return ()
        return pieces
    return ()
