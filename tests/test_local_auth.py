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
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
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
