"""Additive isolated schema; NOT registered with application metadata/Alembic.

Only the explicit internal disposable runner may create these relations. Source
history has no run parent: deleting a run cannot cascade into source history.
PostgreSQL vector/GIN SQL is compiled offline; SQLite is a constraints test double.
"""
from sqlalchemy import (MetaData, Table, Column, Integer, String, Text, Float, JSON,
    ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint, CheckConstraint,
    Index, text)
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
    Column('payload', JSON, nullable=False), pk(MAN), fk(RUN, 'canary_runs'),
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
    pk((*DOC, 'entry_id')), fk((*DOC,'entry_id','input_hash'), 'canary_entries'),
    CheckConstraint("embedding_source='SYNTHETIC_TEST'"))

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
    pk((*DOC,'chunk_id')), fk(DOC, 'retrieval_manifest_documents'),
    CheckConstraint("lane='LEGACY_CONTROL' AND embedding_source='SYNTHETIC_TEST'"), CheckConstraint('chunk_id>0'))

work = Table('canary_embedding_work', metadata, *cols(DOC),
    Column('entry_id', String(64), nullable=False), Column('input_hash', String(64), nullable=False),
    Column('state', String(32), nullable=False), Column('attempts', Integer, nullable=False),
    pk((*DOC,'entry_id')), fk((*DOC,'entry_id','input_hash'), 'canary_entries'),
    CheckConstraint("state IN ('pending','succeeded','failed')"), CheckConstraint('attempts BETWEEN 0 AND 1'))

Index('ix_canary_memberships_reverse', *[memberships.c[k] for k in (*MAN,'document_id','atom_id','entry_id')])
Index('ix_canary_atoms_content_fts_en_v1', text("to_tsvector('english'::regconfig, coalesce(canonical_text, ''))"),
    postgresql_using='gin', _table=atoms).ddl_if(dialect='postgresql')

RUN_TABLES = (runs, manifests, documents, entries, vectors, atoms, memberships, spans, legacy, work)


def postgres_seal_guards():
    """Installed only inside owned schema after explicit approval, never serving DB.

    Payload writes lock the same run row as seal/cancel. Deletes require OFF or
    terminal state, so late staging cannot publish or resurrect a cancelled run.
    """
    body = """CREATE FUNCTION canary_payload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
 SELECT state INTO s FROM canary_runs WHERE organization_id=COALESCE(NEW.organization_id,OLD.organization_id)
 AND bot_id=COALESCE(NEW.bot_id,OLD.bot_id) AND run_id=COALESCE(NEW.run_id,OLD.run_id) FOR UPDATE;
 IF TG_OP='DELETE' THEN
   IF s IS NOT NULL AND s NOT IN ('OFF','FAILED','CANCELLED','EXPIRED','STALE') THEN RAISE EXCEPTION 'CANARY_SEALED'; END IF;
   RETURN OLD;
 END IF;
 IF TG_OP='UPDATE' OR s IS DISTINCT FROM 'EMBEDDING_STAGING' THEN RAISE EXCEPTION 'CANARY_IMMUTABLE'; END IF;
 RETURN NEW;
END $$"""
    return (body, *(f'CREATE TRIGGER canary_payload_guard BEFORE INSERT OR UPDATE OR DELETE ON {t.name} '
                   'FOR EACH ROW EXECUTE FUNCTION canary_payload_guard()' for t in RUN_TABLES[1:]))
