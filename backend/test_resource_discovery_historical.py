"""Historical hold-out only: run after generic development/heldout policy freeze."""
import inspect
import unittest
from pathlib import Path

from services.retrieval_contracts import SemanticScopeState
from test_resource_discovery import ResourceFixture


class HistoricalResourceTests(ResourceFixture):
    def test_historical_reordered_reference_without_invented_alias(self):
        self.add(5129, "Turmeric Boost", kind="product")
        self.add(5134, "Grass-Fed Collagen Peptides Powder (Chocolate)", kind="product")
        self.project(5129, 5134)
        question = "For joint comfort, would Turmeric Boost or the chocolate collagen give me a fair trial before the money-back guarantee runs out?"
        contract = self.contract(question)
        self.assertEqual(contract.original_query, question)
        self.assertEqual(contract.permitted_document_ids, [5129, 5134], contract.to_debug_dict())
        self.assertEqual(contract.execution.soft_scope.state, SemanticScopeState.RESOLVED_MULTI)
        self.assertEqual(len(contract.execution.soft_scope.resolved_resources), 2)

    def test_runtime_no_historical_overfit(self):
        root = Path(__file__).parent / "services"
        for filename in ("resource_catalog.py", "resource_channels.py", "resource_discovery.py", "resource_normalization.py", "resource_scope_adapter.py"):
            content = (root / filename).read_text(encoding="utf-8").casefold()
            for value in ("wowmd", "turmeric", "collagen", "chocolate", "5129", "5134"):
                self.assertNotIn(value, content, filename)


if __name__ == "__main__":
    unittest.main()
