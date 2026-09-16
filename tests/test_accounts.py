"""Self-service accounts: enumeration-safe sign-up, tokens, profile endpoints, the mail queue and its transports."""
import hashlib
import json
import os
import re
import urllib.error
from contextlib import contextmanager
from pathlib import Path
import psycopg.errors
import pytest
from fastapi.testclient import TestClient
from src.auth.passwords import password_hash
from src.db.store import connection
from src.settings import settings, Settings
from src.api.main import app, current_user
from src.api import hub_access
from src import mail as mailer

HEADERS={'Origin':'http://localhost:3105'}
PASSWORD='a brand new long passphrase'
CONSOLE_PASSWORD='a long test passphrase'

@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST')=='1','Use a dedicated test database'
    monkeypatch.setattr(settings(),'signup_enabled',True)
    with connection() as c:
        c.execute('TRUNCATE jobsearch.users,jobsearch.sessions,jobsearch.login_limits,jobsearch.audit_events,jobsearch.auth_tokens,jobsearch.outbound_mail CASCADE')
        c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local','console','Console',ARRAY['member'],%s)",(password_hash(CONSOLE_PASSWORD),))
    with TestClient(app) as client:
        yield client

def signup(client,username='newuser',email='New.User@Example.com',password=PASSWORD,display_name='New User'):
    return client.post('/api/auth/signup',json={'username':username,'email':email,'password':password,'display_name':display_name},headers=HEADERS)

def login(client,username='newuser',password=PASSWORD):
    return client.post('/api/auth/login',json={'username':username,'password':password},headers=HEADERS)

def verify(client,token):
    return client.post('/api/auth/verify',json={'token':token},headers=HEADERS)

def queued(purpose=None):
    with connection() as c:
        if purpose: return c.execute('SELECT * FROM jobsearch.outbound_mail WHERE purpose=%s ORDER BY id',(purpose,)).fetchall()
        return c.execute('SELECT * FROM jobsearch.outbound_mail ORDER BY id').fetchall()

def token_from(row,kind):
    return re.search(r'\?'+kind+r'=([A-Za-z0-9_-]+)',row['text_body']).group(1)

def outcomes(action):
    with connection() as c:
        return [r['outcome'] for r in c.execute('SELECT outcome FROM jobsearch.audit_events WHERE action=%s ORDER BY id',(action,)).fetchall()]

def signed_up_and_verified(client):
    signup(client)
    assert verify(client,token_from(queued('verify')[0],'verify')).status_code==200
    assert login(client).status_code==200


def test_signup_creates_unverified_user_and_queues_mail(client):
    r=signup(client)
    assert r.status_code==202 and r.json()=={'detail':'check your email'}
    with connection() as c:
        user=c.execute("SELECT * FROM jobsearch.users WHERE subject='newuser'").fetchone()
    assert user['email']=='New.User@example.com' and user['email_verified_at'] is None and user['roles']==['member']  # a new account can open every product
    assert user['active'] and user['display_name']=='New User' and user['created_at'] and user['password_hash'].startswith('$argon2id$')
    rows=queued('verify')
    assert len(rows)==1 and rows[0]['to_address']=='New.User@example.com' and rows[0]['status']=='queued' and rows[0]['attempts']==0
    token=token_from(rows[0],'verify')
    assert 'http://localhost:3105/?verify='+token in rows[0]['text_body'] and token in rows[0]['html_body'] and rows[0]['subject']
    with connection() as c:
        stored=c.execute("SELECT token_hash,purpose,used_at,expires_at>now()+interval '23 hours' AS long FROM jobsearch.auth_tokens").fetchone()
        audit_text=str(c.execute('SELECT * FROM jobsearch.audit_events').fetchall())
    assert stored['purpose']=='verify' and stored['long'] and stored['used_at'] is None
    assert stored['token_hash']==hashlib.sha256(token.encode()).hexdigest()
    assert 'example.com' not in audit_text.lower() and token not in audit_text
    assert client.get('/api/session').json()['signup_enabled'] is True

def test_duplicate_email_mails_the_owner_and_taken_username_is_409(client):
    first=signup(client)
    same_email=signup(client,username='another',email='  new.user@EXAMPLE.com ')
    assert (same_email.status_code,same_email.json())==(first.status_code,first.json())==(202,{'detail':'check your email'})
    with connection() as c:
        assert c.execute('SELECT count(*) n FROM jobsearch.users').fetchone()['n']==2
        assert not c.execute("SELECT 1 FROM jobsearch.users WHERE subject='another'").fetchone()
    notices=queued('account_exists')
    assert len(notices)==1 and notices[0]['to_address']=='New.User@example.com' and notices[0]['subject']=='You already have a Bagala account'
    body=notices[0]['text_body']
    assert 'newuser' in body and 'http://localhost:3105/' in body and 'http://localhost:3105/?forgot=1' in body and 'newuser' in notices[0]['html_body']
    assert '?verify=' not in body and '?reset=' not in body and len(queued('verify'))==1
    # Usernames are public: a taken one is named, and the reply is identical whether or not the email is also in use.
    taken=signup(client,username='NewUser',email='other@example.com')
    taken_both=signup(client,username='newuser',email='new.user@example.com')
    assert (taken.status_code,taken.json())==(taken_both.status_code,taken_both.json())==(409,{'detail':'That username is taken'})
    with connection() as c:
        assert c.execute('SELECT count(*) n FROM jobsearch.users').fetchone()['n']==2
    assert len(queued('account_exists'))==2
    # Notices share the per-address mail budget (3 per 15 minutes) with resend and reset mail.
    for name in ('third','fourth'):
        assert signup(client,username=name,email='NEW.USER@example.com').status_code==202
    assert len(queued('account_exists'))==3
    with connection() as c:
        details=[r['details'] for r in c.execute("SELECT details FROM jobsearch.audit_events WHERE action='account.signup' ORDER BY id").fetchall()]
        audit_text=str(c.execute('SELECT * FROM jobsearch.audit_events').fetchall()).lower()
    assert outcomes('account.signup')==['allowed','duplicate','username_taken','username_taken','duplicate','duplicate']
    assert details[1]=={'email_in_use':True,'mail':'queued'} and details[2]=={'email_in_use':False,'mail':'none'} and details[-1]['mail']=='throttled'
    assert 'example.com' not in audit_text
    assert signup(client,username='fifth',email='new.user@example.com').status_code==429

def test_login_accepts_username_or_email_with_one_budget(client):
    signed_up_and_verified(client)
    client.cookies.clear()
    assert login(client,'  NEW.user@Example.COM ').status_code==200
    client.cookies.clear()
    wrong=login(client,'new.user@example.com','a wrong but long passphrase')
    assert wrong.status_code==401 and wrong.json()=={'detail':'Invalid username, email or password'}
    assert login(client,'nobody@example.com').json()=={'detail':'Invalid username, email or password'}
    assert login(client,'newuser','a wrong but long passphrase').status_code==401
    bucket='user:'+hashlib.sha256(b'newuser').hexdigest()
    with connection() as c:
        assert c.execute('SELECT attempts FROM jobsearch.login_limits WHERE bucket=%s',(bucket,)).fetchone()['attempts']==4
    # Alternating the username and the email cannot double the per-account budget of 10.
    for n in range(6):
        assert login(client,'newuser' if n%2 else 'New.User@example.com','a wrong but long passphrase').status_code==401
    assert login(client,'new.user@example.com').status_code==429 and login(client).status_code==429
    # Older usernames that contain '@' still sign in when no account has that email address.
    with connection() as c:
        c.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local','legacy@name.example','Legacy',ARRAY['member'],%s)",(password_hash(CONSOLE_PASSWORD),))
    assert login(client,'Legacy@Name.example',CONSOLE_PASSWORD).status_code==200

def test_signup_disabled_validation_and_throttle(client,monkeypatch):
    monkeypatch.setattr(settings(),'signup_enabled',False)
    assert signup(client).status_code==404
    assert client.get('/api/session').json()['signup_enabled'] is False
    monkeypatch.setattr(settings(),'signup_enabled',True)
    assert signup(client,password='short').status_code==422
    assert signup(client,email='not-an-address').status_code==422
    assert signup(client,username='x').status_code==422
    assert client.post('/api/auth/signup',json={'username':'u','email':'a@b.co','password':PASSWORD}).status_code==403
    assert len(queued())==0
    for n in range(5):
        assert signup(client,username='user'+str(n),email='same@example.com').status_code==202
    r=signup(client,username='user6',email='same@example.com')
    assert r.status_code==429 and r.headers['retry-after']=='900'
    assert outcomes('account.signup')[-1]=='throttled'

def test_verify_is_single_use_and_expires(client):
    signup(client)
    token=token_from(queued('verify')[0],'verify')
    denied=login(client)
    assert denied.status_code==403 and denied.json()=={'detail':'Verify your email address before signing in.'}
    assert login(client,'console',CONSOLE_PASSWORD).status_code==200  # console accounts have no email and sign in as before
    client.cookies.clear()
    assert verify(client,'not-a-token').status_code==400
    assert verify(client,token).status_code==200
    assert verify(client,token).status_code==400 and verify(client,token).json()=={'detail':'invalid or expired token'}
    assert login(client).status_code==200
    assert outcomes('login')==['unverified','allowed','allowed'] and outcomes('account.verify')==['denied','allowed','denied','denied']
    client.cookies.clear()
    signup(client,username='late',email='late@example.com')
    late=token_from(queued('verify')[1],'verify')
    with connection() as c:
        c.execute("UPDATE jobsearch.auth_tokens SET expires_at=now()-interval '1 second' WHERE user_id=(SELECT id FROM jobsearch.users WHERE subject='late')")
    assert verify(client,late).status_code==400

def test_resend_reissues_only_for_unverified_accounts(client):
    signup(client)
    unknown=client.post('/api/auth/resend',json={'email':'nobody@example.com'},headers=HEADERS)
    known=client.post('/api/auth/resend',json={'email':'new.user@example.com'},headers=HEADERS)
    assert unknown.status_code==known.status_code==202 and unknown.json()==known.json()
    rows=queued('verify')
    assert len(rows)==2 and rows[1]['to_address']=='New.User@example.com'
    assert verify(client,token_from(rows[0],'verify')).status_code==400  # a new link retires the old one
    assert verify(client,token_from(rows[1],'verify')).status_code==200
    assert client.post('/api/auth/resend',json={'email':'new.user@example.com'},headers=HEADERS).status_code==202
    assert len(queued('verify'))==2
    assert outcomes('account.resend')==['ignored','queued','ignored']
    for _ in range(3): client.post('/api/auth/resend',json={'email':'bomb@example.com'},headers=HEADERS)
    assert client.post('/api/auth/resend',json={'email':'bomb@example.com'},headers=HEADERS).status_code==429

def test_reset_request_and_reset_revoke_sessions(client):
    signed_up_and_verified(client)
    assert client.get('/api/auth/profile').status_code==200
    unknown=client.post('/api/auth/reset-request',json={'email':'nobody@example.com'},headers=HEADERS)
    known=client.post('/api/auth/reset-request',json={'email':'new.user@example.com'},headers=HEADERS)
    assert unknown.status_code==known.status_code==202 and unknown.json()==known.json()
    rows=queued('reset')
    assert len(rows)==1 and '/?reset=' in rows[0]['text_body'] and 'Your username is newuser.' in rows[0]['text_body']
    token=token_from(rows[0],'reset')
    with connection() as c:
        assert c.execute("SELECT expires_at<=now()+interval '61 minutes' AS short FROM jobsearch.auth_tokens WHERE purpose='reset'").fetchone()['short']
    assert client.post('/api/auth/reset',json={'token':token,'password':'short'},headers=HEADERS).status_code==422
    assert client.post('/api/auth/reset',json={'token':'wrong','password':'another very long passphrase'},headers=HEADERS).status_code==400
    assert client.post('/api/auth/reset',json={'token':token,'password':'another very long passphrase'},headers=HEADERS).status_code==200
    assert client.get('/api/auth/profile').status_code==401
    assert client.post('/api/auth/reset',json={'token':token,'password':'another very long passphrase'},headers=HEADERS).status_code==400
    assert login(client).status_code==401 and login(client,password='another very long passphrase').status_code==200
    assert outcomes('account.reset')==['denied','allowed','denied']
    # A reset link also proves control of an unverified address.
    client.cookies.clear()
    signup(client,username='fresh',email='fresh@example.com')
    client.post('/api/auth/reset-request',json={'email':'fresh@example.com'},headers=HEADERS)
    assert client.post('/api/auth/reset',json={'token':token_from(queued('reset')[1],'reset'),'password':'yet another long passphrase'},headers=HEADERS).status_code==200
    assert login(client,'fresh','yet another long passphrase').status_code==200

def test_profile_password_and_sessions(client):
    signed_up_and_verified(client)
    profile=client.get('/api/auth/profile').json()
    assert profile['username']=='newuser' and profile['email']=='New.User@example.com' and profile['email_verified'] is True
    assert profile['roles']==['member'] and profile['created_at'] and profile['last_login_at'] and 'password_hash' not in profile
    with TestClient(app) as other:
        assert login(other).status_code==200
        listed=client.get('/api/auth/sessions').json()
        assert len(listed)==2 and [s['current'] for s in listed].count(True)==1 and all(s['created_at'] and s['expires_at'] for s in listed)
        assert client.post('/api/auth/password',json={'current':'wrong password value','new':'a replacement long passphrase'},headers=HEADERS).status_code==400
        assert client.post('/api/auth/password',json={'current':PASSWORD,'new':'short'},headers=HEADERS).status_code==422
        assert client.post('/api/auth/password',json={'current':PASSWORD,'new':'a replacement long passphrase'},headers=HEADERS).status_code==200
        assert other.get('/api/auth/profile').status_code==401 and client.get('/api/auth/profile').status_code==200
        assert login(other).status_code==401 and login(other,password='a replacement long passphrase').status_code==200
        r=client.post('/api/auth/sessions/revoke-all',json={},headers=HEADERS)
        assert r.status_code==200 and r.json()['revoked']==1
        assert other.get('/api/auth/profile').status_code==401 and len(client.get('/api/auth/sessions').json())==1
    assert client.patch('/api/auth/profile',json={'display_name':'  Renamed   User '},headers=HEADERS).status_code==200
    assert client.get('/api/auth/profile').json()['display_name']=='Renamed User'
    assert client.get('/api/session').json()['user']['name']=='Renamed User'
    assert client.patch('/api/auth/profile',json={'display_name':'   '},headers=HEADERS).status_code==422
    assert client.patch('/api/auth/profile',json={'email':'changed@example.org'},headers=HEADERS).status_code==200
    profile=client.get('/api/auth/profile').json()
    assert profile['email']=='changed@example.org' and profile['email_verified'] is False
    assert len(queued('verify'))==2 and queued('verify')[1]['to_address']=='changed@example.org'
    assert login(client,password='a replacement long passphrase').status_code==403
    with connection() as c:
        c.execute("INSERT INTO jobsearch.users(issuer,subject,email,email_verified_at) VALUES('local','taken','Taken@example.org',now())")
    duplicate=client.patch('/api/auth/profile',json={'email':'taken@example.org'},headers=HEADERS)
    assert duplicate.status_code==200 and duplicate.json()=={'ok':True}
    assert client.get('/api/auth/profile').json()['email']=='changed@example.org' and len(queued('verify'))==2
    assert outcomes('account.profile')==['allowed','allowed','duplicate']

def test_hub_origins_cors_session_links_and_library_origins(client,monkeypatch):
    monkeypatch.setattr(settings(),'hub_origins',['https://hub.bagala.ai'])
    monkeypatch.setattr(settings(),'cookie_domain','bagala.ai')
    monkeypatch.setattr(settings(),'library_origins',['https://library.bagala.ai'])
    records=[]
    @contextmanager
    def conn(): yield object()
    monkeypatch.setattr(hub_access,'connection',conn)
    monkeypatch.setattr(hub_access,'audit',lambda *a,**kw: records.append(kw))
    app.dependency_overrides[current_user]=lambda:{'id':1,'roles':['administrator'],'display_name':'T'}
    try:
        r=client.get('/api/workflow',headers={'Origin':'https://hub.bagala.ai'})
        assert r.status_code==200 and r.headers['access-control-allow-origin']=='https://hub.bagala.ai' and r.headers['access-control-allow-credentials']=='true'
        assert 'access-control-allow-origin' not in client.get('/api/workflow',headers={'Origin':'http://localhost:3180'}).headers
        assert client.get('/api/hub/library-authorize',headers={'x-original-method':'POST','x-original-origin':'http://localhost:3001'}).status_code==403
        assert client.get('/api/hub/library-authorize',headers={'x-original-method':'POST','x-original-origin':'https://library.bagala.ai'}).status_code==204
        assert records==[{'details':{'method':'POST'}}]
    finally:
        app.dependency_overrides.clear()
    local=client.get('/api/session').json()
    assert local['links']==settings().hub_links_local and local['links']['hub']=='http://localhost:3180/'
    public=client.get('/api/session',headers={'Host':'jobs.bagala.ai'}).json()
    # The Library is advertised at its short path on the shared host (library.bagala.ai still serves it).
    assert public['links']==settings().hub_links_public and public['links']['library']=='https://bagala.ai/library/reader'
    # Job Prep is advertised at its short path on the shared host. The trailing slash matters:
    # prepStartUrl (frontend/app/session.ts) appends 'start?role=…' to this value, so the
    # "Prepare for this job" hand-off lands on https://bagala.ai/jobprep/start?role=…
    assert public['links']['prep']=='https://bagala.ai/jobprep/' and public['links']['prep'].endswith('/')
    assert client.get('/api/session',headers={'Host':'notbagala.ai'}).json()['links']==settings().hub_links_local

def test_mailer_log_transport_marks_sent(client,capsys):
    with connection() as c:
        mailer.queue_mail(c,'verify','person@example.com','Subject','text body with token SECRETTOKEN','<p>x</p>')
    with connection() as c:
        assert mailer.deliver_pending(c,'log')==1
    out=capsys.readouterr().out
    assert json.loads(out.strip().splitlines()[-1])=={'event':'mail.sent','purpose':'verify','to_domain':'example.com','transport':'log'}
    assert 'person@' not in out and 'SECRETTOKEN' not in out
    row=queued()[0]
    assert row['status']=='sent' and row['sent_at'] and row['attempts']==1 and row['last_error'] is None
    with connection() as c:
        assert mailer.deliver_pending(c,'log')==0

class FakeResponse:
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.body

def test_mailer_resend_transport(client,monkeypatch,tmp_path,capsys):
    key_file=tmp_path/'api.key'
    key_file.write_text('re_test_key_value\n')
    monkeypatch.setattr(settings(),'resend_api_key_file',str(key_file))
    monkeypatch.setattr(settings(),'mail_from','Bagala <no-reply@bagala.ai>')
    calls=[]
    def fake_urlopen(request,timeout=None):
        calls.append(request)
        return FakeResponse(b'{"id":"provider-123"}')
    monkeypatch.setattr(mailer.urllib.request,'urlopen',fake_urlopen)
    with connection() as c:
        mailer.queue_mail(c,'reset','person@example.com','Subject','text body','<p>x</p>')
    with connection() as c:
        assert mailer.deliver_pending(c,'resend')==1
    request=calls[0]
    headers={k.lower():v for k,v in request.header_items()}
    assert request.full_url=='https://api.resend.com/emails' and request.get_method()=='POST'
    assert headers['authorization']=='Bearer re_test_key_value' and headers['content-type']=='application/json' and headers['idempotency-key']
    assert json.loads(request.data)=={'from':'Bagala <no-reply@bagala.ai>','to':['person@example.com'],'subject':'Subject','text':'text body','html':'<p>x</p>'}
    row=queued()[0]
    assert row['status']=='sent' and row['provider_id']=='provider-123' and row['attempts']==1
    out=capsys.readouterr().out
    assert 're_test_key_value' not in out and 'person@' not in out and 're_test_key_value' not in str(row)

def test_mailer_retries_then_fails(client,monkeypatch,tmp_path,capsys):
    key_file=tmp_path/'api.key'
    key_file.write_text('re_test_key_value')
    monkeypatch.setattr(settings(),'resend_api_key_file',str(key_file))
    def failing(request,timeout=None):
        raise urllib.error.HTTPError(request.full_url,500,'Server Error: person@example.com',{},None)
    monkeypatch.setattr(mailer.urllib.request,'urlopen',failing)
    with connection() as c:
        mailer.queue_mail(c,'verify','person@example.com','Subject','text body')
    for attempt in range(1,6):
        with connection() as c:
            assert mailer.deliver_pending(c,'resend',backoff_seconds=0)==0
        row=queued()[0]
        assert row['attempts']==attempt and row['last_error']=='HTTP 500' and row['status']==('failed' if attempt==5 else 'queued')
    with connection() as c:
        mailer.deliver_pending(c,'resend',backoff_seconds=0)
    assert queued()[0]['attempts']==5
    out=capsys.readouterr().out
    assert 'person@' not in out and 're_test_key_value' not in out and '"event": "mail.failed"' in out
    # A failed attempt waits attempts x backoff before the next try; other error classes are recorded by name only.
    def unreachable(request,timeout=None): raise urllib.error.URLError('proxy down for person@example.com')
    monkeypatch.setattr(mailer.urllib.request,'urlopen',unreachable)
    with connection() as c:
        mailer.queue_mail(c,'verify','second@example.com','Subject','text body')
    with connection() as c:
        mailer.deliver_pending(c,'resend',backoff_seconds=0)
    with connection() as c:
        mailer.deliver_pending(c,'resend',backoff_seconds=3600)
    row=queued()[1]
    assert row['attempts']==1 and row['last_error']=='URLError' and row['status']=='queued'

def test_mailer_once_touches_heartbeat_and_reports_failures(client,monkeypatch,tmp_path):
    from scripts import mailer as loop
    monkeypatch.setenv('JOBSEARCH_MAILER_HEARTBEAT',str(tmp_path/'heartbeat'))
    monkeypatch.setattr(settings(),'mail_transport','log')
    with connection() as c:
        mailer.queue_mail(c,'verify','person@example.com','Subject','text body')
    assert loop.main(['--once'])==0
    assert (tmp_path/'heartbeat').exists() and queued()[0]['status']=='sent'
    @contextmanager
    def broken():
        raise RuntimeError('database unavailable')
        yield
    monkeypatch.setattr(loop,'connection',broken)
    (tmp_path/'heartbeat').unlink()
    assert loop.main(['--once'])==1 and not (tmp_path/'heartbeat').exists()

def test_console_roles_email_and_verify(client,monkeypatch):
    from scripts.accounts import main
    monkeypatch.setattr('sys.argv',['accounts','roles','console','--roles','operator','member'])
    main()
    with connection() as c:
        assert c.execute("SELECT roles FROM jobsearch.users WHERE subject='console'").fetchone()['roles']==['operator','member']
    monkeypatch.setattr('sys.argv',['accounts','roles','console'])
    with pytest.raises(SystemExit): main()
    monkeypatch.setattr('sys.argv',['accounts','email','console','Console@Example.com'])
    main()
    rows=queued('verify')
    assert len(rows)==1 and rows[0]['to_address']=='Console@example.com'
    assert login(client,'console',CONSOLE_PASSWORD).status_code==403
    monkeypatch.setattr('sys.argv',['accounts','verify','console'])
    main()
    assert login(client,'console',CONSOLE_PASSWORD).status_code==200
    with connection() as c:
        c.execute("INSERT INTO jobsearch.users(issuer,subject,email) VALUES('local','other','other@example.com')")
    monkeypatch.setattr('sys.argv',['accounts','email','console','other@example.com'])
    with pytest.raises(SystemExit): main()
    with connection() as c:
        assert c.execute("SELECT email FROM jobsearch.users WHERE subject='console'").fetchone()['email']=='Console@example.com'
        assert [r['action'] for r in c.execute("SELECT action FROM jobsearch.audit_events WHERE actor='local-console' ORDER BY id").fetchall()]==['account.roles','account.email','account.verify']

def test_migration_reapplies_and_enforces_constraints(client):
    sql=(Path(__file__).resolve().parents[1]/'src/db/015_accounts.sql').read_text()
    with connection() as c:
        c.execute(sql)
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=15').fetchone()
        for table in ('auth_tokens','outbound_mail'):
            assert not c.execute("SELECT has_table_privilege('jobsearch_worker',%s,'SELECT') allowed",('jobsearch.'+table,)).fetchone()['allowed']
            assert c.execute("SELECT has_table_privilege('jobsearch_app',%s,'INSERT') allowed",('jobsearch.'+table,)).fetchone()['allowed']
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection() as c:
            c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','bad',ARRAY['root'])")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with connection() as c:
            c.execute("INSERT INTO jobsearch.users(issuer,subject,email) VALUES('local','e1','Same@Example.com'),('local','e2','same@example.com')")
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection() as c:
            c.execute("INSERT INTO jobsearch.outbound_mail(purpose,to_address,subject,text_body,status) VALUES('x','a@b.co','s','t','lost')")

def test_settings_parse_lists_json_and_defaults(monkeypatch):
    monkeypatch.setenv('JOBSEARCH_ALLOWED_ORIGINS','http://localhost:3105, https://jobs.bagala.ai/')
    monkeypatch.setenv('JOBSEARCH_HUB_ORIGINS','https://hub.bagala.ai')
    monkeypatch.setenv('JOBSEARCH_PUBLIC_ORIGIN','https://jobs.bagala.ai')
    monkeypatch.setenv('JOBSEARCH_HUB_LINKS_PUBLIC','{"hub":"https://hub.example/"}')
    monkeypatch.setenv('JOBSEARCH_SIGNUP_DEFAULT_ROLES','viewer,member')
    monkeypatch.setenv('JOBSEARCH_COOKIE_DOMAIN','.Bagala.ai')
    monkeypatch.setenv('JOBSEARCH_COOKIE_SAMESITE','Lax')
    monkeypatch.delenv('JOBSEARCH_SECURE_COOKIES',raising=False)
    s=Settings(_env_file=None)
    assert s.allowed_origins==['http://localhost:3105','https://jobs.bagala.ai'] and s.hub_origins==['https://hub.bagala.ai']
    assert s.secure_cookies is True and s.cookie_domain=='bagala.ai' and s.cookie_samesite=='lax' and s.public_origin=='https://jobs.bagala.ai'
    assert s.hub_links_public=={'hub':'https://hub.example/'} and s.hub_links_local['prep']=='http://localhost:3188/' and s.signup_default_roles==['viewer','member']
    assert s.mail_transport=='log' and s.resend_api_key_file=='/run/secrets/resend/api.key' and s.owner_username=='admin' and s.signup_enabled is False
    monkeypatch.delenv('JOBSEARCH_ALLOWED_ORIGINS')
    assert Settings(_env_file=None).allowed_origins==['http://localhost:3105','https://jobs.bagala.ai']
    monkeypatch.delenv('JOBSEARCH_PUBLIC_ORIGIN')
    s=Settings(_env_file=None)
    assert s.public_origin=='http://localhost:3105' and s.secure_cookies is False and s.allowed_origins==['http://localhost:3105']
    monkeypatch.setenv('JOBSEARCH_SIGNUP_DEFAULT_ROLES','root')
    with pytest.raises(ValueError): Settings(_env_file=None)
