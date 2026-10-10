import concurrent.futures
import os
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from services.structural_chunking import SerializationError, local_tokenizer
from workers import chat_worker


class ChatWorkerWarmupTests(unittest.TestCase):
    def tearDown(self):
        local_tokenizer.cache_clear()

    def test_concurrent_cold_tokenizer_builds_one_encoder_with_same_tokens(self):
        baseline, fingerprint = local_tokenizer()
        texts = ['Hello 世界', 'Take two capsules with food.', '<|endoftext|>']
        expected = [baseline.encode_ordinary(text) for text in texts]
        local_tokenizer.cache_clear()
        barrier = threading.Barrier(10)

        def read(_):
            barrier.wait(timeout=10)
            encoder, signature = local_tokenizer()
            return encoder, signature, [encoder.encode_ordinary(text) for text in texts]

        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(read, range(10)))
        self.assertEqual(len({id(row[0]) for row in results}), 1)
        self.assertTrue(all(signature == fingerprint and tokens == expected
                            for _, signature, tokens in results))

    def test_llama_path_is_loaded_and_assets_validated_before_registration(self):
        order = []
        with patch.dict(os.environ, {'CHAT_EXECUTION_MODE': 'hatchet', 'KNOWLEDGE_ENGINE': 'llamaindex'}), \
             patch.object(chat_worker, 'import_module', side_effect=lambda name: order.append(name)), \
             patch('services.structural_chunking.local_tokenizer', side_effect=lambda: order.append('tokenizer')):
            chat_worker.warm_runtime()
        self.assertEqual(order, ['services.rag_service', 'services.llama_rag.answer', 'tokenizer'])

    def test_missing_asset_refuses_start_before_any_worker_registration(self):
        local_tokenizer.cache_clear()
        with tempfile.TemporaryDirectory() as empty_assets:
            with patch.dict(os.environ, {'CHAT_EXECUTION_MODE': 'hatchet',
                    'KNOWLEDGE_ENGINE': 'llamaindex', 'TIKTOKEN_CACHE_DIR': empty_assets}), \
                 patch.object(chat_worker, 'import_module'), \
                 patch('services.chat_execution.get_broker') as broker, \
                 patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
                with self.assertRaisesRegex(SerializationError, 'local tokenizer asset unavailable'):
                    chat_worker.main()
                broker.assert_not_called()

    def test_ragflow_path_does_not_acquire_llama_assets(self):
        with patch.dict(os.environ, {'KNOWLEDGE_ENGINE': 'ragflow'}), \
             patch.object(chat_worker, 'import_module') as imports, \
             patch('services.structural_chunking.local_tokenizer') as tokenizer:
            chat_worker.warm_runtime()
        self.assertEqual([call.args[0] for call in imports.call_args_list],
                         ['services.rag_service', 'services.native_rag.answer'])
        tokenizer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
