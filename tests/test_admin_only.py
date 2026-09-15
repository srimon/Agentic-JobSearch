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


def test_library_gateway_operations_are_administrator_only_and_the_reader_is_for_everyone(client, monkeypatch):
    # /api/hub/library-authorize: the Library's monitoring and operations follow the same rule as Job Search's
    # (tests/test_library_access.py covers the full path policy).
    from contextlib import contextmanager
    from src.api import hub_access
    @contextmanager
    def conn(): yield object()
    monkeypatch.setattr(hub_access, 'connection', conn)
    monkeypatch.setattr(hub_access, 'audit', lambda *a, **kw: None)
    for roles in (['viewer'], ['member'], ['operator']):
        app.dependency_overrides[current_user] = lambda roles=roles: {'id': 'x', 'roles': roles}
        assert client.get('/api/hub/library-authorize', headers={'x-original-uri': '/reader/operations'}).status_code == 403
        assert client.get('/api/hub/library-authorize', headers={'x-original-uri': '/reader'}).status_code == 204
    app.dependency_overrides[current_user] = lambda: {'id': 'x', 'roles': ['administrator']}
    assert client.get('/api/hub/library-authorize', headers={'x-original-uri': '/reader/operations'}).status_code == 204


def test_ranking_explanation_is_administrator_only(client):
    import uuid
    job = uuid.uuid4()
    with connection() as c:
        source = c.execute("INSERT INTO jobsearch.sources(company,provider,board) VALUES('Ranking Example','lever','ranking-example') ON CONFLICT(provider,board) DO UPDATE SET company=excluded.company RETURNING id").fetchone()['id']
        c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,reason,description,url,content_hash,posted_at)
          VALUES(%s,%s,%s,'Ranking Example','Director Data Engineering','US','Remote','us_based','Director','match','test','d',%s,'h',now())""",
                  (job, source, 'ranking-' + str(job), 'https://example.com/ranking/' + str(job)))
    try:
        for roles in (['viewer'], ['member'], ['operator']):
            signed_in(roles)
            for sort in ('newest', 'recommended'):
                items = client.get('/api/jobs?sort=' + sort + '&q=Ranking%20Example').json()['items']
                assert items and all('learning' not in item for item in items), (roles, sort)
            detail = client.get('/api/jobs/' + str(job))
            assert detail.status_code == 200 and 'learning' not in detail.json()
        signed_in(['administrator'])
        for sort in ('newest', 'recommended'):
            items = client.get('/api/jobs?sort=' + sort + '&q=Ranking%20Example').json()['items']
            assert items and all('version' in item['learning'] for item in items), sort
    finally:
        with connection() as c:
            c.execute('DELETE FROM jobsearch.jobs WHERE id=%s', (job,))
