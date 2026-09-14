"""Offline validation of Phase 3.1 test infrastructure; never connects remotely."""
from contextlib import contextmanager
import inspect
import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from sqlalchemy.dialects import postgresql
from scripts import phase31_remote as remote
from scripts import test_phase3_postgres as original
from scripts.phase31_fixture import documents,GOLDEN,NATURAL

SYNTHETIC="postgresql://fixture:fixture@disposable.invalid:5432/temporary"


class RemoteGuardTests(unittest.TestCase):
    def url(self, values, configured=()):
        with patch.dict(os.environ,values,clear=True):
            return remote.authorized_url(configured)

    def test_requires_both_explicit_inputs(self):
        for values in ({},{"PHASE3_ALLOW_REMOTE_DISPOSABLE":"1"},{"PHASE3_TEST_DATABASE_URL":SYNTHETIC},
                       {"PHASE3_TEST_DATABASE_URL":SYNTHETIC,"PHASE3_ALLOW_REMOTE_DISPOSABLE":"true"}):
            with self.subTest(keys=sorted(values)),self.assertRaises(remote.DisposableUnavailable):
                self.url(values)

    def test_explicit_disposable_remote_accepted_structurally(self):
        url=self.url({"PHASE3_TEST_DATABASE_URL":SYNTHETIC,"PHASE3_ALLOW_REMOTE_DISPOSABLE":"1"})
        self.assertEqual(url.drivername,"postgresql+psycopg2")

    def test_application_endpoint_refused_even_with_different_credentials_driver(self):
        for configured in (SYNTHETIC,"postgres://different:credentials@disposable.invalid:5432/temporary"):
            with self.assertRaises(remote.DisposableUnavailable):
                self.url({"PHASE3_TEST_DATABASE_URL":SYNTHETIC,"PHASE3_ALLOW_REMOTE_DISPOSABLE":"1"},[configured])

    def test_no_application_or_phase2_fallback(self):
        with self.assertRaises(remote.DisposableUnavailable):
            self.url({"DATABASE_URL":SYNTHETIC,"PHASE2_TEST_DATABASE_URL":SYNTHETIC,"PHASE3_ALLOW_REMOTE_DISPOSABLE":"1"})

    def test_rejects_libpq_target_overrides_and_malformed_urls_redacted(self):
        for value in (SYNTHETIC+"?host=another.invalid",SYNTHETIC+"?options=unsafe","malformed-secret",SYNTHETIC.replace(":5432", "")):
            with self.assertRaises(remote.DisposableUnavailable) as error:
                self.url({"PHASE3_TEST_DATABASE_URL":value,"PHASE3_ALLOW_REMOTE_DISPOSABLE":"1"})
            self.assertNotIn(value,str(error.exception))
            self.assertNotIn("fixture:fixture",str(error.exception))

    def test_original_local_default_still_refuses_remote(self):
        with patch.dict(os.environ,{"PHASE3_TEST_DATABASE_URL":SYNTHETIC},clear=True),self.assertRaises(original.DisposableUnavailable):
            original.explicit_local_url()

    def test_catalog_guard_refuses_before_extensions_or_schema(self):
        conn=Mock()
        conn.execute.return_value.mappings.return_value.one.return_value={}
        conn.execute.return_value.all.return_value=[("organizations",)]
        with self.assertRaises(remote.DisposableUnavailable):
            remote.preflight(conn)
        conn.exec_driver_sql.assert_not_called()

    def test_stale_schema_refuses_without_ddl(self):
        conn=Mock()
        conn.execute.return_value.mappings.return_value.one.return_value={}
        conn.execute.return_value.all.return_value=[]
        conn.execute.return_value.first.return_value=(1,)
        with self.assertRaises(remote.DisposableUnavailable):
            remote.preflight(conn)
        conn.exec_driver_sql.assert_not_called()
        sql,params=conn.execute.call_args.args
        self.assertIn(":a",str(sql))
        compiled=sql.compile(dialect=postgresql.dialect())
        self.assertNotIn("phase3_acceptance_%",str(compiled))
        self.assertEqual(params["a"],"phase3_acceptance_%")

    def test_preflight_pass_select_only(self):
        conn=Mock()
        facts=Mock();facts.mappings.return_value.one.return_value={"server_version":"18.6"}
        empty=Mock();empty.all.return_value=[]
        stale=Mock();stale.first.return_value=None
        extension=Mock();extension.all.return_value=[("vector","0.8.6","public",12)]
        packages=Mock();packages.all.return_value=[("vector","0.8.6"),("pg_trgm","1.6")]
        conn.execute.side_effect=[facts,empty,stale,extension,packages]
        result,_=remote.preflight(conn)
        self.assertTrue(result["empty_database_guard"])
        conn.exec_driver_sql.assert_not_called()
        self.assertTrue(all(str(c.args[0]).lstrip().startswith("SELECT") for c in conn.execute.call_args_list))

    def test_fresh_extension_packages_pass_without_installing_during_preflight(self):
        conn=Mock()
        facts=Mock();facts.mappings.return_value.one.return_value={}
        empty=Mock();empty.all.return_value=[];empty.first.return_value=None
        packages=Mock();packages.all.return_value=[("vector","0.8.6"),("pg_trgm","1.6")]
        conn.execute.side_effect=[facts,empty,empty,empty,packages]
        result,_=remote.preflight(conn)
        self.assertEqual(result["extensions"],{})
        self.assertEqual(result["available_extensions"]["vector"],"0.8.6")
        conn.exec_driver_sql.assert_not_called()

    def test_missing_vector_package_refuses_no_install(self):
        conn=Mock()
        facts=Mock();facts.mappings.return_value.one.return_value={}
        empty=Mock();empty.all.return_value=[];empty.first.return_value=None
        packages=Mock();packages.all.return_value=[("pg_trgm","1.6")]
        conn.execute.side_effect=[facts,empty,empty,empty,packages]
        with self.assertRaises(remote.DisposableUnavailable):
            remote.preflight(conn)
        conn.exec_driver_sql.assert_not_called()

    def test_extension_cleanup_is_namespace_and_oid_bound(self):
        source=inspect.getsource(remote.disposable_database)
        self.assertIn('set(ext) != set(state["extensions"])',source)
        self.assertIn('extnamespace=:oid',source)
        self.assertIn('CREATE EXTENSION vector WITH SCHEMA',source)

    def test_cleanup_requires_marker_oid_owner_and_restrict(self):
        source=inspect.getsource(remote.disposable_database)
        for required in ("pg_try_advisory_lock","current != owner","dict(rows) != state","set(functions)",
                         "marker changed","extension ownership changed","RESTRICT","unrelated_objects_unchanged"):
            self.assertIn(required,source)
        self.assertNotIn("DROP DATABASE",source)
        self.assertNotIn(" CASCADE",source)
        self.assertNotIn("DROP EXTENSION vector",source)

    def test_engine_disposed_and_url_never_printed(self):
        engine=Mock();engine.connect.side_effect=RuntimeError("synthetic exception")
        with patch.object(remote,"authorized_url",return_value="synthetic"),patch.object(remote,"create_engine",return_value=engine):
            with self.assertRaises(RuntimeError):
                with remote.disposable_database():
                    self.fail("unreachable")
        engine.dispose.assert_called_once()

    def test_scale_fixture_and_golden_membership_frozen(self):
        docs=documents()
        self.assertEqual(len(docs),6000)
        self.assertEqual(len({d["id"] for d in docs}),6000)
        self.assertEqual(len({d["organization_id"] for d in docs}),30)
        self.assertEqual(len(GOLDEN),50)
        self.assertGreaterEqual(sum(i<=30 and e in {"positive","category"} for i,(_,_,e) in enumerate(GOLDEN,1)),25)
        from services.resource_catalog import projection
        from types import SimpleNamespace
        self.assertGreaterEqual(sum(len(projection(SimpleNamespace(**d,source_url=None))[2]) for d in docs),30000)

    def test_bulk_fixture_preserves_reference_metadata(self):
        from test_resource_discovery import ResourceFixture
        from test_resource_discovery_benchmark import populate
        from database.models import Document
        from services.resource_catalog import projection
        from types import SimpleNamespace
        f=ResourceFixture();f.setUp()
        try:
            populate(f)
            bulk={d["id"]:d for d in documents()}
            for doc in f.db.query(Document).all():
                self.assertEqual(projection(doc),projection(SimpleNamespace(**bulk[doc.id],source_url=None)))
        finally:
            f.doCleanups()

    def test_handoff_records_use_actual_nested_retriever_contract(self):
        from types import SimpleNamespace
        from scripts.phase31_acceptance import evidence_rows
        from services import rag_service as rag
        nested=[{"chunk":SimpleNamespace(id=7,content="Factual source only."),"document":SimpleNamespace(id=11)}]
        with self.assertRaises(KeyError):
            _={item["document_id"] for item in nested}  # Exact former harness failure.
        self.assertEqual(evidence_rows(nested),[{"id":7,"document_id":11,"content":"Factual source only."}])
        self.assertEqual(evidence_rows([]),[])

    def test_large_telemetry_frames_are_bounded_and_lossless(self):
        from io import StringIO
        import json
        from scripts.phase31_acceptance import emit
        payload={"fixture":"x"*70000,"quoted":"Unicode café 東京 / quotes \" and backslash \\","metric":1.23456789}
        with patch('sys.stdout',new_callable=StringIO) as output:
            emit("large_test",payload)
        lines=output.getvalue().splitlines()
        self.assertTrue(all(len(line)<2500 for line in lines))
        frames=[json.loads(line) for line in lines]
        self.assertEqual(len(frames),frames[0]["parts"])
        self.assertEqual([f["part"] for f in frames],list(range(len(frames))))
        self.assertEqual(json.loads(''.join(f["fragment"] for f in frames)),{"stage":"large_test","data":payload})


if __name__=="__main__":
    unittest.main()
