"""API keys (stage 2 of the hub's docs/plans/api-gateway-and-mcp.md, 17 Sep 2026).

A program sends "Authorization: Bearer hub_<id>_<secret>" instead of the session cookie. The key is created from
a signed-in browser session with the password entered again, shown once, stored as a digest, listed without its
secret, renamed and revoked in place; it carries the account's roles, counts against a daily quota per UTC day,
is refused beside a cookie, cannot touch the account, and is honoured by the Library's authorization call, Job
Prep's identity call and the API gateway's key check the same way as by Job Search's own routes.
"""
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from src.api import main, hub_access
from src.auth import api_keys
from src.auth.passwords import password_hash
from src.db.store import connection
from src.settings import settings, Settings

HEADERS = {'Origin': 'http://localhost:3105'}
PASSWORD = 'a long test passphrase'
USERS = {'member': ['member'], 'viewer': ['viewer'], 'operator': ['member', 'operator'], 'boss': ['administrator']}


@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    monkeypatch.setattr(settings(), 'api_keys_enabled', True)
    monkeypatch.setattr(settings(), 'api_key_daily_quota', 1000)
    monkeypatch.setattr(settings(), 'api_keys_per_account', 10)
    with connection() as c:
        c.execute('TRUNCATE jobsearch.users,jobsearch.sessions,jobsearch.login_limits,jobsearch.audit_events,jobsearch.api_keys,jobsearch.api_key_days CASCADE')
        for name, roles in USERS.items():
            c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local',%s,%s,%s,%s)",
                      (name, name.capitalize(), roles, password_hash(PASSWORD)))
    with TestClient(app=main.app) as browser:
        # A second client with no cookie jar: the program. The pool the first one's lifespan opened serves both.
        yield browser, TestClient(main.app)


def sign_in(browser, username='member'):
    assert browser.post('/api/auth/login', json={'username': username, 'password': PASSWORD}, headers=HEADERS).status_code == 200


def create(browser, name='laptop', password=PASSWORD, **extra):
    return browser.post('/api/auth/keys', json={'name': name, 'password': password, **extra}, headers=HEADERS)


def made(browser, name='laptop', **extra):
    answer = create(browser, name, **extra)
    assert answer.status_code == 201, answer.text
    return answer.json()


def auth(key):
    return {'Authorization': 'Bearer ' + key}


def outcomes(action):
    with connection() as c:
        return [(r['outcome'], r['resource']) for r in c.execute('SELECT outcome,resource FROM jobsearch.audit_events WHERE action=%s ORDER BY id', (action,)).fetchall()]


def day_row(key_id):
    with connection() as c:
        return c.execute('SELECT calls,refused FROM jobsearch.api_key_days WHERE key_id=%s ORDER BY day DESC LIMIT 1', (key_id,)).fetchone()


# ----- the key itself ---------------------------------------------------------------------------

def test_a_key_is_shown_once_carries_the_roles_and_is_listed_without_its_secret(client):
    browser, program = client
    sign_in(browser)
    key = made(browser, 'laptop')
    token = key['key']
    match = api_keys.KEY_SHAPE.match(token)
    assert match and key['id'] == match.group('id') and re.fullmatch('[0-9a-f]{12}', key['id'])
    assert key['products'] == ['jobsearch', 'library', 'prep'] and key['daily_quota'] == 1000 and key['revoked_at'] is None
    with connection() as c:
        stored = c.execute('SELECT secret_hash FROM jobsearch.api_keys WHERE id=%s', (key['id'],)).fetchone()['secret_hash']
    assert stored == hashlib.sha256(match.group('secret').encode()).hexdigest() and token not in stored
    listing = browser.get('/api/auth/keys').json()
    assert [k['id'] for k in listing['keys']] == [key['id']] and 'key' not in listing['keys'][0] and listing['keys'][0]['used_today'] == 0
    assert listing['products'] == ['jobsearch', 'library', 'prep'] and listing['daily_quota_max'] == 1000 and listing['limit'] == 10
    assert listing['limit_class'] == 'member'
    # The program: no cookie, the key alone, the account's roles.
    session = program.get('/api/session', headers=auth(token))
    assert session.status_code == 200 and session.json()['user'] == {'name': 'Member', 'roles': ['member']}
    assert program.get('/api/jobs', headers=auth(token)).status_code == 200
    assert program.get('/api/jobs').status_code == 401
    assert program.get('/api/jobs', headers=auth('hub_' + key['id'] + '_' + 'x' * 43)).status_code == 401
    assert program.get('/api/jobs', headers=auth('hub_000000000000_' + match.group('secret'))).status_code == 401
    assert program.get('/api/jobs', headers={'Authorization': 'Bearer nothing-of-ours'}).status_code == 401
    # Counted, stamped, and no secret anywhere in the audit trail.
    assert browser.get('/api/auth/keys').json()['keys'][0]['used_today'] == 2
    assert day_row(key['id'])['calls'] == 2 and day_row(key['id'])['refused'] == 0
    with connection() as c:
        assert c.execute('SELECT last_used_at FROM jobsearch.api_keys WHERE id=%s', (key['id'],)).fetchone()['last_used_at'] is not None
        assert not c.execute('SELECT 1 FROM jobsearch.audit_events WHERE details::text LIKE %s', ('%' + match.group('secret') + '%',)).fetchone()
    assert outcomes('account.api_key.create') == [('allowed', key['id'])]


def test_creation_asks_for_the_password_and_a_session_and_keeps_names_unique_and_bounded(client, monkeypatch):
    browser, program = client
    sign_in(browser)
    assert program.post('/api/auth/keys', json={'name': 'x', 'password': PASSWORD}, headers=HEADERS).status_code == 401
    assert create(browser, 'laptop', 'not the password').status_code == 400
    assert create(browser, '').status_code == 422 and create(browser, 'bad$name').status_code == 422 and create(browser, 'x' * 61).status_code == 422
    key = made(browser, 'laptop', products=['library', 'nothing'], daily_quota=5000)
    assert key['products'] == ['library'] and key['daily_quota'] == 1000  # the ceiling applies
    assert create(browser, ' laptop ').status_code == 409
    assert create(browser, 'other', products=['nothing']).status_code == 422
    monkeypatch.setattr(settings(), 'api_keys_per_account', 1)
    assert create(browser, 'second').status_code == 409
    # A key never manages keys, or anything else under /api/auth/.
    token = key['key']
    assert program.get('/api/auth/keys', headers=auth(token)).status_code == 403
    assert program.post('/api/auth/keys', json={'name': 'x', 'password': PASSWORD}, headers=auth(token)).status_code == 403
    assert program.post('/api/auth/logout', headers=auth(token)).status_code == 403
    assert program.get('/api/auth/profile', headers=auth(token)).status_code == 403
    assert [o for o, _ in outcomes('account.api_key.create')] == ['denied', 'allowed', 'duplicate', 'limit']


def test_rename_and_revoke(client):
    browser, program = client
    sign_in(browser)
    first, second = made(browser, 'one'), made(browser, 'two')
    assert browser.patch('/api/auth/keys/' + first['id'], json={'name': 'uno'}, headers=HEADERS).status_code == 200
    assert browser.patch('/api/auth/keys/' + first['id'], json={'name': 'two'}, headers=HEADERS).status_code == 409
    assert browser.patch('/api/auth/keys/000000000000', json={'name': 'x'}, headers=HEADERS).status_code == 404
    assert program.get('/api/jobs', headers=auth(second['key'])).status_code == 200
    revoked = browser.delete('/api/auth/keys/' + second['id'], headers=HEADERS)
    assert revoked.status_code == 200 and revoked.json()['revoked_at']
    refused = program.get('/api/jobs', headers=auth(second['key']))
    assert refused.status_code == 401 and 'revoked' in refused.json()['detail']
    assert program.get('/api/jobs', headers=auth(first['key'])).status_code == 200
    names = {k['id']: (k['name'], k['revoked_at'] is not None) for k in browser.get('/api/auth/keys').json()['keys']}
    assert names == {first['id']: ('uno', False), second['id']: ('two', True)}
    # Another account cannot see or touch them.
    browser.cookies.clear()
    sign_in(browser, 'viewer')
    assert browser.get('/api/auth/keys').json()['keys'] == []
    assert browser.delete('/api/auth/keys/' + first['id'], headers=HEADERS).status_code == 404
    assert outcomes('account.api_key.rename') == [('allowed', first['id'])] and outcomes('account.api_key.revoke') == [('allowed', second['id'])]


def test_the_daily_quota_answers_429_until_utc_midnight(client, monkeypatch):
    browser, program = client
    sign_in(browser)
    key = made(browser, 'small', daily_quota=3)
    token = key['key']
    clock = {'now': datetime(2031, 3, 4, 23, 59, 30, tzinfo=timezone.utc)}
    monkeypatch.setattr(api_keys, 'now', lambda: clock['now'])
    assert [program.get('/api/jobs', headers=auth(token)).status_code for _ in range(3)] == [200, 200, 200]
    over = program.get('/api/jobs', headers=auth(token))
    assert over.status_code == 429 and over.headers['retry-after'] == '30' and 'midnight UTC' in over.json()['detail']
    # /api/session answers an anonymous 200 for any refused credential, a key over its quota included; still counted.
    assert program.get('/api/session', headers=auth(token)).json()['user'] is None
    assert day_row(key['id']) == {'calls': 5, 'refused': 2}
    assert outcomes('api_key.limited') == [('limited', key['id'])]  # once per key per day
    # The next UTC day starts a fresh budget; a zero quota is unlimited.
    clock['now'] = datetime(2031, 3, 5, 0, 0, 1, tzinfo=timezone.utc)
    assert program.get('/api/jobs', headers=auth(token)).status_code == 200
    monkeypatch.setattr(settings(), 'api_key_daily_quota', 0)
    free = made(browser, 'free', daily_quota=0)
    assert [program.get('/api/jobs', headers=auth(free['key'])).status_code for _ in range(5)] == [200] * 5


def test_a_cookie_and_a_key_together_are_refused(client):
    browser, program = client
    sign_in(browser)
    key = made(browser)
    both = browser.get('/api/jobs', headers=auth(key['key']))
    assert both.status_code == 401 and 'not both' in both.json()['detail']
    assert browser.get('/api/jobs').status_code == 200
    assert program.get('/api/jobs', headers=auth(key['key'])).status_code == 200


def test_keys_off_refuses_every_key_and_hides_management(client, monkeypatch):
    browser, program = client
    sign_in(browser)
    key = made(browser)
    monkeypatch.setattr(settings(), 'api_keys_enabled', False)
    refused = program.get('/api/jobs', headers=auth(key['key']))
    assert refused.status_code == 401 and 'not enabled' in refused.json()['detail']
    assert browser.get('/api/auth/keys').status_code == 404 and create(browser, 'x').status_code == 404
    assert browser.get('/api/session').json()['features']['api_keys'] is False
    assert browser.get('/api/jobs').status_code == 200
    monkeypatch.setattr(settings(), 'api_keys_enabled', True)
    assert browser.get('/api/session').json()['features']['api_keys'] is True


def test_a_keyed_write_needs_no_origin_but_a_cookie_still_does(client):
    browser, program = client
    sign_in(browser)
    key = made(browser)
    job = '/api/jobs/00000000-0000-0000-0000-000000000000/saved'
    # No Origin at all on a keyed write: past the CSRF check, refused only because the job does not exist.
    answer = program.put(job, json={'saved': True}, headers=auth(key['key']))
    assert answer.status_code == 404 and answer.json()['detail'] == 'Job not found'
    # The same write from the browser without its Origin is still refused before any handler runs.
    assert browser.put(job, json={'saved': True}).json()['detail'] == 'Origin rejected'
    # A key beside a cookie does not open the CSRF door: without an Origin the cookie's check still refuses it
    # first, and with the Origin the credential check refuses the pair.
    assert browser.put(job, json={'saved': True}, headers=auth(key['key'])).json()['detail'] == 'Origin rejected'
    assert browser.put(job, json={'saved': True}, headers={**HEADERS, **auth(key['key'])}).status_code == 401
    # An invalid key without a cookie skips the Origin check too, and is refused at the credential check.
    assert program.put(job, json={'saved': True}, headers=auth('hub_000000000000_' + 'x' * 43)).status_code == 401


# ----- the other products' gateways --------------------------------------------------------------

def library(program, key, uri, method='GET', origin=None):
    headers = {**auth(key), 'x-original-method': method, 'x-original-uri': uri}
    if origin:
        headers['x-original-origin'] = origin
    return program.get('/api/hub/library-authorize', headers=headers)


def test_the_library_and_prep_gateways_honour_a_key_with_its_products_and_the_model_spending_rule(client, monkeypatch):
    browser, program = client
    monkeypatch.setattr(hub_access, 'daily_count', lambda *a: 1)
    keys = {}
    for name in USERS:
        browser.cookies.clear()
        sign_in(browser, name)
        keys[name] = made(browser, 'gw')['key']
    # The Reader for every keyed account with the roles named; nothing an administrator's page for the rest.
    answer = library(program, keys['member'], '/reader')
    assert answer.status_code == 204 and answer.headers['x-hub-roles'] == 'member' and answer.headers['x-hub-user']
    assert library(program, keys['member'], '/library/api?op=books').status_code == 204
    assert library(program, keys['member'], '/reader/operations').status_code == 403
    assert library(program, keys['boss'], '/reader/operations').status_code == 204
    # A question spends model tokens: operator and administrator keys only, and no Origin is needed for a key.
    member_asks = library(program, keys['member'], '/api?op=ask', 'POST')
    assert member_asks.status_code == 403 and 'operator or administrator key' in member_asks.json()['detail']
    assert library(program, keys['viewer'], '/api?op=ask', 'POST').status_code == 403
    assert library(program, keys['operator'], '/api?op=ask', 'POST').status_code == 204
    assert library(program, keys['operator'], '/library/api/?op=ask', 'POST', origin='https://evil.example').status_code == 204
    assert library(program, keys['boss'], '/api?op=ask', 'POST').status_code == 204
    with connection() as c:
        rows = c.execute("SELECT details FROM jobsearch.audit_events WHERE action='hub.library.authorize' ORDER BY id").fetchall()
    assert all(r['details']['method'] == 'POST' and re.fullmatch('[0-9a-f]{12}', r['details']['key']) for r in rows) and len(rows) == 3
    # Job Prep's identity call: member and above, as for a cookie.
    identity = program.get('/api/hub/prep-identity', headers=auth(keys['member']))
    assert identity.status_code == 200 and identity.json()['roles'] == ['member'] and identity.json()['subject'].startswith('jobsearch:')
    assert program.get('/api/hub/prep-identity', headers=auth(keys['viewer'])).status_code == 403
    # A key covers only the products it was made for.
    browser.cookies.clear()
    sign_in(browser, 'boss')
    narrow = made(browser, 'jobsearch-only', products=['jobsearch'])['key']
    assert program.get('/api/jobs', headers=auth(narrow)).status_code == 200
    covered = library(program, narrow, '/reader')
    assert covered.status_code == 403 and 'does not cover library' in covered.json()['detail']
    assert program.get('/api/hub/prep-identity', headers=auth(narrow)).status_code == 403
    # A cookie session with no key is unchanged.
    assert browser.get('/api/hub/library-authorize', headers={'x-original-method': 'GET', 'x-original-uri': '/reader'}).status_code == 204


def test_the_api_gateway_front_asks_key_authorize_which_verifies_without_counting(client, monkeypatch):
    browser, program = client
    sign_in(browser, 'operator')
    key = made(browser, 'front', daily_quota=2)
    token = key['key']
    check = lambda product, headers=None: program.get('/api/hub/key-authorize', headers={**auth(token), 'X-Original-Product': product, **(headers or {})})
    answer = check('jobsearch')
    assert answer.status_code == 204
    assert answer.headers['x-hub-key-id'] == key['id'] and answer.headers['x-hub-roles'] == 'member,operator'
    assert answer.headers['x-hub-limit-class'] == 'operator' and answer.headers['x-hub-products'] == 'jobsearch,library,prep'
    assert answer.headers['x-hub-user'] and answer.headers['cache-control'] == 'no-store'
    assert check('library').status_code == 204 and check('prep').status_code == 204
    assert check('').status_code == 403 and check('mail').status_code == 403
    assert program.get('/api/hub/key-authorize', headers={'X-Original-Product': 'jobsearch'}).status_code == 401
    assert program.get('/api/hub/key-authorize', headers={**auth('hub_000000000000_' + 'x' * 43), 'X-Original-Product': 'jobsearch'}).status_code == 401
    # Not counted: the product's own check counts the call once.
    assert day_row(key['id']) is None
    # Once the product-side count reaches the quota, the front's check refuses too, as a 403 the gateway can pass on.
    clock = {'now': datetime(2031, 3, 4, 23, 59, 30, tzinfo=timezone.utc)}
    monkeypatch.setattr(api_keys, 'now', lambda: clock['now'])
    assert [program.get('/api/jobs', headers=auth(token)).status_code for _ in range(2)] == [200, 200]
    front = check('jobsearch')
    assert front.status_code == 403 and front.headers['x-hub-limit'] == 'key-daily' and front.headers['retry-after'] == '30'
    # The same refusal on the two other gateway paths, and a plain 429 on a Job Search route.
    over = library(program, token, '/reader')
    assert over.status_code == 403 and over.headers['x-hub-limit'] == 'key-daily'
    identity = program.get('/api/hub/prep-identity', headers=auth(token))
    assert identity.status_code == 403 and identity.headers['x-hub-limit'] == 'key-daily'
    assert program.get('/api/jobs', headers=auth(token)).status_code == 429
    # Classes by role.
    for name, expected in (('member', 'member'), ('viewer', 'member'), ('boss', 'administrator')):
        browser.cookies.clear()
        sign_in(browser, name)
        other = made(browser, 'front')['key']
        assert program.get('/api/hub/key-authorize', headers={**auth(other), 'X-Original-Product': 'jobsearch'}).headers['x-hub-limit-class'] == expected


# ----- settings and the migration ---------------------------------------------------------------

def test_the_settings_default_off_and_read_their_environment(monkeypatch):
    fields = Settings.model_fields
    assert fields['api_keys_enabled'].default is False and fields['api_key_daily_quota'].default == 1000 and fields['api_keys_per_account'].default == 10
    monkeypatch.setenv('JOBSEARCH_API_KEYS_ENABLED', 'true')
    monkeypatch.setenv('JOBSEARCH_API_KEY_DAILY_QUOTA', '250')
    monkeypatch.setenv('JOBSEARCH_API_KEYS_PER_ACCOUNT', '3')
    s = Settings(_env_file=None)
    assert s.api_keys_enabled is True and s.api_key_daily_quota == 250 and s.api_keys_per_account == 3
    monkeypatch.setenv('JOBSEARCH_API_KEY_DAILY_QUOTA', '-1')
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_the_migration_is_additive_and_the_key_shape_is_what_the_gateway_maps():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / 'src/db/021_api_keys.sql').read_text()
    assert 'CREATE TABLE IF NOT EXISTS jobsearch.api_keys' in sql and 'CREATE TABLE IF NOT EXISTS jobsearch.api_key_days' in sql
    assert 'DROP' not in sql and 'VALUES(21)' in sql
    assert 'GRANT SELECT,INSERT,UPDATE ON jobsearch.api_keys,jobsearch.api_key_days TO jobsearch_app' in sql
    assert "CHECK(id ~ '^[0-9a-f]{12}$')" in sql
    # What the hub's front reads before the secret is checked: hub_<12 hex>_<secret>; the id has no underscore.
    key_id, secret, token = api_keys.new_key()
    assert token == 'hub_{}_{}'.format(key_id, secret) and api_keys.KEY_SHAPE.match(token).group('id') == key_id
    assert re.fullmatch('[0-9a-f]{12}', key_id) and re.fullmatch('[A-Za-z0-9_-]{43}', secret)
    assert api_keys.limit_class(['member']) == 'member' and api_keys.limit_class(['operator', 'member']) == 'operator'
    assert api_keys.limit_class(['operator', 'administrator']) == 'administrator' and api_keys.limit_class([]) == 'member'
    assert api_keys.seconds_to_utc_midnight(datetime(2031, 3, 4, 23, 59, 30, tzinfo=timezone.utc)) == 30
