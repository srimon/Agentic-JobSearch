from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from src.settings import settings


@contextmanager
def connection():
    with psycopg.connect(settings().database_url, row_factory=dict_row, connect_timeout=5) as conn:
        yield conn


def audit(conn, actor, action, resource='', outcome='allowed', details=None):
    conn.execute('INSERT INTO jobsearch.audit_events(actor,action,resource,outcome,details) VALUES(%s,%s,%s,%s,%s)',
                 (actor, action, str(resource), outcome, Jsonb(details or {})))
