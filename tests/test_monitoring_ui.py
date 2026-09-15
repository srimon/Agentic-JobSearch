import os
os.environ.setdefault('JOBSEARCH_TELEMETRY','false')
import json
import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient
from src.api.main import app,current_user
from src.api import monitoring_ui as ui

@pytest.fixture
def client():
    app.dependency_overrides.clear()
    with TestClient(app) as c: yield c
    app.dependency_overrides.clear()

def test_access_and_headers(client,monkeypatch):
    monkeypatch.setattr(ui,'fetch',lambda *args:Response('vendor interface',media_type='text/html'))
    path='/api/monitoring/grafana/d/jobsearch-operations'
    assert client.get(path).status_code==401
    for roles in (['member'],['viewer'],['operator']):
        app.dependency_overrides[current_user]=lambda roles=roles:{'roles':roles}
        assert client.get(path).status_code==403
    app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
    r=client.get(path)
    assert r.status_code==200 and r.headers['x-frame-options']=='SAMEORIGIN'
    assert client.get('/api/not-real').headers['x-frame-options']=='DENY'
    assert client.post('/api/monitoring/grafana/api/ds/query',json={}).status_code==403

@pytest.mark.parametrize('tool,path,method,body',[
 ('unknown','','GET',b''),('grafana','../secrets','GET',b''),
 ('phoenix','%252e%252e/foo','GET',b''),('grafana','api/user','PATCH',b'{}'),
 ('prometheus','-/reload','POST',b''),('phoenix','graphql','POST',b'{"query":"mutation { deleteProject(id: 1) }"}'),
 ('phoenix','graphql','POST',b'{"query":"query { projects { id } } mutation { deleteProject(id: 1) }"}'),
 ('phoenix','graphql','POST',b'[]')])
def test_rejected(tool,path,method,body):
    with pytest.raises(HTTPException):ui.validate(tool,path,method,body)

def test_read_queries():
    ui.validate('phoenix','graphql','POST',json.dumps({'query':'query Projects { projects { id } }'}).encode())
    ui.validate('grafana','api/ds/query','POST',b'{}')
    ui.validate('prometheus','api/v1/query','GET',b'')

def test_get_graphql_cannot_bypass_mutation_guard(client,monkeypatch):
    app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
    monkeypatch.setattr(ui,'fetch',lambda *a:pytest.fail('Mutation reached upstream'))
    assert client.get('/api/monitoring/phoenix/graphql',params={'query':'mutation { __typename }'}).status_code==403

def test_unavailable_is_explicit(client,monkeypatch):
    app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
    monkeypatch.setattr(ui,'fetch',lambda *a:Response(status_code=503))
    assert client.get('/api/monitoring-status/phoenix').json()=={'available':False}

class FakeSession:
    trust_env=True
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def request(self,*args,**kwargs):
        assert self.trust_env is False
        assert kwargs['allow_redirects'] is False
        assert 'Cookie' not in kwargs['headers']
        return self.response

class Upstream:
    status_code=200
    headers={'Content-Type':'text/html','Set-Cookie':'secret=must-not-forward'}
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def iter_content(self,size):yield b'vendor page'

def test_proxy_bounds_headers_and_redirects(monkeypatch):
    session=FakeSession();session.response=Upstream()
    monkeypatch.setattr(ui.requests,'Session',lambda:session)
    r=ui.fetch('phoenix','projects','','GET',b'')
    assert r.body==b'vendor page' and 'set-cookie' not in r.headers
    assert r.headers['content-security-policy']=="frame-ancestors 'self'"
    session.response.headers={'Location':'https://untrusted.invalid/'}
    with pytest.raises(HTTPException) as error:ui.fetch('phoenix','','','GET',b'')
    assert error.value.status_code==502
    session.response.headers={}
    monkeypatch.setattr(ui,'MAX_RESPONSE',3)
    with pytest.raises(HTTPException) as error:ui.fetch('phoenix','','','GET',b'')
    assert error.value.status_code==502

def test_monitoring_does_not_trace_itself(client,monkeypatch):
    import src.api.main as main
    app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
    monkeypatch.setattr(ui,'fetch',lambda *args:Response('vendor interface'))
    monkeypatch.setattr(main.trace,'get_tracer',lambda *a:pytest.fail('Monitoring created a self trace'))
    assert client.get('/api/monitoring/phoenix/projects').status_code==200
    assert client.get('/api/monitoring-status/phoenix').status_code==200
    monkeypatch.setattr(ui,'phoenix_displays',lambda hours:{'hours':hours})
    assert client.get('/api/phoenix-graphql/displays').status_code==200

def test_graphql_displays_require_administrator_and_fixed_range(client,monkeypatch):
    monkeypatch.setattr(ui,'phoenix_displays',lambda hours:{'hours':hours})
    assert client.get('/api/phoenix-graphql/displays').status_code==401
    for roles in (['member'],['operator']):
        app.dependency_overrides[current_user]=lambda roles=roles:{'roles':roles}
        assert client.get('/api/phoenix-graphql/displays').status_code==403
    app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
    assert client.get('/api/phoenix-graphql/displays').json()['hours']==24
    assert client.get('/api/phoenix-graphql/displays?hours=168').json()['hours']==168
    assert client.get('/api/phoenix-graphql/displays?hours=1').status_code==422

def test_graphql_display_query_avoids_private_content():
    assert 'input {' not in ui.DISPLAY_QUERY and 'output {' not in ui.DISPLAY_QUERY
    assert 'attributes' not in ui.DISPLAY_QUERY and 'metadata' not in ui.DISPLAY_QUERY
    assert 'sort: {col: startTime, dir: desc}' in ui.DISPLAY_QUERY
