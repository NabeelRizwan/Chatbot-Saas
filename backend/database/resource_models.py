"""Catalog identity records, never factual answer evidence."""
from database.connection import Base
from database.resource_schema_v1 import define_tables

_state, _resource, _term, _link = define_tables(Base.metadata)


class ResourceCatalogState(Base):
    __table__ = _state


class KnowledgeResource(Base):
    __table__ = _resource


class KnowledgeResourceTerm(Base):
    __table__ = _term


class KnowledgeResourceDocument(Base):
    __table__ = _link
