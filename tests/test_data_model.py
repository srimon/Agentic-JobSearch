from contextlib import contextmanager
from types import SimpleNamespace
from fastapi.testclient import TestClient
from src.api.main import app,current_user
from src.api import data_model


def test_paths():
    for p in ('../secret','/etc/passwd','x//y','x/../y','x\\y','%2e%2e/file',''):
        assert not data_model.valid_path(p)
    assert data_model.valid_path('diagrams/summary/relationships.real.large.svg')

def test_authorization_and_assets(monkeypatch):
    class Cursor:
        def __init__(self,row):self.row=row
        def fetchone(self):return self.row
    class Conn:
        def execute(self,query,args=None):
            if 'to_regclass' in query:return Cursor({'name':'exists'})
            if 'SELECT body' in query:return Cursor({'body':b'<html>diagram</html>'} if args==('index.html',) else None)
            return Cursor({'generated_at':'2026-09-13T00:00:00Z','metadata':{'tables':2}})
    @contextmanager
    def connection():yield Conn()
    monkeypatch.setattr(data_model,'connection',connection)
    monkeypatch.setattr(data_model,'settings',lambda:SimpleNamespace(database_url='postgresql://localhost/jobsearch_staging'))
    try:
        with TestClient(app) as c:
            for path in ('/api/data-model','/api/data-model/report/index.html'):
                assert c.get(path).status_code==401
                app.dependency_overrides[current_user]=lambda:{'roles':['member']}
                assert c.get(path).status_code==403
                app.dependency_overrides.clear()
            app.dependency_overrides[current_user]=lambda:{'roles':['operator']}
            assert c.get('/api/data-model').json()['status']=='ready'
            r=c.get('/api/data-model/report/index.html');assert r.status_code==200
            assert r.headers['cache-control']=='no-store'
            assert r.headers['x-frame-options']=='SAMEORIGIN'
            assert "object-src 'self'" in r.headers['content-security-policy']
            assert "connect-src 'none'" in r.headers['content-security-policy']
            assert c.get('/api/data-model/report/missing.html').status_code==404
            monkeypatch.setattr(data_model,'settings',lambda:SimpleNamespace(database_url='postgresql://localhost/jobsearch'))
            assert c.get('/api/data-model').status_code==404
            assert c.get('/api/data-model/report/index.html').status_code==404
    finally:app.dependency_overrides.clear()
