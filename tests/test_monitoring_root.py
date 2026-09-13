from fastapi.testclient import TestClient
from fastapi.responses import Response
from src.api.main import app, current_user
from src.api import monitoring_ui

def test_monitoring_root_never_redirects_to_internal_api(monkeypatch):
    monkeypatch.setattr(monitoring_ui, 'fetch', lambda *args: Response('upstream HTML', media_type='text/html'))
    try:
        with TestClient(app) as client:
            for path in ('/api/monitoring/phoenix', '/api/monitoring/phoenix/'):
                assert client.get(path, follow_redirects=False).status_code == 401
            app.dependency_overrides[current_user] = lambda: {'roles': ['operator']}
            for path in ('/api/monitoring/phoenix', '/api/monitoring/phoenix/'):
                response = client.get(path, follow_redirects=False)
                assert response.status_code == 200
                assert 'location' not in response.headers
    finally:
        app.dependency_overrides.clear()
