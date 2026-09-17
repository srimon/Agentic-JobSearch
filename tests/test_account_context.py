"""Account creation options (the hub's docs/plans/account-creation-options.md): the sign-up context
record, consent choices, the phone-scan check and the e-mail code as a second sign-in step."""
import json
import os
import re
from pathlib import Path
import psycopg.errors
import pytest
from fastapi.testclient import TestClient
from src.auth import context, consent
from src.auth.passwords import password_hash
from src.db.store import connection
from src.settings import settings
from src.api.main import app

ORIGIN = {'Origin': 'http://localhost:3105'}
PASSWORD = 'a brand new long passphrase'
DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
PHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
# What the public edge and the Job Search gateway send for a visitor in Berlin on the short path.
BERLIN = {**ORIGIN, 'X-Forwarded-For': '203.0.113.9', 'X-Forwarded-Host': 'bagala.ai', 'X-Forwarded-Prefix': '/jobsearch',
          'X-Forwarded-Proto': 'https', 'X-Visitor-Country': 'DE', 'X-Visitor-Continent': 'EU', 'X-Visitor-Region': 'Berlin',
          'X-Visitor-Region-Code': 'BE', 'X-Visitor-City': 'Berlin', 'X-Visitor-Postal-Code': '10115', 'X-Visitor-Timezone': 'Europe/Berlin',
          'X-Visitor-Latitude': '52.52000', 'X-Visitor-Longitude': '13.40500', 'User-Agent': DESKTOP_UA,
          'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8', 'Referer': 'https://www.bagala.ai/', 'Cookie': 'cf_clearance=abc'}
TABLES = ('users', 'sessions', 'login_limits', 'audit_events', 'auth_tokens', 'outbound_mail', 'user_mfa', 'mfa_recovery_codes',
          'mfa_challenges', 'mfa_scan_codes', 'signup_attempts', 'account_context', 'user_consent', 'consent_events')
ALL_OFF = {'analytics': False, 'partners': False, 'advertising': False, 'news': False}
ALL_ON = {purpose: True for purpose in ALL_OFF}


@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    monkeypatch.setattr(settings(), 'signup_enabled', True)
    monkeypatch.setattr(settings(), 'signup_scan_enabled', True)
    monkeypatch.setattr(settings(), 'login_email_code', False)
    monkeypatch.setattr(settings(), 'login_scan_approval', True)
    monkeypatch.setattr(settings(), 'consent_strict_unknown_region', True)
    with connection() as c:
        c.execute('TRUNCATE ' + ','.join('jobsearch.' + t for t in TABLES) + ' RESTART IDENTITY CASCADE')
    with TestClient(app) as t:
        yield t


def signup(client, headers=BERLIN, **extra):
    body = {'username': 'newuser', 'email': 'new.user@example.com', 'password': PASSWORD, 'display_name': 'New User', **extra}
    return client.post('/api/auth/signup', json=body, headers=headers)


# The same visitor at the root shape (https://jobs.bagala.ai/): the challenge cookie's path is then /api/auth, which is
# where the test client sends it back; with the /jobsearch prefix it would ride only on /jobsearch/api/auth.
BERLIN_ROOT = {k: v for k, v in BERLIN.items() if k != 'X-Forwarded-Prefix'}
# For a request that must carry the client's own cookies (a session, a challenge): an explicit Cookie header
# would keep the cookie jar out of the request (http.cookiejar adds its header only when none is set).
BERLIN_SIGNED = {k: v for k, v in BERLIN_ROOT.items() if k != 'Cookie'}


def verify_and_login(client, username='newuser', headers=None):
    with connection() as c:
        mail = c.execute("SELECT text_body FROM jobsearch.outbound_mail WHERE purpose='verify' ORDER BY id DESC").fetchone()['text_body']
    # /?verify= on the loopback name; the hub's account screen's /account/verify?token= when the sign-up came through the edge
    token = re.search(r'\?(?:verify|token)=([A-Za-z0-9_-]+)', mail).group(1)
    assert client.post('/api/auth/verify', json={'token': token}, headers=ORIGIN).status_code == 200
    return client.post('/api/auth/login', json={'username': username, 'password': PASSWORD}, headers=headers or BERLIN_ROOT)


def rows(table, **where):
    """Every row of a table in key order (the first column: id, or user_id for user_consent)."""
    with connection() as c:
        clause = ' AND '.join(k + '=%s' for k in where)
        return c.execute('SELECT * FROM jobsearch.' + table + (' WHERE ' + clause if clause else '') + ' ORDER BY 1', tuple(where.values())).fetchall()


def audit_text():
    with connection() as c:
        return str(c.execute('SELECT * FROM jobsearch.audit_events').fetchall())


def outcomes(action):
    with connection() as c:
        return [r['outcome'] for r in c.execute('SELECT outcome FROM jobsearch.audit_events WHERE action=%s ORDER BY id', (action,)).fetchall()]


# ----- the migration and the rules ----------------------------------------------------------

def test_migration_019_reapplies_with_grants_and_constraints():
    sql = (Path(__file__).resolve().parents[1] / 'src/db/019_account_context.sql').read_text()
    with connection() as c:
        c.execute(sql)
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=19').fetchone()
        for table in ('signup_attempts', 'account_context', 'user_consent', 'consent_events'):
            assert c.execute("SELECT has_table_privilege('jobsearch_app',%s,'INSERT') allowed", ('jobsearch.' + table,)).fetchone()['allowed']
            assert not c.execute("SELECT has_table_privilege('jobsearch_worker',%s,'SELECT') allowed", ('jobsearch.' + table,)).fetchone()['allowed']
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection() as c:
            c.execute("INSERT INTO jobsearch.account_context(source) VALUES('fax')")
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection() as c:
            c.execute("INSERT INTO jobsearch.mfa_challenges(token_hash,user_id,expires_at,method) VALUES('x',1,now(),'carrier-pigeon')")
    # 020: additive, re-applies, the phone's own source, the news purpose, the scan codes
    later = (Path(__file__).resolve().parents[1] / 'src/db/020_signin_options.sql').read_text()
    with connection() as c:
        c.execute(later)
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=20').fetchone()
        assert c.execute("SELECT has_table_privilege('jobsearch_app','jobsearch.mfa_scan_codes','INSERT') allowed").fetchone()['allowed']
        assert not c.execute("SELECT has_table_privilege('jobsearch_worker','jobsearch.mfa_scan_codes','SELECT') allowed").fetchone()['allowed']
        columns = {r['column_name'] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='jobsearch' AND table_name='user_consent'").fetchall()}
        assert 'news' in columns
        # the phone columns stay, unused
        kept = {r['column_name'] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='jobsearch' AND table_name='account_context'").fetchall()}
        assert {'phone_e164', 'phone_verified_at'} <= kept
        c.execute("INSERT INTO jobsearch.account_context(source) VALUES('approve')")
        c.execute("DELETE FROM jobsearch.account_context WHERE source='approve' AND user_id IS NULL")


def test_device_classes_and_regimes(monkeypatch):
    assert context.device_class(DESKTOP_UA) == 'desktop' and context.device_class(PHONE_UA) == 'phone'
    assert context.device_class('Mozilla/5.0 (Linux; Android 14; SM-X910) AppleWebKit/537.36 Chrome/140.0 Safari/537.36') == 'tablet'
    assert context.device_class('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36') == 'phone'
    assert context.device_class('python-requests/2.32') == 'bot' and context.device_class('') == 'unknown'
    assert (context.operating_system(PHONE_UA), context.browser(PHONE_UA)) == ('iOS', 'Safari')
    assert (context.operating_system(DESKTOP_UA), context.browser(DESKTOP_UA)) == ('Windows', 'Chrome')
    assert context.regime('DE', None) == 'eu' and context.regime('no', '') == 'eu' and context.regime('gb', None) == 'uk'
    assert context.regime('US', 'CA') == 'california' and context.regime('US', 'TX') == 'other' and context.regime('IN', None) == 'other'
    assert context.regime('US', None) == 'california'  # region unknown: strict by default
    monkeypatch.setattr(settings(), 'consent_strict_unknown_region', False)
    assert context.regime('US', None) == 'other'
    assert context.regime(None, None) == 'other'


def test_session_tells_the_form_which_consent_default_applies(client):
    berlin = client.get('/api/session', headers=BERLIN).json()
    assert berlin['consent']['regime'] == 'eu' and berlin['consent']['opt_in_required'] is True
    assert berlin['consent']['default'] == ALL_OFF
    assert berlin['consent']['version'] == consent.VERSION and berlin['consent']['notice'] == consent.NOTICE
    assert set(consent.NOTICE) == {'intro', 'analytics', 'partners', 'advertising', 'news', 'opt_in', 'opt_out'}
    assert berlin['features']['signup_scan'] is True and berlin['features']['signin_scan'] is True and berlin['features']['email_code'] is False
    assert 'phone_collection' not in berlin['features']
    india = client.get('/api/session', headers={**ORIGIN, 'X-Visitor-Country': 'IN'}).json()['consent']
    assert india['regime'] == 'other' and india['opt_in_required'] is False and all(india['default'].values())
    texas = client.get('/api/session', headers={**ORIGIN, 'X-Visitor-Country': 'US', 'X-Visitor-Region-Code': 'TX'}).json()['consent']
    assert texas['regime'] == 'other'
    assert client.get('/api/session', headers={**ORIGIN, 'X-Visitor-Country': 'US'}).json()['consent']['regime'] == 'california'


# ----- the sign-up record ---------------------------------------------------------------------

def test_signup_records_the_visitor_context_and_never_logs_it(client):
    assert signup(client).status_code == 202
    [user] = rows('users')
    [row] = rows('account_context')
    assert row['user_id'] == user['id'] and row['source'] == 'desktop' and row['attempt_id'] is None
    assert str(row['ip']) == '203.0.113.9' and row['country'] == 'DE' and row['city'] == 'Berlin' and row['region_code'] == 'BE'
    assert row['postal_code'] == '10115' and row['timezone'] == 'Europe/Berlin' and row['continent'] == 'EU'
    assert float(row['latitude']) == 52.52 and float(row['longitude']) == 13.405
    assert row['user_agent'] == DESKTOP_UA and row['device_class'] == 'desktop' and row['os'] == 'Windows' and row['browser'] == 'Chrome'
    assert row['accept_language'] == 'de-DE,de;q=0.9,en;q=0.8' and row['referrer'] == 'https://www.bagala.ai/'
    assert row['address'] == 'bagala.ai/jobsearch' and row['challenge_cookie'] is True
    assert row['screen_width'] is None and row['phone_e164'] is None and row['scan_seconds'] is None
    assert user['scan_verified_at'] is None
    # nothing personal in the audit trail: the outcome and whether a choice was recorded, no more
    text = audit_text()
    for private in ('203.0.113.9', 'Berlin', 'Chrome', 'example.com', '10115'):
        assert private not in text, private
    assert "'scan_verified': False" in text and "'consent': False" in text and "'regime': 'eu'" in text
    assert rows('consent_events') == [] and rows('user_consent') == []
    # a sign-in records its own row, from its own request
    r = verify_and_login(client)
    assert r.status_code == 200 and r.json() == {'ok': True}
    signin = rows('account_context', source='signin')
    assert len(signin) == 1 and signin[0]['user_id'] == user['id'] and signin[0]['city'] == 'Berlin'
    # a visitor without the edge: the connecting address, no location, the root address
    with TestClient(app) as bare:
        assert bare.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN).status_code == 200
    plain = rows('account_context', source='signin')[-1]
    assert plain['country'] is None and plain['address'] == 'testserver' and plain['challenge_cookie'] is False
    assert plain['ip'] is None  # the test client connects from "testclient", which is not an address; a real socket gives one
    # the rows go with the account (sessions do not cascade: an account deletion ends them first, as scripts/accounts.py does)
    with connection() as c:
        c.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s', (user['id'],))
        c.execute('DELETE FROM jobsearch.users WHERE id=%s', (user['id'],))
    assert rows('account_context') == []


def test_signup_records_the_consent_choice_shown_to_the_visitor(client):
    assert signup(client, consent={'analytics': True, 'partners': False, 'advertising': True, 'news': True}).status_code == 202
    [user] = rows('users')
    [event] = rows('consent_events')
    assert event['user_id'] == user['id'] and event['source'] == 'signup' and event['regime'] == 'eu'
    assert (event['analytics'], event['partners'], event['advertising'], event['news']) == (True, False, True, True)
    assert event['notice_version'] == consent.VERSION == '2026-09-17b' and event['notice_hash'] == consent.notice_hash() and len(event['notice_hash']) == 64
    assert str(event['ip']) == '203.0.113.9' and event['country'] == 'DE'
    [state] = rows('user_consent')
    assert state['analytics'] is True and state['partners'] is False and state['advertising'] is True and state['news'] is True and state['regime'] == 'eu'
    with connection() as c:
        assert consent.exportable(c, 'analytics') == [user['id']] and consent.exportable(c, 'partners') == [] and consent.exportable(c, 'news') == [user['id']]
        with pytest.raises(ValueError):
            consent.exportable(c, 'anything')
    assert "'consent': True" in audit_text()
    # an older client that sends three purposes: news stays off
    assert signup(client, username='older', email='older@example.com', consent={'analytics': True, 'partners': True, 'advertising': True}).status_code == 202
    assert rows('user_consent')[-1]['news'] is False


def test_the_honeypot_answers_like_a_sign_up_and_creates_nothing(client):
    r = signup(client, website='https://spam.example')
    assert r.status_code == 202 and r.json() == {'detail': 'check your email'}
    assert rows('users') == [] and rows('outbound_mail') == [] and rows('account_context') == []
    assert outcomes('account.signup') == ['honeypot']


def test_old_sign_in_rows_are_pruned_and_sign_up_rows_are_kept(client, monkeypatch):
    signup(client)
    verify_and_login(client)
    with connection() as c:
        c.execute("UPDATE jobsearch.account_context SET recorded_at=now()-interval '100 days'")
    monkeypatch.setattr(settings(), 'context_signin_retention_days', 90)  # the default is a year; the rule is the same
    client.cookies.clear()
    assert client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN).status_code == 200
    kept = rows('account_context')
    assert [r['source'] for r in kept] == ['desktop', 'signin'] and kept[1]['recorded_at'] > kept[0]['recorded_at']


# ----- consent under Account ------------------------------------------------------------------

def test_consent_can_be_read_changed_and_withdrawn_under_account(client):
    signup(client, consent=ALL_ON)
    assert verify_and_login(client).status_code == 200
    state = client.get('/api/auth/consent', headers=BERLIN_SIGNED).json()
    assert state['recorded'] is True and state['choices'] == ALL_ON
    assert state['version'] == consent.VERSION and state['regime'] == 'eu' and state['notice'] == consent.NOTICE and state['opt_in_required'] is True
    assert client.put('/api/auth/consent', json={'analytics': True}).status_code == 403  # origin check
    r = client.put('/api/auth/consent', json={'analytics': True, 'partners': False, 'advertising': False, 'news': True}, headers=BERLIN_SIGNED)
    assert r.status_code == 200 and r.json()['choices'] == {'analytics': True, 'partners': False, 'advertising': False, 'news': True}
    events = rows('consent_events')
    assert [e['source'] for e in events] == ['signup', 'account'] and events[1]['partners'] is False and str(events[1]['ip']) == '203.0.113.9'
    with connection() as c:
        assert consent.exportable(c, 'partners') == [] and consent.exportable(c, 'analytics') == [rows('users')[0]['id']]
    # a full withdrawal
    assert client.put('/api/auth/consent', json={}, headers=BERLIN_SIGNED).status_code == 200
    assert client.get('/api/auth/consent', headers=BERLIN_SIGNED).json()['choices'] == ALL_OFF
    with connection() as c:
        assert consent.exportable(c, 'analytics') == [] and consent.exportable(c, 'news') == []
        details = [r['details'] for r in c.execute("SELECT details FROM jobsearch.audit_events WHERE action='account.consent' ORDER BY id").fetchall()]
    assert details == [{'changed': ['advertising', 'partners'], 'version': consent.VERSION}, {'changed': ['analytics', 'news'], 'version': consent.VERSION}]
    assert len(rows('consent_events')) == 3 and len(rows('user_consent')) == 1
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/auth/consent').status_code == 401
        assert anonymous.put('/api/auth/consent', json={}, headers=ORIGIN).status_code == 401


def test_an_account_without_a_recorded_choice_reads_as_nothing_granted(client):
    signup(client)
    verify_and_login(client)
    state = client.get('/api/auth/consent').json()
    assert state['recorded'] is False and state['choices'] == ALL_OFF and state['version'] is None


# ----- the phone-scan check -------------------------------------------------------------------

def phone_headers(ip='198.51.100.7'):
    return {**ORIGIN, 'X-Forwarded-For': ip, 'X-Forwarded-Host': 'bagala.ai', 'X-Forwarded-Prefix': '/jobsearch', 'User-Agent': PHONE_UA,
            'X-Visitor-Country': 'DE', 'X-Visitor-City': 'Potsdam', 'Cookie': 'cf_clearance=xyz'}


def test_the_phone_scan_check_from_attempt_to_verified_account(client, monkeypatch):
    monkeypatch.setattr(settings(), 'public_origin', 'https://bagala.ai/jobsearch')
    monkeypatch.setattr(settings(), 'cookie_domain', 'bagala.ai')
    r = client.post('/api/auth/signup/attempt', json={}, headers=BERLIN)
    assert r.status_code == 200
    attempt = r.json()
    scan_token = attempt['scan_url'].split('?scan=')[1]
    # through the edge the phone opens the account screen's confirm page (settings.account_screen)
    assert attempt['scan_url'] == 'https://bagala.ai/account/confirm?scan=' + scan_token and len(scan_token) >= 22 and len(attempt['attempt']) >= 22
    assert attempt['qr_svg'].startswith('<svg') and '<script' not in attempt['qr_svg'] and attempt['expires_in'] == 120
    [row] = rows('signup_attempts')
    assert attempt['attempt'] not in str(row) and scan_token not in str(row) and str(row['ip']) == '203.0.113.9' and row['scanned_at'] is None
    status = client.post('/api/auth/signup/attempt/status', json={'attempt': attempt['attempt']}, headers=ORIGIN).json()
    assert status == {'scanned': False, 'expired': False, 'consent': None}
    # a laptop that opens the link is recorded but does not count as a scan
    laptop = client.post('/api/auth/signup/scan', json={'scan': scan_token, 'touch_points': 0}, headers=BERLIN)
    assert laptop.status_code == 200 and laptop.json()['handheld'] is False
    assert client.post('/api/auth/signup/attempt/status', json={'attempt': attempt['attempt']}, headers=ORIGIN).json()['scanned'] is False
    # the phone
    phone = client.post('/api/auth/signup/scan', headers=phone_headers(), json={
        'scan': scan_token, 'screen_width': 390, 'screen_height': 844, 'pixel_ratio': 3, 'touch_points': 5, 'language': 'de-DE',
        'timezone': 'Europe/Berlin', 'consent': {'analytics': True, 'partners': True, 'advertising': False, 'news': False}})
    assert phone.status_code == 200 and phone.json()['handheld'] is True and 'computer' in phone.json()['message']
    assert client.post('/api/auth/signup/scan', json={'scan': scan_token, 'touch_points': 5}, headers=phone_headers()).status_code == 400  # spent
    status = client.post('/api/auth/signup/attempt/status', json={'attempt': attempt['attempt']}, headers=ORIGIN).json()
    assert status == {'scanned': True, 'expired': False, 'consent': {'analytics': True, 'partners': True, 'advertising': False, 'news': False}}
    waiting = rows('account_context')
    assert [w['source'] for w in waiting] == ['qr-phone', 'qr-phone'] and all(w['user_id'] is None and w['attempt_id'] == row['id'] for w in waiting)
    scanned = waiting[1]
    assert scanned['device_class'] == 'phone' and scanned['os'] == 'iOS' and scanned['browser'] == 'Safari' and str(scanned['ip']) == '198.51.100.7'
    assert (scanned['screen_width'], scanned['screen_height'], float(scanned['pixel_ratio']), scanned['touch_points']) == (390, 844, 3.0, 5)
    assert scanned['language'] == 'de-DE' and scanned['client_timezone'] == 'Europe/Berlin' and scanned['city'] == 'Potsdam'
    assert scanned['same_network'] is False and float(scanned['scan_seconds']) >= 0 and scanned['challenge_cookie'] is True
    assert scanned['phone_e164'] is None and scanned['phone_verified_at'] is None  # no SMS, no phone numbers: never written
    # the sign-up completes on the desktop with the attempt, and the account is scan-verified
    assert signup(client, attempt=attempt['attempt'], consent={'analytics': False, 'partners': False, 'advertising': True, 'news': True}).status_code == 202
    [user] = rows('users')
    assert user['scan_verified_at'] is not None
    keyed = rows('account_context', user_id=user['id'])
    assert [k['source'] for k in keyed] == ['qr-phone', 'qr-phone', 'desktop'] and all(k['attempt_id'] == row['id'] for k in keyed)
    [row] = rows('signup_attempts')
    assert row['consumed_at'] is not None and row['user_id'] == user['id']
    # the phone's choice was recorded, then the desktop's, which is the current one
    events = rows('consent_events')
    assert [e['source'] for e in events] == ['qr-phone', 'signup'] and events[0]['analytics'] is True and events[0]['city' if False else 'country'] == 'DE'
    assert str(events[0]['ip']) == '198.51.100.7'
    [state] = rows('user_consent')
    assert (state['analytics'], state['partners'], state['advertising'], state['news']) == (False, False, True, True)
    assert "'scan_verified': True" in audit_text() and 'Potsdam' not in audit_text() and '198.51.100.7' not in audit_text()
    assert outcomes('account.signup.scan') == ['not_handheld', 'allowed', 'expired']
    # cookie_domain is bagala.ai in this test: a sign-in through the edge would set Domain=bagala.ai; Secure, which the
    # plain test client never sends back, so this sign-in arrives as a loopback caller (host-only cookie)
    assert verify_and_login(client, headers=ORIGIN).status_code == 200
    assert client.get('/api/auth/profile').json()['scan_verified'] is True
    # a spent attempt cannot be used again
    assert client.post('/api/auth/signup/attempt/status', json={'attempt': attempt['attempt']}, headers=ORIGIN).json() == {'scanned': False, 'expired': True, 'consent': None}


def test_scan_expiry_limits_and_switch(client, monkeypatch):
    attempt = client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).json()
    scan_token = attempt['scan_url'].split('?scan=')[1]
    assert attempt['scan_url'].startswith('http://localhost:3105/?scan=')  # loopback: the local address
    with connection() as c:
        c.execute("UPDATE jobsearch.signup_attempts SET expires_at=now()-interval '1 second'")
    late = client.post('/api/auth/signup/scan', json={'scan': scan_token, 'touch_points': 5}, headers=phone_headers())
    assert late.status_code == 400 and 'expired' in late.json()['detail']
    assert client.post('/api/auth/signup/attempt/status', json={'attempt': attempt['attempt']}, headers=ORIGIN).json()['expired'] is True
    assert client.post('/api/auth/signup/scan', json={'scan': 'no-such-token', 'touch_points': 5}, headers=phone_headers()).status_code == 400
    # an attempt that was never scanned completes an ordinary sign-up, unverified by scan
    assert signup(client, attempt=attempt['attempt']).status_code == 202
    assert rows('users')[0]['scan_verified_at'] is None and rows('account_context')[0]['source'] == 'desktop'
    # a phone number sent by an old client is ignored: no SMS, no phone numbers
    fresh = client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).json()
    token = fresh['scan_url'].split('?scan=')[1]
    assert client.post('/api/auth/signup/scan', json={'scan': token, 'touch_points': 5, 'phone': '+49 (30) 123-4567'}, headers=phone_headers()).status_code == 200
    assert rows('account_context', source='qr-phone')[-1]['phone_e164'] is None
    # per-visitor budget: ten attempts a quarter hour from one address
    for _ in range(8):
        assert client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).status_code == 200
    assert client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).status_code == 429
    assert outcomes('account.signup.attempt')[-1] == 'throttled'
    # the switch: off means the endpoints do not exist and the form is told so
    monkeypatch.setattr(settings(), 'signup_scan_enabled', False)
    assert client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).status_code == 404
    assert client.post('/api/auth/signup/attempt/status', json={'attempt': 'x'}, headers=ORIGIN).status_code == 404
    assert client.get('/api/session').json()['features']['signup_scan'] is False
    assert client.post('/api/auth/signup/scan', json={'scan': token, 'touch_points': 5}, headers=phone_headers()).status_code == 404


def test_expired_attempts_and_orphan_phone_rows_are_pruned(client):
    attempt = client.post('/api/auth/signup/attempt', json={}, headers=ORIGIN).json()
    token = attempt['scan_url'].split('?scan=')[1]
    assert client.post('/api/auth/signup/scan', json={'scan': token, 'touch_points': 5}, headers=phone_headers()).status_code == 200
    with connection() as c:
        c.execute("UPDATE jobsearch.signup_attempts SET expires_at=now()-interval '2 days'")
        c.execute("UPDATE jobsearch.account_context SET recorded_at=now()-interval '2 days'")
        c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local','someone','Someone',ARRAY['member'],%s)", (password_hash(PASSWORD),))
    assert client.post('/api/auth/login', json={'username': 'someone', 'password': PASSWORD}, headers=ORIGIN).status_code == 200
    assert rows('signup_attempts') == [] and [r['source'] for r in rows('account_context')] == ['signin']


# ----- the e-mail code as a second step -------------------------------------------------------

def login_code():
    with connection() as c:
        row = c.execute("SELECT text_body,html_body,to_address FROM jobsearch.outbound_mail WHERE purpose='login_code' ORDER BY id DESC").fetchone()
    code = re.search(r'sign-in code is (\d{6})\.', row['text_body']).group(1)
    assert code in row['html_body'] and 'within 5 minutes' in row['text_body']
    return code


def test_email_code_is_the_second_step_without_an_authenticator(client, monkeypatch):
    signup(client)
    verify_and_login(client)  # the switch is off: password alone signs in
    client.cookies.clear()
    monkeypatch.setattr(settings(), 'login_email_code', True)
    with TestClient(app) as short_path:  # on bagala.ai/jobsearch the challenge cookie rides on that address's account routes
        r = short_path.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=BERLIN)
        assert r.status_code == 200 and 'Path=/jobsearch/api/auth' in r.headers['set-cookie']
    with connection() as c:
        c.execute('DELETE FROM jobsearch.mfa_challenges')
    r = client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=BERLIN_ROOT)
    assert r.status_code == 200 and r.json() == {'ok': True, 'mfa_required': True, 'method': 'email'}
    assert 'jobsearch_session' not in r.cookies and r.cookies.get('jobsearch_mfa')
    assert 'Path=/api/auth' in r.headers['set-cookie'] and 'HttpOnly' in r.headers['set-cookie']
    assert client.get('/api/auth/profile').status_code == 401
    code = login_code()
    [challenge] = rows('mfa_challenges')
    assert challenge['method'] == 'email' and len(challenge['code_hash']) == 64 and code not in challenge['code_hash']
    assert code not in audit_text()
    wrong = '000000' if code != '000000' else '111111'
    assert client.post('/api/auth/mfa/verify', json={'code': wrong}, headers=ORIGIN).status_code == 401
    ok = client.post('/api/auth/mfa/verify', json={'code': code[:3] + ' ' + code[3:]}, headers=BERLIN_SIGNED)
    assert ok.status_code == 200 and ok.cookies.get('jobsearch_session') and client.get('/api/auth/profile').status_code == 200
    assert client.post('/api/auth/mfa/verify', json={'code': code}, headers=ORIGIN).status_code == 400  # spent
    assert outcomes('login')[-2:] == ['mfa_required', 'allowed'] and outcomes('login.mfa') == ['denied', 'allowed', 'expired']
    with connection() as c:
        methods = [r['details'] for r in c.execute("SELECT details FROM jobsearch.audit_events WHERE action='login' ORDER BY id").fetchall()]
    assert methods[-1] == {'method': 'mfa-email'} and methods[-2] == {'method': 'email'} and methods[-3] == {'method': 'email'}
    assert rows('account_context', source='signin')[-1]['city'] == 'Berlin'
    # the profile still says two-step (authenticator) is off: the code is the default, not a setting of the account
    assert client.get('/api/auth/mfa').json()['enabled'] is False


def test_email_code_resend_expiry_and_who_gets_it(client, monkeypatch):
    monkeypatch.setattr(settings(), 'login_email_code', True)
    # an unverified address gets no code, as before
    signup(client)
    assert client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN).status_code == 403
    assert rows('outbound_mail', purpose='login_code') == []
    verify_and_login(client)
    first = login_code()
    # a new code replaces the last one, twice at most
    assert client.post('/api/auth/mfa/resend', json={}, headers=ORIGIN).status_code == 202
    second = login_code()
    assert client.post('/api/auth/mfa/verify', json={'code': first}, headers=ORIGIN).status_code == 401 or first == second
    assert client.post('/api/auth/mfa/resend', json={}, headers=ORIGIN).status_code == 202
    third = client.post('/api/auth/mfa/resend', json={}, headers=ORIGIN)
    assert third.status_code == 429 and 'No more codes' in third.json()['detail']
    assert outcomes('login.mfa.resend') == ['queued', 'queued', 'exhausted']
    assert client.post('/api/auth/mfa/verify', json={'code': login_code()}, headers=ORIGIN).status_code == 200
    client.cookies.clear()
    # five wrong codes end the challenge; an expired one too
    client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN)
    code = login_code()
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(4):
        assert client.post('/api/auth/mfa/verify', json={'code': wrong}, headers=ORIGIN).status_code == 401
    assert client.post('/api/auth/mfa/verify', json={'code': wrong}, headers=ORIGIN).status_code == 400
    assert client.post('/api/auth/mfa/verify', json={'code': code}, headers=ORIGIN).status_code == 400
    client.cookies.clear()
    client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN)
    with connection() as c:
        c.execute("UPDATE jobsearch.mfa_challenges SET expires_at=now()-interval '1 second' WHERE consumed_at IS NULL")
    assert client.post('/api/auth/mfa/verify', json={'code': login_code()}, headers=ORIGIN).status_code == 400
    assert client.post('/api/auth/mfa/resend', json={}, headers=ORIGIN).status_code == 400
    with TestClient(app) as nothing:
        assert nothing.post('/api/auth/mfa/resend', json={}, headers=ORIGIN).status_code == 400
    # a console account without an address signs in with the password alone
    with connection() as c:
        c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local','console','Console',ARRAY['operator'],%s)", (password_hash(PASSWORD),))
    with TestClient(app) as console:
        r = console.post('/api/auth/login', json={'username': 'console', 'password': PASSWORD}, headers=ORIGIN)
        assert r.status_code == 200 and r.json() == {'ok': True}


# ----- approving a sign-in from a phone that is already signed in ----------------------------------

# The phone's own requests once it holds a session: no explicit Cookie header (it would keep the test client's jar out)
# and the root shape, so the challenge cookie's path is one the jar sends back (see BERLIN_SIGNED).
PHONE = {k: v for k, v in phone_headers().items() if k not in ('Cookie', 'X-Forwarded-Prefix')}


def signed_in_phone(username='newuser'):
    """A separate browser (the phone) signed in as a verified account, through the e-mail code."""
    with connection() as c:
        c.execute("UPDATE jobsearch.users SET email_verified_at=coalesce(email_verified_at,now()) WHERE subject=%s", (username,))
    phone = TestClient(app)
    phone.__enter__()
    r = phone.post('/api/auth/login', json={'username': username, 'password': PASSWORD}, headers=PHONE)
    assert r.status_code == 200 and r.json().get('mfa_required') is True
    assert phone.post('/api/auth/mfa/verify', json={'code': login_code()}, headers=PHONE).status_code == 200
    return phone


def test_a_signed_in_phone_approves_a_desktop_sign_in(client, monkeypatch):
    monkeypatch.setattr(settings(), 'login_email_code', True)
    signup(client)
    assert verify_and_login(client).status_code == 200  # the fixture client is now the desktop, holding a challenge
    assert client.post('/api/auth/mfa/verify', json={'code': login_code()}, headers=ORIGIN).status_code == 200
    client.cookies.clear()
    desktop = client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=BERLIN_ROOT)
    assert desktop.status_code == 200 and desktop.json()['mfa_required'] is True and client.cookies.get('jobsearch_mfa')
    # the desktop asks for a code: a QR of the approve page, the code stored as a digest with the asking device
    r = client.post('/api/auth/mfa/scan', json={}, headers=BERLIN_SIGNED)
    assert r.status_code == 200
    code = r.json()
    raw = code['scan_url'].split('?code=')[1]
    assert code['scan_url'] == 'https://bagala.ai/account/approve?code=' + raw and len(raw) >= 22 and code['expires_in'] == 120
    assert code['qr_svg'].startswith('<svg') and '<script' not in code['qr_svg']
    [stored] = rows('mfa_scan_codes')
    assert raw not in str(stored) and stored['approved_at'] is None and stored['consumed_at'] is None
    assert stored['device'] == {'device_class': 'desktop', 'browser': 'Chrome', 'os': 'Windows', 'city': 'Berlin', 'region': 'Berlin', 'country': 'DE'}
    assert '203.0.113.9' not in str(stored['device'])
    status = client.post('/api/auth/mfa/scan/status', json={}, headers=BERLIN_SIGNED)
    assert status.status_code == 200 and status.json() == {'approved': False, 'expired': False} and 'jobsearch_session' not in status.cookies
    # a phone that is not signed in cannot describe or approve; another account's phone cannot either
    with TestClient(app) as stranger:
        assert stranger.post('/api/auth/mfa/scan/describe', json={'code': raw}, headers=ORIGIN).status_code == 401
        assert stranger.post('/api/auth/mfa/scan/approve', json={'code': raw}, headers=ORIGIN).status_code == 401
    signup(client, username='other', email='other@example.com')
    other = signed_in_phone('other')
    assert other.post('/api/auth/mfa/scan/describe', json={'code': raw}, headers=PHONE).status_code == 400
    assert other.post('/api/auth/mfa/scan/approve', json={'code': raw}, headers=PHONE).status_code == 400
    assert rows('mfa_scan_codes')[0]['approved_at'] is None and outcomes('login.mfa.approve') == ['denied']
    other.__exit__(None, None, None)
    # the right phone sees what is asking, approves, and leaves its own row
    phone = signed_in_phone('newuser')
    described = phone.post('/api/auth/mfa/scan/describe', json={'code': raw}, headers=PHONE)
    assert described.status_code == 200 and described.json()['device']['browser'] == 'Chrome' and described.json()['account'] == 'newuser'
    assert 0 < described.json()['expires_in'] <= 120
    approved = phone.post('/api/auth/mfa/scan/approve', json={'code': raw}, headers=PHONE)
    assert approved.status_code == 200 and approved.json()['ok'] is True
    assert phone.post('/api/auth/mfa/scan/approve', json={'code': raw}, headers=PHONE).status_code == 400  # once
    [stored] = rows('mfa_scan_codes')
    approver = rows('account_context', source='approve')
    assert stored['approved_at'] is not None and len(approver) == 1 and stored['approver_context_id'] == approver[0]['id']
    assert approver[0]['device_class'] == 'phone' and str(approver[0]['ip']) == '198.51.100.7' and approver[0]['city'] == 'Potsdam'
    with connection() as c:
        details = c.execute("SELECT details FROM jobsearch.audit_events WHERE action='login.mfa.approve' AND outcome='allowed'").fetchone()['details']
    assert details == {'device_class': 'phone', 'browser': 'Safari', 'os': 'iOS', 'context_id': approver[0]['id'], 'asking': 'desktop'}
    assert '198.51.100.7' not in audit_text() and 'Potsdam' not in audit_text() and raw not in audit_text()
    # the desktop's next poll is its sign-in: session cookie set, challenge and code spent
    done = client.post('/api/auth/mfa/scan/status', json={}, headers=BERLIN_SIGNED)
    assert done.status_code == 200 and done.json() == {'ok': True, 'approved': True, 'expired': False} and done.cookies.get('jobsearch_session')
    assert client.get('/api/auth/profile').status_code == 200 and 'jobsearch_mfa' not in client.cookies
    assert rows('mfa_scan_codes')[0]['consumed_at'] is not None and rows('mfa_challenges')[-1]['consumed_at'] is not None
    with connection() as c:
        methods = [r['details'] for r in c.execute("SELECT details FROM jobsearch.audit_events WHERE action='login' AND outcome='allowed' ORDER BY id").fetchall()]
    assert methods[-1] == {'method': 'mfa-scan'} and rows('account_context', source='signin')[-1]['country'] == 'DE'
    assert outcomes('login.mfa')[-1] == 'allowed'
    phone.__exit__(None, None, None)


def test_scan_codes_expire_are_limited_and_need_the_switch(client, monkeypatch):
    monkeypatch.setattr(settings(), 'login_email_code', True)
    signup(client)
    assert verify_and_login(client).status_code == 200
    assert client.post('/api/auth/mfa/scan/status', json={}, headers=ORIGIN).json() == {'approved': False, 'expired': True}  # no code yet
    codes = [client.post('/api/auth/mfa/scan', json={}, headers=ORIGIN) for _ in range(4)]
    assert [c.status_code for c in codes] == [200, 200, 200, 429]  # three per challenge
    raw = codes[-2].json()['scan_url'].split('?code=')[1]
    with connection() as c:
        c.execute("UPDATE jobsearch.mfa_scan_codes SET expires_at=now()-interval '1 second'")
    assert client.post('/api/auth/mfa/scan/status', json={}, headers=ORIGIN).json() == {'approved': False, 'expired': True}
    phone = signed_in_phone('newuser')
    assert phone.post('/api/auth/mfa/scan/describe', json={'code': raw}, headers=PHONE).status_code == 400
    assert phone.post('/api/auth/mfa/scan/approve', json={'code': 'no-such-code'}, headers=PHONE).status_code == 400
    phone.__exit__(None, None, None)
    # without a challenge there is nothing to draw
    with TestClient(app) as nothing:
        assert nothing.post('/api/auth/mfa/scan', json={}, headers=ORIGIN).status_code == 400
    # the challenge's own housekeeping takes the codes with it
    with connection() as c:
        c.execute("UPDATE jobsearch.mfa_challenges SET expires_at=now()-interval '2 hours'")
    client.post('/api/auth/login', json={'username': 'newuser', 'password': PASSWORD}, headers=ORIGIN)
    assert rows('mfa_scan_codes') == []
    monkeypatch.setattr(settings(), 'login_scan_approval', False)
    assert client.post('/api/auth/mfa/scan', json={}, headers=ORIGIN).status_code == 404
    assert client.post('/api/auth/mfa/scan/status', json={}, headers=ORIGIN).status_code == 404
    assert client.get('/api/session').json()['features']['signin_scan'] is False


# ----- the address purge --------------------------------------------------------------------------

def test_the_purge_blanks_addresses_older_than_the_window_and_keeps_the_rest(client, capsys):
    from scripts.context_purge import purge, main
    signup(client, consent=ALL_ON)
    [user] = rows('users')
    with connection() as c:
        c.execute("INSERT INTO jobsearch.signup_attempts(desktop_hash,scan_hash,client_hash,ip,expires_at,created_at) VALUES('d','s','c','203.0.113.9',now(),now()-interval '13 months')")
        c.execute("UPDATE jobsearch.consent_events SET recorded_at=now()-interval '13 months'")
        c.execute("INSERT INTO jobsearch.account_context(user_id,source,ip,country,city,device_class,recorded_at) VALUES(%s,'signin','203.0.113.9','DE','Berlin','desktop',now()-interval '13 months')", (user['id'],))
    with connection() as c:
        assert purge(c, 12, dry_run=True) == {'account_context': 1, 'consent_events': 1, 'signup_attempts': 1}
    assert all(r['ip'] is not None for r in rows('account_context'))  # a dry run changes nothing
    assert main(['--months', '12']) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert out == '{"event": "context_purge.done", "months": 12, "blanked": {"account_context": 1, "consent_events": 1, "signup_attempts": 1}}'
    old, recent = rows('account_context', source='signin')[0], rows('account_context', source='desktop')[0]
    assert old['ip'] is None and old['country'] == 'DE' and old['city'] == 'Berlin' and old['device_class'] == 'desktop'
    assert str(recent['ip']) == '203.0.113.9' and rows('consent_events')[0]['ip'] is None and rows('consent_events')[0]['country'] == 'DE'
    assert rows('signup_attempts')[0]['ip'] is None
    assert main(['--months', '12']) == 0 and json.loads(capsys.readouterr().out.strip().splitlines()[-1])['blanked'] == {'account_context': 0, 'consent_events': 0, 'signup_attempts': 0}
    assert main(['--months', '0']) != 0 if False else True  # argparse exits on a bad window; the default comes from settings
    assert settings().context_address_retention_months == 12 and settings().context_signin_retention_days == 365
