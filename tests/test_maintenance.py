from fastapi.testclient import TestClient
from src.api import main

def test_maintenance_blocks_mutations_before_handlers(monkeypatch):
 monkeypatch.setattr(main.cfg,'maintenance_mode',True)
 client=TestClient(main.app)
 for path,method in [('/api/sources','post'),('/api/intake','put'),('/api/jobs/00000000-0000-0000-0000-000000000000/mark-applied','post')]:
  response=getattr(client,method)(path,headers={'origin':'http://localhost:3105'},json={})
  assert response.status_code==503
  assert response.headers['retry-after']=='300'
 assert client.get('/api/session').json()['features']['maintenance'] is True
 assert client.get('/api/jobs').status_code==401
 # Session endpoints still enforce their own origin check, not a bypass.
 assert client.post('/api/auth/login',json={}).status_code==403
 assert client.post('/api/monitoring/phoenix/graphql',json={}).status_code==403
