"""Keep engine rollout explicit and prevent silent cross-engine fallback."""
import os
import unittest
from unittest.mock import patch

from services import knowledge_runtime


class EngineSelectionTests(unittest.TestCase):
    def test_existing_deployment_keeps_ragflow_without_new_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(knowledge_runtime.engine_name(), 'ragflow')

    def test_explicit_engine_selection_and_invalid_settings(self):
        for configured, expected in [('llamaindex', 'llamaindex'), (' RAGFLOW ', 'ragflow')]:
            with self.subTest(configured=configured), patch.dict(os.environ, {'KNOWLEDGE_ENGINE': configured}):
                self.assertEqual(knowledge_runtime.engine_name(), expected)
        for configured in ['', 'unknown']:
            with self.subTest(configured=configured), patch.dict(os.environ, {'KNOWLEDGE_ENGINE': configured}):
                with self.assertRaises(ValueError):
                    knowledge_runtime.engine_name()

    def test_selected_llama_service_failure_never_uses_legacy_readiness(self):
        with patch.dict(os.environ, {'KNOWLEDGE_ENGINE': 'llamaindex'}), \
                patch('services.llama_rag.client.RetrievalClient', side_effect=RuntimeError('unavailable')), \
                patch('services.native_rag.readiness.readiness', return_value='ready') as native, \
                patch('services.combined_rag.readiness.readiness', return_value='ready') as ranker:
            self.assertEqual(knowledge_runtime.readiness(), 'unavailable')
            native.assert_not_called()
            ranker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
