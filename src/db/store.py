"""PostgreSQL access. Callers write `with connection() as conn:`: the block's work is committed when
it succeeds and rolled back when it raises, and rows come back as dicts.

The API process opens a pool at startup (open_pool, from the lifespan in src/api/main.py), so that
one to three API copies share a bounded number of connections. Nothing else opens it: the worker,
scheduler, mailer and scripts get a fresh connection from every connection(), closed when the block
ends, as before the pool existed.

A pooled connection outlives the request that borrowed it, so reset_connection() clears the session
on every return. State that has to end with its connection - a session advisory lock, a role set for
a whole connection, an autocommit gate - belongs on direct_connection(), which is never pooled."""
import threading
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from src.settings import settings

APPLICATION_NAME = 'jobsearch-api'
_pool = None
_pool_lock = threading.Lock()


def reset_connection(conn):
    """Give the next borrower a clean session. psycopg_pool calls this on every return.

    DISCARD ALL ends what a request can leave on the server: settings such as jobsearch.user_id, a
    SET ROLE, session advisory locks, temporary tables, prepared statements, cursors and LISTEN. It
    cannot run inside a transaction. The client-side options after it are the ones it cannot see."""
    conn.autocommit = True
    conn.execute('DISCARD ALL')
    conn.autocommit = False
    conn.read_only = None
    conn.isolation_level = None
    conn.deferrable = None
    conn.row_factory = dict_row
    conn.prepare_threshold = None


def open_pool():
    """Open this process's pool; only the API calls it, once, at startup. It does not wait for the
    database: while PostgreSQL is unreachable the pool keeps connecting in the background and
    requests get the database-unavailable answer."""
    global _pool
    with _pool_lock:
        if _pool is None:
            config = settings()
            pool = ConnectionPool(
                config.database_url, open=False, name=APPLICATION_NAME,
                min_size=config.database_pool_min_size, max_size=config.database_pool_max_size,
                timeout=config.database_pool_timeout_seconds, max_waiting=config.database_pool_max_waiting,
                max_lifetime=config.database_pool_max_lifetime_seconds, max_idle=config.database_pool_max_idle_seconds,
                check=ConnectionPool.check_connection, reset=reset_connection,
                # prepare_threshold=None: psycopg prepares a statement once one connection has run it five
                # times and keeps its name, but it can miss the DISCARD ALL of a later reset, and the next
                # borrower would then be sent to a statement the server has dropped (tests/test_db_pool.py).
                kwargs={'row_factory': dict_row, 'connect_timeout': 5, 'application_name': APPLICATION_NAME,
                        'prepare_threshold': None})
            pool.open(wait=False)
            _pool = pool
        return _pool


def close_pool(timeout=5.0):
    """Close the pool at shutdown. Idle connections close now and borrowed ones when they come back;
    connection() opens direct connections again afterwards."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close(timeout=timeout)


@contextmanager
def direct_connection():
    """A connection of its own, never taken from the pool and closed when the block ends."""
    with psycopg.connect(settings().database_url, row_factory=dict_row, connect_timeout=5) as conn:
        yield conn


@contextmanager
def connection():
    """Borrowed from the pool once the API has opened it, otherwise a direct connection. Waiting
    longer than the pool timeout raises psycopg_pool.PoolTimeout, an OperationalError like an
    unreachable database, and the API answers both with the same 503."""
    pool = _pool
    if pool is None:
        with direct_connection() as conn:
            yield conn
    else:
        with pool.connection(timeout=settings().database_pool_timeout_seconds) as conn:
            yield conn


def audit(conn, actor, action, resource='', outcome='allowed', details=None):
    conn.execute('INSERT INTO jobsearch.audit_events(actor,action,resource,outcome,details) VALUES(%s,%s,%s,%s,%s)',
                 (actor, action, str(resource), outcome, Jsonb(details or {})))
