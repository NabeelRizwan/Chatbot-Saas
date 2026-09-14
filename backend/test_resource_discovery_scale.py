"""3,000-resource SQL-shape test; not a production latency benchmark."""
from time import perf_counter
import unittest
from sqlalchemy import event
from database.models import Organization, Bot, Document, Chunk
from database.resource_models import KnowledgeResource, KnowledgeResourceTerm
from services.resource_catalog import ResourceCatalogProjector
from services.retrieval_contracts import HardKnowledgeScope
from services.resource_channels import ResourceProbe
from services.resource_discovery import ResolutionState
from test_resource_discovery import ResourceFixture


class ResourceScaleTests(ResourceFixture):
    def test_20_tenants_3000_resources_bounded_sql(self):
        start = perf_counter()
        for org in range(2, 21):
            self.db.add(Organization(id=org, name=f"Fixture {org}", slug=f"fixture-{org}"))
        self.db.flush()
        for org in range(2, 21):
            self.db.add(Bot(id=org, organization_id=org, customer_id=1, name=f"Fixture {org}"))
        self.db.flush()
        docs, chunks = [], []
        for org in range(1, 21):
            for index in range(150):
                number = org * 1000 + index
                docs.append(dict(id=number, organization_id=org, bot_id=org, title=f"Meridian Resource {index}",
                    filename="fixture.txt", source_type="txt", status="ready", processing_status="completed", version=1,
                    metadata_json={"resource_type": "custom", "aliases": [f"Meridian Alias {index}", "Shared Desk"]}))
                chunks.append(dict(id=number, organization_id=org, bot_id=org, document_id=number,
                    content="Synthetic fixture source.", embedding=[0.] * 768, status="ready"))
        self.db.bulk_insert_mappings(Document, docs)
        self.db.bulk_insert_mappings(Chunk, chunks)
        self.db.commit()
        for org in range(1, 21):
            ResourceCatalogProjector().project(self.db, HardKnowledgeScope(org, org), range(org*1000, org*1000+150))
            self.db.commit()
        self.assertEqual(self.db.query(KnowledgeResource).count(), 3000)
        self.assertGreaterEqual(self.db.query(KnowledgeResourceTerm).count(), 12000)
        queries = []
        def capture(_, __, sql, *rest):
            queries.append(sql)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            for org in (1, 10, 20):
                hard = HardKnowledgeScope(org, org)
                before = len(queries)
                results = [self.service.discover(self.db, hard, [ResourceProbe("Meridian Resource 149")]) for _ in range(2)]
                self.assertEqual(len(queries)-before, 12)
                self.assertEqual(results[0].candidates, results[1].candidates)
                self.assertEqual(results[0].resolutions[0].candidate.resource.document_ids, (org*1000+149,))
                ambiguous = self.service.discover(self.db, hard, [ResourceProbe("Shared Desk")])
                self.assertEqual(ambiguous.resolutions[0].state, ResolutionState.AMBIGUOUS)
                for result in (*results, ambiguous):
                    self.assertLessEqual(len(result.candidates), 128)
                    self.assertTrue(all(c.resource.organization_id == org and c.resource.bot_id == org for c in result.candidates))
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertFalse(any('chunks.content' in sql or 'chunks.embedding,' in sql for sql in queries))
        print(f"PHASE3 SYNTHETIC SCALE: orgs=20 resources=3000 terms={self.db.query(KnowledgeResourceTerm).count()} queries={len(queries)} elapsed_s={perf_counter()-start:.3f}; no production latency claim")


if __name__ == '__main__':
    unittest.main()
