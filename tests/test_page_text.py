"""The shared text store (the owner's 18 September batch, section 5): GET /api/hub/page-text for everyone,
PUT for an administrator, and every refusal in between.

Job Search owns accounts, so it owns this table and these routes; the public edge and the product gateways
forward /__hub/page-text here. Needs the disposable test database, like the other route tests.
"""
import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, current_user
from src.db.store import connection

HEADERS = {'Origin': 'http://localhost:3105'}
KEY = 'jobsearch.matches.heading'


@pytest.fixture()
def client():
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    with connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d'] == 'jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.page_text')
        c.execute('TRUNCATE jobsearch.users CASCADE')
        c.execute('TRUNCATE jobsearch.audit_events RESTART IDENTITY')
        users = {role: c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local',%s,%s) RETURNING *", (role, [role])).fetchone()
                 for role in ('member', 'administrator')}
    with TestClient(app) as t:
        t.users = users
        yield t
    app.dependency_overrides.clear()


def as_role(client, role):
    app.dependency_overrides[current_user] = lambda: client.users[role]


def rows():
    with connection() as c:
        return c.execute('SELECT * FROM jobsearch.page_text ORDER BY key').fetchall()


def audit():
    with connection() as c:
        return c.execute("SELECT * FROM jobsearch.audit_events WHERE action='page_text.update' ORDER BY id").fetchall()


def test_migration_022_is_recorded():
    sql = (Path(__file__).resolve().parents[1] / 'src/db/022_page_text.sql').read_text()
    assert 'jobsearch_app' in sql and 'VALUES(22)' in sql
    with connection() as c:
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=22').fetchone()
        columns = {r['column_name']: r['data_type'] for r in c.execute(
            "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='jobsearch' AND table_name='page_text'").fetchall()}
    assert columns == {'key': 'text', 'value': 'text', 'updated_by': 'text', 'updated_at_utc': 'bigint'}


def test_anyone_may_read_the_words_and_they_are_never_cached(client):
    app.dependency_overrides.clear()  # nobody is signed in
    first = client.get('/api/hub/page-text')
    assert first.status_code == 200 and first.json() == {}
    assert first.headers['cache-control'] == 'no-store'
    as_role(client, 'administrator')
    assert client.put('/api/hub/page-text', json={KEY: 'Open roles'}, headers=HEADERS).status_code == 200
    app.dependency_overrides.clear()
    again = client.get('/api/hub/page-text')
    assert again.json() == {KEY: 'Open roles'} and again.headers['cache-control'] == 'no-store'


def test_an_administrator_writes_a_batch_and_the_write_is_attributed(client):
    as_role(client, 'administrator')
    before = int(time.time())
    body = client.put('/api/hub/page-text', json={KEY: 'Open roles', 'footer.copyright': '© 2026 Bagala.ai'}, headers=HEADERS)
    assert body.status_code == 200 and body.json()['updated'] == 2
    stored = {row['key']: row for row in rows()}
    assert set(stored) == {KEY, 'footer.copyright'}
    for row in stored.values():
        assert row['updated_by'] == str(client.users['administrator']['id'])
        assert before <= row['updated_at_utc'] <= int(time.time()) + 1
    # the audit trail names the keys and what happened to them, never the words
    [event] = audit()
    assert event['actor'] == str(client.users['administrator']['id'])
    assert sorted(event['details']['set']) == ['footer.copyright', KEY] and event['details']['cleared'] == []
    assert 'Open roles' not in str(event)
    # a second write replaces the value and keeps one row
    assert client.put('/api/hub/page-text', json={KEY: 'Roles for you'}, headers=HEADERS).status_code == 200
    assert {row['key']: row['value'] for row in rows()}[KEY] == 'Roles for you'
    assert len(rows()) == 2


def test_an_empty_value_removes_the_override_so_a_page_returns_to_its_own_words(client):
    as_role(client, 'administrator')
    client.put('/api/hub/page-text', json={KEY: 'Open roles'}, headers=HEADERS)
    assert client.put('/api/hub/page-text', json={KEY: '   '}, headers=HEADERS).json()['updated'] == 1
    assert rows() == []
    assert client.get('/api/hub/page-text').json() == {}
    [_, cleared] = audit()
    assert cleared['details']['cleared'] == [KEY] and cleared['details']['set'] == []


def test_only_an_administrator_may_write(client):
    as_role(client, 'member')
    assert client.put('/api/hub/page-text', json={KEY: 'Open roles'}, headers=HEADERS).status_code == 403
    app.dependency_overrides.clear()
    assert client.put('/api/hub/page-text', json={KEY: 'Open roles'}, headers=HEADERS).status_code == 401
    assert rows() == []


def test_a_write_from_another_origin_is_refused_like_every_other_write(client):
    as_role(client, 'administrator')
    assert client.put('/api/hub/page-text', json={KEY: 'Open roles'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.put('/api/hub/page-text', json={KEY: 'Open roles'}).status_code == 403, 'no Origin at all is refused too'
    assert rows() == []


@pytest.mark.parametrize('batch', [
    {'not a key': 'words'},                       # not <page>.<slug>
    {'nodot': 'words'},
    {'Upper.Case': 'words'},
    {'a.b': 'x' * 2001},                          # over 2000 characters
    {'a.b': 'one\x00two'},                        # a control character
    {'a.b': '<b>bold</b>'},                       # markup
    {'a.b': '</p>'},
    {'a.b': '<!-- hidden -->'},
    {'a.b': 7},                                   # not a string
    {},                                           # nothing to write
])
def test_a_value_that_is_not_plain_text_is_refused_and_nothing_is_written(client, batch):
    as_role(client, 'administrator')
    assert client.put('/api/hub/page-text', json=batch, headers=HEADERS).status_code == 422
    assert rows() == []


def test_one_bad_value_refuses_the_whole_batch(client):
    as_role(client, 'administrator')
    answer = client.put('/api/hub/page-text', json={KEY: 'Open roles', 'a.b': '<script>'}, headers=HEADERS)
    assert answer.status_code == 422 and 'a.b' in answer.json()['detail']
    assert '<script>' not in answer.text, 'the refusal names the key, never the value'
    assert rows() == []


def test_a_batch_is_small(client):
    as_role(client, 'administrator')
    many = {'a.k' + str(n): 'words' for n in range(201)}
    assert client.put('/api/hub/page-text', json=many, headers=HEADERS).status_code == 422
    assert rows() == []
    assert client.put('/api/hub/page-text', json={'a.k' + str(n): 'words' for n in range(200)}, headers=HEADERS).status_code == 200
    assert len(rows()) == 200


def test_a_value_of_exactly_2000_characters_is_kept_whole(client):
    as_role(client, 'administrator')
    words = 'a' * 2000
    assert client.put('/api/hub/page-text', json={'a.b': words}, headers=HEADERS).status_code == 200
    assert client.get('/api/hub/page-text').json()['a.b'] == words


@pytest.mark.parametrize('key,value', [
    ('nodot', 'words'), ('Upper.Case', 'words'), ('.leading', 'words'), ('trailing.', 'words'),
    ('a.b', ''), ('a.b', 'x' * 2001),
])
def test_the_table_itself_refuses_what_the_route_would_refuse(client, key, value):
    """The route's rules are the table's as well, so nothing else reaching this database can break them."""
    with pytest.raises(Exception):
        with connection() as c:
            c.execute('INSERT INTO jobsearch.page_text(key,value) VALUES(%s,%s)', (key, value))
    assert rows() == []
    sql = (Path(__file__).resolve().parents[1] / 'src/db/022_page_text.sql').read_text()
    assert re.search(r"key text PRIMARY KEY CHECK\(key ~ '\^\[a-z0-9\]", sql)
    assert 'char_length(value) BETWEEN 1 AND 2000' in sql
