"""Offline Markdown/text -> frozen structural-v1 values. No persistence or I/O.

CommonMark block grammar is delegated to markdown-it-py, already installed by
the application and now explicitly pinned. We retain source bytes, not renderer
output. See the Phase 4.1C addendum in the OSS implementation ledger.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re

from markdown_it import MarkdownIt

from services.structural_document import (
    ByteRange, CellAttributes, ListAttributes, NodeAttributes, NodeIdentity,
    Provenance, RevisionIdentity, SourceLocation, SourceQuality, SourceSpan,
    StructuralDocument, StructuralEdge, StructuralNode, StructureRevisionDescriptor,
    TableAttributes, TimelineAttributes, make_node_key,
)
from services import structural_text_rules as rules

MARKDOWN_POLICY = "markdown-structure-v1"
TEXT_POLICY = "text-structure-v1"
NORMALIZER_POLICY = "source-utf8-v1"


class StructuralParseError(ValueError):
    """Safe typed outcome; never logs source content or emits a partial success."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParserLimits:
    # Same default source-byte ceiling as KNOWLEDGE_MAX_UPLOAD_MB=20. A future
    # caller can pass a stricter accepted limit, never expand this parser envelope.
    source_bytes: int = 20 * 1024 * 1024
    nodes: int = 10000
    depth: int = 32
    edges: int = 20000
    lines: int = 100000
    links_per_block: int = 64
    targets: int = 256

    def __post_init__(self):
        caps = (20*1024*1024, 10000, 32, 20000, 100000, 64, 256)
        for value, cap in zip(vars(self).values(), caps):
            if type(value) is not int or not 1 <= value <= cap:
                raise StructuralParseError("invalid_limits")


@dataclass(frozen=True)
class LinkTarget:
    """Explicit server-owned, version-pinned target, NOT URL-derived permission.

    The adapter performs no lookup. Multiple identities for one exact href are
    ambiguous. Future ingestion must supply authorized targets; no ACL inference.
    """
    href: str
    node: NodeIdentity


@dataclass(eq=False)
class _Node:
    kind: str
    start: int
    end: int
    text_start: int | None = None
    text_end: int | None = None
    role: str = "unknown"
    attrs: NodeAttributes = field(default_factory=NodeAttributes)
    basis: str = "explicit source block"
    children: list = field(default_factory=list)
    heading_level: int = 0
    inert: bool = False
    headers: tuple = ()


class _Tokens(list):
    def __init__(self, limits):
        super().__init__()
        self.limits = limits

    def append(self, token):
        if len(self) >= self.limits.nodes * 6:
            raise StructuralParseError("token_limit")
        # Raise BEFORE markdown-it's maxNesting would silently skip content.
        if token.level > self.limits.depth * 2:
            raise StructuralParseError("depth_limit")
        super().append(token)


class _Parser:
    def __init__(self, artifact, identity, source_format, fidelity, limits, targets):
        if not isinstance(identity, RevisionIdentity):
            raise StructuralParseError("trusted_identity_required")
        self.identity = RevisionIdentity.model_validate_json(identity.canonical_json())
        if source_format not in ("markdown", "text"):
            raise StructuralParseError("unsupported_format")
        if not isinstance(limits, ParserLimits):
            raise StructuralParseError("invalid_limits")
        if type(artifact) not in (bytes, str):
            raise StructuralParseError("immutable_utf8_required")
        if len(artifact) > limits.source_bytes:
            raise StructuralParseError("source_size_limit")
        try:
            raw = artifact.encode("utf-8") if isinstance(artifact, str) else artifact
            self.text = raw.decode("utf-8")
        except UnicodeError:
            raise StructuralParseError("invalid_utf8") from None
        if len(raw) > limits.source_bytes:
            raise StructuralParseError("source_size_limit")
        if sha256(raw).hexdigest() != identity.source.source_sha256:
            raise StructuralParseError("source_hash_mismatch")
        if "\x00" in self.text:
            raise StructuralParseError("nul_not_supported")
        self.limits, self.format, self.fidelity = limits, source_format, fidelity
        self.policy = MARKDOWN_POLICY if source_format == "markdown" else TEXT_POLICY
        self.bytes = array("I", [0])
        total = 0
        for char in self.text:
            total += len(char.encode("utf-8"))
            self.bytes.append(total)
        # CommonMark recognizes CR/LF only; Unicode separators remain inert text.
        self.lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", self.text)
        if self.lines and self.lines[-1] == "": self.lines.pop()
        if len(self.lines) > limits.lines:
            raise StructuralParseError("line_limit")
        self.starts, pos = [0], 0
        for line in self.lines:
            pos += len(line)
            self.starts.append(pos)
        if type(targets) is not tuple or len(targets) > limits.targets:
            raise StructuralParseError("target_limit")
        self.targets = {}
        for target in targets:
            if not isinstance(target, LinkTarget) or type(target.href) is not str:
                raise StructuralParseError("typed_target_required")
            node = NodeIdentity.model_validate_json(target.node.canonical_json())
            src = node.revision.source
            if (src.organization_id, src.bot_id) != (identity.source.organization_id, identity.source.bot_id):
                raise StructuralParseError("foreign_target")
            if rules.link_attributes(target.href, "").safety.value != "safe":
                raise StructuralParseError("unsafe_target")
            self.targets.setdefault(target.href, set()).add(node)
        self.count = 0
        self.relationships = []
        self.has_title = False

    def node(self, kind, start, end, *, content=False, **kwargs):
        self.count += 1
        if self.count > self.limits.nodes:
            raise StructuralParseError("node_limit")
        return _Node(kind, start, end, start if content else None, end if content else None, **kwargs)

    def line_span(self, i):
        start = self.starts[i]
        return start, start + len(self.lines[i].rstrip("\r\n"))

    def block_span(self, mapping):
        a, b = mapping
        if not 0 <= a < b <= len(self.lines):
            raise StructuralParseError("invalid_parser_map")
        return self.starts[a], self.line_span(b-1)[1]

    def span(self, start, end):
        return SourceSpan(source=self.identity.source, location=SourceLocation(system="utf8_bytes",
            byte_range=ByteRange(start=self.bytes[start], end=self.bytes[end])))

    def provenance(self, node, basis=None):
        return Provenance(method="deterministic", method_version=self.policy,
            basis=basis or node.basis, spans=(self.span(node.start, node.end),))

    def relation(self, a, b, kind, evidence):
        if len(self.relationships) >= self.limits.edges:
            raise StructuralParseError("edge_limit")
        self.relationships.append((a,b,kind,evidence))

    def paragraph(self, first, end, *, content_start=None, inert=False):
        a, b = self.block_span((first,end))
        if inert:
            return self.node("group", a,b,content=True,inert=True,basis="inert code or raw markup")
        if end-first == 1:
            return self.node("paragraph", content_start if content_start is not None else a,b,content=True)
        group = self.node("group",a,b,basis="source line group")
        for i in range(first,end):
            x,y = self.line_span(i)
            if i == first and content_start is not None: x = content_start
            if self.text[x:y].strip():
                group.children.append(self.node("paragraph",x,y,content=True))
        return group

    def markdown_blocks(self):
        md = MarkdownIt("commonmark", {"html": True, "maxNesting": 256})
        # No renderer, inline execution, typographer, linkification or network.
        md.enable("table")
        md.disable("reference")  # Reference definitions remain source, not a lost side channel.
        tokens = _Tokens(self.limits)
        normalized = self.text.replace("\r\n", "\n").replace("\r", "\n")
        prefix = None
        if self.lines and self.lines[0].strip() == "---":
            for i in range(1,min(len(self.lines),128)):
                if self.lines[i].strip() in ("---", "..."):
                    prefix = self.paragraph(0,i+1,inert=True)
                    # Same line count. Values never become parser configuration.
                    normalized = "\n"*(i+1) + "".join(self.lines[i+1:]).replace("\r\n","\n").replace("\r","\n")
                    break
        md.block.parse(normalized, md, {}, tokens)
        root = [] if prefix is None else [prefix]
        stack = [(None,root)]
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if kind == "table_open":
                table = self.table(token.map)
                stack[-1][1].append(table)
                while i < len(tokens) and tokens[i].type != "table_close": i += 1
            elif kind in ("bullet_list_open", "ordered_list_open", "list_item_open", "blockquote_open"):
                a,b = self.block_span(token.map)
                physical = "list" if "list_open" in kind else "list_item" if kind == "list_item_open" else "group"
                attrs = NodeAttributes(list=ListAttributes(ordered=kind == "ordered_list_open",item_count=0,source_block_complete=True)) if physical == "list" else NodeAttributes()
                node = self.node(physical,a,b,attrs=attrs,basis="explicit Markdown "+kind)
                stack[-1][1].append(node)
                stack.append((node,node.children))
            elif kind in ("bullet_list_close", "ordered_list_close", "list_item_close", "blockquote_close"):
                node,_ = stack.pop()
                if node.kind == "list":
                    node.attrs = NodeAttributes(list=ListAttributes(ordered=node.attrs.list.ordered,
                        item_count=sum(n.kind == "list_item" for n in node.children),source_block_complete=True))
            elif kind == "heading_open":
                a,b = self.block_span(token.map)
                stack[-1][1].append(self.node("heading",a,b,content=True,heading_level=int(token.tag[1:])))
            elif kind == "paragraph_open":
                a,b = self.block_span(token.map)
                first = token.map[0]
                # Source syntax is retained in the parent span, visible item text
                # starts after its exact marker. No global substring matching.
                if stack[-1][0] is not None and stack[-1][0].kind == "list_item":
                    m = re.match(r"[ \t]*(?:[-+*]|\d{1,9}[.)])\s+",self.lines[first])
                    if m: a += m.end()
                stack[-1][1].append(self.paragraph(*token.map,content_start=a))
            elif kind in ("fence", "code_block", "html_block"):
                stack[-1][1].append(self.paragraph(*token.map,inert=True))
            elif kind == "hr":
                a,b = self.block_span(token.map)
                stack[-1][1].append(self.node("group",a,b,content=True,inert=True,basis="thematic break"))
            i += 1
        return root

    def plain_blocks(self):
        result, lists = [], []
        for i,line in enumerate(self.lines):
            a,b = self.line_span(i)
            if not line.strip():
                lists = []
                continue
            m = re.match(r"(?P<indent>[ \t]*)(?P<mark>[-+*]|\d{1,9}[.)]|[a-z][.)])\s+",line)
            if m:
                indent = len(m.group("indent").expandtabs(4))
                ordered = m.group("mark")[0].isalnum()
                while lists and indent < lists[-1][0]: lists.pop()
                if lists and indent == lists[-1][0] and ordered != lists[-1][1].attrs.list.ordered: lists.pop()
                if not lists or indent > lists[-1][0]:
                    n = self.node("list",a,b,attrs=NodeAttributes(list=ListAttributes(ordered=ordered,item_count=0,source_block_complete=True)))
                    (lists[-1][1].children[-1].children if lists else result).append(n)
                    lists.append((indent,n))
                n = lists[-1][1]
                item = self.node("list_item",a,b)
                item.children.append(self.node("paragraph",a+m.end(),b,content=True))
                n.children.append(item)
                n.end = b
                n.attrs = NodeAttributes(list=ListAttributes(ordered=ordered,item_count=len(n.children),source_block_complete=True))
            else:
                lists = []
                result.append(self.node("paragraph",a,b,content=True))
        return result

    def cells(self, start, end):
        """Escaped pipes respected; keep source positions, not unescaped output."""
        positions, begin, escaped = [], start, False
        for p in range(start,end):
            c = self.text[p]
            if c == "|" and not escaped:
                positions.append((begin,p)); begin = p+1
            escaped = not escaped if c == "\\" else False
        positions.append((begin,end))
        if positions and not self.text[slice(*positions[0])].strip() and self.text[start:end].lstrip().startswith("|"):
            positions.pop(0)
        if positions and not self.text[slice(*positions[-1])].strip() and self.text[start:end].rstrip().endswith("|"):
            positions.pop()
        trimmed = []
        for a,b in positions:
            while a<b and self.text[a].isspace(): a+=1
            while b>a and self.text[b-1].isspace(): b-=1
            trimmed.append((a,b))
        return trimmed

    def table(self, mapping):
        first,end = mapping
        a,b = self.block_span(mapping)
        rows = [(i,self.cells(*self.line_span(i))) for i in range(first,end) if i != first+1]
        width = len(rows[0][1])
        # Unlike GFM rendering, do NOT fill absent cells or discard extra cells.
        if any(len(cells) != width for _,cells in rows):
            return self.paragraph(first,end,inert=True)
        table = self.node("table",a,b,attrs=NodeAttributes(table=TableAttributes(row_count=len(rows),column_count=width)))
        headers = []
        for r,(line,cells) in enumerate(rows):
            row = self.node("table_row",*self.line_span(line))
            table.children.append(row)
            for col,(x,y) in enumerate(cells):
                unit = None
                header_text = self.text[headers[col].start:headers[col].end] if r else self.text[x:y]
                m = re.search(r"\(([A-Za-z%][A-Za-z0-9/%^ -]{0,24})\)\s*$",header_text)
                if m and m.group(1) in {"kg","g","mg","mcg","oz","lb","ml","mL","L","cm","mm","m","GB","MB","TB","%","USD","EUR","GBP","kg/m3","g/L"}:
                    unit=m.group(1)
                cell = self.node("table_cell",x,y,content=True,attrs=NodeAttributes(cell=CellAttributes(row=r,column=col,is_header=r==0,unit=unit)),
                    headers=() if r==0 else (headers[col],))
                row.children.append(cell)
                if r == 0: headers.append(cell)
        return table

    def hierarchy(self, blocks, depth=0):
        if depth > self.limits.depth:
            raise StructuralParseError("depth_limit")
        # Lists/quotes have their own local headings; never leak a child heading.
        for n in blocks:
            if n.children: n.children = self.hierarchy(n.children,depth+1)
        result, headings = [], []
        for n in blocks:
            if n.kind == "heading":
                while headings and headings[-1][0] >= n.heading_level: headings.pop()
                section = self.node("section",n.start,n.end,basis="Markdown heading boundary")
                (headings[-1][1].children if headings else result).append(section)
                section.children.append(n)
                headings.append((n.heading_level,section))
                if n.heading_level == 1 and depth == 0 and not self.has_title:
                    n.role = "title"
                    self.has_title = True
            else:
                (headings[-1][1].children if headings else result).append(n)
            for _,s in headings: s.end = max(s.end,n.end)
        return result

    def explicit_line_layouts(self, blocks, depth=0):
        """Small extensions; only explicit adjacent layout, not prose semantics."""
        if depth > self.limits.depth: raise StructuralParseError("depth_limit")
        result=[]
        for n in blocks:
            if n.children: n.children=self.explicit_line_layouts(n.children,depth+1)
            if n.basis=="source line group":
                labels=sum(bool(rules.TIMELINE.fullmatch(self.text[c.start:c.end].strip())) for c in n.children)
                if labels>=2:
                    result.extend(n.children)
                    continue
                # Alphabetic legal lists are not CommonMark. Require a contiguous
                # indented a/b/... sequence; a lone 'a.' prose line is insufficient.
                run=[]
                output=[]
                def flush():
                    if len(run)<2:
                        output.extend(c for c,_ in run)
                    else:
                        listing=self.node("list",run[0][0].start,run[-1][0].end,
                            attrs=NodeAttributes(list=ListAttributes(ordered=True,item_count=len(run),source_block_complete=True)),
                            basis="explicit indented alphabetic sequence")
                        for child,match in run:
                            item=self.node("list_item",child.start,child.end)
                            child.start+=match.end();child.text_start=child.start
                            item.children=[child];listing.children.append(item)
                        output.append(listing)
                    run.clear()
                for child in n.children:
                    m=re.match(r"([ \t]{2,})([a-z])[.)]\s+",self.text[child.start:child.end])
                    if m and ord(m.group(2))-ord('a')==len(run):
                        run.append((child,m))
                    else:
                        flush();output.append(child)
                flush()
                n.children=output
            result.append(n)
        return result

    @staticmethod
    def walk(roots):
        stack = list(reversed(roots))
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def timelines(self, blocks):
        """Group repeated explicit time labels before heading hierarchy assembly."""
        labels = [i for i,n in enumerate(blocks) if n.kind == "paragraph" and
                  rules.TIMELINE.fullmatch(self.text[n.start:n.end].strip())]
        if len(labels) < 2:
            return blocks
        # A time label does not bridge unrelated sections. A stage heading is
        # permitted only immediately after its label; a later heading is a boundary.
        def boundary(i,limit):
            level=blocks[i+1].heading_level if i+1<limit and blocks[i+1].kind=="heading" else None
            for k in range(i+1,limit):
                x=blocks[k]
                if x.kind=="heading" and (level is None or (k>i+1 and x.heading_level<=level)):
                    return k
            return limit
        runs=[]
        run=[labels[0]]
        for previous,current in zip(labels,labels[1:]):
            if boundary(previous,current)!=current:
                if len(run)>=2: runs.append(run)
                run=[]
            run.append(current)
        if len(run)>=2: runs.append(run)
        allowed={i for run in runs for i in run}
        labels=[i for i in labels if i in allowed]
        if not labels: return blocks
        result, cursor = [], 0
        for order,i in enumerate(labels):
            if i < cursor: continue
            result.extend(blocks[cursor:i])
            last = labels[order+1] if order+1<len(labels) else len(blocks)
            last=boundary(i,last)
            label = self.text[blocks[i].start:blocks[i].end].strip()
            end = blocks[last-1].end
            n = self.node("group",blocks[i].start,end,role="timeline_stage",basis="repeated explicit time-label layout",
                attrs=NodeAttributes(timeline=TimelineAttributes(stage_order=order,stage_label=label,
                    qualifiers=rules.qualifiers(self.text[blocks[i].end:end]))))
            n.children = blocks[i:last]
            if ":" in label:
                blocks[i].kind,blocks[i].heading_level = "heading",1
            result.append(n)
            cursor = last
        result.extend(blocks[cursor:])
        return result

    def links(self, node):
        """Bounded cursor scanner; retain unsafe destinations as inert link data.

        Delimited labels and balanced destinations, escaped punctuation and code
        spans. Unsupported/reference Markdown stays as exact parent text.
        """
        start,end = node.start,node.end
        p, count = start,0
        while p < end:
            if self.text[p] == "\\": p += 2; continue
            if self.text[p] == "`":
                q=p+1
                while q<end and self.text[q]=="`": q+=1
                closer=self.text.find(self.text[p:q],q,end)
                p=closer+(q-p) if closer>=0 else q
                continue
            if self.text[p] != "[" or (p>start and self.text[p-1]=="!"):
                p+=1; continue
            q,pair = p+1,1
            while q<end and pair:
                if self.text[q]=="\\": q+=2; continue
                if self.text[q]=="[": pair+=1
                if self.text[q]=="]": pair-=1
                if pair>32: raise StructuralParseError("link_depth_limit")
                q+=1
            if pair or q>=end or self.text[q]!="(": p=q; continue
            anchor_end=q-1
            d=q+1
            while d<end and self.text[d].isspace(): d+=1
            h=d
            if d<end and self.text[d]=="<":
                d+=1; h=d
                while d<end and self.text[d] not in ">\r\n": d+=1
                href_end=d
                if d>=end or self.text[d]!=">": p=d; continue
                d+=1
            else:
                nesting=0
                while d<end:
                    c=self.text[d]
                    if c=="\\" and d+1<end: d+=2; continue
                    if c=="(": nesting+=1
                    if c==")":
                        if nesting==0: break
                        nesting-=1
                    if nesting>32: raise StructuralParseError("link_depth_limit")
                    if c.isspace(): break
                    d+=1
                href_end=d
            while d<end and self.text[d].isspace(): d+=1
            if d<end and self.text[d] in "\"'":
                quote=self.text[d];d+=1
                while d<end and self.text[d]!=quote:
                    d+=2 if self.text[d]=="\\" else 1
                d+=1
                while d<end and self.text[d].isspace(): d+=1
            if d>=end or self.text[d]!=")" or h==href_end:
                p=max(q+1,d);continue
            href,anchor=self.text[h:href_end],self.text[p+1:anchor_end]
            count+=1
            if count>self.limits.links_per_block: raise StructuralParseError("block_link_limit")
            attrs=rules.link_attributes(href,anchor,target_count=len(self.targets.get(href,())))
            node.children.append(self.node("link",p,d+1,content=True,attrs=NodeAttributes(link=attrs),basis="explicit inline Markdown link"))
            p=d+1

    def annotations(self, roots):
        original = list(self.walk(roots))
        for n in original:
            if n.inert or n.text_start is None or n.kind not in ("paragraph","heading","table_cell"):
                continue
            self.links(n)
            if n.kind != "paragraph": continue
            value = self.text[n.start:n.end]
            # Amount/quantity regexes must not inspect URLs or inline code.
            masked=list(value)
            for link in n.children:
                if link.kind=="link": masked[link.start-n.start:link.end-n.start]=" "*(link.end-link.start)
            for m in re.finditer(r"(`+).*?\1",value): masked[m.start():m.end()]=" "*(m.end()-m.start())
            visible="".join(masked)
            n.attrs = NodeAttributes(quantities=rules.quantities(visible))
            for a,b,attrs in rules.commercial_values(visible):
                n.children.append(self.node("paragraph",n.start+a,n.start+b,content=True,role="price_block",
                    attrs=NodeAttributes(commercial=attrs),basis="explicit amount; role only when directly labeled"))
            entries=rules.enumeration_spans(visible)
            if entries:
                listing=self.node("list",n.start+entries[0][0],n.start+entries[-1][1],
                    attrs=NodeAttributes(list=ListAttributes(ordered=False,item_count=len(entries),source_block_complete=True)),
                    basis="explicit closed comma enumeration, not global exhaustive truth")
                for a,b in entries: listing.children.append(self.node("list_item",n.start+a,n.start+b,content=True))
                n.children.append(listing)
            if rules.REVIEW_LABEL.match(value): n.role="review"
        # Sibling ordering and same-section signatures, never keyword proximity.
        for n in original:
            if n.kind == "section":
                direct=[]
                for c in n.children:
                    if c.kind in ("paragraph","group") and c.role!="timeline_stage":
                        direct.extend(x for x in self.walk([c]) if x.kind=="paragraph" and not x.inert)
                signatures=[x for x in direct if rules.REVIEW_SIGNATURE.match(self.text[x.start:x.end])]
                if len(signatures)==1 and not any(c.kind=="section" for c in n.children):
                    n.kind,n.role="group","review"
            if n.role=="review":
                # Only the signature line, or a labeled single-line review, binds
                # a link. Navigation elsewhere in the same section cannot steal it.
                candidates=[]
                for x in self.walk([n]):
                    text=self.text[x.start:x.end]
                    if x.kind=="paragraph" and (rules.REVIEW_LABEL.match(text) or rules.REVIEW_SIGNATURE.match(text)):
                        candidates.extend(c for c in x.children if c.kind=="link")
                if len(candidates)==1:
                    link=candidates[0]; attrs=link.attrs.link
                    if attrs.safety.value=="safe" and attrs.resolution=="resolved":
                        self.relation(n,next(iter(self.targets[attrs.original_href])),"REFERS_TO",link)
        for n in original:
            if n.kind != "section": continue
            heading=next((c for c in n.children if c.kind=="heading"),None)
            if heading is None: continue
            label=re.sub(r"^\s*#{1,6}\s+|\s+#+\s*$","",self.text[heading.start:heading.end]).strip()
            bodies=[c for c in n.children if c is not heading and c.kind!="section"]
            question=bool(rules.QUESTION.fullmatch(label))
            if question and bodies: heading.role="faq_question"
            for body in bodies:
                if question:
                    body.role="faq_answer"
                    self.relation(heading,body,"QA_PAIR",body)
                else:
                    self.relation(heading,body,"HEADING_FOR",body)

    def build(self):
        blocks=self.markdown_blocks() if self.format=="markdown" else self.plain_blocks()
        if self.format=="markdown":
            blocks=self.hierarchy(self.timelines(self.explicit_line_layouts(blocks)))
            self.annotations(blocks)
        root=self.node("document",0,len(self.text),basis="immutable source artifact")
        root.children=blocks
        # Containers can span nested children (including plain-text nested lists).
        # No descendant text is duplicated; provenance covers its source block.
        for container in reversed(list(self.walk([root]))):
            if container.text_start is None and container.children:
                container.start=min(container.start,min(c.start for c in container.children))
                container.end=max(container.end,max(c.end for c in container.children))
        identities,nodes={},[]
        stack=[(root,None,0)]
        leaf=0
        while stack:
            node,parent,depth=stack.pop()
            if depth>self.limits.depth: raise StructuralParseError("depth_limit")
            # Siblings with identical source ranges retain stable insertion order.
            node.children.sort(key=lambda c:(c.start,c.end))
            value=self.text[node.text_start:node.text_end] if node.text_start is not None else ""
            path=f"/nodes/{len(nodes)}"
            identity=NodeIdentity(revision=self.identity,node_key=make_node_key(self.identity.source,path,0,value))
            identities[node]=identity
            attrs=node.attrs
            if node.headers:
                attrs=attrs.model_copy(update={"cell":attrs.cell.model_copy(update={"header_keys":tuple(identities[h].node_key for h in node.headers)})})
            nodes.append(StructuralNode(identity=identity,parser_path=path,occurrence=0,
                parent=identities[parent] if parent is not None else None,preorder=len(nodes),
                leaf_order=leaf if not node.children else None,node_type=node.kind,semantic_role=node.role,
                text=value,attributes=attrs,provenance=self.provenance(node)))
            if not node.children: leaf+=1
            stack.extend((child,node,depth+1) for child in reversed(node.children))
        edges=[]
        for a,b,kind,evidence in self.relationships:
            edges.append(StructuralEdge(from_node=identities[a],to_node=b if isinstance(b,NodeIdentity) else identities[b],
                relation=kind,provenance=self.provenance(evidence,"explicit local "+kind+" structure"),validation_state="validated"))
        recipe={"limits":vars(self.limits),"parser":self.policy,"grammar":"markdown-it-py-4.2.0" if self.format=="markdown" else "plain-lines-v1",
            "targets":sorted((href,n.canonical_json()) for href,values in self.targets.items() for n in values)}
        quality=SourceQuality(classification="unknown",disposition="manual_review",detector_version="not-assessed-v1",
            reason_codes=("source_quality_not_assessed",),evidence=(self.span(0,len(self.text)),))
        descriptor=StructureRevisionDescriptor(identity=self.identity,parser_version=self.policy,normalizer_version=NORMALIZER_POLICY,
            configuration_sha256=sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest(),source_format=self.format,
            fidelity=self.fidelity,state="staging",quality=quality)
        return StructuralDocument(revision=descriptor,nodes=tuple(nodes),edges=tuple(edges))


def parse_structural_text(artifact: str | bytes, *, identity: RevisionIdentity,
                          source_format: str, fidelity: str,
                          limits: ParserLimits = ParserLimits(),
                          link_targets: tuple[LinkTarget, ...] = ()) -> StructuralDocument:
    """Pure deterministic adapter. All ownership comes from the required caller DTO.

    Returns the complete validated DTO or raises StructuralParseError. Does not
    create chunks, persist/activate revisions, assess quality, fetch or infer ACLs.
    """
    return _Parser(artifact,identity,source_format,fidelity,limits,link_targets).build()
