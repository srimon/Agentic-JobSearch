from contextlib import contextmanager
from fastapi.testclient import TestClient
from src.api.main import app,current_user
from src.api import hub_access

def test_library_gateway_auth_and_csrf(monkeypatch):
    records=[]
    @contextmanager
    def conn():yield object()
    monkeypatch.setattr(hub_access,'connection',conn)
    monkeypatch.setattr(hub_access,'audit',lambda *a,**kw: records.append(kw))
    try:
        with TestClient(app) as c:
            assert c.get('/api/hub/library-authorize').status_code==401
            app.dependency_overrides[current_user]=lambda:{'id':'test-id','roles':['member']}
            assert c.get('/api/hub/library-authorize').status_code==403
            app.dependency_overrides[current_user]=lambda:{'id':'test-id','roles':['operator']}
            assert c.get('/api/hub/library-authorize').status_code==204
            assert c.get('/api/hub/library-authorize',headers={'x-original-method':'POST'}).status_code==403
            assert c.get('/api/hub/library-authorize',headers={'x-original-method':'POST','x-original-origin':'https://evil.example'}).status_code==403
            result=c.get('/api/hub/library-authorize',headers={'x-original-method':'POST','x-original-origin':'http://localhost:3001'})
            assert result.status_code==204 and result.headers['x-hub-user']=='test-id'
            assert records==[{'details':{'method':'POST'}}]
    finally:app.dependency_overrides.clear()
