"""Frozen, file-only evaluation inputs; GOLD is never a retrieval argument."""
import json
from dataclasses import asdict
from hashlib import sha256
from services.canary_contracts import CanaryError
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity
from services.structural_chunking import digest


def snapshots(root, plan):
    folder = root / '.codex_real_corpus_v1'
    path = folder / 'REAL_CORPUS_V1_EVAL_V1.json'
    if sha256(path.read_bytes()).hexdigest() != plan['evaluation_sha256']:
        raise CanaryError('FROZEN_EVALUATION_CHANGED')
    cases = json.loads(path.read_text(encoding='utf-8'))['cases']
    result = []
    for case in cases:
        key = int(case['id'])
        prefix = ('VERIFIER_RETEST_EVAL_V1' if key <= 8 else
                  'VERIFIER_RETEST_EVAL_V1_CONTINUATION' if key <= 39 else
                  'PLANNER_CONTRACT_EVAL_V1' if key <= 68 else 'FINAL_PLANNER_EVAL_V1')
        saved_path = folder / f'{prefix}_{key}.json'
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        if saved['question'] != case['question'] or int(saved['id']) != key:
            raise CanaryError('COMMON_SNAPSHOT_QUESTION_MISMATCH')
        contract = saved['contract']
        execution = contract['execution']
        hard = dict(execution['hard_scope'])
        hard['embedding_profile'] = ProfileIdentity(**hard['embedding_profile'])
        scope = HardKnowledgeScope(**hard)
        # Reuse exactly the historical scope decision. Never broaden using GOLD.
        selected = execution['scope_decision']['effective_document_ids']
        if selected is not None:
            hard['authorized_document_ids'] = scope.intersect(selected)
            scope = HardKnowledgeScope(**hard)
        query = contract.get('retrieval_query') or contract.get('resolved_query') or case['question']
        snapshot = dict(id=key, question=case['question'], history=saved['history'],
            contract=contract, query=query, hard_scope=asdict(scope),
            replay_file=saved_path.name, replay_sha256=sha256(saved_path.read_bytes()).hexdigest())
        snapshot['snapshot_hash'] = digest(snapshot)
        result.append((snapshot, scope))
    if len(result) != 90 or len({v[0]['id'] for v in result}) != 90:
        raise CanaryError('COMMON_SNAPSHOT_INVENTORY_MISMATCH')
    return tuple(result)


def score_case(trace, gold, lane, effective, entry_atoms=None):
    """Exact sidecar identities only; no inferred field labels or semantic gold.

    A mapped historical span is detected when a known source-proven constituent
    atom is selected. This is span-hit recall, NOT full fact/qualification recall.
    Mapping gaps stay out of both lanes' common denominators.
    """
    support = [v for v in gold['support'] if v['span_mapping'] == 'EXACT_UNIQUE_OCCURRENCE'
               and v['candidate_atoms'] and v['legacy_exact']]
    def doc(route): return route['source']['revision']['source']['document_id']
    def hit(obligation, route, evidence=None):
        if doc(route) != obligation['development_document_id']: return False
        if lane == 'LEGACY_CONTROL':
            return route['key'] == str(obligation['legacy_chunk_id'])
        if evidence is not None:
            return evidence in {a['atom'] for a in obligation['candidate_atoms']}
        if route['kind']=='ENTRY' and entry_atoms is not None:
            return bool(set(entry_atoms.get((doc(route),route['key']),())) &
                        {a['atom'] for a in obligation['candidate_atoms']})
        return any((route['kind'], route['key']) == tuple(a['route']) for a in obligation['candidate_atoms'])
    metrics = {}
    for channel in ('dense', 'fts'):
        for limit in (5, 10, 48):
            rows = trace['raw_' + channel][:limit]
            metrics[f'{channel}_span_hit_recall_{limit}'] = [sum(any(hit(s, r['route'],
                r['evidence_key'] if channel == 'fts' and lane != 'LEGACY_CONTROL' else None)
                for r in rows) for s in support), len(support)]
    for limit in (10, 48):
        metrics[f'rrf_span_hit_recall_{limit}'] = [sum(any(hit(s, r['route'])
            for r in trace['rrf'][:limit]) for s in support), len(support)]
    units = trace['materialized']['units']
    metrics['materialized_span_hit_recall'] = [sum(any(hit(s, u['route'], u['key'])
        for u in units) for s in support), len(support)]
    required = {s['development_document_id'] for s in support}
    returned = [doc(u['route']) for u in units]
    metrics['required_document_recall'] = [len(required & set(returned)), len(required)]
    metrics['source_noise_relative_to_mapped_support'] = [sum(d not in required for d in returned) if required else 0,
                                                        len(returned) if required else 0]
    identities = [(doc(u['route']), u['key']) for u in units]
    metrics['duplicate_evidence_rate'] = [len(identities)-len(set(identities)), len(identities)]
    return dict(metrics=metrics, gold_mapping_gaps=len(gold['support'])-len(support),
        query_understanding_failure=bool(required-set(effective)),
        candidate_diversity=len({doc(r['route']) for r in trace['rrf']}),
        lexical_collapse=trace['route_collapse_ratio'],
        atom_only=sum(r['route']['kind']=='ATOM_ONLY' for r in trace['rrf']),
        incomplete_budget=trace['final_status']=='INCOMPLETE_BUDGET',
        false_absence=None, wrong_source_claim=None,
        explanation='No answers generated; absence/wrong-claim metrics unscored; field assignments remain unreviewed.')


def safe_trace(trace):
    """Digest/ID/rank trace only. No corpus text, prompts or vector coordinates."""
    def route(r):
        return dict(document=r['source']['revision']['source']['document_id'],
            kind=r['kind'], key=r['key'], generation=r['generation'])
    return dict(manifest=trace['manifest'], effective_scope=trace['effective_scope'],
        hard_scope=trace['hard_scope'], query_hash=sha256(trace['query'].encode()).hexdigest(),
        mode=trace['mode'], lexical_query_status=trace['lexical_query_status'],
        channels=trace['channels'], rrf_ms=trace['rrf_ms'],
        materialization_ms=trace['materialization_ms'], total_ms=trace['total_ms'],
        raw_dense=[dict(route=route(h['route']), rank=h['rank'], score=h['score']) for h in trace['raw_dense']],
        raw_fts=[dict(route=route(h['route']), rank=h['rank'], score=h['score'], atom=h['evidence_key']) for h in trace['raw_fts']],
        rrf=[dict(route=route(r['route']), rank=r['rank'], total=r['total'],
            dense_rank=r['dense_rank'], fts_rank=r['fts_rank']) for r in trace['rrf'][:48]],
        materialized=[dict(route=route(u['route']), key=u['key']) for u in trace['materialized']['units']],
        bytes=trace['materialized']['bytes'], status=trace['final_status'],
        source_revalidation=trace['source_revalidation'])
