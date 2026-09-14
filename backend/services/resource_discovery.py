"""One discovery/fusion/resolution owner. No generative or embedding calls.

License/pattern ledger: OPEN_SOURCE_ADAPTATION_NOTES_PHASE_3.md. RapidFuzz is
used only on the bounded SQL candidate union; no Python catalog fuzzy scan.
"""
from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter
import hashlib
import json
import os
import re

from rapidfuzz.fuzz import token_set_ratio, token_sort_ratio
from sqlalchemy import select, literal_column, and_, or_, func
from sqlalchemy.exc import SQLAlchemyError
from database.models import Document
from database.resource_models import KnowledgeResource as Resource, KnowledgeResourceTerm as Term
from services.hybrid_retrieval import weighted_rank_union
from services.resource_catalog import catalog_revision, safe_navigation_url
from services.resource_channels import (CHANNEL_LIMIT, MAX_PROBES, IDENTITY_KINDS, SQLResourceChannel,
    ResourceProbe, FeatureUnavailable, eligible_anchors, term_statement, bounded_terms, CandidateSignal)
from services.resource_normalization import normalize_resource_text
from services.retrieval_contracts import KnowledgeResourceRef, ResourceCandidate
from services.resource_semantic_gap import SemanticGapAssessment, SEMANTIC_GAP_VERSION, assess_semantic_gap

DISCOVERY_VERSION = "resource-discovery-3.4"
POLICY_VERSION = "informative-evidence-6-numeric-constraints"


def numeric_relation(query, identity):
    """An omitted identifier is not a contradictory identifier.

    Keep whole alphanumeric tokens (X12 is not Y12) and ordered numeric
    components. Explicit partial versions cannot certify a unique identity.
    This supplies a constraint only, never affirmative identity evidence.
    """
    def components(value):
        return tuple(t for t in normalize_resource_text(value).split() if re.search(r'\d', t))
    asked, stored = components(query), components(identity)
    if not asked:
        return 'no_query_numeric_constraint'
    if asked == stored:
        return 'exact_match'
    if not stored or set(asked) < set(stored) or set(stored) < set(asked):
        return 'partial_or_ambiguous'
    return 'conflict'


def _numeric_compatible(candidate):
    relation = next((r.split(':', 1)[1] for r in candidate.reason_codes
                     if r.startswith('numeric_relation:')), None)
    # Older in-process candidates/tests carry the prior diagnostic score.
    return relation in {'exact_match', 'no_query_numeric_constraint'} if relation else dict(candidate.scores).get('numeric_agreement') == 1
CHANNEL_WEIGHTS = {"exact": 2.0, "fts": 1.0, "trigram": 1.0, "metadata": .5, "legacy": .5, "dense": .5}
RRF_K = 60.0


def resource_discovery_enabled():
    raw = os.getenv("RAG_RESOURCE_DISCOVERY", "off").strip().casefold()
    if raw not in {"off", "on"}:
        raise ValueError("Invalid resource discovery rollout configuration")
    return raw == "on"


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ResourceDiscoveryError(RuntimeError):
    """Technical failure, never a catalog absence assertion; no raw DB error."""


@dataclass(frozen=True)
class ResourceResolution:
    probe: ResourceProbe
    state: ResolutionState
    candidate: ResourceCandidate | None = None
    alternatives: tuple[ResourceCandidate, ...] = ()
    reason_codes: tuple[str, ...] = ()
    semantic_gap: SemanticGapAssessment | None = None


@dataclass(frozen=True)
class ResourceDiscoveryResult:
    candidates: tuple[ResourceCandidate, ...]
    resolutions: tuple[ResourceResolution, ...]
    catalog_revision: int
    diagnostics: tuple[dict, ...] = ()
    status: str = "available"

    def trace(self):
        return {"backend": DISCOVERY_VERSION, "policy": POLICY_VERSION, "status": self.status,
                "catalog_revision": self.catalog_revision, "channels": list(self.diagnostics),
                "resolutions": [{"probe": normalize_resource_text(r.probe.text), "provenance": r.probe.provenance,
                    "original_span_sha256": hashlib.sha256((r.probe.original_span or r.probe.text).encode()).hexdigest(),
                    "probe_kind": r.probe.probe_kind, "explicit_type": r.probe.explicit_resource_type_hint,
                    "inherited_type": r.probe.inherited_resource_type_hint, "comparison_group": r.probe.comparison_group_id,
                    "comparison_member_index": r.probe.comparison_member_index, "category_intent": r.probe.category_intent,
                    "relation_intent": r.probe.relation_intent,
                    "variants": [{"search_text": normalize_resource_text(v.text), "provenance": v.provenance,
                                  "transformations": v.transformations} for v in r.probe.variants],
                    "state": r.state.value, "reason_codes": r.reason_codes,
                    "candidate_count": len(r.alternatives),
                    "semantic_gap": r.semantic_gap.trace() if r.semantic_gap else None,
                    "selected_resource_id": r.candidate.resource.resource_id if r.candidate else None,
                    "candidates": [{"resource_id": c.resource.resource_id, "resource_type": c.resource.resource_type,
                        "document_ids": c.resource.document_ids, "channels": c.match_sources,
                        "matched_term_kind": next((s.partition(":")[2] for s in c.match_sources if s.startswith("term_kind:")), None),
                        "scores": dict(c.scores), "reason_codes": c.reason_codes} for c in r.alternatives[:16]]}
                    for r in self.resolutions]}

    def cache_identity(self, hard):
        from services.resource_probe_builder import PROBE_VERSION
        probes = [(normalize_resource_text(r.probe.text), r.probe.provenance, r.probe.explicit_resource_type_hint,
                   r.probe.inherited_resource_type_hint, r.probe.category_intent, r.probe.relation_intent,
                   r.probe.comparison_group_id, r.probe.comparison_member_index) for r in self.resolutions]
        return {"backend": DISCOVERY_VERSION, "policy": POLICY_VERSION, "revision": self.catalog_revision,
                "probe_contract": PROBE_VERSION,
                "semantic_gap_policy": SEMANTIC_GAP_VERSION,
                "semantic_gaps": [r.semantic_gap.cache_identity() if r.semantic_gap else None for r in self.resolutions],
                "hard": hard.identity(), "probes_sha256": hashlib.sha256(json.dumps(probes).encode()).hexdigest()}


class ResourceResolutionPolicy:
    """Evidence rules, separate from rank fusion. False certainty is costly."""
    def resolve(self, probe, candidates, *, overflow=False, exact_overflow=False, exact_unavailable=False):
        hint = probe.explicit_resource_type_hint or probe.inherited_resource_type_hint
        if hint:
            matching = [c for c in candidates if normalize_resource_text(c.resource.resource_type) == hint]
            if matching:
                candidates = matching  # Soft type corroboration; hard SQL already authorized every candidate.
        def result(state, candidate=None, reason="no_match"):
            return ResourceResolution(probe, state, candidate, tuple(candidates), (reason,))
        if probe.provenance == "category":
            return result(ResolutionState.UNRESOLVED, reason="category_resource_set")
        if probe.relation_intent:
            return result(ResolutionState.UNRESOLVED, reason="structured_relation_required")
        if exact_overflow:
            return result(ResolutionState.AMBIGUOUS, reason="candidate_limit_prevents_uniqueness")
        exact = [c for c in candidates if c.canonical_exact or c.alias_exact or "title_exact" in c.match_sources or "legacy_verified" in c.match_sources]
        if len(exact) > 1:
            return result(ResolutionState.AMBIGUOUS, reason="conflicting_exact_identities")
        if exact_unavailable:
            return result(ResolutionState.UNRESOLVED, reason="identity_channel_unavailable")
        if len(exact) == 1 and probe.provenance not in {"planner_hint", "full_query"}:
            c = exact[0]
            return result(ResolutionState.RESOLVED, replace(c, confidence=1.0, match_sources=c.match_sources + ("authorized_identity",)),
                          "exact_unique")
        if overflow:
            return result(ResolutionState.AMBIGUOUS, reason="candidate_limit_prevents_uniqueness")
        tokens = set(normalize_resource_text(probe.text).split())
        # Complete term equality under token order differs from subset coverage.
        # Both full permutations must remain ambiguous; longer qualified names
        # are not equal merely because token_set_ratio happens to be 100.
        complete = [c for c in candidates if "identity_term" in c.reason_codes and "fts" in c.match_sources
                    and dict(c.scores).get("token_sort") == 100 and _numeric_compatible(c)]
        if len(tokens) >= 2 and probe.provenance not in {"planner_hint", "full_query"} and complete:
            if len(complete)>1:
                return result(ResolutionState.AMBIGUOUS,reason="conflicting_complete_token_identities")
            c=complete[0]
            return result(ResolutionState.RESOLVED,replace(c,confidence=.95,match_sources=c.match_sources+("authorized_identity",)),
                          "unique_complete_token_identity")
        # A single token/short acronym may discover candidates but cannot earn
        # fuzzy identity. Stored unique exact aliases are handled above.
        from services.resource_probe_builder import informative_tokens
        information=informative_tokens(probe.text)
        typed_stem=(len(information)==1 and len(next(iter(information)))>=6 and bool(hint)
                    and hint in tokens and len(tokens)>=2)
        if (len(information) < 2 and not typed_stem) or probe.provenance in {"planner_hint", "full_query"}:
            return result(ResolutionState.AMBIGUOUS if len(candidates) > 1 else ResolutionState.UNRESOLVED,
                          reason="insufficient_specificity")
        plausible, strong = [], []
        for c in candidates:
            scores = dict(c.scores)
            if not _numeric_compatible(c):
                continue
            if scores.get("informative_sort", scores.get("token_sort", 0)) >= 75 or scores.get("informative_coverage", scores.get("token_coverage", 0)) >= .66:
                plausible.append(c)
            subset = scores.get("token_coverage") == 1 and scores.get("token_set") == 100 and "fts" in c.match_sources
            fuzzy = scores.get("token_sort", 0) >= 88 and "trigram" in c.match_sources
            if typed_stem:
                subset=False
                fuzzy=fuzzy and normalize_resource_text(c.resource.resource_type)==hint
            if (subset or fuzzy) and "identity_term" in c.reason_codes:
                strong.append(c)
        if len(strong) == 1 and len(plausible) == 1:
            c = strong[0]
            return result(ResolutionState.RESOLVED, replace(c, confidence=.9, match_sources=c.match_sources + ("authorized_identity",)),
                          "unique_corroborated_identity")
        return result(ResolutionState.AMBIGUOUS if len(plausible) > 1 else ResolutionState.UNRESOLVED,
                      reason="competing_candidates" if len(plausible) > 1 else "weak_match")


class ResourceDiscoveryService:
    def __init__(self, channels=None, policy=None):
        self.channels = tuple(channels) if channels is not None else tuple(SQLResourceChannel(c) for c in ("exact", "fts", "trigram", "metadata"))
        if len(self.channels) > 6 or len({c.name for c in self.channels}) != len(self.channels) or any(c.name not in CHANNEL_WEIGHTS for c in self.channels):
            raise ValueError("Invalid resource channel composition")
        self.policy = policy or ResourceResolutionPolicy()

    def discover(self, db, hard, probes, conversation_context=None, *, legacy_candidates=()):
        probes = tuple(probes)
        if len(probes) > MAX_PROBES:
            raise ValueError("Too many resource probes")
        for p in probes:
            normalize_resource_text(p.text)  # Reject overflow; never truncate identity.
            if len(p.variants) > 4:
                raise ValueError("Too many variants per logical probe")
            for v in p.variants:
                normalize_resource_text(v.text)
        if hard.empty:
            return self._classify_gaps(ResourceDiscoveryResult((), tuple(ResourceResolution(p, ResolutionState.UNRESOLVED)
                for p in probes), 0, status="empty_hard_scope"), hard)
        try:
            if any(p.variants for p in probes):
                answer = self._discover_variants(db, hard, probes, legacy_candidates)
            else:
                answer = self._discover(db, hard, probes, legacy_candidates)
            return self._classify_gaps(answer, hard)
        except SQLAlchemyError:
            raise ResourceDiscoveryError("Resource catalog technical failure") from None

    @staticmethod
    def _classify_gaps(answer, hard=None):
        """Separate future search eligibility from unchanged identity evidence.

        A partially failed batch is conservatively ineligible; no extra search
        is performed. Unknown resource and eligible search can both be true.
        """
        healthy = bool(answer.diagnostics) and all(d.get("status") == "success" for d in answer.diagnostics)
        resolutions = []
        for r in answer.resolutions:
            gap = assess_semantic_gap(r, hard=hard, search_healthy=healthy, catalog_available=answer.status == "available")
            reasons = r.reason_codes
            if gap.basis == "structured_relation_required":
                reasons += ("structured_relation_required",)
            if gap.eligible_for_optimizer:
                if gap.candidate_count == 0:
                    reasons += ("unresolved_unknown_resource",)
                reasons += ("query_optimizer_eligible",)
            elif (r.state == ResolutionState.UNRESOLVED and healthy
                  and set(reasons) & {"weak_match", "insufficient_specificity"}
                  and not r.probe.category_intent and not r.probe.relation_intent):
                reasons += ("unresolved_unknown_resource",)
            resolutions.append(replace(r, reason_codes=tuple(dict.fromkeys(reasons)), semantic_gap=gap))
        return replace(answer, resolutions=tuple(resolutions))

    def _discover_variants(self, db, hard, probes, legacy_candidates):
        """One bounded SQL pass/hydration, one resolution per logical member.

        Variants never sum rank scores. Prefer explicit identity, then stronger
        provenance; conflicting equally valid transformations remain ambiguous.
        """
        from services.resource_channels import ProbeVariant
        flat, groups = [], []
        for p in probes:
            start=len(flat)
            variants=p.variants or (ProbeVariant(p.text,p.provenance,0),)
            for v in sorted(variants,key=lambda v:v.priority):
                flat.append(replace(p,text=v.text,provenance=v.provenance,variants=()))
            groups.append((p,start,len(flat)))
        raw=self._discover(db,hard,flat,legacy_candidates)
        merged=[]
        for p,start,end in groups:
            rows=raw.resolutions[start:end]
            alternatives={}
            for row in rows:
                for c in row.alternatives:
                    alternatives.setdefault(c.resource.resource_id,c)
            # Preserve a strong original identity or exact ambiguity. Reduced
            # text cannot erase an explicit duplicate identity in the catalog.
            first=rows[0]
            if first.reason_codes in {("exact_unique",),("conflicting_exact_identities",),("candidate_limit_prevents_uniqueness",)}:
                chosen=first
            else:
                resolved=[r for r in rows if r.state==ResolutionState.RESOLVED]
                ids={r.candidate.resource.resource_id for r in resolved}
                if len(ids)>1:
                    chosen=ResourceResolution(p,ResolutionState.AMBIGUOUS,reason_codes=("conflicting_probe_variants",))
                elif resolved:
                    chosen=resolved[0]
                else:
                    chosen=rows[-1] if p.category_intent else next((r for r in rows if r.state==ResolutionState.AMBIGUOUS),rows[-1])
            if p.category_intent:
                if chosen.state==ResolutionState.RESOLVED:
                    p=replace(p,category_intent=False,provenance="explicit_user",probe_kind="entity")
                else:
                    # Entity hypothesis cannot pollute the requested type set.
                    alternatives={c.resource.resource_id:c for c in rows[-1].alternatives}
            ordered=list(alternatives.values())
            if chosen.candidate:
                ordered=[chosen.candidate]+[c for c in ordered if c.resource.resource_id!=chosen.candidate.resource.resource_id]
            reasons=chosen.reason_codes
            if chosen.state==ResolutionState.UNRESOLVED and not p.category_intent:
                reasons+= ("deterministic_discovery_insufficient",)
            merged.append(replace(chosen,probe=p,alternatives=tuple(ordered),reason_codes=reasons))
        pooled={}
        for resolution in merged:
            for candidate in resolution.alternatives:
                pooled.setdefault(candidate.resource.resource_id,candidate)
        return replace(raw,candidates=tuple(pooled.values()),resolutions=tuple(merged))

    def _discover(self, db, hard, probes, legacy_candidates):
        revision = catalog_revision(db, hard)
        by_probe, diagnostics, ids = [], [], set()
        with db.no_autoflush:
            for probe in probes:
                signals, overflow, exact_overflow, unavailable = [], False, False, set()
                for channel in self.channels:
                    if probe.provenance == "category" and channel.name != "metadata":
                        continue
                    start = perf_counter()
                    try:
                        batch = channel.search(db, hard, probe, CHANNEL_LIMIT)
                        if len(batch.signals) > CHANNEL_LIMIT:
                            raise ResourceDiscoveryError("Resource channel exceeded bound")
                        signals.extend(batch.signals)
                        overflow |= batch.overflow
                        exact_overflow |= channel.name == "exact" and batch.overflow
                        diagnostics.append({"channel": channel.name, "status": "success", "count": len(batch.signals), "overflow": batch.overflow,
                                            "ms": round((perf_counter()-start)*1000, 3)})
                    except (FeatureUnavailable, TimeoutError) as exc:
                        unavailable.add(channel.name)
                        diagnostics.append({"channel": channel.name, "status": "feature_unavailable" if isinstance(exc, FeatureUnavailable) else "timeout"})
                # Existing content/title/typo identity is a bounded candidate
                # channel, not a separate final decision. Match the current
                # probe explicitly; stale state and excluded mentions cannot
                # supply a different subject through this compatibility bridge.
                verified_docs = {d for c in legacy_candidates if c.confidence >= .8 and not c.ambiguous
                    and "authorized_identity" in c.match_sources and c.resource.organization_id == hard.organization_id
                    and c.resource.bot_id == hard.bot_id
                    and normalize_resource_text(c.resource.canonical_name) == normalize_resource_text(probe.text)
                    for d in c.resource.document_ids}
                if verified_docs and probe.provenance not in {"category", "full_query", "planner_hint"}:
                    anchors = eligible_anchors(db, hard)
                    matches = select(anchors.c.resource_id).where(anchors.c.document_id.in_(verified_docs))
                    rows = db.execute(bounded_terms(term_statement(db, hard, literal_column("1.0"), anchors=anchors).where(
                        Resource.id.in_(matches), Term.term_kind == "canonical"), CHANNEL_LIMIT)).all()
                    signals.extend(CandidateSignal(r.resource_id, "legacy", rank, 1.0, r.term_id,
                        "legacy_identity", normalize_resource_text(probe.text), "existing_authorized_identity", ("legacy_verified",))
                        for rank, r in enumerate(rows[:CHANNEL_LIMIT], 1))
                    overflow |= len(rows) > CHANNEL_LIMIT
                    exact_overflow |= len(rows) > CHANNEL_LIMIT
                    diagnostics.append({"channel": "legacy", "status": "success", "count": min(len(rows), CHANNEL_LIMIT)})
                by_probe.append((probe, signals, overflow, exact_overflow, unavailable))
                ids.update(s.resource_id for s in signals)
            # One batch, projected descriptors only, authorized anchors rechecked.
            anchors = eligible_anchors(db, hard)
            # Descriptor text/URL must originate in an authorized anchor too;
            # shared catalog display metadata may belong to a restricted primary
            # document. Explicit admin-owned canonical terms may use the catalog
            # descriptor, but cannot bypass anchor eligibility.
            from sqlalchemy import case
            rows = db.execute(select(Resource.id, Term.term_text.label("canonical_name"), Resource.resource_type,
                case((Term.source_document_id.is_(None), Resource.title), else_=Document.title).label("title"),
                case((Term.source_document_id.is_(None), Resource.url),
                     else_=func.coalesce(Document.canonical_url, Document.source_url)).label("url"),
                Resource.version, anchors.c.document_id).join(anchors, anchors.c.resource_id == Resource.id)
                .join(Document, and_(Document.id == anchors.c.document_id, Document.organization_id == hard.organization_id,
                                     Document.bot_id == hard.bot_id))
                .join(Term, and_(Term.resource_id == Resource.id, Term.organization_id == hard.organization_id,
                    Term.bot_id == hard.bot_id, Term.term_kind == "canonical",
                    or_(and_(Term.source_document_id == anchors.c.document_id, Term.source_version == anchors.c.version,
                        or_(Term.source_crawl_id == anchors.c.crawl_id, and_(Term.source_crawl_id.is_(None), anchors.c.crawl_id.is_(None)))),
                        and_(Term.source_document_id.is_(None), Term.term_source.in_(("admin", "explicit"))))))
                .where(Resource.id.in_(ids), Resource.organization_id == hard.organization_id, Resource.bot_id == hard.bot_id,
                       Resource.status == "ready").order_by(Resource.id, anchors.c.document_id, Term.id).limit(1025)).all() if ids else []
        hydration_overflow = len(rows) > 1024
        rows = rows[:1024]
        if hydration_overflow:
            diagnostics.append({"channel": "hydration", "status": "bounded_incomplete", "count": 1024})
        resources, doc_ids = {}, {}
        for row in rows:
            doc_ids.setdefault(row.id, set()).add(row.document_id)
            resources.setdefault(row.id, row)
        refs = {i: KnowledgeResourceRef(f"org:{hard.organization_id}:bot:{hard.bot_id}:resource:{i}", hard.organization_id,
                hard.bot_id, row.canonical_name, resource_type=row.resource_type, title=row.title,
                url=safe_navigation_url(row.url), document_ids=tuple(sorted(doc_ids[i])), version=row.version)
                for i, row in resources.items()}
        resolutions, all_candidates = [], {}
        for probe, signals, overflow, exact_overflow, unavailable in by_probe:
            signals = [s for s in signals if s.resource_id in refs]
            grouped, ranks = {}, {}
            for s in signals:
                grouped.setdefault(s.resource_id, []).append(s)
                ranks.setdefault(s.channel, []).append(((hard.organization_id, hard.bot_id, s.resource_id), s.rank))
            fused = weighted_rank_union(ranks, CHANNEL_WEIGHTS, RRF_K)
            candidates = []
            query_tokens = set(normalize_resource_text(probe.text).split())
            for fused_rank, (identity, total, contributions) in enumerate(fused, 1):
                i = identity[2]
                sigs = grouped[i]
                # Corroborate the best bounded identity term; metadata-only hits
                # cannot invent a canonical/alias identity proof.
                identity_signals = [s for s in sigs if s.term_kind in IDENTITY_KINDS]
                best = max(identity_signals or sigs, key=lambda s: (token_sort_ratio(normalize_resource_text(probe.text), s.normalized_term), -s.term_id))
                from services.resource_probe_builder import informative_tokens
                information = informative_tokens(probe.text)
                score = {"rrf": total, "fused_rank": fused_rank,
                         "informative_sort": token_sort_ratio(" ".join(sorted(information)),
                                                              " ".join(sorted(informative_tokens(best.normalized_term)))),
                         "informative_coverage": len(information & informative_tokens(best.normalized_term)) / max(1,len(information)),
                         "token_sort": token_sort_ratio(normalize_resource_text(probe.text), best.normalized_term),
                         "token_set": token_set_ratio(normalize_resource_text(probe.text), best.normalized_term),
                         # Compatibility diagnostic for existing opportunity/
                         # acceptance consumers; identity decisions use the
                         # explicit four-state relation, not digit equality.
                         "numeric_agreement": int(numeric_relation(probe.text, best.normalized_term) in {'exact_match', 'no_query_numeric_constraint'}),
                         "token_coverage": len(query_tokens & set(best.normalized_term.split())) / max(1, len(query_tokens))}
                for s in sigs:
                    score[s.channel + "_rank"] = s.rank
                    score[s.channel + "_raw"] = s.raw_score
                score.update((c + "_contribution", value) for c, value in contributions)
                sources = tuple(sorted({s.channel for s in sigs} | ({"legacy_identity"} if any(c == "legacy" for c, _ in contributions) else set())))
                exact = [s for s in sigs if s.channel == "exact"]
                if any(s.term_kind == "title" for s in exact):
                    sources += ("title_exact",)
                if any("legacy_verified" in s.reason_codes for s in sigs):
                    sources += ("legacy_verified",)
                sources += ("term_kind:" + best.term_kind,)
                candidate = ResourceCandidate(refs[i], mention=probe.text, match_sources=sources,
                    canonical_exact=any(s.term_kind == "canonical" for s in exact),
                    alias_exact=any(s.term_kind == "alias" and s.term_source in {"explicit", "admin", "document_metadata"} for s in exact),
                    scores=tuple(sorted(score.items())), reason_codes=(
                        "identity_term" if identity_signals else "navigation_metadata",
                        "numeric_relation:" + numeric_relation(probe.text, best.normalized_term)))
                candidates.append(candidate)
                all_candidates[candidate.resource.resource_id] = candidate
            resolutions.append(self.policy.resolve(probe, candidates, overflow=overflow,
                exact_overflow=exact_overflow or hydration_overflow, exact_unavailable="exact" in unavailable))
        # revision=0 distinguishes an unpopulated rollout catalog, not a missing
        # schema (which raises above). No background projection is triggered.
        return ResourceDiscoveryResult(tuple(all_candidates.values()), tuple(resolutions), revision,
                                       tuple(diagnostics), "catalog_empty" if revision == 0 else "available")
