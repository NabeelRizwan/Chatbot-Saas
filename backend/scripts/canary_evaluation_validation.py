"""Bounded retained validation transport. No serving SQL or representation changes.

Document checks mirror CanaryRepository/RealCanaryRepository's exact generation
checks; the offline equivalence suite exercises both implementations. Rows are
never sampled. A fresh transaction owns each document's complete validation.
"""
from collections import defaultdict
import json

from sqlalchemy import select, func
from database import canary_schema as s
from services.canary_contracts import CanaryError, Lane, canonicalize_vector_f32
from services.canary_repository import document_values, source_values, where
from services.canary_representation import prepare_batch, source_pin, exact_input_hash
from services.structural_chunking import digest
from services import structural_retrieval_entries_v2 as m

PAGE_SIZE = 100
PAGE_BYTES = 16 * 1024 * 1024


def require(ok, guard):
    if not ok:
        raise CanaryError(guard)


def tables_for(manifest):
    return ((s.legacy, s.legacy_work) if manifest.lane == Lane.LEGACY_CONTROL else
            (s.sources, s.entries, s.vectors, s.atoms, s.work, s.memberships, s.spans))


def fetch_document(conn, manifest, pin, *, page_size=PAGE_SIZE):
    """One source row separately; at most six bounded table sets per round trip.

    Exact scope predicates are unchanged. PK ordering and a final short page
    prove exhaustion, including unexpected extra rows. SQLite is an offline
    transport double, not a claim about PostgreSQL JSON/pgvector semantics.
    """
    require(1 <= page_size <= PAGE_SIZE, 'VALIDATION_PAGE_BOUND')
    tables = tables_for(manifest)
    output = {t.name: [] for t in tables}
    pending, offset = list(tables), 0
    if conn.dialect.name == 'postgresql' and s.sources in pending:
        # Source DTOs can be several MiB on their own. Do not combine this one
        # immutable row with another page's payloads in the same transfer.
        rows = [dict(r) for r in conn.execute(select(s.sources).where(where(s.sources, source_values(pin))).limit(2)).mappings()]
        require(len(rows) == 1, 'INCOMPLETE_SOURCE')
        require(len(json.dumps(rows, ensure_ascii=True).encode()) <= PAGE_BYTES, 'VALIDATION_RESPONSE_BYTE_BOUND')
        output[s.sources.name] = rows
        pending.remove(s.sources)
    # Existing DTO limits bound total mappings too; refuse before accumulating
    # more than the maximum possible declared span inventory plus one page.
    row_limit = max(len(pin.atoms), len(pin.legacy_members), len(pin.entries)*256, 1) + PAGE_SIZE
    while pending:
        statements = []
        for table in pending:
            scope = source_values(pin) if table is s.sources else document_values(manifest, pin)
            statements.append(select(table).where(where(table, scope))
                .order_by(*table.primary_key.columns).offset(offset).limit(page_size))
        if conn.dialect.name == 'postgresql':
            columns = []
            for table, statement in zip(pending, statements):
                page = statement.subquery()
                columns.append(select(func.json_agg(func.row_to_json(page.table_valued())))
                               .scalar_subquery().label(table.name))
            groups = dict(conn.execute(select(*columns)).mappings().one())
            require(len(json.dumps(groups, ensure_ascii=True).encode()) <= PAGE_BYTES,
                    'VALIDATION_RESPONSE_BYTE_BOUND')
        else:
            groups = {table.name: [dict(r) for r in conn.execute(statement).mappings()]
                      for table, statement in zip(pending, statements)}
        following = []
        for table in pending:
            rows = groups[table.name] or []
            require(len(rows) <= page_size, 'VALIDATION_PAGE_BOUND')
            for row in rows:
                if 'embedding' in row:
                    raw = row['embedding']
                    row['embedding'] = canonicalize_vector_f32(json.loads(raw) if isinstance(raw, str) else raw)
            output[table.name].extend(rows)
            require(len(output[table.name]) <= row_limit, 'VALIDATION_INVENTORY_BOUND')
            if len(rows) == page_size:
                following.append(table)
        pending, offset = following, offset + page_size
    return output


def validate_document(repo, manifest, pin, data):
    """Same exact checks as the old logical validator, plus explicit PK/scope checks."""
    repo._require_profile(manifest)
    for table in tables_for(manifest):
        scope = source_values(pin) if table is s.sources else document_values(manifest, pin)
        rows = data[table.name]
        keys = [tuple(r[k.name] for k in table.primary_key.columns) for r in rows]
        require(len(keys) == len(set(keys)), 'DUPLICATE_VALIDATION_ROW')
        require(all(all(r[k] == v for k, v in scope.items()) for r in rows), 'VALIDATION_SCOPE_MISMATCH')
    if manifest.lane == Lane.LEGACY_CONTROL:
        rows = sorted(data[s.legacy.name], key=lambda r:r['chunk_id'])
        require(tuple(r['chunk_id'] for r in rows) == pin.legacy_members
                and digest([r['payload'] for r in rows]) == pin.batch_hash, 'INCOMPLETE_LEGACY_BUILD')
        require(all(repo._validate_stored_vector(manifest, r, r['text']) for r in rows), 'INVALID_LEGACY_VECTOR')
        work = data[s.legacy_work.name]
        by_key = {r['chunk_id']: r for r in rows}
        require({r['chunk_id'] for r in work} == set(pin.legacy_members)
                and all(r['state'] == 'succeeded' and r['input_hash'] == by_key[r['chunk_id']]['input_hash']
                        for r in work), 'INCOMPLETE_LEGACY_WORK')
    else:
        require(len(data[s.sources.name]) == 1, 'INCOMPLETE_SOURCE')
        raw = data[s.sources.name][0]
        require(raw['payload_hash'] == digest(raw['payload']), 'SOURCE_PAYLOAD_CORRUPTION')
        batch = m.RetrievalEntryBatch.model_validate(raw['payload'])
        batch, projections, routes, _ = prepare_batch(batch)
        require(source_pin(batch, source_id=pin.source_id, website_id=pin.website_id) == pin, 'PIN_INTEGRITY_FAILURE')
        es = {r['entry_id']:r for r in data[s.entries.name]}
        vs = {r['entry_id']:r for r in data[s.vectors.name]}
        ats = {r['atom_id']:r for r in data[s.atoms.name]}
        ws = {r['entry_id']:r for r in data[s.work.name]}
        vector_keys = set(manifest.vector_entries(pin))
        require(set(es) == set(pin.entries) and set(vs) == vector_keys and set(ats) == set(pin.atoms)
                and set(ws) == vector_keys, 'INCOMPLETE_BUILD')
        for e in batch.entries:
            r = es[e.entry_key]
            require(r['payload'] == e.model_dump(mode='json') and r['text'] == e.text
                    and r['input_hash'] == exact_input_hash(e.text)
                    and (e.entry_key not in vector_keys or (repo._validate_stored_vector(manifest, vs[e.entry_key], e.text)
                        and ws[e.entry_key]['state'] == 'succeeded'
                        and ws[e.entry_key]['input_hash'] == exact_input_hash(e.text))), 'ENTRY_VECTOR_CORRUPTION')
        for payload in projections:
            key = payload['atom']['atom_key']; r = ats[key]; kind, target = routes[key]
            require(r['payload'] == payload and r['payload_hash'] == digest(payload)
                    and r['canonical_text'] == payload['canonical_text'] and r['route_kind'] == kind
                    and r['route_entry'] == (target if kind == 'ENTRY' else None), 'ATOM_PROJECTION_CORRUPTION')
        expected_members = defaultdict(list)
        for e in batch.entries:
            for member in e.memberships:
                expected_members[(e.entry_key, member.atom_key)].append(member.model_dump(mode='json'))
        require({(r['entry_id'], r['atom_id']):r['payload'] for r in data[s.memberships.name]} == dict(expected_members),
                'MEMBERSHIP_CORRUPTION')
        expected_spans = []
        for e in batch.entries:
            for i, v in enumerate(e.mappings):
                expected_spans.append((e.entry_key, v.atom_key, i, v.node.node_key, v.node_slice.start, v.node_slice.end,
                                      v.entry_slice.start, v.entry_slice.end, v.usage, v.origin_usage))
        columns = ('entry_id','atom_id','ordinal','node_key','node_start','node_end','entry_start','entry_end','usage','origin')
        require(sorted(tuple(r[k] for k in columns) for r in data[s.spans.name]) == sorted(expected_spans), 'SPAN_CORRUPTION')
    return validation_digest(manifest, pin, data)


def validation_digest(manifest, pin, data):
    # Full rows, including exact f32 coordinates, are hashed in memory only.
    canonical = {}
    for table in tables_for(manifest):
        rows = []
        for original in data[table.name]:
            row = dict(original)
            if 'embedding' in row:
                row['embedding'] = list(canonicalize_vector_f32(row['embedding']))
            rows.append(row)
        canonical[table.name] = sorted(rows, key=lambda r:tuple(r[k.name] for k in table.primary_key.columns))
    return digest(dict(manifest=manifest.canonical_hash(), source=source_values(pin), rows=canonical))
