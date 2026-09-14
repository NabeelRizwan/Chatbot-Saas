"""Phase 3.4 controlled acceptance; reuse unchanged Phase 3.1 ownership guards.

Only test orchestration/measurement lives here. No runtime search substitute is
used remotely. SQLite is used solely in the explicitly diagnostic parity audit.
"""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import re
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import MetaData
from scripts import phase31_acceptance as core, phase33_acceptance as previous
from scripts import phase31_fixture as data

require = previous.require
GateFailure = previous.GateFailure
ZERO_ORG, ZERO_BOT = 27, 28


@dataclass(frozen=True)
class NaturalCase:
    key: str
    question: str
    family: str
    organization: int
    bot: int


def natural_cases():
    # Zero presence is tested ONLY in the isolated two-resource bot. Normal
    # catalogs use observed-outcome safety; fuzzy presence is never guessed.
    descriptions = (
        'design office interiors', 'develop mobile applications', 'train laboratory assistants',
        'schedule patient visits', 'prepare business taxes', 'review commercial leases',
        'repair gaming laptops', 'track freight shipments', 'reserve conference rooms',
        'monitor irrigation systems', 'restore antique paintings', 'coordinate volunteer assignments',
    )
    short = ('AI', 'Pro', 'PDF', 'service', 'plan', 'form', 'support', 'HR', 'x', 'guide')
    categories = ('What services do you offer?', 'What plans do you have?', 'What courses are available?',
                  'What forms do you offer?', 'What departments are available?')
    domains = ('devices', 'interiors', 'finance', 'learning', 'appointments')
    rows = [NaturalCase(f'free-{i}', q, 'candidate_free', ZERO_ORG, ZERO_BOT) for i, q in enumerate(descriptions)]
    rows += [NaturalCase('fuzzy-0', 'reserve conference rooms', 'fuzzy', 28, 29)]
    rows += [NaturalCase(f'fuzzy-{i+1}', f'Can you show me {q}?', 'fuzzy', 3, 4)
             for i, q in enumerate(fuzzy_probes()[::3][:11])]
    rows += [NaturalCase(f'short-{i}', q, 'short', 28, 29) for i, q in enumerate(short)]
    rows += [NaturalCase(f'category-{i}', q, 'category', 29, 30) for i, q in enumerate(categories)]
    rows += [NaturalCase(f'relation-{i}', f'What is between Bronze {d} Plan and Gold {d} Plan?', 'relation', 29, 30)
             for i, d in enumerate(domains)]
    rows += [NaturalCase(f'ambiguous-{i}', f'Show me Amber {d} Choice.', 'ambiguous', 29, 30)
             for i, d in enumerate(domains)]
    return tuple(rows)


def system_documents():
    """One existing bulk seed; isolate two filler rows, not benchmark identities.

    Other org-27 filler rows move to org 26. Original 612/50/48 fixtures and
    normal fuzzy bot remain byte-equivalent; totals remain 6,000 documents.
    """
    rows = previous.augmented_documents()
    isolated = 0
    for row in rows:
        if row['organization_id'] != ZERO_ORG:
            continue
        if isolated < 2:
            row.update(title=('ZXQJ 78124', 'VKMZ 95367')[isolated],
                       metadata_json={'resource_type': 'custom'})
            isolated += 1
        else:
            row.update(organization_id=26, bot_id=27)
    require(isolated == 2, 'tiny_fixture')
    return rows


def member_safe(member):
    """Acceptance oracle over observed evidence, not a replacement resolver.

    Fixed runtime decision/proof codes must agree with the actual candidate
    count. No raw RRF/semantic winner is accepted. Candidate bounds/identity
    uniqueness remain the frozen ResourceResolutionPolicy's responsibility.
    """
    gap = member.get('semantic_gap') or {}
    count = member.get('candidate_count', -1)
    state, selected = member.get('state'), member.get('selected_resource_id')
    basis, eligible = gap.get('basis'), gap.get('eligible_for_optimizer')
    reasons = set(member.get('reason_codes', ()))
    if count < 0 or gap.get('candidate_count') != count:
        return False
    if count and basis == 'candidate_free_informative':
        return False
    if basis in {'empty_hard_scope', 'technical_failure', 'category', 'structured_relation_required'}:
        return not selected and state == 'unresolved' and eligible is False
    protected = {'candidate_limit_prevents_uniqueness', 'conflicting_exact_identities',
                 'conflicting_complete_token_identities', 'conflicting_probe_variants'}
    if reasons & protected:
        return state == 'ambiguous' and not selected and basis == 'ambiguity' and eligible is False
    if state == 'resolved':
        candidates = [c for c in member.get('candidates', ()) if c['resource_id'] == selected]
        if not count or len(candidates) != 1 or eligible or basis != 'not_eligible':
            return False
        c = candidates[0]; channels = set(c['channels']); scores = c['scores']
        if 'authorized_identity' not in channels:
            return False
        if 'exact_unique' in reasons:
            return bool(channels & {'exact', 'legacy_verified', 'title_exact'})
        if 'identity_term' not in c['reason_codes'] or scores.get('numeric_agreement') != 1:
            return False
        if 'unique_complete_token_identity' in reasons:
            return 'fts' in channels and scores.get('token_sort') == 100
        if 'unique_corroborated_identity' in reasons:
            return (('trigram' in channels and scores.get('token_sort', 0) >= 88) or
                    ('fts' in channels and scores.get('token_coverage') == 1 and scores.get('token_set') == 100))
        return False
    if selected or state not in {'ambiguous', 'unresolved'}:
        return False
    if count == 0 and gap.get('informative_token_count', 0) >= 2:
        return state == 'unresolved' and basis == 'candidate_free_informative' and eligible is True
    return basis != 'candidate_free_informative' and (
        not eligible or (count > 0 and basis == 'candidate_backed_insufficient'))


def natural_record(case, contract):
    execution = contract.execution
    trace = execution.resource_discovery
    members = trace.get('resolutions', [])
    soft = execution.soft_scope
    selected = list(soft.resolved_document_ids)
    exact = execution.scope_decision.exact_narrowing_applied
    eligibility = [m.get('semantic_gap') or {} for m in members]
    no_selected = not selected and not exact
    if case.family == 'fuzzy':
        selected_members = {d for m in members for c in m.get('candidates', ())
                            if c['resource_id'] == m.get('selected_resource_id') for d in c['document_ids']}
        all_resolved = bool(members) and all(m['state'] == 'resolved' for m in members)
        passed = (bool(members) and all(member_safe(m) for m in members)
                  and set(selected) == selected_members and (all_resolved or not exact))
    elif case.family == 'candidate_free':
        passed = (len(members) == 1 and no_selected and not soft.resource_candidates
                  and members[0]['state'] == 'unresolved' and members[0]['candidate_count'] == 0
                  and eligibility[0].get('eligible_for_optimizer') is True
                  and eligibility[0].get('basis') == 'candidate_free_informative'
                  and not contract.requires_clarification)
    elif case.family == 'short':
        passed = no_selected and not any(g.get('eligible_for_optimizer') for g in eligibility)
    elif case.family == 'category':
        passed = no_selected and bool(members) and all(m['category_intent'] for m in members)
        passed &= all(g.get('basis') == 'category' and not g.get('eligible_for_optimizer') for g in eligibility)
    elif case.family == 'relation':
        passed = no_selected and bool(eligibility) and all(g.get('basis') == 'structured_relation_required' for g in eligibility)
    else:
        passed = (no_selected and contract.requires_clarification and soft.ambiguity
                  and any(m['candidate_count'] >= 2 for m in members)
                  and any(g.get('basis') == 'candidate_backed_insufficient' for g in eligibility))
    healthy = trace.get('status') == 'available' and bool(trace.get('channels')) and all(
        d.get('status') == 'success' for d in trace['channels'])
    leaks = sum(c.resource.organization_id != case.organization or c.resource.bot_id != case.bot for c in soft.resource_candidates)
    return dict(key=case.key, question=case.question, family=case.family, passed=bool(passed and healthy and not leaks),
        state=soft.state.value, scope=execution.scope_decision.strategy.value, selected=selected,
        candidate_count=len(soft.resource_candidates), leaks=leaks, trace=trace,
        search_healthy=healthy, safe_members=bool(members) and all(member_safe(m) for m in members))


def natural_gates(engine, result):
    with Session(engine) as db:
        f = core.fixture(db, 3, 4)
        result['stage'] = 'q_one'
        q1 = previous.golden_record(f, 1)
        result['former_four'] = [q1]
        core.emit('q1_actual', q1)
        members = q1['trace']['resolutions']
        first = members[0] if members else {}
        q1['reviewed_ok'] = bool(q1['frozen_match'] and not q1['leaks'] and members
                                and all(member_safe(m) for m in members))
        core.emit('q1_reviewed', q1)
        require(q1['reviewed_ok'], 'q_one_safe_comparison')
        result['stage'] = 'controlled_and_fuzzy'
        result['unrelated'] = []
        for case in natural_cases():
            f = core.fixture(db, case.organization, case.bot)
            row = natural_record(case, f.contract(case.question))
            row['passed'] &= row['search_healthy'] and row['safe_members']
            result['unrelated'].append(row)
            core.emit('unrelated_semantic_gap', row)
            require(row['passed'], 'unrelated_semantic_gap')
        require(len(result['unrelated']) == 49, 'unrelated_count')
        result['stage'] = 'former_three'
        f = core.fixture(db, 3, 4)
        for number in (2, 3, 10):
            row = previous.golden_record(f, number)
            result['former_four'].append(row)
            core.emit('former_three', row)
            require(row['reviewed_ok'] and row['frozen_match'] and not row['leaks'], 'former_three')
        result['stage'] = 'reviewed_fifty'
        saved = {r['id']: r for r in result['former_four']}
        result['golden'] = []
        for number in range(1, 51):
            row = saved.get(number)
            if row is None:
                row = previous.golden_record(f, number)
                core.emit('golden_case', row)
            result['golden'].append(row)
            require(row['reviewed_ok'] and not row['leaks'], 'reviewed_fifty')


def candidate_free_handoffs(engine, result):
    from services import rag_service as rag
    from services.observability_service import ChatTrace
    sessions = sessionmaker(bind=engine)
    rows = []
    with patch.object(rag, 'SessionLocal', sessions), patch.object(rag, 'generate_embedding', return_value=data.vector()), \
         patch.object(rag, 'resolve_active_embedding_profile', return_value=SimpleNamespace(
             provider='gemini', model='gemini-embedding-001', version=1, dimensions=768)), \
         patch.dict(os.environ, {'RAG_LEXICAL_BACKEND': 'postgres_fts', 'RAG_RESOURCE_DISCOVERY': 'on'}):
        with sessions() as db:
            f = core.fixture(db, ZERO_ORG, ZERO_BOT)
            for case in [r for r in natural_cases() if r.family == 'candidate_free']:
                c = f.contract(case.question)
                require(natural_record(case, c)['passed'], 'free_handoff_contract')
                trace = ChatTrace(ZERO_BOT, 'synthetic-phase34')
                chunks = rag.retrieve_relevant_chunks(db, ZERO_BOT, c.retrieval_query, query_contract=c, trace=trace)
                evidence = core.evidence_rows(chunks)
                from database.models import Document
                ids = {r['document_id'] for r in evidence}
                authorized = {x[0] for x in db.query(Document.id).filter(Document.organization_id == ZERO_ORG, Document.bot_id == ZERO_BOT).all()}
                ok = bool(evidence) and ids <= authorized and not c.execution.scope_decision.exact_narrowing_applied
                ok &= 'UNSUPPORTED SUMMARY' not in str(evidence) and '90-day refund guarantee' not in str(evidence)
                rows.append(dict(question=case.question, passed=bool(ok), documents=sorted(ids),
                                 evidence=evidence, trace=trace.to_debug_dict()))
                core.emit('candidate_free_handoff', rows[-1])
                require(ok, 'candidate_free_handoff')
    result['candidate_free_handoffs'] = rows
    require(len(rows) == 12, 'candidate_free_handoff_count')


def non_exact_handoffs(engine, result):
    """Actual incomplete-comparison retrieval and ambiguity terminal, no LLM."""
    from services import rag_service as rag
    from database.models import Document
    sessions = sessionmaker(bind=engine)
    rows = []
    with patch.object(rag, 'SessionLocal', sessions), patch.object(rag, 'generate_embedding', return_value=data.vector()), \
         patch.object(rag, 'resolve_active_embedding_profile', return_value=SimpleNamespace(
             provider='gemini', model='gemini-embedding-001', version=1, dimensions=768)), \
         patch.dict(os.environ, {'RAG_LEXICAL_BACKEND': 'postgres_fts', 'RAG_RESOURCE_DISCOVERY': 'on'}):
        with sessions() as db:
            f = core.fixture(db, 3, 4)
            authorized = {d for (d,) in db.query(Document.id).filter(Document.organization_id == 3, Document.bot_id == 4)}
            for number in (1, 2):
                c = f.contract(data.GOLDEN[number-1][0])
                require(not c.execution.scope_decision.exact_narrowing_applied, 'non_exact_handoff')
                if number == 2:
                    ok = c.requires_clarification and not c.execution.soft_scope.resolved_document_ids
                    evidence = []  # Application must stop at clarification.
                else:
                    require(not c.requires_clarification and c.execution.soft_scope.state.value == 'incomplete_comparison',
                            'incomplete_handoff_contract')
                    evidence = core.evidence_rows(rag.retrieve_relevant_chunks(db, 4, c.retrieval_query, query_contract=c))
                    ids = {r['document_id'] for r in evidence}
                    ok = bool(evidence) and ids <= authorized and '90-day refund guarantee' not in str(evidence)
                rows.append(dict(id=number, passed=bool(ok), evidence=evidence,
                                 scope=c.execution.scope_decision.strategy.value))
                core.emit('non_exact_handoff', rows[-1])
                require(ok, 'non_exact_handoff')
    result['non_exact_handoffs'] = rows


def fuzzy_probes():
    probes = []
    for _, title, _, _ in data.NATURAL[:20]:
        words = title.split()
        index = next(i for i, word in enumerate(words) if len(word) >= 4)
        word = words[index]
        for changed in (word[:1] + word[2:3] + word[1:2] + word[3:], word[:-1], word[:2] + 'x' + word[3:]):
            altered = words[:]
            altered[index] = changed
            probes.append(' '.join(altered))
    return tuple(probes)


def surrogate_audit(engine, result):
    from test_resource_discovery import ResourceFixture, SQLiteTestChannel
    from services.resource_discovery import ResourceDiscoveryService
    from services.resource_channels import ResourceProbe, SQLResourceChannel
    local = ResourceFixture()
    local.setUp()
    rows = []
    try:
        for n, name, kind, aliases in data.NATURAL:
            local.add(n, name, kind=kind, aliases=aliases)
        local.project(*[x[0] for x in data.NATURAL])
        local.service = ResourceDiscoveryService([SQLiteTestChannel('trigram')])
        with Session(engine) as db:
            remote = core.fixture(db, 3, 4, service=ResourceDiscoveryService([SQLResourceChannel('trigram')]))
            for query in fuzzy_probes():
                ranked = []
                for f in (local, remote):
                    answer = f.service.discover(f.db, f.hard, (ResourceProbe(query),))
                    require(all(c.resource.organization_id == f.hard.organization_id and c.resource.bot_id == f.hard.bot_id
                                for c in answer.candidates), 'parity_isolation')
                    ranked.append([d for c in answer.candidates for d in c.resource.document_ids])
                sql, pg = ranked
                union = set(sql[:5]) | set(pg[:5])
                rows.append(dict(query=query, surrogate=sql, postgres=pg,
                    presence_agrees=bool(sql) == bool(pg), postgres_only=sorted(set(pg)-set(sql)),
                    surrogate_only=sorted(set(sql)-set(pg)),
                    top_five_jaccard=len(set(sql[:5]) & set(pg[:5])) / len(union) if union else 1.0))
                core.emit('surrogate_parity_case', rows[-1])
    finally:
        local.doCleanups()
    require(len(rows) == 60, 'parity_count')
    result['surrogate_parity'] = dict(probes=60, presence_agreement=sum(r['presence_agrees'] for r in rows)/60,
        postgres_only_cases=sum(bool(r['postgres']) and not r['surrogate'] for r in rows),
        surrogate_only_cases=sum(bool(r['surrogate']) and not r['postgres'] for r in rows),
        postgres_only_candidates=sum(len(r['postgres_only']) for r in rows),
        surrogate_only_candidates=sum(len(r['surrogate_only']) for r in rows),
        mean_top_five_jaccard=sum(r['top_five_jaccard'] for r in rows)/60,
        interpretation='Diagnostic only; PostgreSQL authoritative; empty/empty top-five overlap = 1.')
    core.emit('surrogate_parity_summary', result['surrogate_parity'])


def performance(engine, result):
    from services.resource_channels import ResourceProbe, SQLResourceChannel
    from services.resource_scope_adapter import discovery_probes
    families = {
        'exact': (29, 30, ('Laptop Repair Service',)),
        'fts': (29, 30, ('Repair Laptop Service',)),
        'trigram': (29, 30, ('Laptop Repiar Service',)),
        'multi_resource': (29, 30, ('Laptop Repair Service', 'Cobalt devices Advisory')),
        'candidate_free': (28, 29, (natural_cases()[0].question,)),
        'natural_query': (3, 4, ('Which service would I need if I want both an app and backend?',)),
    }
    measured = {}; all_walls = []; all_db = []
    with Session(engine) as db:
        for family, (org, bot, names) in families.items():
            f = core.fixture(db, org, bot)
            probes = (discovery_probes(f.contract(names[0]), {}) if family == 'natural_query'
                      else tuple(ResourceProbe(q) for q in names))
            walls = []; executions = []; plans = []
            for _ in range(5):
                start = perf_counter()
                f.service.discover(db, f.hard, probes)
                walls.append((perf_counter()-start)*1000)
                sample = []
                for p in probes:
                    for v in p.variants or (SimpleNamespace(text=p.text, provenance=p.provenance),):
                        for channel in ('exact', 'fts', 'trigram', 'metadata'):
                            statement = SQLResourceChannel(channel).statement(db, f.hard, ResourceProbe(v.text, v.provenance), 32)
                            compiled = statement.compile(dialect=engine.dialect, compile_kwargs={'render_postcompile': True})
                            plan = db.connection().exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+str(compiled), compiled.params).scalar()[0]
                            sample.append(plan)
                executions.append(sum(p['Execution Time'] for p in sample))
                if not plans: plans = sample
            measured[family] = dict(service_wall=core.percentiles(walls),
                channel_db_execution_sum=core.percentiles(executions), natural_plans=plans)
            all_walls.extend(walls); all_db.extend(executions)
            core.emit('phase34_performance_family', {family: measured[family]})
    measured['mixed'] = dict(service_wall=core.percentiles(all_walls), channel_db_execution_sum=core.percentiles(all_db))
    result['performance'] = measured
    core.emit('phase34_performance_mixed', measured['mixed'])


def setup_system_fixture(conn, result):
    """Required fixture creation only; no repeated infrastructure acceptance."""
    from database.connection import Base
    from database import models
    from database.resource_schema_v1 import TABLE_NAMES
    old = MetaData()
    for table in Base.metadata.tables.values():
        if table.name not in TABLE_NAMES:
            clone = table.to_metadata(old)
            for constraint in tuple(clone.constraints):
                if constraint.name in {'uq_bots_resource_tenant', 'uq_documents_resource_tenant'}:
                    clone.constraints.remove(constraint)
    old.create_all(conn)
    core.register(conn); conn.commit()
    core.migrate(conn, 'upgrade')  # Fixture prerequisite, unchanged migration.
    core.register(conn); conn.commit()
    docs = system_documents()
    with patch.object(data, 'documents', return_value=docs):
        result['fixture'] = data.bulk_seed(conn)
    conn.exec_driver_sql("CREATE INDEX ix_chunks_content_fts_en_v1 ON chunks USING gin (to_tsvector('english'::regconfig, coalesce(content,'')))")
    conn.exec_driver_sql('ANALYZE')
    core.register(conn); conn.commit()
    result['fixture']['isolated_bot_resources'] = sum(d['bot_id'] == ZERO_BOT for d in docs)
    core.emit('bulk_seed', result['fixture'])


def light_concurrency(engine, result):
    """Exactly 20 simultaneous reads. Fixed expected identity; no repeat/writes."""
    from services.resource_channels import ResourceProbe
    from services.resource_discovery import ResourceDiscoveryService
    from services.retrieval_contracts import HardKnowledgeScope
    barrier = Barrier(20, timeout=30)
    def read_case(i):
        org, bot, expected = 4+i, 5+i, 100000+i
        with Session(engine) as db:
            barrier.wait()
            answer = ResourceDiscoveryService().discover(db, HardKnowledgeScope(org, bot),
                [ResourceProbe(f'Atlas Sector {i} Reference')])
            selected = {d for r in answer.resolutions if r.candidate for d in r.candidate.resource.document_ids}
            return dict(expected=expected, selected=sorted(selected), stable=selected == {expected},
                leaks=sum(c.resource.organization_id != org or c.resource.bot_id != bot for c in answer.candidates))
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        rows = list(pool.map(read_case, range(20)))
    result['concurrency'] = dict(requests=20, stable=all(r['stable'] for r in rows),
        leaks=sum(r['leaks'] for r in rows), errors=0, writes=0, seconds=perf_counter()-started, results=rows)
    core.emit('light_concurrency', result['concurrency'])
    require(result['concurrency']['stable'] and not result['concurrency']['leaks'], 'concurrency')


def run(engine, conn, result):
    result['stage'] = 'migration_seed'
    setup_system_fixture(conn, result)
    require(result.get('fixture', {}).get('documents') == 6000 and
            result['fixture'].get('isolated_bot_resources') == 2, 'fixture_shape')
    natural_gates(engine, result)
    result['stage'] = 'application_handoffs'; previous.handoffs(engine, result)
    candidate_free_handoffs(engine, result)
    non_exact_handoffs(engine, result)
    result['stage'] = 'generic_612'; core.benchmarks(engine, result)
    require(len(result.get('benchmark', {})) == 2 and all(all(b['gates'].values()) for b in result['benchmark'].values()), 'generic_612')
    result['stage'] = 'surrogate_parity'; surrogate_audit(engine, result)
    result['stage'] = 'light_concurrency'; light_concurrency(engine, result)
    result['stage'] = 'historical_last'; core.historical(engine, result)
    core.emit('historical_last', result['historical'])
    require(result['historical']['pass'], 'historical_last')


def main():
    started = perf_counter(); result = {'stage': 'preflight'}; facts = {}; status = 1
    try:
        with core.isolated_application_imports(), core.disposable_database() as (engine, conn, facts):
            core.emit('preflight', facts)
            run(engine, conn, result)
        require(all(facts.get('cleanup', {}).get(k) for k in ('schema_absent', 'marker_tables_indexes_absent',
                    'unrelated_objects_unchanged', 'existing_extensions_retained')), 'cleanup')
        status = 0
    except Exception as exc:
        result['failure'] = {'stage': result['stage'], 'class': type(exc).__name__}
        if isinstance(exc, GateFailure) and re.fullmatch('[a-z_]+', str(exc)):
            result['failure']['gate'] = str(exc)
        result['failure']['sqlstate'] = getattr(getattr(exc, 'orig', exc), 'pgcode', None)
        status = 2 if isinstance(exc, core.DisposableUnavailable) else 1
    finally:
        os.environ.pop('PHASE3_TEST_DATABASE_URL', None)
        os.environ.pop('PHASE3_ALLOW_REMOTE_DISPOSABLE', None)
    summary = {k:v for k,v in result.items() if k not in {'former_four', 'unrelated', 'golden', 'handoffs',
        'candidate_free_handoffs', 'benchmark', 'performance', 'natural_plans'}}
    summary.update(facts=facts, total_seconds=perf_counter()-started, status=status)
    summary['counts'] = {key: {'total': len(result.get(key, [])),
        'passed': sum(r.get('reviewed_ok', r.get('passed', False)) for r in result.get(key, []))}
        for key in ('former_four', 'unrelated', 'golden', 'handoffs', 'candidate_free_handoffs', 'non_exact_handoffs')}
    summary['original_oracle'] = sum(r['original_ok'] for r in result.get('golden', []))
    summary['verdict'] = 'PHASE 3 FULLY ACCEPTED — READY FOR PHASE 4' if status == 0 else 'PHASE 3 NOT YET ACCEPTED'
    core.emit('phase34_final', summary)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
