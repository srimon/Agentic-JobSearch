from contextlib import contextmanager
from types import SimpleNamespace
from fastapi.testclient import TestClient
from src.api.main import app,current_user
from src.api import governance

def test_governance_scope_permissions_and_missing_snapshot(monkeypatch):
    class Cursor:
        def fetchone(self):return {'name':None}
    class Conn:
        def execute(self,*args):return Cursor()
    @contextmanager
    def connection():yield Conn()
    monkeypatch.setattr(governance,'connection',connection)
    monkeypatch.setattr(governance,'settings',lambda:SimpleNamespace(data_management_enabled=True))
    try:
        with TestClient(app) as client:
            assert client.get('/api/governance').status_code==401
            for roles in (['member'],['operator']):
                app.dependency_overrides[current_user]=lambda roles=roles:{'roles':roles}
                assert client.get('/api/governance').status_code==403
            app.dependency_overrides[current_user]=lambda:{'roles':['administrator']}
            assert client.get('/api/governance').json()=={'status':'not_generated'}
            monkeypatch.setattr(governance,'settings',lambda:SimpleNamespace(data_management_enabled=False))
            assert client.get('/api/governance').status_code==404
    finally:app.dependency_overrides.clear()
