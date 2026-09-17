import os
os.environ.setdefault('JOBSEARCH_TELEMETRY','false')
import json
import pathlib
import pytest
from fastapi.testclient import TestClient
from src.api.main import app,current_user
from src.api import observability as monitor

@pytest.fixture
def client():
    app.dependency_overrides.clear()
    with TestClient(app) as client:yield client
    app.dependency_overrides.clear()

def admin():app.dependency_overrides[current_user]=lambda:{'id':1,'roles':['administrator']}

def test_anonymous_and_member_cannot_read(client,monkeypatch):
    monkeypatch.setattr(monitor,'get_json',lambda *a,**k:pytest.fail('Unauthenticated upstream access'))
    assert client.get('/api/observability/prometheus').status_code==401
    app.dependency_overrides[current_user]=lambda:{'id':1,'roles':['member']}
    assert client.get('/api/observability/phoenix').status_code==403

def test_no_arbitrary_tools_or_mutations(client,monkeypatch):
    admin()
    monkeypatch.setattr(monitor,'get_json',lambda *a,**k:pytest.fail('Unexpected upstream access'))
    assert client.get('/api/observability/anything').status_code==422
    assert client.post('/api/observability/phoenix',headers={'origin':'http://localhost:3105'}).status_code==405

def test_missing_metrics_are_not_zero_and_targets_are_scoped(client,monkeypatch):
    admin()
    def get(tool,path,params=None):
        assert tool=='prometheus'
        if path.endswith('/targets'):return {'data':{'activeTargets':[{'labels':{'job':'jobsearch-api'},'health':'up','lastScrape':'2026-09-12T00:00:00Z','lastScrapeDuration':.02,'lastError':'private upstream detail'},{'labels':{'job':'other-app'},'health':'up'}]}}
        # One value per metric however many API copies export it.
        if path.endswith('/query'):
            assert params=={'query':'max by (__name__) ({__name__=~"jobsearch_queue_ready|jobsearch_queue_running|jobsearch_queue_oldest_seconds|jobsearch_current_matches"})'}
            return {'status':'success','data':{'result':[{'metric':{'__name__':'jobsearch_queue_ready'},'value':[1,'NaN']}]}}
        assert params['query']=='max(jobsearch_queue_ready)'
        return {'status':'success','data':{'result':[]}}
    monkeypatch.setattr(monitor,'get_json',get)
    response=client.get('/api/observability/prometheus?url=http://malicious.invalid')
    data=response.json()
    assert data['available'] and data['metrics']['jobsearch_queue_ready'] is None
    assert data['metrics']['jobsearch_queue_running'] is None and data['samples']==[]
    assert len(data['targets'])==1
    assert 'private upstream detail' not in response.text and 'other-app' not in response.text
    assert response.headers['cache-control']=='no-store'

def test_phoenix_only_returns_operational_metadata(client,monkeypatch):
    admin()
    def get(tool,path,params=None):
        assert tool=='phoenix'
        if path=='/v1/projects':return {'data':[{'name':'jobsearch'},{'name':'library'}]}
        assert path=='/v1/projects/jobsearch/traces'
        return {'data':[{'trace_id':'a'*32,'start_time':'2026-09-12T00:00:00Z','end_time':'2026-09-12T00:00:01Z','attributes':{'input.value':'private resume'},'spans':[{'name':'source.collect','parent_id':None,'status_code':'UNSET','attributes':{'secret':'private demographic'}}]}]}
    monkeypatch.setattr(monitor,'get_json',get)
    response=client.get('/api/observability/phoenix');data=response.json()
    assert data['traces'][0]['latency_ms']==1000
    assert data['traces'][0]['span_count']==1 and data['traces'][0]['status']=='UNSET'
    assert 'private' not in response.text and 'library' not in response.text

def test_phoenix_empty_and_unavailable_are_distinct(client,monkeypatch):
    admin();monkeypatch.setattr(monitor,'get_json',lambda *a,**k:{'data':[]})
    data=client.get('/api/observability/phoenix').json()
    assert data['available'] and data['traces']==[]
    def fail(*a,**k):raise RuntimeError('password=do-not-return')
    monkeypatch.setattr(monitor,'get_json',fail)
    response=client.get('/api/observability/phoenix')
    assert not response.json()['available'] and 'password' not in response.text

@pytest.mark.parametrize('status,size',[(302,0),(200,2_000_001)])
def test_redirect_and_size_boundaries(monkeypatch,status,size):
    class Response:
        status_code=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,*args):yield b'x'*size
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            assert url=='http://phoenix:6006/v1/projects'
            assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
            assert not self.trust_env
            return Response()
    monkeypatch.setattr(monitor.requests,'Session',Session)
    with pytest.raises(RuntimeError):monitor.get_json('phoenix','/v1/projects')


def test_grafana_fixed_queries_and_redacted_series(client,monkeypatch):
    admin()
    def get(tool,path,params=None):
        assert tool=='grafana'
        if path.endswith('jobsearch-operations'):
            return {'dashboard':{'title':'Jobsearch Operations','panels':[{'id':1,'title':'Opportunities','targets':[{'expr':'arbitrary-query'}]},{'id':10,'title':'Raw logs'}]}}
        assert params=={'query':'max without (instance) (jobsearch_current_matches)'}
        return {'status':'success','data':{'result':[{'metric':{'job':'jobsearch-worker','secret':'private-value'},'value':[1,'5']}]}}
    monkeypatch.setattr(monitor,'get_json',get)
    response=client.get('/api/observability/grafana');data=response.json()
    assert data['available'] and len(data['panels'])==1
    assert data['panels'][0]['series'][0]['samples'][0]['value']==5
    assert 'private-value' not in response.text

def test_grafana_availability_keeps_one_row_per_api_copy(client,monkeypatch):
    admin()
    def get(tool,path,params=None):
        if path.endswith('jobsearch-operations'):return {'dashboard':{'panels':[{'id':4,'title':'API and worker available','type':'stat'}]}}
        assert params=={'query':'up{job=~"jobsearch-.*"}'}
        return {'status':'success','data':{'result':[{'metric':{'job':'jobsearch-api','instance':'10.42.0.15:9108'},'value':[1,'1']},{'metric':{'job':'jobsearch-api','instance':'10.42.0.16:9108'},'value':[1,'0']}]}}
    monkeypatch.setattr(monitor,'get_json',get)
    series=client.get('/api/observability/grafana').json()['panels'][0]['series']
    assert [(s['name'],s['samples'][0]['value']) for s in series]==[('jobsearch-api / 10.42.0.15:9108',1),('jobsearch-api / 10.42.0.16:9108',0)]

def test_grafana_queries_mirror_the_provisioned_dashboard(monkeypatch):
    provisioned=pathlib.Path(__file__).resolve().parents[1]/'infra/observability/grafana/dashboards/jobsearch.json'
    dashboard=json.loads(provisioned.read_text())
    sent=[]
    def get(tool,path,params=None):
        if path.endswith('jobsearch-operations'):return {'dashboard':dashboard}
        sent.append(params['query'])
        return {'status':'success','data':{'result':[]}}
    monkeypatch.setattr(monitor,'get_json',get)
    monitor.grafana()
    panels={p['id']:p['targets'][0]['expr'] for p in dashboard['panels'] if p['id']!=10}
    # Panel 4 alone is narrowed to Jobsearch's own targets; every other query is the panel's.
    assert panels.pop(4)=='up'
    assert sorted(sent)==sorted(list(panels.values())+['up{job=~"jobsearch-.*"}'])

def test_grafana_panel_failure_is_explicit(client,monkeypatch):
    admin()
    def get(tool,path,params=None):
        if path.endswith('jobsearch-operations'):return {'dashboard':{'panels':[{'id':1,'title':'Opportunities'}]}}
        raise RuntimeError('secret')
    monkeypatch.setattr(monitor,'get_json',get)
    response=client.get('/api/observability/grafana')
    assert response.json()['panels'][0]['available'] is False
    assert 'secret' not in response.text
