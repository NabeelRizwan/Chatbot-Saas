"""Model lifetime, tenant cache isolation and bounded inference admission."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import service
from retrieval_engine.config import RetrievalConfig
from retrieval_engine.model_runtime import ModelRuntime
from retrieval_engine.retrieval import LocalRetrievalEngine


class CorpusEngine:
    creations = 0

    def __init__(self, config):
        type(self).creations += 1
        self.config = config
        self.documents = []

    def build_or_load(self):
        self.documents = [json.loads(line) for line in self.config.corpus_path.read_text().splitlines()]

    def status(self):
        return {'ready': True}


def corpus(bot, org=1, text=None):
    rows = [dict(id='1', source_id='1', title='Instructions', url='https://example.test/item',
                 text=text or f'Private instructions for organization {org}, bot {bot}.', version=1, crawl_id=None)]
    return service.Scope(organization_id=org, bot_id=bot, fingerprint=service.fingerprint(rows)), rows


def make_store(tmp_path):
    CorpusEngine.creations = 0
    return service.IndexStore(tmp_path / 'cache', tmp_path / 'models', CorpusEngine)


def test_switching_bots_reuses_only_their_own_cached_index(tmp_path):
    store = make_store(tmp_path)
    a, rows_a = corpus(1)
    b, rows_b = corpus(2)
    c, rows_c = corpus(1, org=2)
    with store.admitted():
        first = store.load(a, rows_a)
        second = store.load(b, rows_b)
        third = store.load(c, rows_c)
        assert store.load(a) is first
        assert store.load(b) is second
        assert store.load(c) is third
    assert CorpusEngine.creations == 3
    assert first.documents == rows_a and second.documents == rows_b and third.documents == rows_c


def test_snapshot_version_is_part_of_memory_cache_identity(tmp_path):
    store = make_store(tmp_path)
    old, old_rows = corpus(1, text='Old instructions.')
    new, new_rows = corpus(1, text='New instructions.')
    with store.admitted():
        first = store.load(old, old_rows)
        second = store.load(new, new_rows)
        assert first is not second
        assert store.load(new).documents == new_rows
        assert store.load(old).documents == old_rows


def test_lru_evicts_cold_indexes_and_keeps_disk_snapshot(tmp_path):
    store = make_store(tmp_path)
    store.memory_max_entries = 2
    a, ar = corpus(1)
    b, br = corpus(2)
    c, cr = corpus(3)
    with store.admitted():
        first = store.load(a, ar)
        store.load(b, br)
        assert store.load(a) is first
        store.load(c, cr)
        assert store.path(a) in store.entries and store.path(b) not in store.entries
        assert (store.path(b) / 'corpus.jsonl').is_file()
        assert store.load(b).documents == br
    assert len(store.entries) == 2
    assert CorpusEngine.creations == 4


def test_single_index_exceeding_memory_budget_fails_closed(tmp_path):
    store = make_store(tmp_path)
    store.memory_max_bytes = 1
    scope, rows = corpus(1)
    with store.admitted(), pytest.raises(HTTPException) as error:
        store.load(scope, rows)
    assert error.value.detail == 'retrieval_memory_capacity_exceeded'
    assert not store.entries


def test_retained_index_bytes_are_bounded(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.memory_max_bytes = 150
    monkeypatch.setattr(store, '_resident_bytes', lambda engine: 100)
    first, first_rows = corpus(1)
    second, second_rows = corpus(2)
    with store.admitted():
        store.load(first, first_rows)
        store.load(second, second_rows)
    assert list(store.entries) == [store.path(second)]
    assert sum(size for _, size in store.entries.values()) <= store.memory_max_bytes


def test_expiry_releases_corpus_but_keeps_warm_models(tmp_path):
    store = make_store(tmp_path)
    class Runtime:
        ready = True
        def shared_object_ids(self):
            return {id(self)}
    runtime = Runtime()
    # Install after fake-engine construction; no inference is needed in this test.
    scope, rows = corpus(1)
    with store.admitted():
        store.load(scope, rows)
    store.runtime = runtime
    old = time.time() - store.ttl - 1
    os.utime(store.path(scope), (old, old))
    store.sweep()
    assert not store.entries
    assert store.runtime is runtime and runtime.ready


def test_ten_admitted_jobs_complete_without_parallel_mutable_inference(tmp_path):
    store = make_store(tmp_path)
    gate = threading.Barrier(10)
    counts = {'active': 0, 'peak': 0}
    def search(bot):
        scope, rows = corpus(bot)
        gate.wait(timeout=5)
        with store.admitted():
            counts['active'] += 1
            counts['peak'] = max(counts['active'], counts['peak'])
            engine = store.load(scope, rows)
            time.sleep(.005)
            result = engine.documents[0]['text']
            counts['active'] -= 1
            return result
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(search, range(1, 11)))
    assert counts['peak'] == 1
    assert results == [corpus(bot)[1][0]['text'] for bot in range(1, 11)]


def test_full_queue_rejects_and_timeout_releases_admission(tmp_path, monkeypatch):
    monkeypatch.setenv('LLAMA_MAX_PENDING_REQUESTS', '0')
    store = make_store(tmp_path)
    with store.admitted():
        with pytest.raises(HTTPException) as error:
            with store.admitted():
                pass
        assert error.value.detail == 'retrieval_queue_full'
    store.wait_seconds = .01
    store.lock.acquire()
    try:
        with pytest.raises(HTTPException) as error:
            with store.admitted():
                pass
        assert error.value.detail == 'retrieval_busy'
    finally:
        store.lock.release()
    with store.admitted():
        pass


def test_sweep_cannot_evict_an_inflight_index(tmp_path):
    store = make_store(tmp_path)
    scope, rows = corpus(1)
    with store.admitted():
        engine = store.load(scope, rows)
        old = time.time() - store.ttl - 1
        os.utime(store.path(scope), (old, old))
        store.sweep()
        assert store.engine is engine
    store.sweep()
    assert not store.entries


def test_shared_model_configuration_is_checked_without_loading(tmp_path):
    config = RetrievalConfig(root=tmp_path)
    runtime = ModelRuntime(config)
    a = LocalRetrievalEngine(config, runtime=runtime)
    b = LocalRetrievalEngine(replace(config, corpus_file=tmp_path / 'other.jsonl'), runtime=runtime)
    assert a.runtime is b.runtime
    assert not runtime.ready
    with pytest.raises(ValueError, match='configuration'):
        LocalRetrievalEngine(replace(config, reranker_batch_size=8), runtime=runtime)


def test_ready_requires_successful_runtime_warmup(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    class Runtime:
        ready = False
        loads = 0
        def load(self):
            self.loads += 1
            self.ready = True
    store.runtime = Runtime()
    monkeypatch.setattr(service, 'store', store)
    monkeypatch.setenv('LLAMA_RETRIEVAL_TOKEN', 'test-token-long-enough-for-authorization')
    with pytest.raises(HTTPException):
        service.ready()
    with TestClient(service.app):
        assert service.ready()['status'] == 'ready'
        assert store.runtime.loads == 1


def test_failed_warmup_prevents_service_startup(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    class Runtime:
        ready = False
        def load(self):
            raise RuntimeError('Failed offline inference')
    store.runtime = Runtime()
    monkeypatch.setattr(service, 'store', store)
    with pytest.raises(RuntimeError, match='Failed offline inference'):
        with TestClient(service.app):
            pass


def save_snapshot(store, scope, rows, age=0):
    with store.admitted():
        store.load(scope, rows)
    modified = time.time() - age
    os.utime(store.path(scope), (modified, modified))


def test_restart_preloads_newest_distinct_bot_snapshots(tmp_path):
    previous = make_store(tmp_path)
    old, old_rows = corpus(1, text='Older snapshot')
    new, new_rows = corpus(1, text='Current snapshot')
    second, second_rows = corpus(2)
    cold, cold_rows = corpus(3)
    for scope, rows, age in [(cold, cold_rows, 40), (old, old_rows, 30),
                             (second, second_rows, 20), (new, new_rows, 10)]:
        save_snapshot(previous, scope, rows, age)
    restarted = make_store(tmp_path)
    restarted.memory_max_entries = 2
    restarted.warm()
    assert restarted.startup_ready
    assert set(restarted.entries) == {restarted.path(new), restarted.path(second)}
    assert CorpusEngine.creations == 2
    with restarted.admitted():
        assert restarted.load(new).documents == new_rows
        assert restarted.load(second).documents == second_rows
    assert CorpusEngine.creations == 2


def test_startup_warm_respects_resident_bytes_and_favours_newest(tmp_path, monkeypatch):
    previous = make_store(tmp_path)
    a, ar = corpus(1)
    b, br = corpus(2)
    save_snapshot(previous, a, ar, 20)
    save_snapshot(previous, b, br, 10)
    restarted = make_store(tmp_path)
    restarted.memory_max_bytes = 150
    monkeypatch.setattr(restarted, '_resident_bytes', lambda engine: 100)
    restarted.warm()
    assert list(restarted.entries) == [restarted.path(b)]
    assert restarted.startup_ready


def test_startup_warm_does_not_reload_expired_snapshots(tmp_path):
    previous = make_store(tmp_path)
    scope, rows = corpus(1)
    save_snapshot(previous, scope, rows, previous.ttl + 10)
    restarted = make_store(tmp_path)
    restarted.warm()
    assert restarted.startup_ready and not restarted.entries
    assert CorpusEngine.creations == 0


def test_startup_warm_can_be_disabled_without_changing_lazy_load(tmp_path, monkeypatch):
    previous = make_store(tmp_path)
    scope, rows = corpus(1)
    save_snapshot(previous, scope, rows)
    monkeypatch.setenv('LLAMA_STARTUP_WARM_MAX_ENTRIES', '0')
    restarted = make_store(tmp_path)
    restarted.warm()
    assert restarted.startup_ready and not restarted.entries
    with restarted.admitted():
        assert restarted.load(scope).documents == rows


def test_corrupt_selected_snapshot_does_not_report_startup_ready(tmp_path):
    previous = make_store(tmp_path)
    scope, rows = corpus(1)
    save_snapshot(previous, scope, rows)
    altered = [dict(rows[0], text='Altered persisted content')]
    (previous.path(scope) / 'corpus.jsonl').write_text(json.dumps(altered[0]) + '\n')
    restarted = make_store(tmp_path)
    with pytest.raises(HTTPException) as error:
        restarted.warm()
    assert error.value.detail == 'snapshot_integrity_failed'
    assert not restarted.startup_ready


def test_startup_ignores_noncanonical_snapshot_paths(tmp_path):
    store = make_store(tmp_path)
    _, rows = corpus(1)
    directory = store.root / 'unscoped' / service.fingerprint(rows)
    directory.mkdir(parents=True)
    (directory / 'corpus.jsonl').write_text(json.dumps(rows[0]) + '\n')
    store.warm()
    assert store.startup_ready and not store.entries


def test_model_readiness_alone_does_not_skip_corpus_startup(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.runtime = type('ReadyRuntime', (), {'ready': True})()
    monkeypatch.setattr(service, 'store', store)
    with pytest.raises(HTTPException):
        service.ready()
