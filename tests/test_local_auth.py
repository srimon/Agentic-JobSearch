import hashlib
import os
import pytest
from fastapi.testclient import TestClient
from src.auth.passwords import password_hash, verify
from src.db.store import connection
from src.api.main import app

@pytest.fixture()
def client():
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    with connection() as c:
        c.execute('TRUNCATE jobsearch.users,jobsearch.sessions,jobsearch.login_limits,jobsearch.audit_events CASCADE')
        c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local','tester','Tester',ARRAY['member'],%s)", (password_hash('a long test passphrase'),))
    with TestClient(app) as client:
        yield client

HEADERS={'Origin':'http://localhost:3105'}
def signin(client, password='a long test passphrase', username='tester'):
    return client.post('/api/auth/login',json={'username':username,'password':password},headers=HEADERS)

def test_passwords():
    h=password_hash('a long test passphrase')
    assert h.startswith('$argon2id$')
    assert verify('a long test passphrase',h)
    assert not verify('wrong',h)
    assert not verify('wrong',None)
    with pytest.raises(ValueError): password_hash('short')

def test_login_and_logout(client):
    assert client.get('/api/jobs').status_code==401
    r=signin(client)
    assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
    assert 'Domain=' not in r.headers['set-cookie'] and 'Secure' not in r.headers['set-cookie']
    raw=client.cookies['jobsearch_session']
    with connection() as c:
        stored=c.execute('SELECT token_hash FROM jobsearch.sessions').fetchone()['token_hash']
    assert stored==hashlib.sha256(raw.encode()).hexdigest()
    assert client.get('/api/session').json()['user']['name']=='Tester'
    assert client.post('/api/auth/logout',headers=HEADERS).status_code==200
    client.cookies.set('jobsearch_session',raw)
    assert client.get('/api/jobs').status_code==401

def test_denials_and_throttle(client):
    assert signin(client,'wrong').json()==signin(client,'wrong','unknown').json()
    for _ in range(9): signin(client,'wrong')
    assert signin(client).status_code==429
    with connection() as c:
        assert c.execute("SELECT count(*) n FROM jobsearch.audit_events WHERE outcome='denied'").fetchone()['n']>=10

def test_disabled_and_expired(client):
    signin(client)
    with connection() as c: c.execute("UPDATE jobsearch.users SET active=false WHERE subject='tester'")
    assert client.get('/api/jobs').status_code==401
    assert signin(client).status_code==401
    with connection() as c:
        c.execute('UPDATE jobsearch.users SET active=true')
        c.execute("UPDATE jobsearch.sessions SET expires_at=now()-interval '1 second'")
    assert client.get('/api/jobs').status_code==401

def test_origin_and_secret_validation(client):
    assert client.post('/api/auth/login',json={'username':'tester','password':'value'}).status_code==403
    secret='x'*129
    r=client.post('/api/auth/login',json={'username':'tester','password':secret},headers=HEADERS)
    assert r.status_code==422 and secret not in r.text
    assert client.get('/api/auth/callback').status_code==404


def test_login_records_last_login_and_prunes(client):
    with connection() as c:
        c.execute("INSERT INTO jobsearch.login_limits(bucket,attempts,window_start) VALUES('stale',3,now()-interval '2 days'),('recent',3,now()-interval '1 hour')")
        uid=c.execute("SELECT id FROM jobsearch.users WHERE subject='tester'").fetchone()['id']
        c.execute("INSERT INTO jobsearch.auth_tokens(token_hash,user_id,purpose,expires_at) VALUES('expired',%s,'verify',now()-interval '1 minute'),('live',%s,'reset',now()+interval '1 hour')",(uid,uid))
    assert signin(client).status_code==200
    with connection() as c:
        assert c.execute("SELECT last_login_at FROM jobsearch.users WHERE subject='tester'").fetchone()['last_login_at'] is not None
        buckets={r['bucket'] for r in c.execute('SELECT bucket FROM jobsearch.login_limits').fetchall()}
        assert 'stale' not in buckets and 'recent' in buckets and 'global' in buckets
        assert [r['token_hash'] for r in c.execute('SELECT token_hash FROM jobsearch.auth_tokens').fetchall()]==['live']

def test_cookie_attributes_follow_request_host(client, monkeypatch):
    from src.settings import settings
    monkeypatch.setattr(settings(),'cookie_domain','bagala.ai')
    monkeypatch.setattr(settings(),'secure_cookies',True)
    monkeypatch.setattr(settings(),'allowed_origins',['http://localhost:3105','https://jobs.bagala.ai'])
    body={'username':'tester','password':'a long test passphrase'}
    # Local development over plain HTTP: host-only cookie and no Secure flag even though secure_cookies is on.
    r=client.post('/api/auth/login',json=body,headers={**HEADERS,'Host':'localhost:3105'})
    assert r.status_code==200 and 'Domain=' not in r.headers['set-cookie'] and 'Secure' not in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
    assert 'Domain=' not in client.post('/api/auth/login',json=body,headers={**HEADERS,'Host':'notbagala.ai','X-Forwarded-Proto':'https'}).headers['set-cookie']
    # Public edge behind the gateway: shared Domain, Secure from X-Forwarded-Proto, and the deletion carries the same attributes.
    public={'Origin':'https://jobs.bagala.ai','Host':'jobs.bagala.ai','X-Forwarded-Proto':'https'}
    r=client.post('/api/auth/login',json=body,headers=public)
    cookie=r.headers['set-cookie']
    assert r.status_code==200 and 'Domain=bagala.ai' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    raw=cookie.split('jobsearch_session=')[1].split(';')[0]
    client.cookies.clear(); client.cookies.set('jobsearch_session',raw)
    r=client.post('/api/auth/logout',headers=public)
    assert r.status_code==200 and 'Domain=bagala.ai' in r.headers['set-cookie'] and 'Secure' in r.headers['set-cookie'] and 'Max-Age=0' in r.headers['set-cookie']
    # A request that is itself HTTPS needs no forwarded header; the apex host also matches the cookie domain.
    with TestClient(app,base_url='https://bagala.ai') as edge:
        cookie=edge.post('/api/auth/login',json=body,headers={'Origin':'https://jobs.bagala.ai'}).headers['set-cookie']
        assert 'Domain=bagala.ai' in cookie and 'Secure' in cookie
    monkeypatch.setattr(settings(),'cookie_samesite','strict')
    assert 'SameSite=strict' in client.post('/api/auth/login',json=body,headers=HEADERS).headers['set-cookie']

def test_allowed_origins_list(client, monkeypatch):
    from src.settings import settings
    monkeypatch.setattr(settings(),'allowed_origins',['http://localhost:3105','https://jobs.bagala.ai'])
    body={'username':'tester','password':'wrong'}
    assert client.post('/api/auth/login',json=body,headers={'Origin':'https://jobs.bagala.ai'}).status_code==401
    assert client.post('/api/auth/login',json=body,headers=HEADERS).status_code==401
    assert client.post('/api/auth/login',json=body,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/auth/login',json=body).status_code==403

def test_console_reset_revokes(client, monkeypatch):
    from scripts.accounts import main
    signin(client)
    monkeypatch.setattr('sys.argv',['accounts','reset','tester'])
    monkeypatch.setattr('getpass.getpass',lambda prompt:'a different long passphrase')
    main()
    assert client.get('/api/jobs').status_code==401
    assert signin(client).status_code==401
    assert signin(client,'a different long passphrase').status_code==200

def test_console_disable_revokes(client, monkeypatch):
    from scripts.accounts import main
    signin(client)
    monkeypatch.setattr('sys.argv',['accounts','disable','tester'])
    main()
    assert client.get('/api/jobs').status_code==401
    assert signin(client).status_code==401
