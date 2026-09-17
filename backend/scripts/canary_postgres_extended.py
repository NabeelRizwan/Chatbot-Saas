"""Additional opt-in PG assertions. Synthetic fixtures only; no default connection.

All connections and ownership guards come from the explicit acceptance runner.
Never mutate a seal or disable triggers to manufacture an accepted fixture.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Event
from time import time

from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError

from database import canary_schema as s
from services.canary_contracts import CanaryError, State, Lane, synthetic_vector
from services.canary_repository import CanaryRepository, document_values, run_values, where
from services.canary_representation import atomic_projection, evidence_view, exact_input_hash
from services.canary_retrieval import normalize, typed_rrf, run_query
from services.structural_chunking import digest, serialize_structural_document
from services.structural_retrieval_entries import RetrievalEntryScope
from services import structural_retrieval_entries_v2 as m
from scripts.canary_stage_a import fixture_batch, make_manifest, hard_scope
from scripts.evaluate_structural_retrieval_entries import namespace_evidence
from scripts.structural_retrieval_entry_gold import evidence


def require(value, code):
    if not value:
        raise CanaryError(code)


def explain(conn, statement, params):
    # Compile with SQLAlchemy's installed psycopg2 dialect, never interpolate data.
    compiled = statement.params(**params).compile(dialect=conn.dialect,
        compile_kwargs={'render_postcompile': True})
    plan = conn.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + str(compiled), compiled.params).scalar_one()
    return {'forced': False, 'plan': plan}


def inspect_query(acceptance, repo, result, vector):
    manifest = acceptance.manifest
    require(manifest.policy.rrf_k == 60 and manifest.policy.dense_weight == manifest.policy.fts_weight == 1, 'RRF_POLICY')
    for channel in ('dense', 'fts'):
        rows = result['raw_' + channel]
        require([r['rank'] for r in rows] == list(range(1, len(rows) + 1)), 'CHANNEL_RANK_BASE')
    for row in result['rrf']:
        d = 0 if row['dense_rank'] is None else 1 / (60 + row['dense_rank'])
        f = 0 if row['fts_rank'] is None else 1 / (60 + row['fts_rank'])
        require((row['dense_contribution'], row['fts_contribution'], row['total']) == (d, f, d + f), 'RRF_CONTRIBUTIONS')
    require(len(result['lexical_routes']) == len({json.dumps(x[0], sort_keys=True) for x in result['lexical_routes']}), 'LEXICAL_ROUTE_COLLAPSE')
    require(len(result['lexical_ledger']) == len(result['raw_fts']), 'RAW_WITNESS_LEDGER')
    dense = repo.dense(manifest, hard_scope(manifest), vector, now=int(time()))
    lexical = repo.fts(manifest, hard_scope(manifest), 'console OR renewal', now=int(time())).hits
    nd = normalize(dense, manifest, manifest.effective(hard_scope(manifest)))
    nf = normalize(lexical, manifest, manifest.effective(hard_scope(manifest)))
    require(typed_rrf(nd, nf, manifest.policy) == typed_rrf(nd, nf, manifest.policy), 'RRF_STABILITY')
    materialized = result['materialized']
    require(len(materialized['units']) <= 48 and materialized['bytes'] <= 131072 and materialized['max_fanout'] <= 32, 'MATERIALIZATION_BOUND')
    expected = {a.atom_key: evidence_view(atomic_projection(acceptance.batch, a)) for a in acceptance.batch.atoms}
    for unit in materialized['units']:
        require(unit['payload'] == expected[unit['key']], 'MATERIALIZATION_NOT_EXACT_SOURCE')
    require(materialized['units'], 'EMPTY_MATERIALIZATION')
    dense_plan = explain(repo.conn, repo.dense_statement(manifest, hard_scope(manifest)),
        {'query_vector': '[' + ','.join(map(str, vector)) + ']'})
    fts_plan = explain(repo.conn, repo.fts_statement(manifest, hard_scope(manifest)), {'query_text': 'console OR renewal'})
    return {'rrf': result['rrf'], 'raw_fts_count': len(lexical), 'collapsed_fts_count': len(nf),
        'raw_witness_count': len(result['lexical_ledger']), 'materialized_units': len(materialized['units']),
        'materialized_bytes': materialized['bytes'], 'exact_payloads': True,
        'channels': result['channels'], 'fusion_ms': result['rrf_ms'],
        'materialization_ms': result['materialization_ms'], 'total_ms': result['total_ms'],
        'natural_dense_explain': dense_plan, 'natural_fts_explain': fts_plan}


def clone_build(repo, original, target, *, omit=None, extra=False):
    """Owned INSERT-only malformed-build fixtures; no trigger/seal bypass."""
    repo.create(target, now=int(time()))
    source = document_values(original, original.documents[0])
    dest = document_values(target, target.documents[0])
    first_atom = repo.conn.execute(select(s.atoms.c.atom_id).where(where(s.atoms, source)).order_by(s.atoms.c.atom_id)).scalars().first()
    for table in (s.entries, s.vectors, s.work, s.atoms, s.memberships, s.spans):
        rows = [dict(r) for r in repo.conn.execute(select(table).where(where(table, source))).mappings()]
        if omit == 'atom' and table in (s.atoms, s.memberships, s.spans):
            rows = [r for r in rows if r['atom_id'] != first_atom]
        if (omit == 'vector' and table is s.vectors) or (omit == 'mapping' and table is s.spans):
            rows = rows[1:]
        if rows:
            repo.conn.execute(insert(table), [r | dest for r in rows])
    if extra:
        key = digest('undeclared-entry')
        for table in (s.entries, s.vectors, s.work):
            row = dict(repo.conn.execute(select(table).where(where(table, dest)).limit(1)).mappings().one())
            row['entry_id'] = key
            if table is s.entries:
                row['ordinal'] += 1000
            repo.conn.execute(insert(table).values(**row))


def seal_negatives(acceptance):
    observations = {}
    cases = ('missing_vector', 'extra_vector', 'missing_atom', 'missing_mapping',
             'manifest_mismatch', 'source_epoch', 'cancelled', 'expired', 'wrong_generation')
    with acceptance.db.transaction() as conn:
        repo = acceptance.repo(conn)
        for name in cases:
            savepoint = conn.begin_nested()
            try:
                target = make_manifest(acceptance.manifest.documents, run='negative-' + name.replace('_', '-'), approved=acceptance.approval)
                omit = {'missing_vector': 'vector', 'missing_atom': 'atom', 'missing_mapping': 'mapping'}.get(name)
                clone_build(repo, acceptance.manifest, target, omit=omit, extra=name == 'extra_vector')
                attempted = target
                if name == 'manifest_mismatch':
                    attempted = target.model_copy(update={'evaluation_hash': digest('different-evaluation')})
                if name == 'wrong_generation':
                    attempted = target.model_copy(update={'generation': 'not-staged'})
                if name == 'cancelled':
                    repo.transition(target, State.CANCELLED, now=int(time()))
                if name == 'source_epoch':
                    conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 1,
                        s.lifecycle.c.organization_id == acceptance.approval.organization_id,
                        s.lifecycle.c.bot_id == acceptance.approval.bot_id).values(epoch=s.lifecycle.c.epoch + 1))
                try:
                    repo.transition(attempted, State.INDEX_READY,
                        now=acceptance.approval.expires_at if name == 'expired' else int(time()))
                except CanaryError as exc:
                    observations[name] = {'result': 'REFUSED', 'guard': str(exc)}
                else:
                    state = conn.execute(select(s.runs.c.state).where(where(s.runs, run_values(target)))).scalar_one()
                    observations[name] = {'result': 'UNEXPECTEDLY_ACCEPTED', 'state': state}
            finally:
                savepoint.rollback()
    acceptance.metrics['seal_negatives'] = observations
    require(all(v['result'] == 'REFUSED' for v in observations.values()), 'SEAL_NEGATIVE_ACCEPTED')
    return observations


def build_namespaced(batch, org, bot, doc, version=1):
    b = namespace_evidence(batch.evidence, organization_id=org, bot_id=bot, document_id=doc, source_version=version)
    return m.build_retrieval_entries(b, scope=RetrievalEntryScope(revision=b.source_graph.revision.identity))


def scoped_candidates(acceptance):
    """Real stronger rows outside authorized scope; rollback fixture rows afterward."""
    approved = acceptance.approval
    foreign = fixture_batch('# Console\n\nconsole console console console console renewal console.', document_id=91)
    vector = synthetic_vector(foreign.entries[-1].text)
    outcomes = {}
    with acceptance.db.transaction() as conn:
        savepoint = conn.begin_nested()
        try:
            for label, org, bot, gen, stale in (
                ('foreign_org', approved.organization_id + 1, approved.bot_id, 'generation-1', False),
                ('foreign_bot', approved.organization_id, approved.bot_id + 1, 'generation-1', False),
                ('stale_generation', approved.organization_id, approved.bot_id, 'old-generation', False),
                ('stale_source', approved.organization_id, approved.bot_id, 'generation-1', True),
            ):
                a = approved.model_copy(update={'organization_id': org, 'bot_id': bot})
                repo = CanaryRepository(conn, a)
                batch = build_namespaced(foreign, org, bot, 91 + len(outcomes))
                pin = repo.register_fixture_source(batch, source_id=91 + len(outcomes))
                manifest = make_manifest((pin,), run='scope-' + label.replace('_', '-'), generation=gen, approved=a)
                repo.create(manifest, now=int(time()))
                repo.stage(manifest, batch, now=int(time()))
                repo.transition(manifest, State.INDEX_READY, now=int(time()))
                repo.transition(manifest, State.CANARY_READ, now=int(time()))
                raw = repo.dense(manifest, hard_scope(manifest), vector, now=int(time()))
                require(raw and raw[0].score < 0.000001, 'FOREIGN_DENSE_FIXTURE_NOT_STRONG')
                lexical = repo.fts(manifest, hard_scope(manifest), 'console', now=int(time())).hits
                require(lexical, 'FOREIGN_FTS_FIXTURE_EMPTY')
                if stale:
                    conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 91 + len(outcomes),
                        s.lifecycle.c.organization_id == org, s.lifecycle.c.bot_id == bot).values(status='deleted', epoch=s.lifecycle.c.epoch + 1))
                authorized = acceptance.repo(conn)
                dense = authorized.dense(acceptance.manifest, hard_scope(acceptance.manifest), vector, now=int(time()))
                fts = authorized.fts(acceptance.manifest, hard_scope(acceptance.manifest), 'console', now=int(time())).hits
                require(dense and raw[0].score < dense[0].score, 'AUTHORIZED_DENSE_FIXTURE_NOT_WEAKER')
                require(fts and lexical[0].score > fts[0].score, 'AUTHORIZED_FTS_FIXTURE_NOT_WEAKER')
                require(all(h.route.manifest == acceptance.manifest.canonical_hash() for h in (*dense, *fts)), 'CROSS_SCOPE_CANDIDATE')
                outcomes[label] = {'foreign_stronger': True, 'leaks': 0}
        finally:
            savepoint.rollback()
    return outcomes


def rich_materialization(acceptance):
    checks = []
    with acceptance.db.transaction() as conn:
        savepoint = conn.begin_nested()
        try:
            for i, spec in enumerate(({'synthetic': 'review'}, {'synthetic': 'timeline'},
                    {'fixture': 'long_stage'}, {'fixture': 'huge_list'}, {'synthetic': 'price'},
                    {'synthetic': 'directions'}, {'text': '# Café\n\nRésumé naïve: €42; 2 mL daily.'}), 200):
                data = namespace_evidence(evidence(spec), organization_id=acceptance.approval.organization_id,
                    bot_id=acceptance.approval.bot_id, document_id=i)
                batch = m.build_retrieval_entries(data, scope=RetrievalEntryScope(revision=data.source_graph.revision.identity))
                repo = acceptance.repo(conn)
                pin = repo.register_fixture_source(batch, source_id=i)
                manifest = make_manifest((pin,), run='materialization-' + str(i), approved=acceptance.approval)
                repo.create(manifest, now=int(time()))
                repo.stage(manifest, batch, now=int(time()))
                repo.transition(manifest, State.INDEX_READY, now=int(time()))
                repo.transition(manifest, State.CANARY_READ, now=int(time()))
                result = run_query(repo, manifest, hard_scope(manifest), query='guide OR days OR daily OR credits OR Café',
                    query_vector=synthetic_vector(batch.entries[0].text), now=int(time()))
                expected = {a.atom_key: evidence_view(atomic_projection(batch, a)) for a in batch.atoms}
                for unit in result['materialized']['units']:
                    require(unit['payload'] == expected[unit['key']], 'RICH_SOURCE_PAYLOAD_LOSS')
                for entry in batch.entries:
                    require(len(entry.mappings) <= 256 and entry.logical_child_count <= 32, 'RICH_MAPPING_BOUND')
                    for span in entry.mappings:
                        node = next(n for n in data.source_graph.nodes if n.identity.node_key == span.node.node_key)
                        require(node.text.encode()[span.node_slice.start:span.node_slice.end] ==
                            entry.text.encode()[span.entry_slice.start:span.entry_slice.end], 'UTF8_SPAN_LOSS')
                checks.append({'fixture': spec, 'units': len(result['materialized']['units']),
                    'status': result['final_status'], 'bytes': result['materialized']['bytes'],
                    'roles': sorted({n.semantic_role.value for n in data.source_graph.nodes}),
                    'continuations': sum(p.part_count > 1 for p in data.chunks)})
            # Existing frozen M lexical-only fixture, under its own disposable scope.
            from scripts.structural_retrieval_heading_gold import cases, evidence as heading_evidence
            from services import structural_retrieval_entries as v1
            spec = next(c for c in cases() if c['name'] == 'lexical_descendant')
            data = namespace_evidence(heading_evidence(spec), document_id=299)
            old = v1.build_retrieval_entries(data, scope=RetrievalEntryScope(revision=data.source_graph.revision.identity))
            entries = tuple(e.model_copy(update={'ordinal': i}) for i, e in enumerate(e for e in old.entries if e.kind == 'heading'))
            entries = tuple(e.model_copy(update={'entry_key': v1._entry_key(e.model_dump(mode='json'))}) for e in entries)
            old = old.model_copy(update={'entries': entries, 'coverage': v1._coverage(old.evidence, old.atoms, entries),
                'batch_key': digest({'scope': old.scope.model_dump(), 'input': old.input_hash,
                    'recipe': old.recipe_hash, 'entries': [e.entry_key for e in entries]})}).verify(scope=old.scope)
            batch = m.revise_heading_allocation(old, scope=old.scope)
            pin = repo.register_fixture_source(batch, source_id=299)
            manifest = make_manifest((pin,), run='atomic-only-route', approved=acceptance.approval)
            repo.create(manifest, now=int(time()))
            repo.stage(manifest, batch, now=int(time()))
            repo.transition(manifest, State.INDEX_READY, now=int(time()))
            repo.transition(manifest, State.CANARY_READ, now=int(time()))
            result = run_query(repo, manifest, hard_scope(manifest), query='plain passage',
                query_vector=synthetic_vector('query'), now=int(time()))
            atomic = [h for h in result['rrf'] if h['route']['kind'] == 'ATOM_ONLY']
            require(atomic and all(h['dense_contribution'] == 0 for h in atomic), 'ATOM_ONLY_RRF_FAILED')
            require(result['lexical_ledger'] and all(h['disposition'] == 'KEPT' for h in result['lexical_ledger']), 'ATOM_ONLY_WITNESS_LOST')
            checks.append({'fixture': 'frozen-M-lexical-descendant', 'atomic_only_routes': len(atomic), 'raw_witnesses_kept': True})
        finally:
            savepoint.rollback()
    return {'fixtures': checks, 'exact_source_payloads': True}


def concurrent_sessions(acceptance):
    """Independent real sessions; cancellation committed before blocked seal resumes."""
    outcomes = {}
    batch = fixture_batch('# Race\n\nOne exact statement.', document_id=401)
    with acceptance.db.transaction() as conn:
        repo = acceptance.repo(conn)
        pin = repo.register_fixture_source(batch, source_id=401)
        target = make_manifest((pin,), run='race-work', approved=acceptance.approval)
        repo.create(target, now=int(time()))

    def attempt(call, entered=None):
        try:
            with acceptance.db.transaction() as conn:
                pid = conn.execute(text('SELECT pg_backend_pid()')).scalar_one()
                if entered:
                    entered.set()
                call(acceptance.repo(conn))
            return {'result': 'committed', 'pid': pid}
        except (CanaryError, DBAPIError) as exc:
            from scripts.canary_postgres_validation import safe_failure
            return {'result': 'refused', 'failure': safe_failure(exc)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, lambda r: r.stage(target, batch, now=int(time()))) for _ in range(2)]
        work = [f.result(timeout=45) for f in futures]
        require(sum(r['result'] == 'committed' for r in work) == 1, 'DUPLICATE_WORK_OWNER')
        outcomes['two_workers'] = work
        with acceptance.db.transaction() as conn:
            repo = acceptance.repo(conn)
            counts = repo.counts(target)
            require(counts[s.vectors.name] == len(batch.entries), 'DUPLICATE_VECTOR')
            repo.transition(target, State.CANCELLED, now=int(time()))
            entered = Event()
            seal = pool.submit(attempt, lambda r: r.transition(target, State.INDEX_READY, now=int(time())), entered)
            require(entered.wait(10), 'RACE_SESSION_START_TIMEOUT')
        outcome = seal.result(timeout=30)
        require(outcome['result'] == 'refused', 'CANCEL_DID_NOT_WIN')
        outcomes['cancel_vs_seal'] = outcome
        late = pool.submit(attempt, lambda r: r.stage(target, batch, now=int(time()))).result(timeout=30)
        require(late['result'] == 'refused', 'LATE_WORK_AFTER_CANCEL')
        outcomes['late_commit_after_cancel'] = late
    with acceptance.db.transaction() as conn:
        repo = acceptance.repo(conn)
        repo.delete_run(target)

    duplicate = make_manifest((pin,), run='race-manifest', approved=acceptance.approval)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, lambda r: r.create(duplicate, now=int(time()))) for _ in range(2)]
        results = [f.result(timeout=45) for f in futures]
        require(sum(r['result'] == 'committed' for r in results) == 1, 'DUPLICATE_MANIFEST_COMMITTED')
        outcomes['duplicate_manifest_generation'] = results
    with acceptance.db.transaction() as conn:
        repo = acceptance.repo(conn)
        require(repo.counts(duplicate)[s.manifests.name] == 1, 'DUPLICATE_MANIFEST_ROWS')
        repo.transition(duplicate, State.CANCELLED, now=int(time()))
        repo.delete_run(duplicate)

    # A read lease acquired in one session must fail after a second commits a change.
    for label in ('source_epoch', 'off', 'cleanup'):
        with acceptance.db.transaction() as writer:
            repo = acceptance.repo(writer)
            target = make_manifest((pin,), run='race-' + label.replace('_', '-'), approved=acceptance.approval)
            repo.create(target, now=int(time()))
            repo.stage(target, batch, now=int(time()))
            repo.transition(target, State.INDEX_READY, now=int(time()))
            repo.transition(target, State.CANARY_READ, now=int(time()))
        with acceptance.db.transaction() as reader:
            read_repo = acceptance.repo(reader)
            lease = read_repo.read_gate(target, hard_scope(target), now=int(time()))
            reader_pid = reader.execute(text('SELECT pg_backend_pid()')).scalar_one()
            with acceptance.db.transaction() as writer:
                require(writer.execute(text('SELECT pg_backend_pid()')).scalar_one() != reader_pid, 'RACE_NOT_INDEPENDENT')
                repo = acceptance.repo(writer)
                if label == 'source_epoch':
                    writer.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 401).values(epoch=s.lifecycle.c.epoch + 1))
                else:
                    repo.transition(target, State.OFF, now=int(time()))
                    if label == 'cleanup':
                        repo.delete_run(target)
            try:
                read_repo.read_gate(target, hard_scope(target), now=int(time()), expected_epoch=lease)
            except CanaryError as exc:
                outcomes[label + '_during_read'] = str(exc)
            else:
                raise CanaryError('STALE_RESULT_RELEASED')
        if label != 'cleanup':
            with acceptance.db.transaction() as writer:
                repo = acceptance.repo(writer)
                if label == 'source_epoch':
                    repo.transition(target, State.OFF, now=int(time()))
                repo.delete_run(target)
    return outcomes
