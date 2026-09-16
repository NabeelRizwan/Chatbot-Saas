"""Offline structural serialization. No storage, provider, activation or retrieval.

See the Phase 4.1E OSS ledger. Frozen structural DTOs are the source of truth;
chunks refer to the batch's immutable graph for attributes, edges and provenance.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
from importlib.metadata import version
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
from types import FunctionType
from typing import Literal

from pydantic import Field, model_validator

from services.structural_document import (
    ByteRange, ChunkStructuralMapping, Digest, NodeIdentity, RevisionIdentity,
    StructuralDocument, StructuralNode, Value,
)


class SerializationError(ValueError):
    """Typed refusal; never partial success or silent truncation."""


class ChunkPolicy(Value):
    version: Literal['structure-chunk-v1'] = 'structure-chunk-v1'
    target: int = Field(default=450, ge=1, le=800)
    merge_min: int = Field(default=250, ge=1, le=800)
    merge_max: int = Field(default=650, ge=1, le=800)
    hard_max: int = Field(default=800, ge=1, le=800)
    prefix_max: int = Field(default=80, ge=0, le=80)
    overlap_max: int = Field(default=60, ge=0, le=60)
    max_mappings: int = Field(default=256, ge=1, le=1024)
    max_parts: int = Field(default=256, ge=1, le=1024)
    max_chunks: int = Field(default=10000, ge=1, le=20000)
    max_input_bytes: int = Field(default=16_777_216, ge=1, le=33_554_432)
    max_output_bytes: int = Field(default=33_554_432, ge=1, le=67_108_864)
    max_byte_expansion: int = Field(default=8, ge=1, le=16)
    max_chunks_per_node: int = Field(default=256, ge=1, le=256)
    max_memberships: int = Field(default=100000, ge=1, le=100000)
    max_batch_bytes: int = Field(default=67_108_864, ge=1, le=67_108_864)

    @model_validator(mode='after')
    def ordered(self):
        if not self.merge_min <= self.target <= self.merge_max <= self.hard_max:
            raise ValueError('inconsistent chunk budgets')
        if self.prefix_max >= self.hard_max:
            raise ValueError('prefix leaves no evidence budget')
        return self


@lru_cache(maxsize=1)
def local_tokenizer():
    """Use the installed cl100k recipe, but make a download impossible.

    No global monkeypatch: only this new function's globals see our BPE loader.
    Missing/corrupt assets fail closed. encode_ordinary treats special strings as data.
    """
    import tiktoken
    from tiktoken_ext import openai_public

    def offline_bpe(url, expected_hash):
        cache = os.environ.get('TIKTOKEN_CACHE_DIR', os.environ.get(
            'DATA_GYM_CACHE_DIR', str(Path(tempfile.gettempdir()) / 'data-gym-cache')))
        path = Path(cache) / hashlib.sha1(url.encode()).hexdigest()
        try:
            data = path.read_bytes()
        except OSError:
            raise SerializationError('local tokenizer asset unavailable') from None
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise SerializationError('local tokenizer checksum mismatch')
        return {base64.b64decode(token, validate=True): int(rank)
                for token, rank in (line.split() for line in data.splitlines() if line)}

    original = openai_public.cl100k_base
    scope = dict(original.__globals__, load_tiktoken_bpe=offline_bpe)
    factory = FunctionType(original.__code__, scope)
    params = factory()
    fingerprint = digest({'name': params['name'], 'version': version('tiktoken'),
                          'factory': inspect.getsource(original),
                          'ranks': hashlib.sha256(b''.join(
                              k + str(v).encode() + b'\n' for k, v in
                              sorted(params['mergeable_ranks'].items()))).hexdigest()})
    return tiktoken.Encoding(**params), fingerprint


def count_tokens(text: str) -> int:
    return len(local_tokenizer()[0].encode_ordinary(text))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


class MappedSpan(Value):
    mapping: ChunkStructuralMapping
    usage: Literal['primary', 'inherited', 'overlap']


class ExcludedSpan(Value):
    node: NodeIdentity
    node_slice: ByteRange
    reason: Literal['navigation', 'furniture', 'quarantine', 'link_metadata_only']


class StructuralChunkSpec(Value):
    revision: RevisionIdentity
    chunk_key: Digest
    ordinal: int = Field(ge=0)
    text: str
    source_nodes: tuple[NodeIdentity, ...]
    heading_path: tuple[NodeIdentity, ...]
    # All members, including empty containers, remain resolvable in source_graph.
    members: tuple[NodeIdentity, ...]
    bundle_key: Digest
    kind: str
    part_index: int = Field(ge=0)
    part_count: int = Field(gt=0)
    complete_unit: bool
    source_block_complete: bool | None
    list_item_indices: tuple[tuple[str, int], ...]
    table_cells: tuple[NodeIdentity, ...]
    mappings: tuple[MappedSpan, ...]
    token_count: int = Field(ge=0, le=800)
    prefix_tokens: int = Field(ge=0, le=80)
    byte_count: int = Field(ge=0)
    policy: ChunkPolicy
    input_hash: Digest
    recipe_hash: Digest


class SerializationBatch(Value):
    source_graph: StructuralDocument
    chunks: tuple[StructuralChunkSpec, ...]
    metadata_only_nodes: tuple[NodeIdentity, ...]
    excluded: tuple[ExcludedSpan, ...]
    input_hash: Digest
    recipe_hash: Digest

    def verify(self):
        """Revalidate at the boundary, including exact UTF-8 output mapping."""
        nodes = {n.identity.node_key: n for n in self.source_graph.nodes}
        for ordinal, c in enumerate(self.chunks):
            if c.ordinal != ordinal or c.revision != self.source_graph.revision.identity:
                raise SerializationError('chunk order/ownership mismatch')
            if c.byte_count != len(c.text.encode()) or c.token_count != count_tokens(c.text):
                raise SerializationError('chunk counts mismatch')
            if c.token_count > c.policy.hard_max or len(c.mappings) > c.policy.max_mappings:
                raise SerializationError('chunk bound exceeded')
            if c.part_index >= c.part_count or c.part_count > c.policy.max_parts:
                raise SerializationError('part bound exceeded')
            for identity in (*c.members, *c.heading_path, *c.source_nodes):
                if identity.node_key not in nodes or nodes[identity.node_key].identity != identity:
                    raise SerializationError('unknown source identity')
            covered = set()
            for i, span in enumerate(c.mappings):
                m = span.mapping
                n = nodes[m.node.node_key]
                if m.node != n.identity or m.chunk_id != c.chunk_key or m.ordinal != i:
                    raise SerializationError('mapping identity mismatch')
                a, b = m.node_slice, m.output_slice
                if a.end > len(n.text.encode()) or b.end > c.byte_count or m.chunk_revision != c.revision:
                    raise SerializationError('mapping bounds/ownership mismatch')
                if (m.bundle_key, m.part_index, m.part_count) != (c.bundle_key,c.part_index,c.part_count):
                    raise SerializationError('mapping bundle mismatch')
                source = n.text.encode()[a.start:a.end]
                output = c.text.encode()[b.start:b.end]
                if not source or source != output:
                    raise SerializationError('mapping byte mismatch')
                source.decode('utf-8')  # refuse mid-codepoint offsets
                covered.update(range(b.start, b.end))
            # Only our explicit newline separators may lack a source claim.
            if any(byte != 10 and i not in covered for i, byte in enumerate(c.text.encode())):
                raise SerializationError('unmapped evidence')
        return self


@dataclass(frozen=True)
class Piece:
    key: str
    start: int
    end: int
    role: str = 'body'
    usage: str = 'primary'


@dataclass
class Unit:
    keys: list[str]
    roots: list[str]
    kind: str
    boundary: tuple
    headings: tuple[str, ...]


class _Serializer:
    def __init__(self, document, policy):
        # Revalidate even if a caller used Pydantic's unchecked model_copy.
        self.p = ChunkPolicy.model_validate_json(policy.canonical_json())
        source_json = document.canonical_json()
        if len(source_json.encode()) > self.p.max_batch_bytes:
            raise SerializationError('source graph byte bound exceeded')
        self.doc = StructuralDocument.model_validate_json(source_json)
        self.nodes = {n.identity.node_key: n for n in self.doc.nodes}
        self.children = {k: [] for k in self.nodes}
        self.ancestors = {}
        self.excluded = []
        self.excluded_keys = set()
        self.alias = {}
        self.input_hash = self.doc.canonical_hash()
        self.recipe = digest({'policy': self.p.model_dump(), 'tokenizer': local_tokenizer()[1],
                              'implementation': 'structural-serializer-1',
                              'implementation_sha256': hashlib.sha256(
                                  Path(__file__).read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest()})
        for k, n in self.nodes.items():
            parent = n.parent.node_key if n.parent else None
            self.ancestors[k] = self.ancestors[parent] + (parent,) if parent else ()
            if parent:
                self.children[parent].append(k)
        self.source_bytes = sum(len(n.text.encode()) for n in self.nodes.values())
        if self.source_bytes > self.p.max_input_bytes:
            raise SerializationError('input byte bound exceeded')

    def text(self, pieces):
        return '\n'.join(self.nodes[p.key].text.encode()[p.start:p.end].decode() for p in pieces)

    def full(self, key, role='body', usage='primary'):
        return Piece(key, 0, len(self.nodes[key].text.encode()), role, usage)

    def descendants(self, key):
        result = [key]
        for child in self.children[key]:
            result.extend(self.descendants(child))
        return result

    def heading_path(self, key):
        result = []
        for ancestor in self.ancestors[key]:
            preceding = [child for child in self.children[ancestor]
                         if self.nodes[child].node_type.value == 'heading'
                         and self.nodes[child].preorder < self.nodes[key].preorder]
            if preceding:
                result.append(preceding[-1])
        return tuple(dict.fromkeys(result))

    def quality(self, key):
        return next((self.nodes[k].quality for k in (key, *reversed(self.ancestors[key]))
                     if self.nodes[k].quality), self.doc.revision.quality)

    def prepare(self):
        # Parent-owned inline annotations are mapped onto their exact containing
        # bytes, never serialized as another amount/link/source occurrence.
        for key, n in self.nodes.items():
            lineage = (*self.ancestors[key], key)
            role = next((self.nodes[k].semantic_role.value for k in lineage
                         if self.nodes[k].semantic_role.value in ('navigation', 'furniture')), None)
            q = self.quality(key)
            reason = role or ('quarantine' if q and q.disposition.value == 'quarantine' else None)
            if reason:
                self.excluded_keys.add(key)
                if n.text:
                    # A containing text node could otherwise reintroduce an
                    # excluded inline annotation. Do not guess a redacted text.
                    for ancestor in self.ancestors[key]:
                        a = self.nodes[ancestor]
                        if a.text and ancestor not in self.excluded_keys:
                            raise SerializationError('excluded inline content requires structural separation')
                    self.excluded.append(ExcludedSpan(node=n.identity,
                        node_slice=ByteRange(start=0, end=len(n.text.encode())), reason=reason))
                continue
            if not n.text:
                continue
            for ancestor in reversed(self.ancestors[key]):
                a = self.nodes[ancestor]
                if not a.text:
                    continue
                ns = [s.location.byte_range for s in n.provenance.spans
                      if s.location.system.value == 'utf8_bytes']
                aps = [s.location.byte_range for s in a.provenance.spans
                       if s.location.system.value == 'utf8_bytes']
                if ns and aps:
                    lo, hi = ns[0].start - aps[0].start, ns[0].end - aps[0].start
                    if 0 <= lo < hi <= len(a.text.encode()) and a.text.encode()[lo:hi] == n.text.encode():
                        self.alias[key] = (ancestor, lo, hi)
                        break

    def units(self):
        qa = {}
        for edge in self.doc.edges:
            if edge.relation.value == 'QA_PAIR' and edge.to_node.revision == self.doc.revision.identity:
                qa[edge.to_node.node_key] = edge.from_node.node_key
                qa[edge.from_node.node_key] = edge.from_node.node_key
        groups = {}
        for key, n in self.nodes.items():
            if not n.text or key in self.excluded_keys or key in self.alias:
                continue
            root, kind = key, 'prose'
            for ancestor in (*self.ancestors[key], key):
                a = self.nodes[ancestor]
                if ancestor in qa:
                    root, kind = qa[ancestor], 'faq'
                    break
                if a.node_type.value in ('list', 'table'):
                    root, kind = ancestor, a.node_type.value
                    break
                if a.semantic_role.value not in ('unknown', 'title', 'faq_answer', 'product_card'):
                    root, kind = ancestor, a.semantic_role.value
                    break
            if kind == 'prose':
                if n.semantic_role.value == 'product_card':
                    kind = 'product_card'
                elif n.node_type.value == 'heading':
                    kind = 'heading'
                elif any(self.nodes[k].attributes.list for k in self.descendants(key)):
                    kind = 'list'
                elif any(self.nodes[k].attributes.commercial for k in self.descendants(key)):
                    kind = 'price_block'
                elif n.attributes.quantities:
                    kind = 'directions'
            groups.setdefault((root, kind), []).append(key)
        result = []
        for (root, kind), keys in groups.items():
            n = self.nodes[root]
            heads = self.heading_path(root)
            subjects = tuple(e.to_node.canonical_json() for e in self.doc.edges
                             if e.from_node.node_key in (*self.ancestors[root], root)
                             and e.relation.value in ('REFERS_TO', 'DESCRIBES', 'VARIANT_OF'))
            boundary = (n.parent.node_key if n.parent else '', heads, subjects,
                        self.quality(root).canonical_json(), n.semantic_role.value)
            unit = Unit(keys, [root], kind, boundary, heads)
            if any(self.quality(k) != self.quality(root) for k in keys):
                raise SerializationError('atomic unit crosses quality boundary')
            if result and kind == result[-1].kind == 'prose' and boundary == result[-1].boundary:
                previous = result[-1]
                siblings = self.children[n.parent.node_key] if n.parent else []
                adjacent = bool(siblings and previous.roots[-1] in siblings and
                                siblings.index(root) == siblings.index(previous.roots[-1])+1)
                before = count_tokens(self.text([self.full(k) for k in previous.keys]))
                joined = count_tokens(self.text([self.full(k) for k in previous.keys + keys]))
                if adjacent and before < self.p.target and joined <= self.p.merge_max - self.p.prefix_max:
                    previous.keys.extend(keys)
                    previous.roots.append(root)
                    continue
            result.append(unit)
        return result

    def pieces(self, key):
        n = self.nodes[key]
        role = 'heading' if n.node_type.value == 'heading' else (
            'header' if n.attributes.cell and n.attributes.cell.is_header else (
                'qualifier' if n.semantic_role.value == 'warning' else 'body'))
        # Link spans are indivisible. Unsafe/oversized tokens live only in graph
        # metadata; surrounding prose keeps its original byte slices.
        links = []
        if n.attributes.link:
            links.append((key, 0, len(n.text.encode())))
        for child, (ancestor, lo, hi) in self.alias.items():
            if ancestor == key and self.nodes[child].attributes.link:
                links.append((child, lo, hi))
        cursor, result = 0, []
        for link_key, lo, hi in sorted(links, key=lambda x: x[1]):
            link = self.nodes[link_key].attributes.link
            if lo < cursor:
                raise SerializationError('overlapping link annotations')
            if lo > cursor:
                result.append(Piece(key, cursor, lo, role))
            raw = n.text.encode()[lo:hi].decode()
            if link.safety.value == 'safe' and count_tokens(raw) <= self.p.hard_max - self.p.prefix_max:
                result.append(Piece(key, lo, hi, role))
            else:
                self.excluded.append(ExcludedSpan(node=n.identity,
                    node_slice=ByteRange(start=lo, end=hi), reason='link_metadata_only'))
            cursor = hi
        if cursor < len(n.text.encode()):
            result.append(Piece(key, cursor, len(n.text.encode()), role))
        return result

    def context(self, unit, body):
        required = []
        if unit.kind == 'faq':
            required = [self.full(unit.roots[0], 'heading', 'inherited')]
        elif unit.kind == 'table':
            required = [self.full(k, 'header', 'inherited') for k in unit.keys
                        if self.nodes[k].attributes.cell and self.nodes[k].attributes.cell.is_header]
        # Explicit warning nodes and exact source-backed qualifier strings only.
        for root in unit.roots:
            for k in self.descendants(root):
                n = self.nodes[k]
                if n.semantic_role.value == 'warning' and n.text:
                    required.append(self.full(k, 'qualifier', 'inherited'))
                qualifiers = list(n.attributes.timeline.qualifiers) if n.attributes.timeline else []
                if n.attributes.commercial:
                    qualifiers.extend(n.attributes.commercial.conditions)
                qualifiers.extend(q.qualifier for q in n.attributes.quantities if q.qualifier)
                for qualifier in qualifiers:
                    for candidate in unit.keys:
                        raw = self.nodes[candidate].text.encode()
                        value = qualifier.encode()
                        start = raw.find(value)
                        if start >= 0:
                            required.append(Piece(candidate, start, start+len(value), 'qualifier', 'inherited'))
                            break
        # Actual mandatory qualifiers are never silently omitted. Overlarge
        # table/question context stays in graph metadata, with its primary text
        # retained in another part; every part retains the same bundle members.
        chosen = []
        for p in dict.fromkeys(required):
            if any(b.key == p.key and b.start <= p.start and b.end >= p.end for b in body):
                continue
            if not self.context_link_safe(p):
                if p.role in ('header','qualifier'):
                    raise SerializationError('required context contains unsafe link')
                continue
            if count_tokens(self.text(chosen + [p])+'\n') <= self.p.prefix_max:
                chosen.append(p)
            elif p.role == 'qualifier':
                raise SerializationError('required qualification exceeds context budget')
            elif p.role == 'header':
                raise SerializationError('required table headers exceed context budget')
        for k in reversed(unit.headings):
            p = self.full(k, 'heading', 'inherited')
            if p.end and self.context_link_safe(p) and not any(b.key == k for b in body) and count_tokens(self.text([p] + chosen)+'\n') <= self.p.prefix_max:
                chosen.insert(0, p)
        return chosen

    def context_link_safe(self, piece):
        if piece.key in self.excluded_keys:
            return False
        n = self.nodes[piece.key]
        links = [(n, 0, len(n.text.encode()))] if n.attributes.link else []
        links.extend((self.nodes[k],lo,hi) for k,(parent,lo,hi) in self.alias.items()
                     if parent == piece.key and self.nodes[k].attributes.link)
        return all(n.attributes.link.safety.value == 'safe' and piece.start <= lo and piece.end >= hi
                   for n,lo,hi in links if max(lo,piece.start)<min(hi,piece.end))

    def fits(self, unit, body, limit=None):
        pieces = self.context(unit, body) + body
        return (len(pieces) <= self.p.max_mappings and
                count_tokens(self.text(pieces)) <= (limit or self.p.hard_max))

    def split_piece(self, unit, p):
        if self.fits(unit, [p]):
            return [p]
        raw = self.nodes[p.key].text.encode()
        # No split inside any explicitly parsed link, regardless of its spelling.
        protected = [(lo, hi) for k, (parent, lo, hi) in self.alias.items()
                     if parent == p.key and self.nodes[k].attributes.link]
        if self.nodes[p.key].attributes.link:
            raise SerializationError('link cannot fit with required context')
        start, parts = p.start, []
        while start < p.end:
            value = raw[start:p.end].decode()
            offsets = [0]
            for char in value:
                offsets.append(offsets[-1] + len(char.encode()))
            low, high, best = 1, len(value), 0
            while low <= high:
                mid = (low + high) // 2
                end = start + offsets[mid]
                candidate = replace(p, start=start, end=end)
                if self.fits(unit, [candidate], self.p.target):
                    best, low = mid, mid + 1
                else:
                    high = mid - 1
            if not best:
                raise SerializationError('no character fits token budget')
            # Prefer a sentence, then whitespace. Never strip source bytes.
            prefix = value[:best]
            sentences = list(re.finditer(r'[.!?](?:["\u201d\u2019])?\s+', prefix))
            words = list(re.finditer(r'\s+', prefix))
            boundary = sentences[-1].end() if sentences else (words[-1].end() if words else best)
            if boundary < best // 2:
                boundary = best
            end = start + offsets[boundary]
            for lo, hi in protected:
                if lo < end < hi:
                    end = lo if lo > start else hi
            candidate = replace(p, start=start, end=end)
            if end <= start or not self.fits(unit, [candidate]):
                raise SerializationError('indivisible source span exceeds budget')
            parts.append(candidate)
            if len(parts) > self.p.max_parts:
                raise SerializationError('atomic part bound exceeded')
            start = end
        return parts

    def parts(self, unit):
        # Prefer whole list items/table rows, not arbitrary cells/paragraphs.
        blocks = []
        for k in unit.keys:
            boundary = k
            if unit.kind in ('list', 'table'):
                expected = 'list_item' if unit.kind == 'list' else 'table_row'
                boundary = next((a for a in (*self.ancestors[k], k)
                                 if self.nodes[a].node_type.value == expected), k)
            pieces = self.pieces(k)
            inline_items = sorted((lo, hi, child) for child, (parent, lo, hi) in self.alias.items()
                                  if parent == k and self.nodes[child].node_type.value == 'list_item')
            if unit.kind == 'list' and inline_items:
                # Closed inline enumerations retain their parent label and exact
                # punctuation; make each annotated item an indivisible block.
                starts = [0] + [lo for lo, _, _ in inline_items[1:]]
                ends = starts[1:] + [len(self.nodes[k].text.encode())]
                for (lo, hi), (_, _, child) in zip(zip(starts, ends), inline_items):
                    group = [replace(p, start=max(p.start,lo), end=min(p.end,hi)) for p in pieces
                             if max(p.start,lo)<min(p.end,hi)]
                    blocks.append((child, group))
                continue
            if blocks and blocks[-1][0] == boundary:
                blocks[-1][1].extend(pieces)
            else:
                blocks.append((boundary, pieces))
        parts, current = [], []
        for _, block in blocks:
            if not block:
                continue
            if self.fits(unit, current + block):
                current += block
                continue
            if current:
                parts.append(current)
                current = []
            if self.fits(unit, block):
                current = block
                continue
            for p in block:
                for small in self.split_piece(unit, p):
                    if current and not self.fits(unit, current + [small]):
                        parts.append(current)
                        current = []
                    current.append(small)
        if current:
            parts.append(current)
        if len(parts) > self.p.max_parts:
            raise SerializationError('atomic part bound exceeded')
        # Optional exact last complete sentence for split prose only.
        if unit.kind == 'prose' and self.p.overlap_max:
            for i in range(len(parts)-1, 0, -1):
                previous = parts[i-1][-1]
                raw = self.nodes[previous.key].text.encode()
                value = raw[previous.start:previous.end].decode()
                matches = list(re.finditer(r'[^.!?]*[.!?](?:["\u201d\u2019])?\s*', value))
                if not matches or matches[-1].end() != len(value):
                    continue
                match = matches[-1]
                sentence = match.group()
                if match.start() == 0 and previous.start and not raw[:previous.start].decode().rstrip().endswith(('.', '!', '?')):
                    continue  # the tail of an oversized sentence is not a sentence
                if sentence.strip() and count_tokens(sentence) <= self.p.overlap_max:
                    p = replace(previous, start=previous.start+len(value[:match.start()].encode()), usage='overlap')
                    if self.fits(unit, [p]+parts[i]):
                        parts[i].insert(0, p)
        return parts

    def run(self):
        self.prepare()
        chunks = []
        membership_count = 0
        for unit in self.units():
            parts = self.parts(unit)
            bundle = digest({'revision': self.doc.revision.identity.model_dump(),
                             'roots': unit.roots, 'recipe': self.recipe})
            members = set(unit.keys) | set(unit.roots)
            for root in set(unit.roots + unit.keys):
                members.update(self.descendants(root))
            members.difference_update(self.excluded_keys)
            membership_count += len(members)*len(parts)
            if membership_count > self.p.max_memberships:
                raise SerializationError('membership expansion bound exceeded')
            for index, body in enumerate(parts):
                context = self.context(unit, body)
                pieces = context + body
                text = self.text(pieces)
                key = digest({'input': self.input_hash, 'recipe': self.recipe, 'bundle': bundle,
                              'part': index, 'pieces': [p.__dict__ for p in pieces]})
                mapped, offset = [], 0
                for p in pieces:
                    end = offset + p.end-p.start
                    candidates = [(p.key, p.start, p.end, offset, end, p.role)]
                    for child, (parent, lo, hi) in self.alias.items():
                        if parent == p.key and max(lo, p.start) < min(hi, p.end):
                            a, b = max(lo, p.start), min(hi, p.end)
                            candidates.append((child, a-lo, b-lo, offset+a-p.start, offset+b-p.start, p.role))
                    for nk, a, b, c, d, role in candidates:
                        mapped.append(MappedSpan(mapping=ChunkStructuralMapping(
                            node=self.nodes[nk].identity, chunk_revision=self.doc.revision.identity,
                            chunk_id=key, ordinal=len(mapped), node_slice=ByteRange(start=a,end=b),
                            output_slice=ByteRange(start=c,end=d), role=role, bundle_key=bundle,
                            part_index=index, part_count=len(parts)), usage=p.usage))
                    offset = end + 1
                if len(mapped) > self.p.max_mappings:
                    raise SerializationError('mapping bound exceeded')
                actual_keys = {m.mapping.node.node_key for m in mapped if m.usage != 'inherited'}
                item_indices = set()
                for nk in actual_keys:
                    for ancestor in (*self.ancestors[nk], nk):
                        item = self.nodes[ancestor]
                        if item.node_type.value == 'list_item' and item.parent:
                            parent = item.parent.node_key
                            siblings = [k for k in self.children[parent] if self.nodes[k].node_type.value == 'list_item']
                            item_indices.add((parent, siblings.index(ancestor)))
                lists = [self.nodes[k].attributes.list for k in members if self.nodes[k].attributes.list]
                chunks.append(StructuralChunkSpec(revision=self.doc.revision.identity,
                    chunk_key=key, ordinal=len(chunks), text=text,
                    source_nodes=tuple(dict.fromkeys(s.mapping.node for s in mapped)),
                    heading_path=tuple(self.nodes[k].identity for k in unit.headings),
                    members=tuple(self.nodes[k].identity for k in sorted(members, key=lambda k:self.nodes[k].preorder)),
                    bundle_key=bundle, kind=unit.kind, part_index=index, part_count=len(parts),
                    complete_unit=len(parts)==1,
                    source_block_complete=all(x.source_block_complete for x in lists) if lists else None,
                    list_item_indices=tuple(sorted(item_indices)),
                    table_cells=tuple(self.nodes[k].identity for k in sorted(actual_keys, key=lambda k:self.nodes[k].preorder)
                                      if self.nodes[k].attributes.cell),
                    mappings=tuple(mapped), token_count=count_tokens(text),
                    prefix_tokens=count_tokens(self.text(context)+'\n') if context else 0, byte_count=len(text.encode()),
                    policy=self.p, input_hash=self.input_hash, recipe_hash=self.recipe))
                if len(chunks) > min(self.p.max_chunks, len(self.nodes)*self.p.max_chunks_per_node):
                    raise SerializationError('chunk expansion bound exceeded')
        size = sum(c.byte_count for c in chunks)
        if size > min(self.p.max_output_bytes, max(1, self.source_bytes)*self.p.max_byte_expansion):
            raise SerializationError('serialized byte expansion bound exceeded')
        represented = {i.node_key for c in chunks for i in (*c.members,*c.source_nodes,*c.heading_path)}
        metadata_only = tuple(n.identity for k,n in self.nodes.items()
                              if k not in represented and k not in self.excluded_keys)
        batch = SerializationBatch(source_graph=self.doc, chunks=tuple(chunks), metadata_only_nodes=metadata_only,
                                   excluded=tuple(self.excluded),
                                   input_hash=self.input_hash, recipe_hash=self.recipe).verify()
        if len(batch.canonical_json().encode()) > self.p.max_batch_bytes:
            raise SerializationError('batch byte bound exceeded')
        return batch


def serialize_structural_document(document: StructuralDocument,
                                  policy: ChunkPolicy | None = None) -> SerializationBatch:
    return _Serializer(document, policy or ChunkPolicy()).run()
