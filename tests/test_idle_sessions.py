"""The idle limit, and the address Job Search is reached at.

The owner's rule: a signed-in account that is not an administrator is signed out after five
minutes without activity. It lives in the account service, in current_user, because that is the
one place every product's authenticated request goes through — Job Search's own API, the
Library's authorization call and Job Prep's identity call all resolve the shared session there,
so one rule covers all three.

The stamp that measures it is on the session row (018_idle_sessions.sql) and is written back
only when it has gone stale, so an active session does not turn every read into a write.
"""
import os
import pytest
from fastapi.testclient import TestClient
from src.api import main
from src.auth.passwords import password_hash
from src.db.store import connection
from src.settings import Settings, settings, origin_of

HEADERS = {'Origin': 'http://localhost:3105'}
PASSWORD = 'a long test passphrase'


@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    monkeypatch.setattr(settings(), 'idle_minutes', 5)
    with connection() as c:
        c.execute('TRUNCATE jobsearch.users,jobsearch.sessions,jobsearch.login_limits,jobsearch.audit_events CASCADE')
        c.execute("""INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash)
                     VALUES('local','member','Member',ARRAY['member'],%s),
                           ('local','boss','Boss',ARRAY['administrator'],%s)""",
                  (password_hash(PASSWORD), password_hash(PASSWORD)))
    with TestClient(app=main.app) as client:
        yield client


def sign_in(client, username='member'):
    assert client.post('/api/auth/login', json={'username': username, 'password': PASSWORD},
                       headers=HEADERS).status_code == 200


def sessions():
    with connection() as c:
        return c.execute('SELECT token_hash,last_seen_at FROM jobsearch.sessions').fetchall()


def age_session(minutes):
    """Make the one open session look as if it was last used `minutes` ago."""
    with connection() as c:
        c.execute("UPDATE jobsearch.sessions SET last_seen_at=now()-(%s * interval '1 minute')", (minutes,))


# ----- the rule ---------------------------------------------------------------------------

def test_a_non_administrator_is_refused_once_the_idle_limit_has_passed_and_the_row_is_gone(client):
    sign_in(client)
    assert client.get('/api/session').json()['user']['name'] == 'Member'
    age_session(6)
    answer = client.get('/api/jobs')
    assert answer.status_code == 401
    assert 'without activity' in answer.json()['detail'] and '5 minutes' in answer.json()['detail']
    # Not merely refused: the session is gone, so the cookie in the browser is worth nothing.
    assert sessions() == []
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM jobsearch.audit_events WHERE action='logout' AND outcome='idle'").fetchone()['n'] == 1


def test_an_administrator_is_exempt(client):
    sign_in(client, 'boss')
    age_session(45)
    assert client.get('/api/session').json()['user']['name'] == 'Boss'
    assert client.get('/api/jobs').status_code != 401
    assert len(sessions()) == 1


def test_activity_refreshes_the_stamp_so_a_session_in_use_is_never_idle(client):
    sign_in(client)
    for _ in range(3):
        # Four minutes since the last request, three times over: still inside the allowance.
        age_session(4)
        assert client.get('/api/session').json()['user'] is not None
    assert len(sessions()) == 1
    age_session(4)
    assert client.get('/api/jobs').status_code != 401
    # ... and the request that found it stale wrote a fresh stamp.
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM jobsearch.sessions WHERE last_seen_at > now()-interval '30 seconds'").fetchone()['n'] == 1


def test_zero_switches_the_idle_limit_off(client, monkeypatch):
    monkeypatch.setattr(settings(), 'idle_minutes', 0)
    sign_in(client)
    age_session(600)
    assert client.get('/api/session').json()['user']['name'] == 'Member'
    assert client.get('/api/jobs').status_code != 401
    assert len(sessions()) == 1


def test_the_stamp_is_not_written_on_every_request(client):
    sign_in(client)
    first = sessions()[0]['last_seen_at']
    for _ in range(5):
        assert client.get('/api/session').json()['user'] is not None
    # Nothing has gone stale in those milliseconds, so nothing was written.
    assert sessions()[0]['last_seen_at'] == first
    # Once it is older than the refresh window, the next request does write.
    age_session(1)
    stale = sessions()[0]['last_seen_at']
    client.get('/api/session')
    assert sessions()[0]['last_seen_at'] > stale
    assert main.ACTIVITY_REFRESH_SECONDS == 30


def test_the_session_answer_tells_the_front_end_this_visitor_s_own_allowance(client, monkeypatch):
    sign_in(client)
    assert client.get('/api/session').json()['idle_minutes'] == 5
    client.post('/api/auth/logout', headers=HEADERS)
    # Signed out, and an administrator, both mean there is nothing to warn about.
    assert client.get('/api/session').json()['idle_minutes'] == 0
    sign_in(client, 'boss')
    assert client.get('/api/session').json()['idle_minutes'] == 0
    monkeypatch.setattr(settings(), 'idle_minutes', 0)
    client.post('/api/auth/logout', headers=HEADERS)
    sign_in(client)
    assert client.get('/api/session').json()['idle_minutes'] == 0


def test_every_product_is_covered_because_they_all_resolve_the_same_session(client):
    sign_in(client)
    # The Library's authorization call and Job Prep's identity call, on an idle session.
    age_session(6)
    assert client.get('/api/hub/library-authorize').status_code == 401
    assert sessions() == []
    sign_in(client)
    age_session(6)
    assert client.get('/api/hub/prep-identity').status_code == 401
    assert sessions() == []


# ----- the address, the origins and the emailed links ---------------------------------------

def test_the_public_address_may_carry_a_path_and_still_yields_a_usable_origin():
    assert origin_of('https://bagala.ai/jobsearch') == 'https://bagala.ai'
    assert origin_of('https://bagala.ai/jobsearch/') == 'https://bagala.ai'
    assert origin_of('https://jobs.bagala.ai') == 'https://jobs.bagala.ai'
    assert origin_of('http://localhost:3105/') == 'http://localhost:3105'
    assert origin_of('') == '' and origin_of(None) == ''


def test_the_short_path_is_the_public_origin_and_the_host_it_is_on_is_an_accepted_origin(monkeypatch):
    monkeypatch.setenv('JOBSEARCH_PUBLIC_ORIGIN', 'https://bagala.ai/jobsearch/')
    monkeypatch.delenv('JOBSEARCH_ALLOWED_ORIGINS', raising=False)
    monkeypatch.delenv('JOBSEARCH_SECURE_COOKIES', raising=False)
    s = Settings(_env_file=None)
    assert s.public_origin == 'https://bagala.ai/jobsearch'
    # An Origin header never carries a path, so the list holds the host the page is served on.
    assert s.allowed_origins == ['http://localhost:3105', 'https://bagala.ai']
    assert s.secure_cookies is True


def test_emailed_links_land_on_the_short_path(monkeypatch):
    from src import mail
    monkeypatch.setenv('JOBSEARCH_PUBLIC_ORIGIN', 'https://bagala.ai/jobsearch')
    origin = Settings(_env_file=None).public_origin
    assert '://bagala.ai/jobsearch/?verify=tok' in ' '.join(str(part) for part in mail.render_verification(origin, 'tok'))
    assert '://bagala.ai/jobsearch/?reset=tok' in ' '.join(str(part) for part in mail.render_reset(origin, 'tok', 'name'))


def test_the_two_step_code_step_rides_on_the_address_the_browser_is_using(client):
    """A cookie scoped to a path has to name the address the browser asks.

    The web app is built under the short path and its /api rewrite takes the prefix off again,
    so by the time the account service sees the request there is nothing in the path to say
    which address it came from. The gateway says it instead, and the challenge cookie follows."""
    from src.auth.local import MFA_COOKIE, request_prefix

    with connection() as c:
        c.execute("""INSERT INTO jobsearch.user_mfa(user_id,secret_enc,enabled_at)
                     SELECT id,'\\x00'::bytea,now() FROM jobsearch.users WHERE subject='member'""")
    body = {'username': 'member', 'password': PASSWORD}
    # The root shape, unchanged: jobs.bagala.ai and the loopback name.
    answer = client.post('/api/auth/login', json=body, headers=HEADERS)
    assert answer.json()['mfa_required'] is True
    cookie = [v for k, v in answer.headers.multi_items() if k == 'set-cookie' and MFA_COOKIE in v][0]
    assert 'Path=/api/auth;' in cookie or cookie.endswith('Path=/api/auth')
    client.cookies.clear()
    # The short path: the gateway names the prefix, so the cookie is sent back on
    # /jobsearch/api/auth/mfa/verify, which is where the browser will ask.
    prefixed = {**HEADERS, 'X-Forwarded-Prefix': '/jobsearch'}
    answer = client.post('/api/auth/login', json=body, headers=prefixed)
    cookie = [v for k, v in answer.headers.multi_items() if k == 'set-cookie' and MFA_COOKIE in v][0]
    assert 'Path=/jobsearch/api/auth' in cookie
    # Nothing a browser sends can widen the path or move it onto another product.
    class Fake:
        def __init__(self, value):
            self.headers = {'x-forwarded-prefix': value}
    for bad in ('/', '', '/../..', '/.', '/jobsearch/..', 'jobsearch', '//evil.example', '/a/b/c/d',
                '/jobsearch"; Path=/', '/job search'):
        assert request_prefix(Fake(bad)) == '', bad
    assert request_prefix(Fake('/jobsearch/')) == '/jobsearch'


def test_a_page_on_the_shared_host_may_post_and_gets_the_shared_cookie(client, monkeypatch):
    monkeypatch.setattr(settings(), 'allowed_origins', ['http://localhost:3105', 'https://jobs.bagala.ai', 'https://bagala.ai'])
    monkeypatch.setattr(settings(), 'cookie_domain', 'bagala.ai')
    monkeypatch.setattr(settings(), 'secure_cookies', True)
    shared = {'Origin': 'https://bagala.ai', 'Host': 'api:8100', 'X-Forwarded-Host': 'bagala.ai', 'X-Forwarded-Proto': 'https'}
    answer = client.post('/api/auth/login', json={'username': 'member', 'password': PASSWORD}, headers=shared)
    assert answer.status_code == 200
    cookie = answer.headers['set-cookie']
    assert 'Domain=bagala.ai' in cookie and 'Secure' in cookie
    # The old product name keeps working, unchanged, on the same deployment.
    client.cookies.clear()
    named = {'Origin': 'https://jobs.bagala.ai', 'Host': 'api:8100', 'X-Forwarded-Host': 'jobs.bagala.ai', 'X-Forwarded-Proto': 'https'}
    assert client.post('/api/auth/login', json={'username': 'member', 'password': PASSWORD}, headers=named).status_code == 200
    # Somebody else's origin is still refused.
    client.cookies.clear()
    foreign = {**shared, 'Origin': 'https://bagala.ai.example'}
    assert client.post('/api/auth/login', json={'username': 'member', 'password': PASSWORD}, headers=foreign).status_code == 403
