"""Canary-only typed rank fusion, witnesses, bounded exact materialization."""
from dataclasses import dataclass, asdict
import json
import math
from time import perf_counter

from services.canary_contracts import CanaryError, Route, Policy, Manifest


@dataclass(frozen=True)
class Hit:
    route: Route
    evidence_key: str
    rank: int
    score: float
    memberships: tuple[str, ...] = ()


@dataclass(frozen=True)
class LexicalResult:
    hits: tuple[Hit, ...]
    query_status: str


def normalize(hits, manifest, eligible):
    if len(hits) > manifest.policy.candidate_limit:
        raise CanaryError('CHANNEL_CANDIDATE_BOUND')
    unique = {}
    for expected, hit in enumerate(hits, 1):
        r = hit.route
        pin = next((p for p in manifest.documents if p.scope == r.source), None)
        if (hit.rank != expected or not math.isfinite(hit.score) or pin is None or
            r.manifest != manifest.canonical_hash() or r.run_id != manifest.run_id or
            r.generation != manifest.generation or r.lane != manifest.lane or
            r.profile != manifest.profile.canonical_hash() or
            r.source.revision.source.document_id not in eligible):
            raise CanaryError('FOREIGN_OR_INVALID_CHANNEL_HIT')
        if ((r.kind == 'ENTRY' and r.key not in pin.entries) or
            (r.kind == 'ATOM_ONLY' and r.key not in pin.atoms) or
            (r.kind == 'LEGACY_CHUNK' and int(r.key) not in pin.legacy_members)):
            raise CanaryError('UNDECLARED_ROUTE')
        unique.setdefault(r, hit)
    return tuple((r, rank) for rank, r in enumerate(unique, 1))


def typed_rrf(dense, lexical, policy: Policy):
    union = {}
    for channel, rows, weight in (('dense', dense, policy.dense_weight), ('fts', lexical, policy.fts_weight)):
        seen = set()
        for r, rank in rows:
            if rank < 1:
                raise CanaryError('NON_ONE_BASED_RANK')
            if r in seen:
                continue
            seen.add(r)
            union.setdefault(r, {})[channel] = (rank, weight / (policy.rrf_k + rank))
    ordered = sorted(union.items(), key=lambda item: (
        -sum(v[1] for v in item[1].values()), min(v[0] for v in item[1].values()),
        item[0].source.revision.source.document_id, item[0].sort_key()))
    return tuple(dict(route=r, rank=i, dense_rank=v.get('dense', (None, 0))[0],
        fts_rank=v.get('fts', (None, 0))[0], dense_contribution=v.get('dense', (None, 0))[1],
        fts_contribution=v.get('fts', (None, 0))[1], total=sum(x[1] for x in v.values()))
        for i, (r, v) in enumerate(ordered, 1))


def reserve_witnesses(hits, policy):
    selected, seen, counts = [], set(), {}
    for first_pass in (True, False):
        for hit in hits:
            identity = (hit.route.source, hit.evidence_key)
            if identity in seen or (first_pass and counts.get(hit.route, 0) >= 2):
                continue
            if len(selected) >= min(policy.witness_limit, policy.evidence_units):
                return tuple(selected)
            selected.append(hit)
            seen.add(identity)
            counts[hit.route] = counts.get(hit.route, 0) + 1
    return tuple(selected)


def materialize(fused, witnesses, repository, manifest, hard, now):
    """No recursion or entry text as evidence. Whole payload or explicit incomplete."""
    policy = manifest.policy
    requested = [(h.route, h.evidence_key, 'lexical_reservation') for h in witnesses]
    max_fanout = 0
    for row in fused[:policy.evidence_units]:
        r = row['route']
        ids = repository.children(manifest, hard, r, now=now)
        max_fanout = max(max_fanout, len(ids))
        if len(ids) > 32:
            raise CanaryError('MATERIALIZATION_FANOUT_BOUND')
        requested.extend((r, key, 'fused_route') for key in ids)
    units, excluded, seen, used = [], [], set(), 0
    for r, key, reason in requested:
        identity = (r.source, key)
        if identity in seen:
            continue
        seen.add(identity)
        # Fetch one complete bounded unit at a time; never hydrate all 1536 texts.
        if len(units) >= policy.evidence_units:
            excluded.append(dict(key=key, status='INCOMPLETE_BUDGET', reason=reason))
            continue
        payload = repository.evidence(manifest, hard, r, key, now=now)
        size = len(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())
        if size + used > policy.evidence_bytes:
            excluded.append(dict(key=key, status='INCOMPLETE_BUDGET', reason=reason))
            continue
        used += size
        units.append(dict(route=r.model_dump(mode='json'), key=key, payload=payload, reason=reason))
    return dict(units=units, exclusions=excluded, bytes=used, max_fanout=max_fanout,
                supplemental_seeds=[r['route'].model_dump(mode='json') for r in fused[:policy.supplemental_seeds]])


def run_query(repository, manifest: Manifest, hard, *, query, query_vector, now,
              dense_call=None, fts_call=None):
    """Internal runner. Callbacks are explicit test faults, never provider fallback."""
    if len(query) > 8192:
        raise CanaryError('QUERY_BOUND')
    start = perf_counter()
    lease = repository.read_gate(manifest, hard, now=now)
    eligible = manifest.effective(hard)
    trace = dict(manifest=manifest.canonical_hash(), embedding_source=manifest.profile.source,
        effective_scope=list(eligible), hard_scope=hard.identity(), query=query,
        cache='DISABLED', channels={})
    results = {}
    for name, callback in (('dense', dense_call or (lambda: repository.dense(manifest, hard, query_vector, now=now))),
                           ('fts', fts_call or (lambda: repository.fts(manifest, hard, query, now=now)))):
        t = perf_counter()
        try:
            results[name] = callback()
            trace['channels'][name] = dict(status='success', ms=(perf_counter()-t)*1000)
        except CanaryError:
            raise  # authorization/identity corruption must NEVER degrade
        except Exception:
            results[name] = None
            trace['channels'][name] = dict(status='error', category='CHANNEL_FAILURE', ms=(perf_counter()-t)*1000)
    if results['dense'] is None and results['fts'] is None:
        raise CanaryError('BOTH_CHANNELS_FAILED')
    trace['mode'] = ('fts_only' if results['dense'] is None else
                     'dense_only' if results['fts'] is None else 'full_hybrid')
    dense, lexical = results['dense'] or (), results['fts'] or ()
    if isinstance(lexical,LexicalResult):
        trace['lexical_query_status']=lexical.query_status
        lexical=lexical.hits
    else:
        trace['lexical_query_status']='injected_rank_fixture' if results['fts'] is not None else 'channel_failure'
    nd, nf = normalize(dense, manifest, eligible), normalize(lexical, manifest, eligible)
    t = perf_counter()
    fused = typed_rrf(nd, nf, manifest.policy)
    trace['rrf_ms'] = (perf_counter()-t)*1000
    witnesses = reserve_witnesses(lexical, manifest.policy)
    t = perf_counter()
    materialized = materialize(fused, witnesses, repository, manifest, hard, now)
    trace['materialization_ms'] = (perf_counter()-t)*1000
    repository.read_gate(manifest, hard, now=now, expected_epoch=lease)
    def hit_json(hit):
        return dict(route=hit.route.model_dump(mode='json'), evidence_key=hit.evidence_key,
                    rank=hit.rank, score=hit.score, memberships=list(hit.memberships))
    selected = {(json.dumps(u['route']['source'], sort_keys=True), u['key']) for u in materialized['units']}
    trace.update(raw_dense=[hit_json(h) for h in dense], raw_fts=[hit_json(h) for h in lexical],
        dense_routes=[(r.model_dump(mode='json'), rank) for r, rank in nd],
        lexical_routes=[(r.model_dump(mode='json'), rank) for r, rank in nf],
        rrf=[{**row, 'route': row['route'].model_dump(mode='json')} for row in fused],
        lexical_reservations=[hit_json(h) for h in witnesses],
        lexical_ledger=[dict(**hit_json(h), disposition=('KEPT' if
            (json.dumps(h.route.source.model_dump(mode='json'), sort_keys=True), h.evidence_key) in selected
            else 'BUDGET_OR_ROUTE_NOT_SELECTED')) for h in lexical],
        materialized=materialized, source_revalidation='PASS', run_epoch=lease,
        route_collapse_ratio=(1-len(nf)/len(lexical) if lexical else 0),
        final_status=('INCOMPLETE_BUDGET' if materialized['exclusions'] else 'COMPLETE'),
        total_ms=(perf_counter()-start)*1000)
    return trace
