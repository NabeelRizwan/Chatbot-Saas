"""Additive isolated schema; NOT registered with application metadata/Alembic.

Only the explicit internal disposable runner may create these relations. Source
history has no run parent: deleting a run cannot cascade into source history.
PostgreSQL vector/GIN SQL is compiled offline; SQLite is a constraints test double.
"""
from sqlalchemy import (MetaData, Table, Column, Integer, String, Text, Float, JSON,
    ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint, CheckConstraint,
    Index, text, event, DDL)
from pgvector.sqlalchemy import Vector

metadata = MetaData()
RUN = ('organization_id', 'bot_id', 'run_id')
MAN = (*RUN, 'lane', 'generation', 'manifest_hash', 'profile_hash', 'policy_hash')
SRC = ('organization_id', 'bot_id', 'document_id', 'document_version_id', 'source_version',
       'source_hash', 'website_id', 'crawl_id', 'crawl_version', 'revision')
DOC = (*MAN, *SRC[2:])
INTS = {'organization_id', 'bot_id', 'document_id', 'source_version', 'website_id', 'crawl_id', 'crawl_version'}


def cols(keys):
    return [Column(k, Integer if k in INTS else String(256), nullable=False) for k in keys]


def fk(keys, target, target_keys=None, cascade=True):
    return ForeignKeyConstraint(keys, [target + '.' + k for k in (target_keys or keys)],
        ondelete='CASCADE' if cascade else 'RESTRICT')


def pk(keys):
    return PrimaryKeyConstraint(*keys)


marker = Table('canary_ownership', metadata,
    Column('database_identity', String(64), primary_key=True),
    Column('marker', String(256), nullable=False),
    Column('environment', String(32), nullable=False),
    CheckConstraint("environment IN ('offline_test','disposable_test')"))

sources = Table('canary_source_history', metadata, *cols(SRC),
    Column('payload', JSON, nullable=False), Column('payload_hash', String(64), nullable=False),
    pk(SRC), CheckConstraint('source_version > 0'),
    CheckConstraint('(website_id=0 AND crawl_id=0 AND crawl_version=0) OR (website_id>0 AND crawl_id>0 AND crawl_version>0)'))

lifecycle = Table('canary_source_lifecycle', metadata, *cols(('organization_id','bot_id','document_id')),
    Column('source_fingerprint', String(64), nullable=False),
    Column('status', String(32), nullable=False), Column('processing', String(32), nullable=False),
    Column('crawl_status', String(32), nullable=False), Column('active_crawl_id', Integer, nullable=False),
    Column('revision_state', String(32), nullable=False), Column('epoch', Integer, nullable=False),
    pk(('organization_id','bot_id','document_id')))

# Same anti-reset invariant in the offline constraints double. PostgreSQL guards
# are installed exclusively by the approved owned-schema migration below.
event.listen(lifecycle, 'after_create', DDL("""CREATE TRIGGER canary_source_epoch_guard
BEFORE UPDATE ON canary_source_lifecycle WHEN NEW.epoch <= OLD.epoch
 OR NEW.organization_id <> OLD.organization_id OR NEW.bot_id <> OLD.bot_id OR NEW.document_id <> OLD.document_id
BEGIN SELECT RAISE(ABORT, 'SOURCE_EPOCH_RESET_REFUSED'); END""").execute_if(dialect='sqlite'))
event.listen(lifecycle, 'after_create', DDL("""CREATE TRIGGER canary_source_delete_guard
BEFORE DELETE ON canary_source_lifecycle
BEGIN SELECT RAISE(ABORT, 'SOURCE_EPOCH_RESET_REFUSED'); END""").execute_if(dialect='sqlite'))

nodes = Table('canary_source_nodes', metadata, *cols(SRC),
    Column('node_key',String(64),nullable=False),Column('payload',JSON,nullable=False),
    pk((*SRC,'node_key')),fk(SRC,'canary_source_history',cascade=False))

runs = Table('canary_runs', metadata, *cols(RUN),
    Column('approval', JSON, nullable=False), Column('approval_hash', String(64), nullable=False),
    Column('database_identity', String(64), nullable=False),
    Column('state', String(32), nullable=False), Column('epoch', Integer, nullable=False),
    Column('expires_at', Integer, nullable=False), pk(RUN),
    fk(('database_identity',), 'canary_ownership', cascade=False),
    CheckConstraint("state IN ('OFF','EMBEDDING_STAGING','INDEX_READY','CANARY_READ','COMPARATIVE_EVAL','FAILED','CANCELLED','EXPIRED','STALE')"))

manifests = Table('retrieval_manifests', metadata, *cols(MAN),
    Column('payload', JSON, nullable=False),
    Column('build_snapshot', JSON, nullable=False), Column('build_identity', String(64), nullable=False),
    Column('state', String(32), nullable=False), Column('state_epoch', Integer, nullable=False),
    pk(MAN), fk(RUN, 'canary_runs'),
    CheckConstraint("state IN ('EMBEDDING_STAGING','INDEX_READY','CANARY_READ','COMPARATIVE_EVAL')"),
    UniqueConstraint(*RUN, 'lane', 'generation'),
    CheckConstraint("lane IN ('LEGACY_CONTROL','STRUCTURAL_CANARY')"))

documents = Table('retrieval_manifest_documents', metadata, *cols(DOC),
    Column('pin_hash', String(64), nullable=False), Column('source_fingerprint', String(64), nullable=False),
    Column('source_id', Integer, nullable=False), Column('payload', JSON, nullable=False),
    pk(DOC), fk(MAN, 'retrieval_manifests'), fk(SRC, 'canary_source_history', cascade=False),
    UniqueConstraint(*MAN, 'document_id'))

entries = Table('canary_entries', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('ordinal', Integer, nullable=False),
    Column('text', Text, nullable=False), Column('input_hash', String(64), nullable=False),
    Column('payload', JSON, nullable=False), pk((*DOC, 'entry_id')), fk(DOC, 'retrieval_manifest_documents'),
    UniqueConstraint(*DOC, 'entry_id', 'input_hash'),
    CheckConstraint("lane='STRUCTURAL_CANARY'"), CheckConstraint('ordinal>=0'))

vectors = Table('canary_entry_vectors', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('input_hash', String(64), nullable=False),
    Column('embedding', JSON().with_variant(Vector(768), 'postgresql'), nullable=False),
    Column('vector_hash', String(64), nullable=False),
    Column('vector_attestation', String(48), nullable=False),
    CheckConstraint("vector_attestation='vector-attestation-f32-v1'"),
    Column('embedding_source', String(32), nullable=False),
    Column('provider_receipt', JSON, nullable=False, default=dict),
    pk((*DOC, 'entry_id')), fk((*DOC,'entry_id','input_hash'), 'canary_entries'),
    CheckConstraint("embedding_source IN ('SYNTHETIC_TEST','REAL_PROVIDER')"))

atoms = Table('canary_atoms', metadata, *cols(DOC),
    Column('atom_id', String(64), nullable=False), Column('bundle_id', String(64), nullable=False),
    Column('kind', String(32), nullable=False), Column('canonical_text', Text, nullable=False),
    Column('payload', JSON, nullable=False), Column('payload_hash', String(64), nullable=False),
    Column('route_kind', String(32), nullable=False), Column('route_entry', String(64)),
    pk((*DOC,'atom_id')), fk(DOC,'retrieval_manifest_documents'),
    fk((*DOC,'route_entry'), 'canary_entries', (*DOC,'entry_id'), cascade=False),
    CheckConstraint("lane='STRUCTURAL_CANARY'"),
    CheckConstraint("(route_kind='ENTRY' AND route_entry IS NOT NULL) OR (route_kind='ATOM_ONLY' AND route_entry IS NULL)"))

memberships = Table('canary_entry_atom_memberships', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('atom_id', String(64), nullable=False),
    Column('payload', JSON, nullable=False), pk((*DOC,'entry_id','atom_id')),
    fk((*DOC,'entry_id'), 'canary_entries'), fk((*DOC,'atom_id'), 'canary_atoms'))

spans = Table('canary_entry_atom_spans', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('atom_id', String(64), nullable=False),
    Column('ordinal', Integer, nullable=False), Column('node_key', String(64), nullable=False),
    Column('node_start', Integer, nullable=False), Column('node_end', Integer, nullable=False),
    Column('entry_start', Integer, nullable=False), Column('entry_end', Integer, nullable=False),
    Column('usage', String(16), nullable=False), Column('origin', String(16), nullable=False),
    pk((*DOC,'entry_id','ordinal')), fk((*DOC,'entry_id','atom_id'), 'canary_entry_atom_memberships'),
    fk((*SRC,'node_key'),'canary_source_nodes',cascade=False),
    CheckConstraint('ordinal BETWEEN 0 AND 255 AND node_start>=0 AND node_end>node_start AND entry_start>=0 AND entry_end>entry_start'),
    CheckConstraint('node_end-node_start=entry_end-entry_start'),
    CheckConstraint("usage IN ('body','heading','header','qualifier','context')"),
    CheckConstraint("origin IN ('primary','inherited','overlap')"))

legacy = Table('canary_legacy_members', metadata, *cols(DOC),
    Column('chunk_id', Integer, nullable=False), Column('text', Text, nullable=False),
    Column('input_hash', String(64), nullable=False), Column('payload', JSON, nullable=False),
    Column('embedding', JSON().with_variant(Vector(768), 'postgresql'), nullable=False),
    Column('vector_hash', String(64), nullable=False),
    Column('vector_attestation', String(48), nullable=False),
    CheckConstraint("vector_attestation='vector-attestation-f32-v1'"),
    Column('embedding_source', String(32), nullable=False),
    Column('provider_receipt', JSON, nullable=False, default=dict),
    pk((*DOC,'chunk_id')), fk(DOC, 'retrieval_manifest_documents'),
    CheckConstraint("lane='LEGACY_CONTROL' AND embedding_source IN ('SYNTHETIC_TEST','REAL_PROVIDER')"), CheckConstraint('chunk_id>0'))

work = Table('canary_embedding_work', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('input_hash', String(64), nullable=False),
    Column('state', String(32), nullable=False), Column('attempts', Integer, nullable=False),
    pk((*DOC,'entry_id')), fk((*DOC,'entry_id','input_hash'), 'canary_entries'),
    CheckConstraint("state IN ('pending','succeeded','failed','unknown')"), CheckConstraint('attempts BETWEEN 0 AND 3'))

# Legacy inputs have no structural entry FK. Keep an equally scoped work ledger
# rather than manufacturing structural entries for the control representation.
legacy_work = Table('canary_legacy_embedding_work', metadata, *cols(DOC),
    Column('chunk_id', Integer, nullable=False), Column('input_hash', String(64), nullable=False),
    Column('state', String(32), nullable=False), Column('attempts', Integer, nullable=False),
    pk((*DOC, 'chunk_id')), fk(DOC, 'retrieval_manifest_documents'),
    CheckConstraint("lane='LEGACY_CONTROL'"),
    CheckConstraint("state IN ('pending','succeeded','failed','unknown')"), CheckConstraint('attempts BETWEEN 0 AND 3'))

Index('ix_canary_memberships_reverse', *[memberships.c[k] for k in (*MAN,'document_id','atom_id','entry_id')])
Index('ix_canary_atoms_content_fts_en_v1', text("to_tsvector('english'::regconfig, coalesce(canonical_text, ''))"),
    postgresql_using='gin', _table=atoms).ddl_if(dialect='postgresql')

RUN_TABLES = (runs, manifests, documents, entries, vectors, atoms, memberships, spans, legacy, work, legacy_work)


def postgres_seal_guards():
    """Installed only inside owned schema after explicit approval, never serving DB.

    Payload writes lock the same run row as seal/cancel. Deletes require OFF or
    terminal state, so late staging cannot publish or resurrect a cancelled run.
    """
    body = """CREATE FUNCTION canary_payload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text; g text;
BEGIN
 SELECT state INTO s FROM canary_runs WHERE organization_id=COALESCE(NEW.organization_id,OLD.organization_id)
 AND bot_id=COALESCE(NEW.bot_id,OLD.bot_id) AND run_id=COALESCE(NEW.run_id,OLD.run_id) FOR UPDATE;
 IF TG_OP='DELETE' THEN
   IF s IS NOT NULL AND s NOT IN ('OFF','FAILED','CANCELLED','EXPIRED','STALE') THEN RAISE EXCEPTION 'CANARY_SEALED'; END IF;
   RETURN OLD;
 END IF;
 IF s IS NULL OR s NOT IN ('EMBEDDING_STAGING','INDEX_READY','CANARY_READ','COMPARATIVE_EVAL') THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
 IF TG_TABLE_NAME='retrieval_manifests' THEN
   IF TG_OP='UPDATE' THEN
     IF (to_jsonb(NEW)-'state'-'state_epoch') IS DISTINCT FROM (to_jsonb(OLD)-'state'-'state_epoch')
       OR NEW.state_epoch <> OLD.state_epoch+1
       OR NOT ((OLD.state='EMBEDDING_STAGING' AND NEW.state='INDEX_READY')
         OR (OLD.state='INDEX_READY' AND NEW.state IN ('CANARY_READ','COMPARATIVE_EVAL')))
       THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
   ELSIF NEW.state <> 'EMBEDDING_STAGING' OR NEW.state_epoch <> 0 THEN
     RAISE EXCEPTION 'CANARY_IMMUTABLE';
   END IF;
 ELSE
   SELECT state INTO g FROM retrieval_manifests WHERE organization_id=NEW.organization_id
     AND bot_id=NEW.bot_id AND run_id=NEW.run_id AND lane=NEW.lane AND generation=NEW.generation
     AND manifest_hash=NEW.manifest_hash AND profile_hash=NEW.profile_hash AND policy_hash=NEW.policy_hash;
   IF g IS DISTINCT FROM 'EMBEDDING_STAGING' THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
   IF TG_OP='UPDATE' THEN
     IF TG_TABLE_NAME NOT IN ('canary_embedding_work','canary_legacy_embedding_work') THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
     IF (to_jsonb(NEW)-'state'-'attempts') IS DISTINCT FROM (to_jsonb(OLD)-'state'-'attempts')
       OR NEW.attempts < OLD.attempts
       OR NOT ((OLD.state='pending' AND NEW.state='unknown' AND NEW.attempts=OLD.attempts+1)
         OR (OLD.state='unknown' AND NEW.state IN ('succeeded','failed')))
       THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$"""
    epoch = """CREATE FUNCTION canary_source_epoch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'SOURCE_EPOCH_RESET_REFUSED'; END IF;
 IF (NEW.organization_id,NEW.bot_id,NEW.document_id) IS DISTINCT FROM (OLD.organization_id,OLD.bot_id,OLD.document_id)
    OR NEW.epoch <= OLD.epoch THEN RAISE EXCEPTION 'SOURCE_EPOCH_RESET_REFUSED'; END IF;
 RETURN NEW;
END $$"""
    return (body, *(f'CREATE TRIGGER canary_payload_guard BEFORE INSERT OR UPDATE OR DELETE ON {t.name} '
                   'FOR EACH ROW EXECUTE FUNCTION canary_payload_guard()' for t in RUN_TABLES[1:]),
            epoch, 'CREATE TRIGGER canary_source_epoch_guard BEFORE UPDATE OR DELETE ON canary_source_lifecycle '
                   'FOR EACH ROW EXECUTE FUNCTION canary_source_epoch_guard()')
