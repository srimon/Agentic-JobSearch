"""Footer enquiries (POST /api/enquiries) and operator-only collection statistics."""
import logging
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from src.db.store import connection
from src.settings import settings
from src.api.main import app, current_user
from src.applications.daily import publish

HEADERS = {'Origin': 'http://localhost:3105'}
GOOD = {'name': 'Ada  Lovelace', 'email': 'Ada@Example.com', 'message': 'I would like to know more about Job Search.', 'company_website': '', 'page': '/help'}


@pytest.fixture()
def client(monkeypatch):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    monkeypatch.setattr(settings(), 'enquiry_recipient', 'admin@example.com')
    with connection() as c:
        c.execute('TRUNCATE jobsearch.enquiries,jobsearch.login_limits,jobsearch.outbound_mail,jobsearch.audit_events RESTART IDENTITY')
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def send(client, headers=HEADERS, **changes):
    return client.post('/api/enquiries', json={**GOOD, **changes}, headers=headers)


def rows(table):
    with connection() as c:
        return c.execute('SELECT * FROM jobsearch.' + table + ' ORDER BY id').fetchall()


def test_migration_017_is_recorded():
    sql = (Path(__file__).resolve().parents[1] / 'src/db/017_enquiries.sql').read_text()
    assert 'jobsearch_app' in sql and 'VALUES(17)' in sql
    with connection() as c:
        assert c.execute('SELECT 1 FROM jobsearch.schema_versions WHERE version=17').fetchone()


def test_enquiry_is_stored_and_mail_queued_without_logging_contents(client, caplog):
    caplog.set_level(logging.INFO)
    r = send(client, headers={**HEADERS, 'X-Forwarded-For': '203.0.113.9, 10.0.0.1'})
    assert r.status_code == 202 and r.json() == {'detail': 'Thank you. Your message has been sent.'}
    [stored] = rows('enquiries')
    assert (stored['name'], stored['email'], stored['page']) == ('Ada Lovelace', 'Ada@example.com', '/help')
    assert stored['message'] == GOOD['message'] and len(stored['client_hash']) == 64 and '203.0.113.9' not in stored['client_hash']
    [mail] = rows('outbound_mail')
    assert mail['purpose'] == 'enquiry' and mail['to_address'] == 'admin@example.com' and mail['subject'] == 'New enquiry from Ada Lovelace'
    for part in ('Ada Lovelace', 'Ada@example.com', '/help', GOOD['message']):
        assert part in mail['text_body']
    audit_text = str(rows('audit_events')).lower()
    assert 'example.com' not in audit_text and 'job search' not in audit_text
    assert 'example.com' not in caplog.text.lower() and GOOD['message'] not in caplog.text


def test_recipient_falls_back_to_report_recipient_then_stores_only(client, monkeypatch, caplog):
    monkeypatch.setattr(settings(), 'enquiry_recipient', '')
    monkeypatch.setattr(settings(), 'report_recipient', 'reports@example.com')
    assert send(client).status_code == 202
    assert [m['to_address'] for m in rows('outbound_mail')] == ['reports@example.com']
    monkeypatch.setattr(settings(), 'report_recipient', '')
    caplog.set_level(logging.WARNING)
    assert send(client, email='second@example.com').status_code == 202
    assert len(rows('enquiries')) == 2 and len(rows('outbound_mail')) == 1
    assert 'enquiry_stored_without_recipient' in caplog.text and 'second@example.com' not in caplog.text


def test_honeypot_answers_202_and_does_nothing(client):
    r = send(client, company_website='http://spam.example', name='', message='x')
    assert r.status_code == 202 and r.json()['detail'] == 'Thank you. Your message has been sent.'
    assert rows('enquiries') == [] and rows('outbound_mail') == []


@pytest.mark.parametrize('changes', [
    {'name': ''}, {'name': '   '}, {'name': 'x' * 121},
    {'email': 'not-an-address'}, {'email': 'a@b.c' + 'x' * 250},
    {'message': 'too short'}, {'message': 'y' * 2001},
    {'page': 'p' * 201},
])
def test_validation(client, changes):
    assert send(client, **changes).status_code == 422
    assert rows('enquiries') == []


def test_origin_is_required(client):
    assert send(client, headers={}).status_code == 403
    assert send(client, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert rows('enquiries') == []


def test_throttle_per_client_per_sender_and_global(client):
    forwarded = {**HEADERS, 'X-Forwarded-For': '198.51.100.7'}
    for i in range(3):
        assert send(client, headers=forwarded, email='sender' + str(i) + '@example.com').status_code == 202
    limited = send(client, headers=forwarded, email='sender9@example.com')
    assert limited.status_code == 429 and limited.headers['retry-after'] == '900'
    # One sender address is limited even when requests are not forwarded (all callers share the gateway address).
    for _ in range(3):
        assert send(client, email='same@example.com').status_code == 202
    assert send(client, email='same@example.com').status_code == 429
    assert len(rows('enquiries')) == 6
    with connection() as c:
        c.execute("UPDATE jobsearch.login_limits SET attempts=30 WHERE bucket='enquiry'")
    assert send(client, email='fresh@example.com').status_code == 429
    assert len(rows('enquiries')) == 6


def test_maintenance_refuses_enquiries(client, monkeypatch):
    from src.api import main
    monkeypatch.setattr(main.cfg, 'maintenance_mode', True)
    assert send(client).status_code == 503


@pytest.mark.parametrize('roles,allowed', [(['viewer'], False), (['member'], False), (['operator'], True), (['administrator'], True)])
def test_collection_statistics_are_operator_only(client, roles, allowed):
    with connection() as c:
        c.execute("DELETE FROM jobsearch.users WHERE subject='stats-user'")
        user = c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','stats-user',%s) RETURNING *", (roles,)).fetchone()
    app.dependency_overrides[current_user] = lambda: user
    for path in ('/api/sources', '/api/collection-status', '/api/runs'):
        assert (client.get(path).status_code == 200) is allowed, path
    if not allowed:
        for path in ('/api/sources', '/api/collection-status', '/api/runs', '/api/analytics', '/api/data-quality', '/api/data-model',
                     '/api/governance', '/api/observability/prometheus', '/api/monitoring-status/grafana', '/api/audit'):
            assert client.get(path).status_code == 403, path
    assert (client.get('/api/jobs?view=review').status_code == 403) is not allowed
    publish(user['id'], {'phase': 'completed', 'counts': {'reviewed': 1}, 'source_counts': {'completed': 4}})
    latest = client.get('/api/workflow').json()['latest']
    assert latest['counts'] == {'reviewed': 1}
    assert ('source_counts' in latest) is allowed
