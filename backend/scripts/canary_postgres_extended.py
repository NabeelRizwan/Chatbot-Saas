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
                    repo.seal_generation(attempted, expected_build_identity=repo.build_identity(target),
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
    # The identical frozen obligations run against real relational state, not a
    # Python-only oracle. Every mutation (including successful controls) rolls back.
    from scripts.canary_seal_gold import cases, exercise, GOLD_SHA
    with acceptance.db.transaction() as conn:
        outer = conn.begin_nested()
        try:
            repo = acceptance.repo(conn)
            batch = fixture_batch('# Synthetic guide\n\nA source-backed statement.', document_id=601)
            pin = repo.register_fixture_source(batch, source_id=601)
            conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 601).values(epoch=10))
            base = make_manifest((pin,), run='seal-gold', approved=acceptance.approval)
            repo.create(base, now=int(time()))
            repo.stage(base, batch, now=int(time()))
            gold_results = {}
            for name, expected in cases():
                point = conn.begin_nested()
                try:
                    gold_results[name] = exercise(repo, base, batch, name, expected, int(time()))
                    acceptance.metrics['seal_negatives']['frozen_gold'] = gold_results
                finally:
                    point.rollback()
            for name, call in (
                ('epoch_reset', lambda: conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 601).values(epoch=9))),
                ('snapshot_mutation', lambda: conn.execute(update(s.manifests).where(s.manifests.c.run_id == base.run_id).values(build_snapshot=[]))),
            ):
                try:
                    with conn.begin_nested():
                        call()
                except DBAPIError as exc:
                    require(getattr(exc.orig, 'pgcode', '') == 'P0001', 'WRONG_IMMUTABLE_GUARD')
                    observations[name] = 'REFUSED'
                else:
                    raise CanaryError('IMMUTABLE_BUILD_OR_EPOCH_MUTATED')
            observations['frozen_gold_sha256'] = GOLD_SHA
            observations['frozen_gold'] = gold_results
        finally:
            outer.rollback()
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
                manifest = make_manifest((pin,), run=acceptance.manifest.run_id if label == 'stale_generation' else
                    'scope-' + label.replace('_', '-'), generation=gen, approved=a)
                repo.create(manifest, now=int(time()))
                repo.stage(manifest, batch, now=int(time()))
                repo.seal_generation(manifest, expected_build_identity=repo.build_identity(manifest), now=int(time()))
                if label != 'stale_generation':
                    repo.transition(manifest, State.CANARY_READ, now=int(time()))
                # Direct fixture-strength characterization is not a read lease:
                # the alternate generation must not acquire a mixed lease.
                raw = conn.execute(repo.dense_statement(manifest, hard_scope(manifest)),
                    {'query_vector': '[' + ','.join(map(str, vector)) + ']'}).mappings().all()
                require(raw and raw[0]['distance'] < 0.000001, 'FOREIGN_DENSE_FIXTURE_NOT_STRONG')
                lexical = conn.execute(repo.fts_statement(manifest, hard_scope(manifest)), {'query_text': 'console'}).mappings().all()
                require(lexical and lexical[0]['score'] is not None, 'FOREIGN_FTS_FIXTURE_EMPTY')
                if stale:
                    conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 91 + len(outcomes),
                        s.lifecycle.c.organization_id == org, s.lifecycle.c.bot_id == bot).values(status='deleted', epoch=s.lifecycle.c.epoch + 1))
                    require(not conn.execute(repo.dense_statement(manifest, hard_scope(manifest)),
                        {'query_vector': '[' + ','.join(map(str, vector)) + ']'}).all(), 'STALE_DENSE_SCOPE_LEAK')
                    stale_fts = conn.execute(repo.fts_statement(manifest, hard_scope(manifest)), {'query_text': 'console'}).mappings().all()
                    require(all(r['document_id'] is None for r in stale_fts), 'STALE_FTS_SCOPE_LEAK')
                authorized = acceptance.repo(conn)
                dense = authorized.dense(acceptance.manifest, hard_scope(acceptance.manifest), vector, now=int(time()))
                fts = authorized.fts(acceptance.manifest, hard_scope(acceptance.manifest), 'console', now=int(time())).hits
                require(dense and raw[0]['distance'] < dense[0].score, 'AUTHORIZED_DENSE_FIXTURE_NOT_WEAKER')
                require(fts and lexical[0]['score'] > fts[0].score, 'AUTHORIZED_FTS_FIXTURE_NOT_WEAKER')
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
                    {'synthetic': 'directions'}, {'text': '# Café\n\nRésumé naïve: €42; 2 mL daily.'},
                    {'synthetic': 'faq'}, {'synthetic': 'warning'}), 200):
                data = namespace_evidence(evidence(spec), organization_id=acceptance.approval.organization_id,
                    bot_id=acceptance.approval.bot_id, document_id=i)
                batch = m.build_retrieval_entries(data, scope=RetrievalEntryScope(revision=data.source_graph.revision.identity))
                repo = acceptance.repo(conn)
                pin = repo.register_fixture_source(batch, source_id=i)
                manifest = make_manifest((pin,), run='materialization-' + str(i), approved=acceptance.approval)
                repo.create(manifest, now=int(time()))
                repo.stage(manifest, batch, now=int(time()))
                repo.seal_generation(manifest, expected_build_identity=repo.build_identity(manifest), now=int(time()))
                repo.transition(manifest, State.CANARY_READ, now=int(time()))
                result = run_query(repo, manifest, hard_scope(manifest), query='guide OR days OR daily OR credits OR Café',
                    query_vector=synthetic_vector(batch.entries[0].text), now=int(time()))
                expected = {a.atom_key: evidence_view(atomic_projection(batch, a)) for a in batch.atoms}
                require(result['materialized']['units'], 'RICH_FIXTURE_EMPTY')
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
            repo.seal_generation(manifest, expected_build_identity=repo.build_identity(manifest), now=int(time()))
            repo.transition(manifest, State.CANARY_READ, now=int(time()))
            result = run_query(repo, manifest, hard_scope(manifest), query='plain passage',
                query_vector=synthetic_vector('query'), now=int(time()))
            atomic = [h for h in result['rrf'] if h['route']['kind'] == 'ATOM_ONLY']
            require(atomic and all(h['dense_contribution'] == 0 for h in atomic), 'ATOM_ONLY_RRF_FAILED')
            require(result['lexical_ledger'] and all(h['disposition'] == 'KEPT' for h in result['lexical_ledger']), 'ATOM_ONLY_WITNESS_LOST')
            expected = {a.atom_key: evidence_view(atomic_projection(batch, a)) for a in batch.atoms}
            for h in atomic:
                require(h['route']['key'] in expected, 'ATOM_ONLY_FAKE_PARENT')
                units = [u for u in result['materialized']['units'] if u['key'] == h['route']['key']]
                require(units and units[0]['payload'] == expected[h['route']['key']], 'ATOM_ONLY_MATERIALIZATION')
            checks.append({'fixture': 'frozen-M-lexical-descendant', 'atomic_only_routes': len(atomic), 'raw_witnesses_kept': True})
            collapse = fixture_batch('# Console guide\n\nConsole supports reports.\n\nConsole supports exports.\n\nConsole supports reminders.', document_id=298)
            pin = repo.register_fixture_source(collapse, source_id=298)
            manifest = make_manifest((pin,), run='lexical-collapse', approved=acceptance.approval)
            repo.create(manifest, now=int(time()))
            repo.stage(manifest, collapse, now=int(time()))
            repo.seal_generation(manifest, expected_build_identity=repo.build_identity(manifest), now=int(time()))
            repo.transition(manifest, State.CANARY_READ, now=int(time()))
            result = run_query(repo, manifest, hard_scope(manifest), query='console',
                query_vector=synthetic_vector('collapse query'), now=int(time()))
            grouped = {}
            for h in result['raw_fts']:
                grouped.setdefault(json.dumps(h['route'], sort_keys=True), []).append(h)
            many = [(key, hits) for key, hits in grouped.items() if len(hits) > 1]
            require(many, 'NO_REAL_LEXICAL_COLLAPSE_FIXTURE')
            require(len(result['lexical_ledger']) == len(result['raw_fts']), 'COLLAPSE_LOST_WITNESSES')
            for key, hits in many:
                votes = [v for v in result['rrf'] if json.dumps(v['route'], sort_keys=True) == key]
                require(len(votes) == 1 and votes[0]['fts_contribution'] ==
                    manifest.policy.fts_weight / (manifest.policy.rrf_k + votes[0]['fts_rank']), 'LEXICAL_SCORE_MULTIPLIED')
            checks.append({'fixture': 'real-many-atoms-one-entry', 'raw_hits': len(result['raw_fts']),
                'routes': len(result['lexical_routes']), 'collapsed_groups': [len(h) for _, h in many],
                'ledger_intact': True, 'one_vote_per_route': True})
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
            seal = pool.submit(attempt, lambda r: r.seal_generation(target, expected_build_identity=r.build_identity(target), now=int(time())), entered)
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
            repo.seal_generation(target, expected_build_identity=repo.build_identity(target), now=int(time()))
            repo.transition(target, State.CANARY_READ, now=int(time()))
        with acceptance.db.transaction() as reader:
            read_repo = acceptance.repo(reader)
            reader_pid = reader.execute(text('SELECT pg_backend_pid()')).scalar_one()
            original_gate = read_repo.read_gate
            released = []
            def final_gate(*args, **kwargs):
                if kwargs.get('expected_epoch') is not None:
                    # Hook only at actual run_query final release, after real
                    # dense, FTS and materialization completed on the reader.
                    released.append('final_release_attempted')
                    with acceptance.db.transaction() as writer:
                        require(writer.execute(text('SELECT pg_backend_pid()')).scalar_one() != reader_pid, 'RACE_NOT_INDEPENDENT')
                        repo = acceptance.repo(writer)
                        if label == 'source_epoch':
                            writer.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 401).values(status='processing',epoch=s.lifecycle.c.epoch + 1))
                            writer.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 401).values(status='ready',epoch=s.lifecycle.c.epoch + 1))
                        else:
                            repo.transition(target, State.OFF, now=int(time()))
                            if label == 'cleanup':
                                repo.delete_run(target)
                return original_gate(*args, **kwargs)
            read_repo.read_gate = final_gate
            try:
                run_query(read_repo, target, hard_scope(target), query='statement',
                    query_vector=synthetic_vector(batch.entries[0].text), now=int(time()))
            except CanaryError as exc:
                require(released == ['final_release_attempted'], 'READ_RACE_DID_NOT_REACH_RELEASE')
                outcomes[label + '_during_read'] = str(exc)
            else:
                raise CanaryError('STALE_RESULT_RELEASED')
        if label != 'cleanup':
            with acceptance.db.transaction() as writer:
                repo = acceptance.repo(writer)
                if label == 'source_epoch':
                    repo.transition(target, State.OFF, now=int(time()))
                repo.delete_run(target)
    # Actual independent writer in the gap after final source validation and
    # before publication: the seal's FOR SHARE locks must block its commit.
    with acceptance.db.transaction() as conn:
        repo = acceptance.repo(conn)
        target = make_manifest((pin,), run='race-final-snapshot', approved=acceptance.approval)
        repo.create(target, now=int(time()))
        repo.stage(target, batch, now=int(time()))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with acceptance.db.transaction() as conn:
            repo = acceptance.repo(conn)
            original = repo._publish
            def publication(*args):
                def writer(r):
                    r.conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 401).values(epoch=s.lifecycle.c.epoch + 1))
                result = pool.submit(attempt, writer).result(timeout=30)
                require(result['result'] == 'refused' and result['failure'].get('sqlstate') == '55P03', 'SOURCE_CHANGED_IN_SEAL_GAP')
                outcomes['final_validation_publication_gap'] = result
                return original(*args)
            repo._publish = publication
            repo.seal_generation(target, expected_build_identity=repo.build_identity(target), now=int(time()))
        # Once the seal transaction ends, a new epoch is allowed, but the sealed
        # generation is stale and cannot acquire/read a lease.
        with acceptance.db.transaction() as conn:
            conn.execute(update(s.lifecycle).where(s.lifecycle.c.document_id == 401).values(epoch=s.lifecycle.c.epoch + 1))
        with acceptance.db.transaction() as conn:
            repo = acceptance.repo(conn)
            try:
                repo.transition(target, State.CANARY_READ, now=int(time()))
            except CanaryError as exc:
                require(str(exc) == 'STALE_SOURCE_EPOCH', 'POST_SEAL_EPOCH_NOT_CHECKED')
            else:
                raise CanaryError('POST_SEAL_STALE_READ')
            repo.transition(target, State.OFF, now=int(time()))
            repo.delete_run(target)
    return outcomes
