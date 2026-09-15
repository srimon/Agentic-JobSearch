"""Monitoring and operational displays are administrator-only; viewers, members and operators are denied."""
import os
import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from src.api.main import app, current_user
from src.api import monitoring_ui, observability
from src.db.store import connection

HEADERS = {'Origin': 'http://localhost:3105'}
READS = ('/api/sources', '/api/runs', '/api/audit', '/api/collection-status', '/api/learning',
         '/api/analytics', '/api/data-quality', '/api/data-model', '/api/data-model/report/index.html', '/api/governance',
         '/api/observability/prometheus', '/api/observability/phoenix', '/api/observability/grafana',
         '/api/monitoring-status/grafana', '/api/monitoring/grafana/d/jobsearch-operations', '/api/phoenix-graphql/displays',
         '/api/jobs?view=review')
WRITES = (('post', '/api/sources', {'company': 'Example', 'provider': 'lever', 'board': 'example'}),
          ('post', '/api/sources/1/refresh', None), ('put', '/api/learning', {'action': 'pause'}))


@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    monkeypatch.setattr(monitoring_ui, 'fetch', lambda *args: Response('vendor interface', media_type='text/html'))
    monkeypatch.setattr(monitoring_ui, 'phoenix_displays', lambda hours: {'hours': hours})
    for tool in ('prometheus', 'phoenix', 'grafana'):
        monkeypatch.setattr(observability, tool, lambda: {'series': []})
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def signed_in(roles):
    with connection() as c:
        c.execute("DELETE FROM jobsearch.users WHERE subject='admin-scope-user'")
        user = c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','admin-scope-user',%s) RETURNING *", (roles,)).fetchone()
    app.dependency_overrides[current_user] = lambda: user
    return user


@pytest.mark.parametrize('roles', [['viewer'], ['member'], ['operator'], ['member', 'operator']])
def test_operational_routes_deny_non_administrators(client, roles):
    signed_in(roles)
    for path in READS:
        assert client.get(path).status_code == 403, path
    for method, path, body in WRITES:
        assert getattr(client, method)(path, json=body, headers=HEADERS).status_code == 403, path
    # The workflow status stays readable (the hub reads it) but per-source collection counts are removed.
    from src.applications.daily import publish
    user = signed_in(roles)
    publish(user['id'], {'phase': 'completed', 'counts': {'reviewed': 1}, 'source_counts': {'completed': 4}})
    latest = client.get('/api/workflow').json()['latest']
    assert latest['counts'] == {'reviewed': 1} and 'source_counts' not in latest
    # Their own job search is unaffected.
    assert client.get('/api/jobs').status_code == 200


def test_operational_routes_allow_administrators(client):
    user = signed_in(['administrator'])
    for path in READS:
        # Allowed means authorization passed; some tools answer 404/503 when not provisioned in the test environment.
        assert client.get(path).status_code not in (401, 403), path
    for path in ('/api/sources', '/api/runs', '/api/audit', '/api/collection-status', '/api/learning', '/api/jobs?view=review'):
        assert client.get(path).status_code == 200, path
    assert client.put('/api/learning', json={'action': 'pause'}, headers=HEADERS).status_code == 200
    from src.applications.daily import publish
    publish(user['id'], {'phase': 'completed', 'counts': {'reviewed': 1}, 'source_counts': {'completed': 4}})
    assert client.get('/api/workflow').json()['latest']['source_counts'] == {'completed': 4}


def test_library_gateway_authorization_is_unchanged_for_operators(client, monkeypatch):
    # /api/hub/library-authorize belongs to the hub's Library gateway and is intentionally left at operator level.
    from contextlib import contextmanager
    from src.api import hub_access
    @contextmanager
    def conn(): yield object()
    monkeypatch.setattr(hub_access, 'connection', conn)
    monkeypatch.setattr(hub_access, 'audit', lambda *a, **kw: None)
    app.dependency_overrides[current_user] = lambda: {'id': 'x', 'roles': ['operator']}
    assert client.get('/api/hub/library-authorize').status_code == 204
    app.dependency_overrides[current_user] = lambda: {'id': 'x', 'roles': ['member']}
    assert client.get('/api/hub/library-authorize').status_code == 403
