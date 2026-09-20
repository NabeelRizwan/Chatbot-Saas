"""Q3 file-only replay of all frozen decisions. GOLD is post-decision scoring only."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.discovery_scope import preserve_discovery_scope
from services.retrieval_contracts import (HardKnowledgeScope, ProfileIdentity, KnowledgeResourceRef,
    ResourceCandidate, SoftSemanticScope, SemanticScopeState, QueryExecutionContract, ScopeDecision,
    ScopeStrategy, AbsenceBasis)
from scripts.canary_real_evaluation import snapshots
from scripts.canary_evaluation_resume import provider_free, atomic_record, require


def load_contract(saved):
    e = saved['execution']
    def resource(row):
        values = {k: tuple(tuple(x) if isinstance(x, list) else x for x in v) if isinstance(v, list) else v
                  for k, v in row.items()}
        return KnowledgeResourceRef(**values)
    hard = HardKnowledgeScope(**dict(e['hard_scope'], embedding_profile=ProfileIdentity(**e['hard_scope']['embedding_profile'])))
    soft = dict(e['soft_scope'])
    soft['resolved_resources'] = tuple(resource(r) for r in soft['resolved_resources'])
    soft['resource_candidates'] = tuple(ResourceCandidate(**dict(c, resource=resource(c['resource'])))
                                         for c in soft['resource_candidates'])
    soft['state'] = SemanticScopeState(soft['state'])
    soft = SoftSemanticScope(**soft)
    d = e['scope_decision']
    decision = ScopeDecision(**dict(d, strategy=ScopeStrategy(d['strategy']), absence_basis=AbsenceBasis(d['absence_basis']),
        effective_document_ids=tuple(d['effective_document_ids']) if d['effective_document_ids'] is not None else None,
        semantic_document_ids=tuple(d['semantic_document_ids'])))
    execution = QueryExecutionContract(e['original_user_message'], e['retrieval_query'], hard, soft, decision,
        requested_fields=tuple(e['requested_fields']), intent=e['intent'], version=e['version'],
        resource_discovery=e['resource_discovery'], discovery_identity=e['discovery_identity'])
    return SimpleNamespace(original_query=saved['original_query'], execution=execution,
        permitted_document_ids=saved['permitted_document_ids'], scope_mode=saved['scope_mode'],
        entity_resolution=dict(saved['entity_resolution']))


def replay(root, accepted):
    protected = {}
    def read(path):
        raw = path.read_bytes(); protected[str(path.relative_to(root))] = sha256(raw).hexdigest()
        return json.loads(raw)
    plan = read(root / 'backend/fixtures/canary_real_embedding_v1/plan.json')
    common = snapshots(root, plan)
    gold = {int(c['case_id']): c for c in read(root / 'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json')['cases']}
    rows = []
    for snapshot, baseline_scope in common:
        case = snapshot['id']
        saved = read(root / '.codex_real_corpus_v1' / snapshot['replay_file'])
        q1 = read(accepted / f'case-{case:02d}-STRUCTURAL_CANARY.json')
        require(q1['snapshot_hash'] == snapshot['snapshot_hash'], 'Q1_SNAPSHOT_CHANGED')
        c = load_contract(saved['contract']); old = c.execution
        before = old.hard_scope.intersect(old.scope_decision.effective_document_ids)
        require(tuple(before) == tuple(q1['trace']['effective_scope']), 'Q1_SCOPE_CHANGED')
        preserve_discovery_scope(c, saved['history'])
        after = c.execution.hard_scope.intersect(c.execution.scope_decision.effective_document_ids)
        require(c.execution.hard_scope is old.hard_scope, 'HARD_SCOPE_CHANGED')
        require(c.execution.soft_scope is old.soft_scope and c.execution.retrieval_query == old.retrieval_query,
                'UPSTREAM_INPUT_CHANGED')
        contained = set(after) <= set(old.hard_scope.authorized_document_ids)
        # Scoring starts only after scope selection, never passed into the policy.
        supported = [s for s in gold[case]['support'] if s['span_mapping'] == 'EXACT_UNIQUE_OCCURRENCE'
                     and s['candidate_atoms'] and s['legacy_exact']]
        units = {(u['route']['document'], u['key']) for u in q1['trace']['materialized']}
        lost = [s['development_document_id'] for s in supported if any(
            (s['development_document_id'], a['atom']) in units for a in s['candidate_atoms'])
            and s['development_document_id'] not in after]
        doc_lost = sorted({s['development_document_id'] for s in supported if s['development_document_id'] in before
                          and s['development_document_id'] not in after})
        scope_misses = [s['development_document_id'] for s in supported if s['development_document_id'] not in after]
        rows.append(dict(case=case, before=before, after=after, reason=c.execution.scope_decision.reason,
            scope_changed=before != after, decision_changed=asdict(old.scope_decision) != asdict(c.execution.scope_decision),
            contained=contained, old_support_made_inaccessible=lost, old_required_docs_made_inaccessible=doc_lost,
            remaining_scope_misses=scope_misses, query_sha256=sha256(snapshot['query'].encode()).hexdigest(),
            hard_scope_identity=old.hard_scope.identity(), snapshot_hash=snapshot['snapshot_hash']))
    require(all(r['contained'] and not r['old_support_made_inaccessible'] and not r['old_required_docs_made_inaccessible']
                for r in rows), 'OFFLINE_SCOPE_GATE_FAILED')
    require(all(sha256((root / p).read_bytes()).hexdigest() == h for p, h in protected.items()), 'FROZEN_INPUT_CHANGED')
    result = dict(status='PASS', cases=90, changed_scope_cases=[r['case'] for r in rows if r['scope_changed']],
        changed_decision_cases=[r['case'] for r in rows if r['decision_changed']],
        remaining_scope_misses=sum(len(r['remaining_scope_misses']) for r in rows),
        old_support_made_inaccessible=0, old_required_docs_made_inaccessible=0,
        provider_calls=0, retrieval_calls=0, protected_file_count=len(protected))
    output = root / '.codex_phase4q' / ('scope-q3-' + uuid.uuid4().hex)
    output.mkdir(exist_ok=False)
    for row in rows:
        atomic_record(output / ('case-%02d.json' % row['case']), row, immutable=True)
    items = list(protected.items())
    for offset in range(0, len(items), 64):
        atomic_record(output / ('protected-%03d.json' % offset), dict(items[offset:offset+64]), immutable=True)
    atomic_record(output / 'scope-replay.json', result, immutable=True)
    print(json.dumps(dict(output=str(output.relative_to(root)), **{k: v for k, v in result.items() if k not in {'rows', 'protected'}})))
    for r in rows:
        if r['decision_changed']: print(json.dumps(r))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted', type=Path, required=True)
    args = parser.parse_args()
    with provider_free():
        replay(Path(__file__).resolve().parents[2], args.accepted.resolve())
