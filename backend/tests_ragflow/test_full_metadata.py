"""Real metadata/tag call path with an IO-only aggregation double."""
import asyncio
import copy
from collections import Counter
import pytest
from ragflow_derived.advanced import operation_for
from ragflow_derived.contracts import EngineError
from ragflow_derived.full_runtime import full_operation
from .fixtures import engine, scope, MemoryFixtureBackend


@pytest.mark.parametrize('value,expected', [('north', 'manual'), ('south', 'terms'), ('unknown', None)])
def test_manual_metadata_filters_before_retrieval(value, expected):
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Inspection schedules for northern laboratories.', metadata={'region': 'north', 'year': 2026})
    e.ingest(s, 'terms', 'Inspection schedules for southern laboratories.', metadata={'region': 'south', 'year': 2027})
    result = asyncio.run(e.retrieve(s, 'Inspection schedules', metadata_filter={
        'method': 'manual', 'manual': [{'key': 'region', 'op': '=', 'value': value}]}))
    assert {item.source_id for item in result} == ({expected} if expected else set())


def test_metadata_cannot_change_under_same_source_version():
    e, s = engine(), scope()
    e.ingest(s, 'manual', 'Inspection schedules.', metadata={'region': 'north'})
    with pytest.raises(EngineError, match='INGESTION_FAILED'):
        e.ingest(s, 'manual', 'Inspection schedules.', metadata={'region': 'south'})


def test_metadata_uses_authorized_ready_sources_only():
    backend = MemoryFixtureBackend()
    e, s = engine(backend), scope()
    e.ingest(s, 'manual', 'Inspection schedules.', metadata={'region': 'north'})
    e.ingest(scope(org='foreign'), 'manual', 'Inspection schedules.', metadata={'region': 'secret'})
    op = operation_for(e, s)
    with full_operation(op):
        assert op.catalog.flattened_metadata() == {'region': {'north': ['doc-a']}}
    backend.delete(s, s.sources[0])
    with full_operation(operation_for(e, s)) as fresh:
        assert fresh.catalog.flattened_metadata() == {}


class AggregationBackend(MemoryFixtureBackend):
    def search(self, fields, highlights, condition, expressions, order, offset, limit, indexes, kb_ids, **kwargs):
        result = super().search(fields, highlights, condition, expressions, order, 0, 10000, indexes, kb_ids)
        if kwargs.get('agg_fields'):
            result['aggregations'] = {}
            for field in kwargs['agg_fields']:
                counts = Counter(tag for hit in result['hits']['hits'] for tag in hit['_source'].get(field, []))
                result['aggregations']['aggs_' + field] = {'buckets': [
                    {'key': key, 'doc_count': count} for key, count in counts.items()]}
        result['hits']['hits'] = result['hits']['hits'][offset:offset + limit]
        return result


def test_actual_tag_aggregation_and_query_features_are_scope_restricted():
    e, s = engine(AggregationBackend()), scope()
    e.ingest(s, 'manual', 'Laboratory calibration weekly.', tags=['laboratory'])
    e.ingest(scope(org='foreign'), 'manual', 'Laboratory calibration weekly.', tags=['private'])
    op = operation_for(e, s)
    with full_operation(op):
        tags = op.retriever.all_tags_in_portion(s.key, [s.bot_id])
        assert set(tags) == {'laboratory'}
        assert op.retriever.tag_query('laboratory', [s.key], [s.bot_id], tags) == {'laboratory': 1}
    result = asyncio.run(e.retrieve(s, 'laboratory', use_tags=True))
    assert result and all(x.scope_key == s.key for x in result)
