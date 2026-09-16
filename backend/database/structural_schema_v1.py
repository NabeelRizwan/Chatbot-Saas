"""Frozen PostgreSQL structural sidecar v1. No connection or runtime registration.

Pattern adaptations (no copied upstream code): see the Phase 4.1B OSS ledger.
Future schema changes require a new migration, not editing these definitions.
"""
from sqlalchemy import text

TABLES = ("document_versions", "document_structure_revisions", "structural_nodes",
          "structural_edges", "chunk_structural_nodes")
FUNCTIONS = ("structural_source_immutable_v1", "structural_revision_guard_v1",
             "structural_payload_guard_v1", "structural_pointer_guard_v1", "structural_active_check_v1")
TRIGGERS = (("document_versions", "structural_source_immutable"),
            ("document_structure_revisions", "structural_revision_guard"),
            ("structural_nodes", "structural_payload_guard"),
            ("structural_edges", "structural_payload_guard"),
            ("chunk_structural_nodes", "structural_payload_guard"),
            ("documents", "structural_pointer_guard"),
            ("documents", "structural_active_check"),
            ("document_structure_revisions", "structural_active_check"))

DDL = (
"ALTER TABLE documents ADD COLUMN IF NOT EXISTS active_structure_revision_id varchar(256)",
"ALTER TABLE chunks ADD COLUMN IF NOT EXISTS document_version_id varchar(256)",
"ALTER TABLE chunks ADD COLUMN IF NOT EXISTS structure_revision_id varchar(256)",
"""DO $$ BEGIN
 IF (SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
 JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
 AND ((c.relname='documents' AND a.attname='active_structure_revision_id') OR
 (c.relname='chunks' AND a.attname IN ('document_version_id','structure_revision_id')))
 AND NOT a.attnotnull AND format_type(a.atttypid,a.atttypmod)='character varying(256)')<>3 THEN
 RAISE EXCEPTION 'incompatible pre-existing structural columns'; END IF;
 END $$""",
"ALTER TABLE chunks ADD CONSTRAINT uq_chunks_structural_identity UNIQUE(id,organization_id,bot_id,document_id,document_version_id,structure_revision_id)",
"ALTER TABLE websites ADD CONSTRAINT uq_websites_structural_owner UNIQUE(id,organization_id,bot_id)",
"ALTER TABLE website_crawls ADD CONSTRAINT uq_crawls_structural_owner UNIQUE(id,organization_id,bot_id,website_id)",
"""CREATE TABLE document_versions (
 organization_id integer NOT NULL, bot_id integer NOT NULL, document_id integer NOT NULL,
 id varchar(256) NOT NULL, source_version integer NOT NULL CHECK(source_version > 0),
 crawl_id integer, website_id integer, source_identity text NOT NULL,
 source_url text, canonical_url text, source_format varchar(32) NOT NULL,
 mime_type varchar(256), fidelity varchar(32) NOT NULL,
 source_sha256 varchar(64) NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 captured_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 source_text text, source_artifact_ref text,
 PRIMARY KEY(organization_id,bot_id,document_id,id),
 CONSTRAINT fk_structural_version_document FOREIGN KEY(document_id,organization_id,bot_id)
 REFERENCES documents(id,organization_id,bot_id) ON DELETE CASCADE,
 CONSTRAINT fk_structural_version_website FOREIGN KEY(website_id,organization_id,bot_id)
 REFERENCES websites(id,organization_id,bot_id),
 CONSTRAINT fk_structural_version_crawl FOREIGN KEY(crawl_id,organization_id,bot_id,website_id)
 REFERENCES website_crawls(id,organization_id,bot_id,website_id),
 CHECK((crawl_id IS NULL) = (website_id IS NULL)),
 CHECK(source_text IS NOT NULL OR source_artifact_ref IS NOT NULL),
 CHECK(length(source_identity)>0), CHECK(length(id)>0),
 CHECK(source_format IN ('markdown','html','text','pdf','docx')),
 CHECK(fidelity IN ('original','extracted_markdown','extracted_text','layout','unknown'))
)""",
"CREATE UNIQUE INDEX uq_structural_source_upload ON document_versions(organization_id,bot_id,document_id,source_version) WHERE crawl_id IS NULL",
"CREATE UNIQUE INDEX uq_structural_source_crawl ON document_versions(organization_id,bot_id,document_id,source_version,crawl_id) WHERE crawl_id IS NOT NULL",
"""CREATE TABLE document_structure_revisions (
 organization_id integer NOT NULL, bot_id integer NOT NULL, document_id integer NOT NULL,
 document_version_id varchar(256) NOT NULL, id varchar(256) NOT NULL,
 build_fingerprint varchar(64) NOT NULL, schema_version varchar(32) NOT NULL CHECK(schema_version='structural-v1'),
 parser_version varchar(256) NOT NULL, normalizer_version varchar(256) NOT NULL,
 chunk_policy_version varchar(256), configuration_sha256 varchar(64) NOT NULL,
 source_format varchar(32) NOT NULL, fidelity varchar(32) NOT NULL,
 ingestion_job_id varchar(256), state varchar(16) NOT NULL DEFAULT 'staging',
 quality jsonb NOT NULL CHECK(jsonb_typeof(quality)='object'),
 expected_nodes integer NOT NULL CHECK(expected_nodes BETWEEN 1 AND 10000),
 expected_edges integer NOT NULL CHECK(expected_edges BETWEEN 0 AND 20000),
 expected_mappings integer NOT NULL CHECK(expected_mappings BETWEEN 0 AND 100000),
 actual_nodes integer NOT NULL DEFAULT 0, actual_edges integer NOT NULL DEFAULT 0,
 actual_mappings integer NOT NULL DEFAULT 0,
 source_sha256 varchar(64) NOT NULL, normalized_hash varchar(64), serialization_hash varchar(64),
 created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at timestamptz,
 PRIMARY KEY(organization_id,bot_id,document_id,id),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,id),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,build_fingerprint),
 CONSTRAINT fk_structural_revision_version FOREIGN KEY(organization_id,bot_id,document_id,document_version_id)
 REFERENCES document_versions(organization_id,bot_id,document_id,id) ON DELETE CASCADE,
 CHECK(state IN ('staging','validated','active','superseded','failed','cancelled')),
 CHECK(build_fingerprint ~ '^[0-9a-f]{64}$' AND configuration_sha256 ~ '^[0-9a-f]{64}$'),
 CHECK(length(id)>0)
)""",
"CREATE INDEX ix_structural_revisions_state ON document_structure_revisions(organization_id,bot_id,document_id,state)",
"CREATE UNIQUE INDEX uq_structural_one_active ON document_structure_revisions(organization_id,bot_id,document_id) WHERE state='active'",
"""CREATE TABLE structural_nodes (
 organization_id integer NOT NULL, bot_id integer NOT NULL, document_id integer NOT NULL,
 document_version_id varchar(256) NOT NULL, structure_revision_id varchar(256) NOT NULL,
 node_key varchar(64) NOT NULL, parent_key varchar(64), parent_preorder integer, parent_depth integer,
 preorder integer NOT NULL CHECK(preorder BETWEEN 0 AND 9999), depth integer NOT NULL CHECK(depth BETWEEN 0 AND 32),
 leaf_order integer CHECK(leaf_order>=0), parser_path varchar(256) NOT NULL, occurrence integer NOT NULL CHECK(occurrence>=0),
 node_type varchar(32) NOT NULL, semantic_role varchar(32) NOT NULL,
 text text NOT NULL, display_text text, attributes jsonb NOT NULL, provenance jsonb NOT NULL, quality jsonb,
 content_hash varchar(64) NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,structure_revision_id,preorder),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,structure_revision_id,leaf_order),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key,preorder,depth),
 CONSTRAINT fk_structural_node_revision FOREIGN KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id)
 REFERENCES document_structure_revisions(organization_id,bot_id,document_id,document_version_id,id) ON DELETE CASCADE,
 CONSTRAINT fk_structural_node_parent FOREIGN KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id,parent_key,parent_preorder,parent_depth)
 REFERENCES structural_nodes(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key,preorder,depth),
 CHECK((parent_key IS NULL AND parent_preorder IS NULL AND parent_depth IS NULL AND preorder=0 AND depth=0 AND node_type='document') OR
       (parent_key IS NOT NULL AND parent_preorder IS NOT NULL AND parent_depth IS NOT NULL AND parent_key<>node_key AND parent_preorder<preorder AND depth=parent_depth+1 AND node_type<>'document')),
 CHECK(node_type IN ('document','section','heading','paragraph','list','list_item','table','table_row','table_cell','group','link','media')),
 CHECK(semantic_role IN ('title','faq_question','faq_answer','review','product_card','price_block','directions','ingredients','timeline_stage','warning','navigation','furniture','unknown')),
 CHECK(node_key ~ '^[0-9a-f]{64}$'), CHECK(jsonb_typeof(attributes)='object' AND jsonb_typeof(provenance)='object')
)""",
"CREATE INDEX ix_structural_nodes_children ON structural_nodes(organization_id,bot_id,structure_revision_id,parent_key,preorder)",
"CREATE INDEX ix_structural_nodes_lookup ON structural_nodes(organization_id,bot_id,structure_revision_id,node_key)",
"""CREATE TABLE structural_edges (
 organization_id integer NOT NULL, bot_id integer NOT NULL, document_id integer NOT NULL,
 document_version_id varchar(256) NOT NULL, structure_revision_id varchar(256) NOT NULL,
 from_node_key varchar(64) NOT NULL, to_document_id integer NOT NULL,
 to_document_version_id varchar(256) NOT NULL, to_structure_revision_id varchar(256) NOT NULL,
 to_node_key varchar(64) NOT NULL, edge_key varchar(64) NOT NULL, logical_identity varchar(64) NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 0 AND 19999),
 relation varchar(32) NOT NULL, field varchar(256), role varchar(32), provenance jsonb NOT NULL,
 validation_state varchar(16) NOT NULL,
 PRIMARY KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id,edge_key),
 UNIQUE(organization_id,bot_id,document_id,document_version_id,structure_revision_id,ordinal),
 CONSTRAINT fk_structural_edge_from FOREIGN KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id,from_node_key)
 REFERENCES structural_nodes(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key) ON DELETE CASCADE,
 CONSTRAINT fk_structural_edge_to FOREIGN KEY(organization_id,bot_id,to_document_id,to_document_version_id,to_structure_revision_id,to_node_key)
 REFERENCES structural_nodes(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key),
 CHECK(relation IN ('CONTAINS','REFERS_TO','VARIANT_OF','DESCRIBES','HEADING_FOR','QA_PAIR')),
 CHECK(validation_state IN ('unvalidated','validated','rejected')),
 CHECK(jsonb_typeof(provenance)='object'), CHECK(edge_key ~ '^[0-9a-f]{64}$')
)""",
"CREATE INDEX ix_structural_edges_from ON structural_edges(organization_id,bot_id,structure_revision_id,from_node_key,relation,edge_key)",
"CREATE INDEX ix_structural_edges_to ON structural_edges(organization_id,bot_id,to_structure_revision_id,to_node_key,relation,edge_key)",
# The trigger computes this SHA-256 from full pinned endpoints/evidence. Avoid
# an oversized B-tree key containing four potentially long UTF-8 revision IDs.
"CREATE UNIQUE INDEX uq_structural_edge_logical ON structural_edges(organization_id,bot_id,logical_identity)",
"""CREATE TABLE chunk_structural_nodes (
 organization_id integer NOT NULL, bot_id integer NOT NULL, document_id integer NOT NULL,
 document_version_id varchar(256) NOT NULL, structure_revision_id varchar(256) NOT NULL,
 chunk_id integer NOT NULL, node_key varchar(64) NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
 node_start integer NOT NULL, node_end integer NOT NULL, output_start integer NOT NULL, output_end integer NOT NULL,
 role varchar(16) NOT NULL CHECK(role IN ('body','heading','header','qualifier')),
 bundle_key varchar(256), part_index integer, part_count integer,
 PRIMARY KEY(organization_id,bot_id,chunk_id,ordinal),
 CONSTRAINT fk_structural_mapping_node FOREIGN KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key)
 REFERENCES structural_nodes(organization_id,bot_id,document_id,document_version_id,structure_revision_id,node_key) ON DELETE CASCADE,
 CONSTRAINT fk_structural_mapping_chunk FOREIGN KEY(chunk_id,organization_id,bot_id,document_id,document_version_id,structure_revision_id)
 REFERENCES chunks(id,organization_id,bot_id,document_id,document_version_id,structure_revision_id) ON DELETE CASCADE,
 CHECK(node_start>=0 AND node_end>=node_start AND output_start>=0 AND output_end>=output_start),
 CHECK((bundle_key IS NULL AND part_index IS NULL AND part_count IS NULL) OR
 (bundle_key IS NOT NULL AND part_index IS NOT NULL AND part_count IS NOT NULL AND part_index>=0 AND part_count>part_index))
)""",
"CREATE INDEX ix_structural_mappings_node ON chunk_structural_nodes(organization_id,bot_id,structure_revision_id,node_key,chunk_id,ordinal)",
"""ALTER TABLE chunks ADD CONSTRAINT fk_chunks_structural_version FOREIGN KEY(organization_id,bot_id,document_id,document_version_id)
 REFERENCES document_versions(organization_id,bot_id,document_id,id)""",
"""ALTER TABLE chunks ADD CONSTRAINT fk_chunks_structural_revision FOREIGN KEY(organization_id,bot_id,document_id,document_version_id,structure_revision_id)
 REFERENCES document_structure_revisions(organization_id,bot_id,document_id,document_version_id,id)""",
"""ALTER TABLE chunks ADD CONSTRAINT ck_chunks_structural_identity CHECK
 ((document_version_id IS NULL AND structure_revision_id IS NULL) OR
 (document_version_id IS NOT NULL AND structure_revision_id IS NOT NULL AND organization_id IS NOT NULL AND bot_id IS NOT NULL))""",
"""ALTER TABLE documents ADD CONSTRAINT fk_document_active_structure FOREIGN KEY(organization_id,bot_id,id,active_structure_revision_id)
 REFERENCES document_structure_revisions(organization_id,bot_id,document_id,id) DEFERRABLE INITIALLY DEFERRED""",
"ALTER TABLE documents ADD CONSTRAINT ck_document_active_structure CHECK(active_structure_revision_id IS NULL OR (organization_id IS NOT NULL AND bot_id IS NOT NULL))",
)

TRIGGER_SQL = (
"""CREATE FUNCTION structural_source_immutable_v1() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN
 IF TG_OP='DELETE' THEN
  IF EXISTS (SELECT 1 FROM documents WHERE id=OLD.document_id AND organization_id=OLD.organization_id AND bot_id=OLD.bot_id) THEN
   RAISE EXCEPTION 'immutable structural source history' USING ERRCODE='23514'; END IF;
  RETURN OLD;
 END IF;
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'immutable structural source' USING ERRCODE='23514'; END IF;
 RETURN NEW; END $$""",
"""CREATE FUNCTION structural_revision_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
 DECLARE n integer; e integer; m integer; v document_versions%ROWTYPE;
 BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.state<>'staging' AND EXISTS (SELECT 1 FROM documents WHERE id=OLD.document_id AND organization_id=OLD.organization_id AND bot_id=OLD.bot_id) THEN
   RAISE EXCEPTION 'sealed structural revision history' USING ERRCODE='23514'; END IF;
  RETURN OLD;
 END IF;
 SELECT * INTO v FROM document_versions WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id
 AND document_id=NEW.document_id AND id=NEW.document_version_id;
 IF NOT FOUND OR NEW.source_sha256<>v.source_sha256 THEN RAISE EXCEPTION 'revision source mismatch' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'staging' THEN RAISE EXCEPTION 'revision must start staging' USING ERRCODE='23514'; END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['state','actual_nodes','actual_edges','actual_mappings','normalized_hash','serialization_hash','completed_at'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','actual_nodes','actual_edges','actual_mappings','normalized_hash','serialization_hash','completed_at'])
  THEN RAISE EXCEPTION 'immutable revision recipe' USING ERRCODE='23514'; END IF;
  IF OLD.state<>'staging' AND (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state') THEN
   RAISE EXCEPTION 'sealed revision content' USING ERRCODE='23514'; END IF;
  IF NEW.state<>OLD.state AND NOT ((OLD.state='staging' AND NEW.state IN ('validated','failed','cancelled')) OR
   (OLD.state='validated' AND NEW.state IN ('active','failed','cancelled')) OR (OLD.state='active' AND NEW.state='superseded')) THEN
   RAISE EXCEPTION 'invalid structural transition' USING ERRCODE='23514'; END IF;
  IF OLD.state='staging' AND NEW.state='validated' THEN
   SELECT count(*) INTO n FROM structural_nodes WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.document_id AND structure_revision_id=NEW.id;
   SELECT count(*) INTO e FROM structural_edges WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.document_id AND structure_revision_id=NEW.id;
   SELECT count(*) INTO m FROM chunk_structural_nodes WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.document_id AND structure_revision_id=NEW.id;
   IF (n,e,m) IS DISTINCT FROM (NEW.expected_nodes,NEW.expected_edges,NEW.expected_mappings) OR NEW.normalized_hash IS NULL THEN
    RAISE EXCEPTION 'structural counts/hash incomplete' USING ERRCODE='23514'; END IF;
   NEW.actual_nodes=n; NEW.actual_edges=e; NEW.actual_mappings=m; NEW.completed_at=CURRENT_TIMESTAMP;
  END IF;
 END IF;
 RETURN NEW;
 END $$""",
"""CREATE FUNCTION structural_payload_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
 DECLARE r record; s text; a structural_nodes%ROWTYPE; b structural_nodes%ROWTYPE; chunk_text text;
 BEGIN
 IF TG_OP='DELETE' THEN r=OLD; ELSE r=NEW; END IF;
 SELECT state INTO s FROM document_structure_revisions WHERE organization_id=r.organization_id AND bot_id=r.bot_id
 AND document_id=r.document_id AND document_version_id=r.document_version_id AND id=r.structure_revision_id FOR UPDATE;
 IF NOT FOUND AND TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF s IS DISTINCT FROM 'staging' THEN RAISE EXCEPTION 'revision is not writable staging' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'staged payload is append-only' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF TG_TABLE_NAME='structural_edges' THEN
  NEW.logical_identity=encode(sha256(convert_to(jsonb_build_array(
   NEW.organization_id,NEW.bot_id,NEW.document_id,NEW.document_version_id,NEW.structure_revision_id,NEW.from_node_key,
   NEW.to_document_id,NEW.to_document_version_id,NEW.to_structure_revision_id,NEW.to_node_key,
   NEW.relation,NEW.field,NEW.role,NEW.provenance-'confidence')::text,'UTF8')),'hex');
  SELECT * INTO a FROM structural_nodes WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.document_id
   AND document_version_id=NEW.document_version_id AND structure_revision_id=NEW.structure_revision_id AND node_key=NEW.from_node_key;
  SELECT * INTO b FROM structural_nodes WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.to_document_id
   AND document_version_id=NEW.to_document_version_id AND structure_revision_id=NEW.to_structure_revision_id AND node_key=NEW.to_node_key;
  IF (NEW.relation='HEADING_FOR' AND a.node_type IS DISTINCT FROM 'heading') OR
     (NEW.relation='QA_PAIR' AND (a.semantic_role IS DISTINCT FROM 'faq_question' OR b.semantic_role IS DISTINCT FROM 'faq_answer')) OR
     (NEW.relation='CONTAINS' AND (a.organization_id,a.bot_id,a.document_id,a.document_version_id,a.structure_revision_id,a.node_key)=
       (b.organization_id,b.bot_id,b.document_id,b.document_version_id,b.structure_revision_id,b.parent_key)) THEN
   RAISE EXCEPTION 'invalid structural edge types/tree duplication' USING ERRCODE='23514'; END IF;
 ELSIF TG_TABLE_NAME='chunk_structural_nodes' THEN
  SELECT * INTO a FROM structural_nodes WHERE organization_id=NEW.organization_id AND bot_id=NEW.bot_id AND document_id=NEW.document_id
   AND document_version_id=NEW.document_version_id AND structure_revision_id=NEW.structure_revision_id AND node_key=NEW.node_key;
  SELECT content INTO chunk_text FROM chunks WHERE id=NEW.chunk_id AND organization_id=NEW.organization_id
   AND bot_id=NEW.bot_id AND document_id=NEW.document_id AND document_version_id=NEW.document_version_id AND structure_revision_id=NEW.structure_revision_id;
  IF NEW.node_end>octet_length(a.text) OR NEW.output_end>octet_length(chunk_text) THEN
   RAISE EXCEPTION 'mapping exceeds source/output bytes' USING ERRCODE='23514'; END IF;
  PERFORM convert_from(substring(convert_to(a.text,'UTF8') FROM 1 FOR NEW.node_start),'UTF8');
  PERFORM convert_from(substring(convert_to(a.text,'UTF8') FROM 1 FOR NEW.node_end),'UTF8');
  PERFORM convert_from(substring(convert_to(chunk_text,'UTF8') FROM 1 FOR NEW.output_start),'UTF8');
  PERFORM convert_from(substring(convert_to(chunk_text,'UTF8') FROM 1 FOR NEW.output_end),'UTF8');
 END IF;
 RETURN NEW;
 END $$""",
"""CREATE FUNCTION structural_pointer_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
 DECLARE r record;
 BEGIN
 IF NEW.active_structure_revision_id IS NULL OR (TG_OP='UPDATE' AND NEW.active_structure_revision_id IS NOT DISTINCT FROM OLD.active_structure_revision_id) THEN RETURN NEW; END IF;
 SELECT v.source_version,v.crawl_id,v.website_id,s.quality INTO r FROM document_structure_revisions s
 JOIN document_versions v ON (v.organization_id,v.bot_id,v.document_id,v.id)=(s.organization_id,s.bot_id,s.document_id,s.document_version_id)
 WHERE s.organization_id=NEW.organization_id AND s.bot_id=NEW.bot_id AND s.document_id=NEW.id AND s.id=NEW.active_structure_revision_id;
 IF NOT FOUND OR (r.source_version,r.crawl_id,r.website_id) IS DISTINCT FROM (NEW.version,NEW.crawl_id,NEW.website_id)
 OR r.quality->>'disposition' IS DISTINCT FROM 'accept' OR NEW.status<>'ready' OR NEW.processing_status<>'completed' THEN
  RAISE EXCEPTION 'active structural source is not eligible/current' USING ERRCODE='23514'; END IF;
 IF NEW.website_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM websites w JOIN website_crawls c ON c.id=w.active_crawl_id
  WHERE w.id=NEW.website_id AND w.organization_id=NEW.organization_id AND w.bot_id=NEW.bot_id AND w.status='ready'
  AND c.id=NEW.crawl_id AND c.website_id=w.id AND c.organization_id=NEW.organization_id AND c.bot_id=NEW.bot_id
  AND c.status='ready' AND c.version=NEW.version) THEN
  RAISE EXCEPTION 'structural activation requires active ready crawl' USING ERRCODE='23514'; END IF;
 RETURN NEW;
 END $$""",
"""CREATE FUNCTION structural_active_check_v1() RETURNS trigger LANGUAGE plpgsql AS $$
 DECLARE d integer; o integer; b integer; pointer varchar(256); active varchar(256);
 BEGIN
 IF TG_TABLE_NAME='documents' THEN d=NEW.id; ELSE d=NEW.document_id; END IF;
 o=NEW.organization_id; b=NEW.bot_id;
 SELECT active_structure_revision_id INTO pointer FROM documents WHERE id=d AND organization_id=o AND bot_id=b;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT id INTO active FROM document_structure_revisions WHERE organization_id=o AND bot_id=b AND document_id=d AND state='active';
 IF active IS DISTINCT FROM pointer THEN RAISE EXCEPTION 'structural pointer/state mismatch' USING ERRCODE='23514'; END IF;
 RETURN NULL;
 END $$""",
"CREATE TRIGGER structural_source_immutable BEFORE UPDATE OR DELETE ON document_versions FOR EACH ROW EXECUTE FUNCTION structural_source_immutable_v1()",
"CREATE TRIGGER structural_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON document_structure_revisions FOR EACH ROW EXECUTE FUNCTION structural_revision_guard_v1()",
*(f"CREATE TRIGGER structural_payload_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION structural_payload_guard_v1()" for table in TABLES[2:]),
"CREATE TRIGGER structural_pointer_guard BEFORE INSERT OR UPDATE OF active_structure_revision_id ON documents FOR EACH ROW EXECUTE FUNCTION structural_pointer_guard_v1()",
"CREATE CONSTRAINT TRIGGER structural_active_check AFTER INSERT OR UPDATE OF active_structure_revision_id ON documents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION structural_active_check_v1()",
"CREATE CONSTRAINT TRIGGER structural_active_check AFTER INSERT OR UPDATE ON document_structure_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION structural_active_check_v1()",
)


def upgrade(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Structural schema requires PostgreSQL")
    for statement in (*DDL, *TRIGGER_SQL):
        connection.execute(text(statement))


def remove_triggers(connection):
    """Used by downgrade and ownership-checked disposable cleanup only."""
    for table, name in reversed(TRIGGERS):
        connection.execute(text(f"DROP TRIGGER {name} ON {table}"))
    for name in reversed(FUNCTIONS):
        connection.execute(text(f"DROP FUNCTION {name}() RESTRICT"))


def downgrade(connection):
    # Never silently destroy a populated structural history on rollback.
    if any(connection.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first() for table in TABLES):
        raise RuntimeError("Structural downgrade refused: populated history; use feature/code rollback")
    remove_triggers(connection)
    for table, constraint in (("documents","fk_document_active_structure"),("documents","ck_document_active_structure"),
        ("chunks","fk_chunks_structural_revision"),("chunks","fk_chunks_structural_version"),("chunks","ck_chunks_structural_identity")):
        connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
    for table in reversed(TABLES):
        connection.execute(text(f"DROP TABLE {table} RESTRICT"))
    for table,constraint in (("chunks","uq_chunks_structural_identity"),("website_crawls","uq_crawls_structural_owner"),("websites","uq_websites_structural_owner")):
        connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
    connection.execute(text("ALTER TABLE documents DROP COLUMN active_structure_revision_id"))
    connection.execute(text("ALTER TABLE chunks DROP COLUMN structure_revision_id"))
    connection.execute(text("ALTER TABLE chunks DROP COLUMN document_version_id"))
