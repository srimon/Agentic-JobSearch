from contextlib import contextmanager
from types import SimpleNamespace
from fastapi.testclient import TestClient
from src.api.main import app, current_user
from src.api import data_quality


def test_quality_auth_scope_and_missing_schema(monkeypatch):
    class Cursor:
        def fetchone(self): return {'name': None}
    class Conn:
        def execute(self, *args): return Cursor()
    @contextmanager
    def connection(): yield Conn()
    monkeypatch.setattr(data_quality, 'connection', connection)
    monkeypatch.setattr(data_quality, 'settings', lambda: SimpleNamespace(database_url='postgresql://localhost/jobsearch_staging'))
    try:
        with TestClient(app) as c:
            assert c.get('/api/data-quality').status_code == 401
            for roles in (['member'], ['operator']):
                app.dependency_overrides[current_user] = lambda roles=roles: {'roles': roles}
                assert c.get('/api/data-quality').status_code == 403
            app.dependency_overrides[current_user] = lambda: {'roles': ['administrator']}
            response=c.get('/api/data-quality')
            assert response.status_code == 200
            assert response.json()['runs'] == []
            assert response.json()['adapters']['soda'] == 'not_verified'
            assert response.json()['adapters']['dbt'] == 'not_verified'
            assert response.json()['adapters']['slack'] == 'disabled'
            monkeypatch.setattr(data_quality, 'settings', lambda: SimpleNamespace(database_url='postgresql://localhost/jobsearch'))
            assert c.get('/api/data-quality').status_code == 404
    finally: app.dependency_overrides.clear()
