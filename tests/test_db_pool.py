"""The API's connection pool, against the disposable database only.

A pooled connection outlives the request that borrowed it, so nothing one request leaves on the
session may reach the next. A starved pool must answer like an unreachable database. Processes that
never open the pool (worker, scheduler, mailer, scripts) keep one direct connection per use, and the
worker's provider lock never rides on a pooled connection."""
import os
import pathlib
import threading
import time
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from ai_core.agents import leases, supervisor
from src.api.main import app
from src.applications import private
from src.db import store
from src.settings import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK_KEY = "hashtextextended('test-db-pool', 0)"


@pytest.fixture(autouse=True)
def disposable_database():
    if os.environ.get('JOBSEARCH_AUTH_TEST') != '1':
        pytest.skip('Requires explicitly enabled disposable PostgreSQL database')
    store.close_pool()
    with store.direct_connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d'] == 'jobsearch_auth_test'
    yield
    store.close_pool()


@pytest.fixture
def pool_of_one(monkeypatch):
    """Settings for a pool of exactly one connection: the next borrower provably gets the same session."""
    config = settings()
    monkeypatch.setattr(config, 'database_pool_min_size', 1)
    monkeypatch.setattr(config, 'database_pool_max_size', 1)
    monkeypatch.setattr(config, 'database_pool_timeout_seconds', 1.0)
    return config


@pytest.fixture
def one_connection(pool_of_one):
    pool = store.open_pool()
    pool.wait(timeout=10)
    yield pool
    store.close_pool()


def backend(c):
    return c.execute('SELECT pg_backend_pid() pid').fetchone()['pid']


def test_the_next_borrower_gets_a_clean_session(one_connection):
    with store.connection() as c:
        pid = backend(c)
        login = c.execute('SELECT current_user AS role').fetchone()['role']
        # A request's owner, transaction-scoped the way private_connection sets it ...
        c.execute("SELECT set_config('jobsearch.user_id', %s, true)", (str(uuid.uuid4()),))
        c.commit()
        # ... then what a careless borrower could leave on the session, returned in autocommit.
        c.autocommit = True
        c.execute("SELECT set_config('jobsearch.user_id', %s, false)", (str(uuid.uuid4()),))
        c.execute('CREATE TEMP TABLE left_behind(x int)')
        c.execute('SELECT pg_advisory_lock(' + LOCK_KEY + ')')
        c.execute('SET ROLE jobsearch_worker')
        assert c.execute('SELECT current_user AS role').fetchone()['role'] == 'jobsearch_worker'
    with store.connection() as c:
        assert backend(c) == pid, 'a pool of one hands back the same session, reset rather than replaced'
        assert c.autocommit is False
        state = c.execute("""SELECT current_setting('jobsearch.user_id', true) AS user_id, current_user AS role,
              (SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()) AS advisory_locks,
              to_regclass('pg_temp.left_behind') AS temporary_table,
              current_setting('application_name') AS application""").fetchone()
    assert state['user_id'] in ('', None)
    assert state['role'] == login
    assert state['advisory_locks'] == 0
    assert state['temporary_table'] is None
    assert state['application'] == 'jobsearch-api'
    with store.direct_connection() as other:
        assert other.execute('SELECT pg_try_advisory_lock(' + LOCK_KEY + ') acquired').fetchone()['acquired']


def test_a_statement_one_borrower_repeats_still_runs_for_the_next(one_connection):
    # psycopg prepares a statement once a connection has run it five times and remembers the name,
    # while the DISCARD ALL of a later reset drops it on the server.
    with store.connection() as c:
        pid = backend(c)
    for _ in range(3):
        with store.connection() as c:
            assert backend(c) == pid
            for _ in range(8):
                assert c.execute('SELECT %s::int AS n', (7,)).fetchone()['n'] == 7


def test_a_starved_pool_answers_like_an_unreachable_database(pool_of_one, monkeypatch):
    with monkeypatch.context() as outage:
        # No lifespan, so no pool, and a database nobody can reach.
        outage.setattr(pool_of_one, 'database_url', 'postgresql://nobody@127.0.0.1:1/unreachable')
        unavailable = TestClient(app).get('/api/health')
    monkeypatch.setattr(pool_of_one, 'database_pool_timeout_seconds', 0.5)
    with TestClient(app) as client:
        pool = store._pool
        assert pool is not None and pool.max_size == 1
        pool.wait(timeout=10)
        with store.connection():
            with pytest.raises(PoolTimeout):
                with store.connection():
                    pytest.fail('borrowed a second connection from a pool of one')
            starved = client.get('/api/health')
        assert client.get('/api/health').status_code == 200
    assert unavailable.status_code == starved.status_code == 503
    assert starved.json() == unavailable.json()


def test_without_the_pool_every_connection_is_direct_and_closed(monkeypatch):
    monkeypatch.setattr(store, 'ConnectionPool', lambda *args, **kwargs: pytest.fail('a pool was created'))
    with store.connection() as c:
        assert c.execute('SELECT 1 AS one').fetchone()['one'] == 1
    assert c.closed
    assert store._pool is None


def test_only_the_api_opens_the_pool():
    callers = sorted(path.relative_to(ROOT).as_posix() for folder in ('src', 'ai_core', 'scripts')
                     for path in (ROOT / folder).rglob('*.py') if 'open_pool(' in path.read_text(encoding='utf-8'))
    assert callers == ['src/api/main.py', 'src/db/store.py']


def test_the_provider_lock_stays_off_the_pool(one_connection):
    with store.direct_connection() as c:
        c.execute('TRUNCATE jobsearch.sources CASCADE')
        for board in ('first', 'second'):
            sid = c.execute("INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Example','ashby',%s,true) RETURNING id",
                            (board,)).fetchone()['id']
            assert supervisor.enqueue(c, sid, 'test')
    with leases.claim('worker-one') as first:
        assert first
        with store.connection() as c:  # the pool's only connection
            holders = c.execute("""SELECT count(*) n FROM pg_locks
                WHERE locktype='advisory' AND granted AND pid<>pg_backend_pid()""").fetchone()['n']
        assert holders == 1, 'the provider lock is held on a connection of its own'
        with leases.claim('worker-two') as second:
            assert second is None, 'one provider still collects one board at a time'
    with leases.claim('worker-three') as third:
        assert third and third['id'] != first['id']


def test_private_connection_refuses_autocommit(monkeypatch):
    @contextmanager
    def autocommit_connection():
        with store.direct_connection() as c:
            c.autocommit = True
            yield c
    monkeypatch.setattr(private, 'connection', autocommit_connection)
    with pytest.raises(RuntimeError, match='autocommit'):
        with private.private_connection(uuid.uuid4()):
            pytest.fail('private work ran without a transaction-scoped owner')


def test_the_api_opens_the_pool_at_startup_and_closes_it_at_shutdown():
    assert store._pool is None
    with TestClient(app) as client:
        pool = store._pool
        assert pool is not None and not pool.closed and pool.name == 'jobsearch-api'
        assert client.get('/api/health').status_code == 200
        pool.wait(timeout=10)
    assert store._pool is None and pool.closed
    assert [t.name for t in threading.enumerate() if t.name.startswith('jobsearch-api-')] == []
    deadline = time.monotonic() + 5
    while True:
        with store.direct_connection() as c:
            remaining = c.execute("""SELECT count(*) n FROM pg_stat_activity
                WHERE application_name='jobsearch-api' AND datname=current_database()""").fetchone()['n']
        if remaining == 0 or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert remaining == 0
