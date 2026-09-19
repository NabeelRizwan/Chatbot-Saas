"""Exclusive wall-time buckets and SQL counts, without SQL text/parameters."""
from contextlib import contextmanager
from time import perf_counter
from sqlalchemy import event

CATEGORIES = ('source_reconstruction','manifest_preparation','entry_atom_staging',
    'membership_span_staging','provider_wait','vector_persistence_readback',
    'work_ledger','seal','query_evaluation','cleanup','other')


class Timing:
    def __init__(self):
        self.current='other';self.last=perf_counter()
        self.ms=dict.fromkeys(CATEGORIES,0.0)
        self.sql=dict.fromkeys(CATEGORIES,0)
        self.parameter_sets=dict.fromkeys(CATEGORIES,0)

    def tick(self):
        now=perf_counter();self.ms[self.current]+=(now-self.last)*1000;self.last=now

    @contextmanager
    def stage(self,name):
        if name not in self.ms:raise ValueError('UNKNOWN_TIMING_BUCKET')
        self.tick();old=self.current;self.current=name
        try:yield
        finally:self.tick();self.current=old

    def attach(self,engine):
        @event.listens_for(engine,'before_cursor_execute')
        def count(conn,cursor,statement,parameters,context,executemany):
            self.sql[self.current]+=1
            self.parameter_sets[self.current]+=len(parameters) if executemany else 1

    def summary(self):
        self.tick()
        return dict(exclusive_ms=dict(self.ms),sql_statements=dict(self.sql),
            dbapi_parameter_sets=dict(self.parameter_sets),
            counting='DBAPI executions/parameter sets; not a packet-level network trace')
