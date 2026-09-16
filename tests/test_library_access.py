"""The Library gateway: reading, Logs and the Explanatory Tool for every verified account, everything else
administrators, 50 questions a day - on both of its addresses, the root shape (library.bagala.ai, localhost:3001)
and the short path on the shared host (bagala.ai/library/)."""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from src.api.main import app, current_user
from src.api import hub_access, library_policy
from src.db.store import connection
from src.settings import settings

ORIGIN = 'http://localhost:3001'
READER_GETS = ('/', '/reader', '/reader/', '/reader?_rsc=abc', '//reader', '/_next/static/chunks/app/reader/page-1a2b.js',
               '/_next/static/css/app.css', '/_next/static/media/font-latin.woff2', '/favicon.ico', '/icon.svg?8f3e',
               '/api/config', '/__hub/session', '/api?op=books&limit=500', '/api/system/book?namespace=pride-and-prejudice',
               '/api/system/character?namespace=pride-and-prejudice&name=Elizabeth%20Bennet',
               # The member views of Logs and the Explanatory Tool: page routes only. Both are drawn from the answer
               # already in the browser, so neither adds a call - which is why the run log, any run's plan and the
               # review endpoint stay below, in ADMIN_GETS and ADMIN_POSTS.
               '/reader/logs', '/reader/logs/', '/reader/logs?_rsc=abc', '/reader/explain', '/reader/explain?_rsc=abc')
QUESTION = '/api?op=ask'
ADMIN_GETS = ('/reader/agent', '/reader/rag', '/reader/architecture', '/reader/observability',
              '/reader/vectordb', '/reader/operations', '/console', '/dashboard/', '/collections/mbk_books',
              '/api/monitoring/grafana/d/library', '/api/monitoring/phoenix', '/api/system/status', '/api/system/data-quality',
              '/api/system/recent_runs', '/api/system/recent_runs?limit=5', '/api/system/namespaces',
              '/api/system/explain?trace_id=1', '/api/system/explain?run_id=4211', '/api/system/explain/review',
              '/api?op=health', '/api?op=mcp-servers', '/api?op=memories&namespace=x', '/api?op=mcp-health', '/api',
              '/api?op=books&op=ask', '/healthz', '/reader/unknown', '/reader/logs/raw', '/reader/explain/plan',
              '/Reader', '/api/system/book/../status', '/unknown/path')
ADMIN_POSTS = ('/api?op=teach', '/api?op=mcp-rag-retrieve', '/api/system/cache/reload?warm=true', '/api/system/explain/review',
               '/api?op=ask&op=teach', '/api/system/character', '/reader', '/reader/logs', '/reader/explain',
               '/collections/mbk_books/points/search')
TRAVERSAL = ('/reader/../api/system/status', '/reader/%2e%2e/api/system/status', '/reader/%252e%252e/x', '/_next/..%2fapi',
             '/reader/./agent', '/reader\\..\\api', 'reader', 'http://evil.example/reader', '/reader%00')


def authorize(client, uri, method='GET', origin=ORIGIN):
    headers = {'x-original-method': method, 'x-original-uri': uri}
    if origin: headers['x-original-origin'] = origin
    return client.get('/api/hub/library-authorize', headers=headers)


def as_user(roles, **extra):
    user = {'id': 'u-' + '-'.join(roles), 'roles': roles, 'active': True, 'email': None, 'email_verified_at': None, **extra}
    app.dependency_overrides[current_user] = lambda: user
    return user


@pytest.fixture()
def fake_db(monkeypatch):
    records = []
    @contextmanager
    def conn(): yield object()
    monkeypatch.setattr(hub_access, 'connection', conn)
    monkeypatch.setattr(hub_access, 'audit', lambda *a, **kw: records.append((a, kw)))
    monkeypatch.setattr(hub_access, 'daily_count', lambda *a: 1)
    try:
        with TestClient(app) as c:
            yield c, records
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('roles', [['viewer'], ['member'], ['operator'], ['member', 'operator']])
def test_every_signed_in_role_reaches_the_reader_and_nothing_else(fake_db, roles):
    client, _ = fake_db
    as_user(roles)
    for uri in READER_GETS:
        assert authorize(client, uri).status_code == 204, uri
        assert authorize(client, uri, 'HEAD').status_code == 204, uri
    assert authorize(client, QUESTION, 'POST').status_code == 204
    for uri in ADMIN_GETS:
        response = authorize(client, uri)
        # 403, not 401: a signed-in visitor sees the no-access page instead of being sent back to sign-in.
        assert response.status_code == 403, uri
        assert 'x-hub-limit' not in response.headers, uri
    for uri in ADMIN_POSTS:
        assert authorize(client, uri, 'POST').status_code == 403, uri
    # A call without a URI (an unknown path) is administrator-only.
    assert client.get('/api/hub/library-authorize').status_code == 403


def test_administrators_reach_every_path(fake_db):
    client, records = fake_db
    as_user(['administrator'])
    for uri in READER_GETS + ADMIN_GETS:
        if '..' in uri: continue
        assert authorize(client, uri).status_code == 204, uri
    for uri in ADMIN_POSTS + (QUESTION,):
        response = authorize(client, uri, 'POST')
        assert response.status_code == 204 and response.headers['x-hub-user'] == 'u-administrator', uri
    assert client.get('/api/hub/library-authorize').status_code == 204
    assert all(kw == {'details': {'method': 'POST'}} for _, kw in records)


def test_logs_and_the_explanatory_tool_are_pages_a_member_may_open_not_calls_they_may_make(fake_db):
    """The two member views read the answer the browser already has, so the pages open and nothing else does."""
    client, _ = fake_db
    as_user(['member'])
    for uri in ('/reader/logs', '/reader/explain'):
        assert authorize(client, uri).status_code == 204, uri
    for uri in ('/api/system/recent_runs?limit=5',      # everyone's last five questions
                '/api/system/explain?run_id=4211',      # any run, by a guessable id
                '/api/system/explain?trace_id=a1b2c3',
                '/api/monitoring/phoenix'):             # the recorded prompts and model calls
        assert authorize(client, uri).status_code == 403, uri
    assert authorize(client, '/api/system/explain/review', 'POST').status_code == 403


@pytest.mark.parametrize('roles,forwarded', [
    (['member'], 'member'),
    (['viewer', 'operator'], 'operator,viewer'),
    (['administrator'], 'administrator'),
    (['member', 'administrator'], 'administrator,member'),
    # A role the gateway could not put in a header safely is left out rather than folded into one.
    (['member', 'bad role', 'a,b', 'x\r\nX-Hub-Roles: administrator'], 'member'),
])
def test_the_answer_names_the_roles_for_the_gateway_to_forward(fake_db, roles, forwarded):
    # The Library API strips another reader's question, the exception text and the prompt out of an answer unless
    # this header says administrator; the gateway copies it onto the proxied request, overwriting the visitor's own.
    client, _ = fake_db
    as_user(roles)
    response = authorize(client, '/reader')
    assert response.status_code == 204 and response.headers['x-hub-roles'] == forwarded
    assert ('administrator' in forwarded.split(',')) is ('administrator' in roles)


def test_a_refusal_hands_out_no_roles(fake_db):
    client, _ = fake_db
    as_user(['member'])
    assert 'x-hub-roles' not in authorize(client, '/reader/operations').headers


@pytest.mark.parametrize('roles', [['member'], ['administrator']])
def test_traversal_and_malformed_uris_are_refused_for_everyone(fake_db, roles):
    client, _ = fake_db
    as_user(roles)
    for uri in TRAVERSAL:
        assert authorize(client, uri).status_code == 403, uri
    assert library_policy.normalize('/reader//x/?a=1') == ('/reader/x', 'a=1')
    assert library_policy.classify('GET', '/reader/%2e%2e/api') == library_policy.INVALID


PREFIX = '/library'


def prefixed(uri):
    """The same request made on the short path: https://bagala.ai/library/... as the gateway forwards it."""
    return PREFIX + uri if uri.startswith('/') else uri


def test_the_short_path_is_judged_exactly_as_the_root_shape():
    """Every request the root shape makes, made under /library, gets the same answer: nothing more, nothing less."""
    cases = ([('GET', u) for u in READER_GETS] + [('HEAD', u) for u in READER_GETS] + [('POST', QUESTION)] +
             [('GET', u) for u in ADMIN_GETS] + [('POST', u) for u in ADMIN_POSTS] + [('GET', u) for u in TRAVERSAL])
    for method, uri in cases:
        assert library_policy.classify(method, prefixed(uri)) == library_policy.classify(method, uri), (method, uri)


def test_the_short_path_s_own_spellings():
    classify = library_policy.classify
    # /library and /library/ are the front door, which lands on the reader.
    for uri in ('/library', '/library/', '/library?x=1', '/library//'):
        assert classify('GET', uri) == library_policy.READER, uri
    # The console asks for its API route as /library/api/ there (Cloudflare exempts paths containing "/api/").
    assert classify('POST', '/library/api/?op=ask') == library_policy.QUESTION
    assert classify('POST', '/library/api?op=ask') == library_policy.QUESTION
    assert classify('GET', '/library/api/?op=books&limit=500') == library_policy.READER
    assert classify('GET', '/library/api/?op=health') == library_policy.ADMINISTRATOR
    assert classify('POST', '/library/api/?op=teach') == library_policy.ADMINISTRATOR
    # Exactly one prefix comes off; a name that merely starts with it, or another case, is not the prefix.
    for uri in ('/library/library/reader', '/library/library/api?op=books', '/libraryx/reader', '/library-reader',
                '/Library/reader', '/LIBRARY/reader', '/libraryreader', '/library/Reader', '/library/reader/operations',
                '/library/dashboard/', '/library/collections/mbk_books', '/library/api/monitoring/phoenix',
                '/library/api/system/recent_runs?limit=5', '/library/healthz'):
        assert classify('GET', uri) == library_policy.ADMINISTRATOR, uri
    # The prefix does not open a way around the traversal checks.
    for uri in ('/library/../reader', '/library/../api/system/status', '/library/%2e%2e/api/system/status',
                '/library%2f..%2fapi', '/library/reader/%252e%252e/x', '/library/./reader', '/library\\reader'):
        assert classify('GET', uri) == library_policy.INVALID, uri
    assert library_policy.without_prefix('/library') == '/'
    assert library_policy.without_prefix('/library/reader/logs') == '/reader/logs'
    assert library_policy.without_prefix('/libraryx') == '/libraryx'


@pytest.mark.parametrize('roles', [['viewer'], ['member'], ['operator']])
def test_every_signed_in_role_reaches_the_reader_on_the_short_path_and_nothing_else(fake_db, roles):
    client, _ = fake_db
    as_user(roles)
    for uri in READER_GETS:
        assert authorize(client, prefixed(uri)).status_code == 204, prefixed(uri)
    # The path decides here; the shared host's own origin is checked below with production's allow-list.
    for uri in ('/library/api/?op=ask', '/library/api?op=ask'):
        assert authorize(client, uri, 'POST').status_code == 204, uri
    for uri in ADMIN_GETS:
        assert authorize(client, prefixed(uri)).status_code == 403, prefixed(uri)
    for uri in ADMIN_POSTS:
        assert authorize(client, prefixed(uri), 'POST').status_code == 403, prefixed(uri)
    for uri in TRAVERSAL:
        assert authorize(client, prefixed(uri)).status_code == 403, prefixed(uri)


def test_administrators_reach_every_path_on_the_short_path(fake_db):
    client, _ = fake_db
    as_user(['administrator'])
    for uri in READER_GETS + ADMIN_GETS:
        if '..' in uri: continue
        assert authorize(client, prefixed(uri)).status_code == 204, prefixed(uri)
    for uri in ADMIN_POSTS + ('/api/?op=ask',):
        assert authorize(client, prefixed(uri), 'POST').status_code == 204, prefixed(uri)


def test_questions_on_the_short_path_keep_the_origin_check(fake_db, monkeypatch):
    # A page on https://bagala.ai/library/ posts with the shared host's own origin, which production lists
    # (JOBSEARCH_LIBRARY_ORIGINS, scripts/jobsearch_release_manifest.py in the hub); any other origin is refused.
    client, _ = fake_db
    monkeypatch.setattr(settings(), 'library_origins', ['http://localhost:3001', 'https://library.bagala.ai', 'https://bagala.ai'])
    as_user(['member'])
    assert authorize(client, '/library/api/?op=ask', 'POST', origin='https://bagala.ai').status_code == 204
    assert authorize(client, '/library/api/?op=ask', 'POST', origin='https://evil.example').status_code == 403
    assert authorize(client, '/library/api/?op=ask', 'POST', origin=None).status_code == 403


@pytest.mark.parametrize('extra', [{'active': False}, {'email': 'someone@example.org', 'email_verified_at': None}])
@pytest.mark.parametrize('roles', [['member'], ['administrator']])
def test_inactive_and_unverified_accounts_are_refused(fake_db, extra, roles):
    client, _ = fake_db
    as_user(roles, **extra)
    for uri in ('/reader', '/api/config', '/reader/operations'):
        assert authorize(client, uri).status_code == 403, uri
    assert authorize(client, QUESTION, 'POST').status_code == 403
    as_user(roles, email='someone@example.org', email_verified_at=datetime.now(timezone.utc))
    assert authorize(client, '/reader').status_code == 204


def test_signed_out_visitors_still_get_401(fake_db):
    client, _ = fake_db
    assert authorize(client, '/reader').status_code == 401


def test_questions_keep_the_origin_check(fake_db):
    client, _ = fake_db
    as_user(['member'])
    assert authorize(client, QUESTION, 'POST', origin=None).status_code == 403
    assert authorize(client, QUESTION, 'POST', origin='https://evil.example').status_code == 403
    assert authorize(client, QUESTION, 'POST').status_code == 204


# The daily limit counts in PostgreSQL, so these use the dedicated test database.
@pytest.fixture()
def db_client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    with connection() as c:
        c.execute("DELETE FROM jobsearch.login_limits WHERE bucket LIKE 'reader-questions:%'")
        c.execute("DELETE FROM jobsearch.audit_events WHERE action='hub.library.reader_question'")
    clock = {'now': datetime(2031, 3, 4, 23, 59, 30, tzinfo=timezone.utc)}
    monkeypatch.setattr(hub_access, 'now', lambda: clock['now'])
    try:
        with TestClient(app) as c:
            yield c, clock
    finally:
        app.dependency_overrides.clear()


def limited_audits():
    with connection() as c:
        return c.execute("SELECT actor,outcome,details FROM jobsearch.audit_events WHERE action='hub.library.reader_question' ORDER BY id").fetchall()


def test_fifty_questions_a_day_then_429_until_utc_midnight(db_client, monkeypatch):
    client, clock = db_client
    monkeypatch.setattr(settings(), 'reader_daily_question_limit', 50)
    user = as_user(['member'])
    for n in range(50):
        assert authorize(client, QUESTION, 'POST').status_code == 204, n
    # Page loads and the book list are not questions.
    assert authorize(client, '/reader').status_code == 204
    assert authorize(client, '/api?op=books&limit=500').status_code == 204
    over = authorize(client, QUESTION, 'POST')
    assert over.status_code == 403 and over.headers['x-hub-limit'] == 'reader-daily'
    assert over.headers['retry-after'] == '30'
    assert "Reader question limit" in over.json()['detail']
    assert authorize(client, QUESTION, 'POST').headers.get('x-hub-limit') == 'reader-daily'
    # Reading still works while the limit holds.
    assert authorize(client, '/reader').status_code == 204
    audits = limited_audits()
    assert [(a['actor'], a['outcome'], a['details']) for a in audits] == [(user['id'], 'limited', {'limit': 50})]
    # The next UTC day starts a fresh budget.
    clock['now'] = datetime(2031, 3, 5, 0, 0, 1, tzinfo=timezone.utc)
    assert authorize(client, QUESTION, 'POST').status_code == 204
    # A different account has its own budget.
    clock['now'] = datetime(2031, 3, 4, 12, 0, tzinfo=timezone.utc)
    as_user(['viewer'])
    assert authorize(client, QUESTION, 'POST').status_code == 204


def test_questions_on_both_addresses_share_one_daily_budget(db_client, monkeypatch):
    """A reader cannot double the limit by asking on library.bagala.ai and on bagala.ai/library/ in turn."""
    client, _ = db_client
    monkeypatch.setattr(settings(), 'reader_daily_question_limit', 3)
    as_user(['member'])
    statuses = [authorize(client, uri, 'POST').status_code
                for uri in (QUESTION, '/library/api/?op=ask', QUESTION, '/library/api?op=ask')]
    assert statuses == [204, 204, 204, 403]
    over = authorize(client, '/library/api/?op=ask', 'POST')
    assert over.status_code == 403 and over.headers['x-hub-limit'] == 'reader-daily'
    # Reading on the short path still works while the limit holds.
    assert authorize(client, '/library/reader').status_code == 204


def test_administrators_and_a_zero_limit_are_unlimited(db_client, monkeypatch):
    client, clock = db_client
    monkeypatch.setattr(settings(), 'reader_daily_question_limit', 2)
    as_user(['administrator'])
    for n in range(5):
        assert authorize(client, QUESTION, 'POST').status_code == 204, n
    as_user(['member'])
    assert [authorize(client, QUESTION, 'POST').status_code for _ in range(3)] == [204, 204, 403]
    monkeypatch.setattr(settings(), 'reader_daily_question_limit', 0)
    clock['now'] += timedelta(days=1)
    for n in range(5):
        assert authorize(client, QUESTION, 'POST').status_code == 204, n
    with connection() as c:
        assert not c.execute("SELECT 1 FROM jobsearch.login_limits WHERE bucket LIKE %s", ('%:' + clock['now'].date().isoformat(),)).fetchone()


def test_the_limit_setting_reads_its_environment_variable(monkeypatch):
    from src.settings import Settings
    assert Settings.model_fields['reader_daily_question_limit'].default == 50
    monkeypatch.setenv('JOBSEARCH_READER_DAILY_QUESTION_LIMIT', '0')
    assert Settings().reader_daily_question_limit == 0
    monkeypatch.setenv('JOBSEARCH_READER_DAILY_QUESTION_LIMIT', '-1')
    with pytest.raises(Exception):
        Settings()
