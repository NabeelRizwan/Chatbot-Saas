"""Phase J OFFLINE proof values. Not an ACL, catalog, extractor service or selector.

Only exact frozen bindings are authoritative. A link is a reference until a
separate source-pinned boundary assertion establishes what it describes.
"""
from collections import defaultdict
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from services.structural_document import Value, RevisionIdentity, NodeIdentity
from services.structural_selection_v2 import _Selection, SelectionPolicy
from services.structural_text_rules import REVIEW_LABEL, REVIEW_SIGNATURE


class Refusal(ValueError):
    pass


State = Literal['RESOLVED', 'PARTIAL', 'AMBIGUOUS', 'UNRESOLVED', 'STALE']
Scope = Literal['DOCUMENT', 'SECTION', 'GROUP', 'CARD', 'REVIEW', 'LINKED_BLOCK']
Basis = Literal['DOCUMENT_RESOURCE_ASSERTION', 'EXPLICIT_RESOURCE_LINK',
    'EXPLICIT_CARD_LINK', 'REVIEW_PRODUCT_LINK', 'CANONICAL_DOCUMENT_MAPPING',
    'EXPLICIT_RESOURCE_GROUP', 'VERIFIED_FRAGMENT_TARGET', 'CONTAINS_RELATION',
    'REFERS_TO_RELATION', 'MANUAL_FROZEN_GOLD']


class SourcePin(Value):
    revision: RevisionIdentity
    source_document_id: int = Field(gt=0)
    source_organization_id: int = Field(gt=0)
    source_bot_id: int = Field(gt=0)
    crawl_id: int | None = Field(default=None, gt=0)
    crawl_version: int | None = Field(default=None, gt=0)
    canonical_url: str = ''


class ResourceTarget(Value):
    key: str = Field(min_length=1)
    pin: SourcePin
    root: NodeIdentity
    canonical_url: str


class AnchorProof(Value):
    pin: SourcePin
    resource_key: str
    fragment: str
    node: NodeIdentity
    # A saved literal ID declaration, not heading text or a suggested slug.
    literal: str
    basis: Literal['SAVED_ANCHOR_ID'] = 'SAVED_ANCHOR_ID'


class RelativeBinding(Value):
    pin: SourcePin
    node: NodeIdentity
    original_href: str
    exact_absolute_href: str


class BoundaryProof(Value):
    pin: SourcePin
    scope: Scope
    root: NodeIdentity
    members: tuple[NodeIdentity, ...] = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    basis: tuple[Basis, ...] = Field(min_length=1)
    evidence_nodes: tuple[NodeIdentity, ...] = Field(min_length=1)
    target_href: str = ''
    resource_key: str = ''
    inventory_complete: bool = False
    primary_assertions: int = Field(default=0, ge=0)


class LinkResolution(Value):
    original_href: str
    base: str
    fragment: str | None
    state: Literal['EXACT_RESOURCE', 'VERIFIED_FRAGMENT', 'UNRESOLVED_FRAGMENT',
        'AMBIGUOUS', 'UNSAFE', 'STALE_VERSION', 'MISSING_TARGET']
    resources: tuple[str, ...] = ()
    evidence_nodes: tuple[NodeIdentity, ...] = ()


class StructuralResourceDescriptor(Value):
    version: Literal['structural-resource-descriptor-j-v1'] = 'structural-resource-descriptor-j-v1'
    proof: BoundaryProof
    state: State
    resource_keys: tuple[str, ...]
    target: LinkResolution | None = None
    conflicts: tuple[str, ...] = ()
    reason: str
    # Value.canonical_hash() hashes every field, including boundary and revision.


class Subject(Value):
    state: State
    subjects: tuple[str, ...] = ()


def combine(rows):
    rows = tuple(rows)
    keys = tuple(sorted({k for r in rows for k in r.subjects}))
    if any(r.state == 'STALE' for r in rows): state = 'STALE'
    elif len(keys) > 1 or any(r.state == 'AMBIGUOUS' for r in rows): state = 'AMBIGUOUS'
    elif keys and any(r.state != 'RESOLVED' for r in rows): state = 'PARTIAL'
    elif keys: state = 'RESOLVED'
    else: state = 'UNRESOLVED'
    return Subject(state=state, subjects=keys)


def byte_bounds(nodes):
    spans = [s.location.byte_range for n in nodes for s in n.provenance.spans
             if s.location.byte_range is not None]
    if not spans: raise Refusal('unlocated_boundary')
    return min(s.start for s in spans), max(s.end for s in spans)


def safe_absolute(href):
    if not href or len(href) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in href):
        return False
    try:
        u = urlsplit(href)
        return u.scheme in {'http', 'https'} and bool(u.hostname) and not (u.username or u.password)
    except ValueError:
        return False


class _SavedAnchorDeclaration(HTMLParser):
    """Read inert source markup only; never renders, executes or fetches HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.identifiers=[]

    def handle_starttag(self, tag, attrs):
        self.identifiers.extend(v for k,v in attrs if k in {'id','name'} and v is not None)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)


class DescriptorStudy:
    def __init__(self, batches, pins, resources=(), anchors=(), relative=(), *, manual=False):
        self.batches = dict(batches)
        self.pins = dict(pins)
        if set(self.batches) != set(self.pins): raise Refusal('pin_inventory')
        self.nodes = {}; self.children = defaultdict(list); self.by_revision = {}
        scopes = set()
        for key, b in self.batches.items():
            b.verify(); pin = self.pins[key]; rev = b.source_graph.revision.identity
            if pin.revision != rev: raise Refusal('graph_pin_mismatch')
            scopes.add((rev.source.organization_id, rev.source.bot_id))
            self.by_revision[rev] = pin
            for n in b.source_graph.nodes:
                self.nodes[n.identity] = n
                if n.parent: self.children[n.parent].append(n.identity)
        if len(scopes) != 1: raise Refusal('foreign_study_scope')
        self.scope = next(iter(scopes)); self.manual = manual
        self.resources = {}; self.urls = defaultdict(list)
        for r in resources:
            if r.key in self.resources: raise Refusal('duplicate_resource_key')
            self._scope(r.pin)
            if r.root.revision != r.pin.revision: raise Refusal('target_root_pin')
            if not safe_absolute(r.canonical_url) or '#' in r.canonical_url or urlsplit(r.canonical_url).query:
                raise Refusal('unsafe_canonical_target')
            if r.canonical_url != r.pin.canonical_url: raise Refusal('target_canonical_mismatch')
            self.resources[r.key] = r; self.urls[r.canonical_url].append(r)
        self.anchors = defaultdict(list)
        for a in anchors:
            self._scope(a.pin)
            r = self.resources.get(a.resource_key)
            if not r or a.pin != r.pin or a.node not in self.nodes: raise Refusal('unowned_anchor')
            if a.node.revision != a.pin.revision or not a.fragment: raise Refusal('anchor_pin')
            # Only an exact quoted HTML id/name declaration is supported in J.
            # This is not a DOM parser: freeze an explicit target node separately.
            allowed = {f'id="{a.fragment}"', f"id='{a.fragment}'", f'name="{a.fragment}"', f"name='{a.fragment}'"}
            node=self.nodes[a.node]
            declaration=_SavedAnchorDeclaration()
            if node.node_type.value=='code' or not node.text.lstrip().startswith('<'):
                raise Refusal('anchor_is_not_saved_markup')
            declaration.feed(node.text);declaration.close()
            if a.literal not in allowed or a.literal not in node.text or declaration.identifiers.count(a.fragment)!=1:
                raise Refusal('anchor_declaration_not_saved')
            self.anchors[(r.key, a.fragment)].append(a)
        self.relative = {}
        for binding in relative:
            self._scope(binding.pin)
            if binding.node not in self.nodes or self.by_revision.get(binding.node.revision) != binding.pin:
                raise Refusal('relative_binding_pin')
            link = self.nodes[binding.node].attributes.link
            if not link or link.original_href != binding.original_href or not safe_absolute(binding.exact_absolute_href):
                raise Refusal('relative_binding_source')
            k = (binding.node, binding.original_href)
            if k in self.relative: raise Refusal('ambiguous_relative_binding')
            self.relative[k] = binding.exact_absolute_href
        self.descriptors = []; self.index = defaultdict(list)

    def _scope(self, pin):
        s = pin.revision.source
        if (s.organization_id, s.bot_id) != self.scope: raise Refusal('foreign_scope')

    def descendants(self, root):
        pending = [root]; result = []
        while pending:
            n = pending.pop(); result.append(n)
            pending.extend(reversed(self.children[n]))
        return tuple(result)

    def target(self, href, node=None):
        original = href
        href = self.relative.get((node, href), href)
        base, separator, fragment = href.partition('#')
        def out(state, keys=(), evidence=()):
            return LinkResolution(original_href=original, base=base, fragment=fragment if separator else None,
                state=state, resources=tuple(sorted(keys)), evidence_nodes=tuple(evidence))
        if not safe_absolute(href):
            try: u = urlsplit(href)
            except ValueError: return out('UNSAFE')
            return out('UNSAFE' if u.scheme or href.startswith('//') or any(c.isspace() for c in href) else 'MISSING_TARGET')
        matches = self.urls.get(base, ())
        if not matches: return out('MISSING_TARGET')
        if len(matches) > 1: return out('AMBIGUOUS', (r.key for r in matches))
        r = matches[0]
        if self.by_revision.get(r.pin.revision) != r.pin or r.root not in self.nodes:
            return out('STALE_VERSION')
        if not separator: return out('EXACT_RESOURCE', (r.key,), (r.root,))
        anchors = self.anchors.get((r.key, fragment), ())
        if len(anchors) > 1: return out('AMBIGUOUS', (r.key,))
        if not anchors: return out('UNRESOLVED_FRAGMENT')
        return out('VERIFIED_FRAGMENT', (r.key,), (anchors[0].node,))

    def proof(self, doc_id, root, members, *, scope, basis, evidence, **kwargs):
        """Construct a bounded assertion; never infers which subject it asserts."""
        ns = [self.nodes[n] for n in members]
        lo, hi = byte_bounds(ns)
        return BoundaryProof(pin=self.pins[doc_id], root=root, members=tuple(members), scope=scope,
            start=min(n.preorder for n in ns), end=max(n.preorder for n in ns)+1,
            byte_start=lo, byte_end=hi, basis=tuple(basis), evidence_nodes=tuple(evidence), **kwargs)

    def validate_boundary(self, p):
        self._scope(p.pin)
        source = p.pin.revision.source
        matching = [v for v in self.pins.values() if v.revision.source.document_id == source.document_id]
        if not matching: raise Refusal('foreign_document')
        if p.pin != matching[0]: return False
        if 'MANUAL_FROZEN_GOLD' in p.basis and not self.manual: raise Refusal('manual_not_automatic')
        if p.root not in self.nodes or p.root.revision != p.pin.revision: raise Refusal('missing_root')
        if len(set(p.members)) != len(p.members): raise Refusal('duplicate_members')
        if any(n not in self.nodes or n.revision != p.pin.revision for n in p.members): raise Refusal('missing_or_foreign_member')
        subtree = self.descendants(p.root)
        selected = tuple(n for n in subtree if p.start <= self.nodes[n].preorder < p.end)
        if selected != p.members: raise Refusal('noncontiguous_or_sibling_leakage')
        ns = [self.nodes[n] for n in p.members]
        if (p.start,p.end) != (min(n.preorder for n in ns),max(n.preorder for n in ns)+1): raise Refusal('boundary_interval')
        if byte_bounds(ns) != (p.byte_start,p.byte_end): raise Refusal('boundary_bytes')
        if any(n not in p.members for n in p.evidence_nodes): raise Refusal('evidence_outside_boundary')
        if p.scope == 'DOCUMENT' and (self.nodes[p.root].parent is not None or p.members != subtree):
            raise Refusal('incomplete_document_boundary')
        # A bounded review cannot silently include a later navigation/card group.
        if p.scope == 'REVIEW':
            terminal = [n for n in ns if n.node_type.value == 'paragraph' and
                        (REVIEW_SIGNATURE.match(n.text) or REVIEW_LABEL.match(n.text))]
            if len(terminal) != 1 or any(n.preorder > max(self.nodes[k].preorder for k in self.descendants(terminal[0].identity)) for n in ns):
                raise Refusal('review_boundary_not_terminal')
        return True

    def add(self, p, *, inventory=()):
        p = BoundaryProof.model_validate_json(p.canonical_json())
        valid = self.validate_boundary(p)
        target = None; keys = (); conflicts = (); state = 'UNRESOLVED'; reason = 'no_subject_assertion'
        if not valid: state, reason = 'STALE', 'exact_source_version_hash_crawl_revision_required'
        elif p.target_href:
            links = [self.nodes[n] for n in p.evidence_nodes if self.nodes[n].attributes.link and self.nodes[n].attributes.link.original_href == p.target_href]
            if not links: raise Refusal('target_link_not_in_evidence')
            target = self.target(p.target_href, links[0].identity)
            keys = target.resources
            state = {'EXACT_RESOURCE':'RESOLVED','VERIFIED_FRAGMENT':'RESOLVED',
                'AMBIGUOUS':'AMBIGUOUS','STALE_VERSION':'STALE'}.get(target.state,'UNRESOLVED')
            reason = target.state
        elif p.resource_key and set(p.basis) & {'DOCUMENT_RESOURCE_ASSERTION','EXPLICIT_RESOURCE_GROUP','MANUAL_FROZEN_GOLD'}:
            r = self.resources.get(p.resource_key)
            if r and self.by_revision.get(r.pin.revision) == r.pin:
                state, keys, reason = 'RESOLVED', (r.key,), 'frozen_explicit_subject_assertion'
        if valid and p.scope == 'DOCUMENT':
            r = self.resources.get(p.resource_key)
            observed = [self.target(self.nodes[n].attributes.link.original_href,n) for n in p.members
                        if self.nodes[n].attributes.link and self.nodes[n].semantic_role.value != 'navigation']
            observed_other = {k for t in observed for k in t.resources} - {p.resource_key}
            if p.primary_assertions > 1: state, reason = 'AMBIGUOUS', 'multiple_primary_assertions'
            elif p.primary_assertions != 1 or 'DOCUMENT_RESOURCE_ASSERTION' not in p.basis:
                state, keys, reason = 'UNRESOLVED', (), 'document_mapping_is_lineage_only'
            elif not r or r.pin != p.pin or r.canonical_url != p.pin.canonical_url:
                state, keys, reason = 'UNRESOLVED', (), 'root_mapping_canonical_mismatch'
            elif observed_other:
                state, conflicts, reason = 'AMBIGUOUS', tuple(sorted(observed_other)), 'competing_source_reference'
            elif not p.inventory_complete or any(d.state != 'RESOLVED' for d in inventory) or any(t.state not in {'EXACT_RESOURCE','VERIFIED_FRAGMENT'} for t in observed):
                state, reason = 'PARTIAL', 'incomplete_or_unresolved_inventory'
            else:
                conflicts = tuple(sorted({k for d in inventory for k in d.resource_keys} - {r.key}))
                if conflicts: state, reason = 'AMBIGUOUS', 'competing_inventory'
        d = StructuralResourceDescriptor(proof=p, state=state, resource_keys=keys,
            target=target, conflicts=conflicts, reason=reason)
        self.descriptors.append(d)
        if valid:
            for n in p.members: self.index[n].append(d)
        return d

    def subject(self, node):
        ds = self.index.get(node, ())
        if not ds: return Subject(state='UNRESOLVED')
        # Explicit strict nesting overrides ancestor assertions, including a
        # nested abstention. Equal or partially overlapping scopes conflict.
        minimal = [d for d in ds if not any(set(x.proof.members) < set(d.proof.members) for x in ds)]
        return combine(Subject(state=d.state, subjects=d.resource_keys) for d in minimal)

    def for_spec(self, c):
        return combine(self.subject(n) for n in {m.mapping.node for m in c.mappings if m.usage == 'primary'})

    def automatic(self, doc_id):
        """Only explicit signature-terminated review blocks have local proof.

        Other groups require a saved boundary/assertion input. Link proximity,
        linked headings and document mappings never assign their paragraphs.
        """
        graph = self.batches[doc_id].source_graph
        for n in graph.nodes:
            if n.semantic_role.value != 'review': continue
            members = self.descendants(n.identity)
            signatures = [self.nodes[k] for k in members if self.nodes[k].node_type.value == 'paragraph'
                and (REVIEW_SIGNATURE.match(self.nodes[k].text) or REVIEW_LABEL.match(self.nodes[k].text))]
            if len(signatures) != 1: continue
            signature = signatures[0]
            end = max(self.nodes[k].preorder for k in self.descendants(signature.identity)) + 1
            # Root's source span may extend into following furniture; don't use
            # the container itself as a member of this truncated source window.
            bounded = tuple(k for k in members if (k != n.identity or n == signature) and self.nodes[k].preorder < end)
            links = [k for k in self.descendants(signature.identity) if self.nodes[k].attributes.link]
            href = self.nodes[links[0]].attributes.link.original_href if len(links) == 1 else ''
            evidence = tuple(links) or (signature.identity,)
            p = self.proof(doc_id,n.identity,bounded,scope='REVIEW',basis=('REVIEW_PRODUCT_LINK',),
                evidence=evidence,target_href=href)
            self.add(p)


class DescriptorPeerEngine(_Selection):
    """Frozen H policy, J identity input. No accepted H artifact can be emitted."""
    def __init__(self,batch,study):
        self.study=study
        super().__init__(batch,SelectionPolicy())

    def boundary(self,c):
        roots,_,roles,quality=super().boundary(c)
        row=self.study.for_spec(c)
        return roots,row.subjects if row.state=='RESOLVED' else (),roles,quality

    def run(self):
        raise Refusal('J_is_not_a_selector_version')


def pair_state(a,b):
    if a.state=='STALE' or b.state=='STALE': return 'STALE_DESCRIPTOR'
    if a.state=='AMBIGUOUS' or b.state=='AMBIGUOUS': return 'AMBIGUOUS'
    if a.state==b.state=='RESOLVED':
        return 'SAME_RESOLVED_RESOURCE' if a.subjects==b.subjects else 'DIFFERENT_RESOLVED_RESOURCE'
    if a.subjects or b.subjects: return 'PARTIAL'
    return 'UNRESOLVED'
