"""Explicit disposable PostgreSQL boundary for Phase O integration tests only.

No dotenv, application settings, provider, default DSN, or automatic retry.
The independently supplied fingerprint must match the explicitly approved URL.
Only a newly created, marked schema can be removed. Exceptions are never printed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
from time import time, perf_counter
import uuid

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from database import canary_schema as s
from services.canary_contracts import Approval, CanaryError
from services.canary_database_guard import DisposableTarget, validate_target
from services.structural_chunking import digest
from scripts.phase2_disposable_postgres import APPLICATION_TABLES


ENV_KEYS = ('CANARY_DATABASE_URL', 'CANARY_TARGET_FINGERPRINT',
            'CANARY_ENVIRONMENT', 'CANARY_APPROVAL_REFERENCE')
NAMESPACE = re.compile(r'canary_stagea_[0-9a-f]{32}')


@dataclass(repr=False)
class Settings:
    url: object
    approval: Approval
    namespace: str


def settings(environ=None):
    env = os.environ if environ is None else environ
    if not env.get('CANARY_DATABASE_URL'):
        raise CanaryError('HOLD_EXPLICIT_CANARY_TARGET_REQUIRED')
    try:
        if env.get('CANARY_ENVIRONMENT') != 'disposable_test':
            raise ValueError()
        fingerprint = env['CANARY_TARGET_FINGERPRINT']
        reference = env['CANARY_APPROVAL_REFERENCE']
        if not re.fullmatch(r'[a-zA-Z0-9_-]{4,128}', reference):
            raise ValueError()
        url = make_url(env['CANARY_DATABASE_URL'])
        if (not all((url.username, url.password, url.host, url.port, url.database))
                or not re.fullmatch(r'[a-zA-Z0-9.:-]+', url.host)
                or not re.fullmatch(r'[a-zA-Z0-9_-]+', url.database)
                or not 1 <= url.port <= 65535
                or re.search(r'(^|[_-])(prod|production|customer|chatbot|supabase)([_-]|$)', url.database, re.I)
                or set(url.query) - {'sslmode'}
                or (url.query and url.query['sslmode'] not in
                    ('disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'))):
            raise ValueError()
        namespace = 'canary_stagea_' + uuid.uuid4().hex
        now = int(time())
        approved = Approval(environment='disposable_test', database_identity=fingerprint,
            ownership_marker=namespace, operator_reference=reference,
            organization_id=70001, bot_id=70002, created_at=now, expires_at=now + 7200)
        target = DisposableTarget(host_database_fingerprint=fingerprint,
            ownership_marker=namespace, approval_reference=reference)
        validate_target(env['CANARY_DATABASE_URL'], target, approved)
        return Settings(url.set(drivername='postgresql+psycopg2'), approved, namespace)
    except Exception:
        raise CanaryError('EXPLICIT_DISPOSABLE_TARGET_REFUSED') from None


def safe_failure(exc):
    """Never serialize DBAPI messages, statement parameters, URLs or locals."""
    result = {'exception_class': type(exc).__name__}
    original = getattr(exc, 'orig', None)
    code = getattr(original, 'pgcode', None)
    if code and re.fullmatch(r'[A-Z0-9]{5}', code):
        result['sqlstate'] = code
    if isinstance(exc, CanaryError) and re.fullmatch(r'[A-Z0-9_]+', str(exc)):
        result['guard'] = str(exc)
    frames = []
    tb = exc.__traceback__
    while tb:
        name = tb.tb_frame.f_code.co_filename.replace('\\', '/')
        if '/backend/' in name:
            frames.append({'file': name.split('/backend/', 1)[1],
                           'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
        tb = tb.tb_next
    result['frames'] = frames
    return result


def catalog_snapshot(conn, excluded):
    """Catalog identity/definitions only; never inspect unrelated row contents."""
    return tuple(tuple(row) for row in conn.execute(text("""
        SELECT kind, namespace, name, identity, definition FROM (
          SELECT 'namespace' kind, n.nspname namespace, n.nspname name,
                 n.oid::text identity, n.nspowner::text definition FROM pg_namespace n
          UNION ALL
          SELECT 'relation', n.nspname, c.relname, c.oid::text,
                 c.relkind::text || ':' || coalesce(pg_get_indexdef(i.indexrelid),'')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_index i ON i.indexrelid=c.oid
          UNION ALL
          SELECT 'function', n.nspname, p.proname, p.oid::text,
                 CASE WHEN p.prokind IN ('f','p') THEN pg_get_functiondef(p.oid)
                      ELSE pg_get_function_identity_arguments(p.oid) END
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          UNION ALL
          SELECT 'type', n.nspname, t.typname, t.oid::text, t.typtype::text
            FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
          UNION ALL
          SELECT 'trigger', n.nspname, t.tgname, t.oid::text, pg_get_triggerdef(t.oid)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
          UNION ALL
          SELECT 'extension', n.nspname, e.extname, e.oid::text, e.extversion
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
          UNION ALL
          SELECT 'constraint', n.nspname, c.conname, c.oid::text, pg_get_constraintdef(c.oid)
            FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        ) objects WHERE namespace <> :excluded AND namespace <> 'information_schema'
          AND namespace NOT LIKE 'pg\\_%' ESCAPE '\\'
        ORDER BY kind,namespace,name,identity
        """), {'excluded': excluded}))


class DisposableCanary:
    def __init__(self, config):
        self.config = config
        self.engine = None
        self.created = False
        self.owned = ()
        self.owned_catalog = ()
        self.before = ()
        self.vector_schema = None
        self.marker_identity = None
        self.schema_identity = None
        self.facts = {}

    def open(self):
        self.engine = create_engine(self.config.url, poolclass=NullPool,
            echo=False, hide_parameters=True, connect_args={'connect_timeout': 8,
                'options': '-c statement_timeout=15000 -c lock_timeout=3000'})
        with self.engine.begin() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            facts = conn.execute(text("""SELECT version(), current_setting('server_version_num'),
                current_setting('server_encoding'), current_setting('TimeZone'),
                current_setting('search_path'), current_schema()""")).one()
            if int(facts[1]) < 140000:
                raise CanaryError('UNSUPPORTED_POSTGRESQL_VERSION')
            self.facts = dict(server_version=facts[0], server_version_num=int(facts[1]),
                encoding=facts[2], timezone=facts[3], search_path=facts[4], current_schema=facts[5],
                namespace=self.config.namespace, host_fingerprint=digest(self.config.url.host.lower()),
                database_fingerprint=digest(self.config.url.database),
                target_fingerprint=self.config.approval.database_identity,
                approval_reference=self.config.approval.operator_reference)
            extension = conn.execute(text("""SELECT e.extversion,n.nspname
                FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                WHERE e.extname='vector'""")).one_or_none()
            available = conn.execute(text("SELECT default_version FROM pg_available_extensions WHERE name='vector'")).scalar_one_or_none()
            self.facts.update(vector_installed=extension is not None, available_vector_version=available)
            if not extension:
                raise CanaryError('PGVECTOR_EXTENSION_REQUIRED')
            if not re.fullmatch(r'[a-z_][a-z0-9_]*', extension[1]) or extension[1].startswith('pg_'):
                raise CanaryError('VECTOR_NAMESPACE_REFUSED')
            self.vector_schema = extension[1]
            self.before = catalog_snapshot(conn, self.config.namespace)
            if APPLICATION_TABLES.intersection(row[2] for row in self.before if row[0] == 'relation'):
                raise CanaryError('APPLICATION_SCHEMA_REFUSED')
            if any(row[0] == 'namespace' and row[1].startswith(('canary_stagea_', 'phase2_test_')) for row in self.before):
                raise CanaryError('STALE_DISPOSABLE_NAMESPACE_REFUSED')
            self.facts.update(pgvector_version=extension[0], vector_namespace=extension[1],
                unrelated_catalog_count=len(self.before), unrelated_catalog_hash=digest(self.before))
        return self.facts

    def configure(self, conn):
        if not NAMESPACE.fullmatch(self.config.namespace) or not self.vector_schema:
            raise CanaryError('CANARY_NAMESPACE_REFUSED')
        # Both identifiers are generated/strictly validated, never raw URL input.
        conn.execute(text(f'SET LOCAL search_path TO "{self.config.namespace}", "{self.vector_schema}", pg_catalog'))

    @contextmanager
    def transaction(self):
        with self.engine.begin() as conn:
            self.configure(conn)
            yield conn

    def relations(self, conn):
        return tuple(tuple(r) for r in conn.execute(text("""SELECT c.relname,c.oid,c.relkind
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=:schema ORDER BY c.relname"""), {'schema': self.config.namespace}))

    def bootstrap(self):
        ns = self.config.namespace
        if not NAMESPACE.fullmatch(ns):
            raise CanaryError('CANARY_NAMESPACE_REFUSED')
        with self.engine.begin() as conn:
            if catalog_snapshot(conn, ns) != self.before:
                raise CanaryError('UNRELATED_CATALOG_CHANGED')
            if conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:name'), {'name': ns}).first():
                raise CanaryError('NAMESPACE_ALREADY_EXISTS')
            conn.execute(text(f'CREATE SCHEMA "{ns}"'))
            self.configure(conn)
            s.marker.create(conn, checkfirst=False)
            a = self.config.approval
            conn.execute(insert(s.marker).values(database_identity=a.database_identity,
                marker=a.ownership_marker, environment=a.environment))
            self.schema_identity = tuple(conn.execute(text('SELECT oid,nspowner FROM pg_namespace WHERE nspname=:name'), {'name': ns}).one())
            self.owned = self.relations(conn)
            self.marker_identity = next(r for r in self.owned if r[0] == s.marker.name)
            self.owned_catalog = tuple(r for r in catalog_snapshot(conn, '') if r[1] == ns)
        self.created = True

    def record_owned(self, conn):
        """Call only inside our successful migration transaction, never on cleanup."""
        objects = self.relations(conn)
        tables = {r[0] for r in objects if r[2] == 'r'}
        if not tables.issubset(s.metadata.tables):
            raise CanaryError('UNKNOWN_OWNED_TABLE')
        self.owned = objects
        self.owned_catalog = tuple(r for r in catalog_snapshot(conn, '') if r[1] == self.config.namespace)

    def cleanup(self):
        started = perf_counter()
        if not self.created:
            return {'owned_schema_created': False}
        ns = self.config.namespace
        with self.transaction() as conn:
            identity = conn.execute(text('SELECT oid,nspowner FROM pg_namespace WHERE nspname=:name'), {'name': ns}).one_or_none()
            if identity is None or tuple(identity) != self.schema_identity:
                raise CanaryError('SCHEMA_OWNERSHIP_CHANGED')
            objects = self.relations(conn)
            if objects != self.owned or self.marker_identity not in objects:
                raise CanaryError('UNKNOWN_OR_REPLACED_SCHEMA_OBJECT')
            if tuple(r for r in catalog_snapshot(conn, '') if r[1] == ns) != self.owned_catalog:
                raise CanaryError('UNKNOWN_OR_REPLACED_SCHEMA_OBJECT')
            a = self.config.approval
            marker = conn.execute(select(s.marker)).mappings().all()
            if [dict(r) for r in marker] != [dict(database_identity=a.database_identity,
                    marker=a.ownership_marker, environment=a.environment)]:
                raise CanaryError('CANARY_OWNERSHIP_REFUSED')
            if catalog_snapshot(conn, ns) != self.before:
                raise CanaryError('UNRELATED_CATALOG_CHANGED')
            # Narrow namespace is generated locally and marker/OIDs attested above.
            conn.execute(text(f'DROP SCHEMA "{ns}" CASCADE'))
        with self.engine.begin() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            if conn.execute(text('SELECT 1 FROM pg_namespace WHERE nspname=:name'), {'name': ns}).first():
                raise CanaryError('SCHEMA_CLEANUP_INCOMPLETE')
            after = catalog_snapshot(conn, ns)
            if after != self.before:
                raise CanaryError('UNRELATED_CATALOG_CHANGED')
        self.created = False
        return {'schema_removed': True, 'marker_tables_indexes_removed': True,
                'unrelated_catalog_unchanged': True, 'catalog_hash': digest(after),
                'cleanup_ms': (perf_counter() - started) * 1000}

    def close(self):
        if self.engine is not None:
            self.engine.dispose()
        # Drop in-memory references and inherited process values, never print them.
        self.config.url = None
        for key in ENV_KEYS:
            os.environ.pop(key, None)
