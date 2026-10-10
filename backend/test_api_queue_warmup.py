import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SETUP = r'''
import asyncio, builtins, concurrent.futures, sys, threading, types
from unittest.mock import patch
from database.connection import Base, engine
import database.models
Base.metadata.create_all(engine)
original_import = builtins.__import__
sdk_imports = []
def track_import(name, *args, **kwargs):
    if name == 'hatchet_sdk' or name.startswith('hatchet_sdk.'):
        sdk_imports.append(name)
    return original_import(name, *args, **kwargs)
with patch('builtins.__import__', side_effect=track_import):
    import main
from services.chat_execution import get_broker
assert sdk_imports == []
'''


class ApiQueueWarmupTests(unittest.TestCase):
    def run_isolated(self, mode, source):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, APP_ENV='test', CHAT_EXECUTION_MODE=mode,
                       DATABASE_URL='sqlite:///' + str(Path(folder) / 'test.sqlite'),
                       REDIS_URL='redis://127.0.0.1:1/0')
            result = subprocess.run([sys.executable, '-c', SETUP + source],
                cwd=Path(__file__).parent, env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_disabled_queue_does_not_import_sdk_or_create_broker(self):
        self.run_isolated('inline', r'''
async def check():
    with patch('builtins.__import__', side_effect=track_import):
        async with main.app.router.lifespan_context(main.app):
            assert get_broker.cache_info().currsize == 0
    assert sdk_imports == []
asyncio.run(check())
''')

    def test_enabled_queue_constructs_one_client_before_serving_and_cleans_failure(self):
        self.run_isolated('hatchet', r'''
clients = []
def make_client():
    client = object()
    clients.append(client)
    return client
fake_sdk = types.ModuleType('hatchet_sdk')
fake_sdk.Hatchet = make_client
async def check():
    with patch.dict(sys.modules, {'hatchet_sdk': fake_sdk}):
        async with main.app.router.lifespan_context(main.app):
            assert len(clients) == 1
            barrier = threading.Barrier(10)
            def obtain(_):
                barrier.wait(timeout=5)
                return get_broker(), get_broker().hatchet
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(obtain, range(10)))
            assert len({id(broker) for broker, _ in results}) == 1
            assert all(client is clients[0] for _, client in results)
            assert len(clients) == 1
        assert get_broker.cache_info().currsize == 0
        def invalid_config():
            raise RuntimeError('invalid scheduler configuration')
        fake_sdk.Hatchet = invalid_config
        try:
            async with main.app.router.lifespan_context(main.app):
                raise AssertionError('must not serve after failed client construction')
        except RuntimeError as exc:
            assert str(exc) == 'invalid scheduler configuration'
        assert get_broker.cache_info().currsize == 0
asyncio.run(check())
''')


if __name__ == '__main__':
    unittest.main()
