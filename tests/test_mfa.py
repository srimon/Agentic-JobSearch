"""Two-step sign-in: RFC 6238 codes, setup and enable, the login challenge, recovery codes, disable and owner reset."""
import base64
import os
import re
from pathlib import Path
import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from src.applications.private import cipher, decrypt
from src.auth import totp
from src.auth.passwords import password_hash
from src.db.store import connection
from src.settings import settings
from src.api.main import app

HEADERS = {'Origin': 'http://localhost:3105'}
PASSWORD = 'a long two step passphrase'
RFC_SECRET = base64.b32encode(b'12345678901234567890').decode()


class Clock:
    t = 1_800_000_015.0

    def step(self, n=1):
        self.t += 30 * n


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(totp, 'now', lambda: c.t)
    return c


@pytest.fixture()
def client(tmp_path, monkeypatch, clock):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    key = tmp_path / 'intake_key'
    key.write_bytes(os.urandom(32))
    monkeypatch.setenv('JOBSEARCH_INTAKE_KEY_FILE', str(key))
    cipher.cache_clear()
    monkeypatch.setattr(settings(), 'signup_enabled', True)
    with connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d'] == 'jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.users,jobsearch.sessions,jobsearch.login_limits,jobsearch.audit_events,jobsearch.auth_tokens,jobsearch.outbound_mail,jobsearch.user_mfa,jobsearch.mfa_recovery_codes,jobsearch.mfa_challenges CASCADE')
        c.execute("""INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash,email,email_verified_at)
            VALUES('local','mfauser','Two Step',ARRAY['viewer'],%s,'Two.Step@example.com',now())""", (password_hash(PASSWORD),))
    with TestClient(app) as t:
        assert login(t).status_code == 200
        yield t
    cipher.cache_clear()


def login(client, name='mfauser', password=PASSWORD):
    return client.post('/api/auth/login', json={'username': name, 'password': password}, headers=HEADERS)

def post(client, path, body):
    return client.post('/api/auth/mfa' + path, json=body, headers=HEADERS)

def outcomes(action):
    with connection() as c:
        return [r['outcome'] for r in c.execute('SELECT outcome FROM jobsearch.audit_events WHERE action=%s ORDER BY id', (action,)).fetchall()]

def user_id():
    with connection() as c:
        return c.execute("SELECT id FROM jobsearch.users WHERE subject='mfauser'").fetchone()['id']

def turn_on(client, clock):
    secret = post(client, '/setup', {'password': PASSWORD}).json()['secret']
    r = post(client, '/enable', {'code': totp.totp(secret)})
    assert r.status_code == 200
    clock.step()
    return secret, r.json()['recovery_codes']

def challenge(client):
    r = login(client)
    assert r.status_code == 200 and r.json() == {'ok': True, 'mfa_required': True, 'method': 'totp'}
    return r


def test_totp_rfc6238_sha1_vectors_and_window():
    key = b'12345678901234567890'
    vectors = {59: '94287082', 1111111109: '07081804', 1111111111: '14050471', 1234567890: '89005924',
               2000000000: '69279037', 20000000000: '65353130'}
    for at, expected in vectors.items():
        assert totp.hotp(key, at // 30, digits=8) == expected
        assert totp.totp(RFC_SECRET, at, digits=8) == expected
        assert totp.totp(RFC_SECRET, at) == expected[-6:]  # six-digit truncation of the same value
    at = 1111111111
    step = at // 30
    assert totp.matching_step(RFC_SECRET, '050471', at=at) == step
    assert totp.matching_step(RFC_SECRET, '050 471', at=at + 30) == step  # one step of drift either way
    assert totp.matching_step(RFC_SECRET, '050471', at=at - 30) == step
    assert totp.matching_step(RFC_SECRET, '050471', at=at + 60) is None
    assert totp.matching_step(RFC_SECRET, '050471', last_used_step=step, at=at) is None  # replay
    assert totp.matching_step(RFC_SECRET, '12345a', at=at) is None and totp.matching_step(RFC_SECRET, '', at=at) is None
    secret = totp.new_secret()
    assert len(totp.secret_bytes(secret)) == 20 and re.fullmatch('[A-Z2-7]{32}', secret)
    codes = totp.new_recovery_codes()
    assert len(set(codes)) == 10 and all(re.fullmatch('[2-9a-hjkmnp-z]{5}-[2-9a-hjkmnp-z]{5}', c) for c in codes)
    assert totp.recovery_hash(1, codes[0]) == totp.recovery_hash(1, codes[0].upper().replace('-', ' ')) != totp.recovery_hash(2, codes[0])


def test_setup_enable_then_login_requires_code(client, clock):
    assert client.get('/api/auth/mfa').json() == {'enabled': False, 'recovery_codes_remaining': 0}
    assert client.get('/api/auth/profile').json()['mfa_enabled'] is False
    assert post(client, '/setup', {'password': 'not the right passphrase'}).status_code == 400
    assert client.post('/api/auth/mfa/setup', json={'password': PASSWORD}).status_code == 403  # origin check
    first = post(client, '/setup', {'password': PASSWORD}).json()
    setup = post(client, '/setup', {'password': PASSWORD}).json()
    assert setup['secret'] != first['secret']
    assert setup['otpauth_uri'] == 'otpauth://totp/Bagala:mfauser?secret=' + setup['secret'] + '&issuer=Bagala&digits=6&period=30'
    assert setup['qr_svg'].startswith('<svg') and '<script' not in setup['qr_svg']
    assert post(client, '/enable', {'code': totp.totp(first['secret'])}).status_code == 400  # the earlier pending secret is gone
    with TestClient(app) as other:
        assert login(other).status_code == 200
        r = post(client, '/enable', {'code': totp.totp(setup['secret'])})
        assert r.status_code == 200
        codes = r.json()['recovery_codes']
        assert len(codes) == 10
        assert other.get('/api/auth/profile').status_code == 401 and client.get('/api/auth/profile').status_code == 200
    assert client.get('/api/auth/mfa').json() == {'enabled': True, 'recovery_codes_remaining': 10}
    assert client.get('/api/auth/profile').json()['mfa_enabled'] is True
    assert post(client, '/setup', {'password': PASSWORD}).status_code == 409
    clock.step()
    with TestClient(app) as fresh:
        r = challenge(fresh)
        assert 'jobsearch_session' not in r.cookies and r.cookies.get('jobsearch_mfa')
        cookie = r.headers['set-cookie']
        assert 'Path=/api/auth' in cookie and 'HttpOnly' in cookie and 'Max-Age=300' in cookie and 'SameSite=lax' in cookie
        assert fresh.get('/api/auth/profile').status_code == 401
        assert post(fresh, '/verify', {'code': '000000' if totp.totp(setup['secret']) != '000000' else '111111'}).status_code == 401
        ok = post(fresh, '/verify', {'code': totp.totp(setup['secret'])})
        assert ok.status_code == 200 and ok.cookies.get('jobsearch_session')
        assert fresh.get('/api/auth/profile').status_code == 200 and 'jobsearch_mfa' not in fresh.cookies
        assert post(fresh, '/verify', {'code': totp.totp(setup['secret'])}).status_code == 400  # the challenge is spent
    with connection() as c:
        audit_text = str(c.execute('SELECT * FROM jobsearch.audit_events').fetchall())
        methods = [r['details'] for r in c.execute("SELECT details FROM jobsearch.audit_events WHERE action='login' AND outcome='allowed' ORDER BY id").fetchall()]
    assert outcomes('login') == ['allowed', 'allowed', 'mfa_required'] + ['allowed']
    assert methods[-1] == {'method': 'mfa-totp'} and outcomes('login.mfa') == ['denied', 'allowed', 'expired']
    assert outcomes('account.mfa.setup') == ['denied', 'allowed', 'allowed', 'already_enabled'] and outcomes('account.mfa.enable') == ['denied', 'allowed']
    assert setup['secret'] not in audit_text and codes[0] not in audit_text and totp.totp(setup['secret']) not in audit_text


def test_wrong_code_five_times_kills_the_challenge(client, clock):
    secret, _ = turn_on(client, clock)
    with TestClient(app) as fresh:
        raw = challenge(fresh).cookies.get('jobsearch_mfa')
        good = totp.totp(secret)
        bad = '123456' if good != '123456' else '654321'
        for _ in range(4):
            assert post(fresh, '/verify', {'code': bad}).status_code == 401
        last = post(fresh, '/verify', {'code': bad})
        assert last.status_code == 400 and last.json() == {'detail': 'Your sign-in attempt expired. Enter your password again.'}
        again = fresh.post('/api/auth/mfa/verify', json={'code': good}, headers={**HEADERS, 'Cookie': 'jobsearch_mfa=' + raw})
        assert again.status_code == 400 and fresh.get('/api/auth/profile').status_code == 401
    with connection() as c:
        assert c.execute('SELECT attempts FROM jobsearch.mfa_challenges').fetchone()['attempts'] == 5
    assert outcomes('login.mfa') == ['denied'] * 4 + ['locked', 'expired']
    with TestClient(app) as nothing:
        assert post(nothing, '/verify', {'code': good}).status_code == 400  # no challenge at all
    with TestClient(app) as late:
        challenge(late)
        with connection() as c:
            c.execute("UPDATE jobsearch.mfa_challenges SET expires_at=now()-interval '1 second' WHERE attempts=0")
        assert post(late, '/verify', {'code': good}).status_code == 400


def test_challenge_verify_shares_the_account_throttle(client, clock):
    turn_on(client, clock)
    with TestClient(app) as fresh:
        challenge(fresh)  # login attempts so far: fixture 1, this one 2
        statuses = [post(fresh, '/verify', {'code': 'abcdefghjk'}).status_code for _ in range(4)]
        challenge(fresh)
        statuses += [post(fresh, '/verify', {'code': 'abcdefghjk'}).status_code for _ in range(3)]
        assert statuses == [401] * 7
        assert post(fresh, '/verify', {'code': 'abcdefghjk'}).status_code == 429


def test_replayed_code_is_rejected(client, clock):
    secret, _ = turn_on(client, clock)
    with TestClient(app) as fresh:
        challenge(fresh)
        code = totp.totp(secret)
        assert post(fresh, '/verify', {'code': code}).status_code == 200
    with TestClient(app) as attacker:
        challenge(attacker)
        assert post(attacker, '/verify', {'code': code}).status_code == 401
        clock.step(-1)
        assert post(attacker, '/verify', {'code': totp.totp(secret)}).status_code == 401  # an older step is also refused
        clock.step(2)
        assert post(attacker, '/verify', {'code': totp.totp(secret)}).status_code == 200


def test_recovery_code_works_once(client, clock):
    _, codes = turn_on(client, clock)
    with TestClient(app) as fresh:
        challenge(fresh)
        assert post(fresh, '/verify', {'recovery_code': codes[0]}).status_code == 200
        assert fresh.get('/api/auth/mfa').json() == {'enabled': True, 'recovery_codes_remaining': 9}
    with TestClient(app) as again:
        challenge(again)
        assert post(again, '/verify', {'recovery_code': codes[0]}).status_code == 401
        assert post(again, '/verify', {'recovery_code': codes[1].upper().replace('-', '')}).status_code == 200
    assert outcomes('login.mfa') == ['recovery_code', 'denied', 'recovery_code']
    with connection() as c:
        rows = c.execute('SELECT code_hash FROM jobsearch.mfa_recovery_codes').fetchall()
    assert len(rows) == 10 and all(re.fullmatch('[0-9a-f]{64}', r['code_hash']) for r in rows)
    assert not any(code.replace('-', '') in str(rows) for code in codes)


def test_new_recovery_codes_replace_old_ones(client, clock):
    secret, codes = turn_on(client, clock)
    assert post(client, '/recovery-codes', {'code': '000000' if totp.totp(secret) != '000000' else '111111'}).status_code == 400
    r = post(client, '/recovery-codes', {'code': totp.totp(secret)})
    assert r.status_code == 200 and len(r.json()['recovery_codes']) == 10 and set(r.json()['recovery_codes']).isdisjoint(codes)
    clock.step()
    with TestClient(app) as fresh:
        challenge(fresh)
        assert post(fresh, '/verify', {'recovery_code': codes[2]}).status_code == 401
        assert post(fresh, '/verify', {'recovery_code': r.json()['recovery_codes'][0]}).status_code == 200


def test_disable_requires_password_and_code(client, clock):
    secret, codes = turn_on(client, clock)
    assert post(client, '/disable', {'password': 'not the right passphrase', 'code': totp.totp(secret)}).status_code == 400
    assert post(client, '/disable', {'password': PASSWORD, 'code': '000000' if totp.totp(secret) != '000000' else '111111'}).status_code == 400
    assert post(client, '/disable', {'password': 'not the right passphrase', 'code': codes[0]}).status_code == 400
    assert client.get('/api/auth/mfa').json() == {'enabled': True, 'recovery_codes_remaining': 10}  # a refused attempt spends nothing
    assert post(client, '/disable', {'password': PASSWORD, 'code': codes[0]}).status_code == 200
    assert client.get('/api/auth/mfa').json() == {'enabled': False, 'recovery_codes_remaining': 0}
    assert post(client, '/disable', {'password': PASSWORD, 'code': codes[1]}).status_code == 409
    with connection() as c:
        assert c.execute('SELECT count(*) n FROM jobsearch.mfa_recovery_codes').fetchone()['n'] == 0
        assert c.execute('SELECT count(*) n FROM jobsearch.user_mfa').fetchone()['n'] == 0
    with TestClient(app) as fresh:
        r = login(fresh)
        assert r.status_code == 200 and r.json() == {'ok': True} and fresh.get('/api/auth/profile').status_code == 200
    assert outcomes('account.mfa.disable') == ['denied', 'denied', 'denied', 'allowed', 'not_enabled']


def test_password_reset_keeps_mfa(client, clock):
    secret, _ = turn_on(client, clock)
    assert client.post('/api/auth/reset-request', json={'email': 'two.step@example.com'}, headers=HEADERS).status_code == 202
    with connection() as c:
        mail = c.execute("SELECT text_body FROM jobsearch.outbound_mail WHERE purpose='reset'").fetchone()['text_body']
    assert 'Your username is mfauser.' in mail
    token = re.search(r'\?reset=([A-Za-z0-9_-]+)', mail).group(1)
    assert client.post('/api/auth/reset', json={'token': token, 'password': 'a fresh replacement passphrase'}, headers=HEADERS).status_code == 200
    with TestClient(app) as fresh:
        r = login(fresh, 'two.step@example.com', 'a fresh replacement passphrase')
        assert r.json() == {'ok': True, 'mfa_required': True, 'method': 'totp'}
        assert post(fresh, '/verify', {'code': totp.totp(secret)}).status_code == 200


def test_secret_is_stored_encrypted_and_bound_to_the_account(client):
    secret = post(client, '/setup', {'password': PASSWORD}).json()['secret']
    uid = user_id()
    with connection() as c:
        stored = bytes(c.execute('SELECT secret_enc FROM jobsearch.user_mfa WHERE user_id=%s', (uid,)).fetchone()['secret_enc'])
    assert secret.encode() not in stored and secret.lower().encode() not in stored and totp.secret_bytes(secret) not in stored
    assert decrypt(uid, 'mfa-totp', stored) == secret
    with pytest.raises(InvalidTag):
        decrypt(uid + 1, 'mfa-totp', stored)
    with pytest.raises(InvalidTag):
        decrypt(uid, 'profile', stored)


def test_signed_out_requests_are_refused(client):
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/auth/mfa').status_code == 401
        assert post(anonymous, '/setup', {'password': PASSWORD}).status_code == 401
        assert post(anonymous, '/enable', {'code': '123456'}).status_code == 401
        assert post(anonymous, '/recovery-codes', {'code': '123456'}).status_code == 401
        assert post(anonymous, '/disable', {'password': PASSWORD, 'code': '123456'}).status_code == 401


def test_owner_reset_script_is_a_dry_run_by_default(client, clock, capsys):
    from scripts.mfa_reset import main
    turn_on(client, clock)
    assert main(['--username', 'MFAUser']) == 0
    assert capsys.readouterr().out.strip() == 'mfauser: two-step sign-in is on; run again with --apply to turn it off'
    assert client.get('/api/auth/mfa').json()['enabled'] is True
    assert main(['--username', 'mfauser', '--apply']) == 0
    assert capsys.readouterr().out.strip() == 'mfauser: two-step sign-in turned off'
    assert client.get('/api/auth/mfa').json() == {'enabled': False, 'recovery_codes_remaining': 0}
    assert main(['--username', 'nobody-here']) == 1 and capsys.readouterr().out.strip() == 'nobody-here: account not found'
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM jobsearch.audit_events WHERE actor='local-console' AND action='account.mfa.reset'").fetchone()['n'] == 1


def test_migration_reapplies_with_grants():
    sql = (Path(__file__).resolve().parents[1] / 'src/db/016_mfa.sql').read_text()
    with connection() as c:
        c.execute(sql)
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=16').fetchone()
        for table in ('user_mfa', 'mfa_recovery_codes', 'mfa_challenges'):
            assert c.execute("SELECT has_table_privilege('jobsearch_app',%s,'INSERT') allowed", ('jobsearch.' + table,)).fetchone()['allowed']
            assert not c.execute("SELECT has_table_privilege('jobsearch_worker',%s,'SELECT') allowed", ('jobsearch.' + table,)).fetchone()['allowed']
