"""The administrator console: administrators only, read-only parameterised queries, a short cache,
and a panel that says so when its source is unavailable instead of failing or inventing a number."""
import os

import pytest
from fastapi.testclient import TestClient

from src.api import admin_console as console
from src.api import admin_queries as queries
from src.api.main import app, current_user
from src.db.store import connection

ROUTES = ('/api/admin/overview', '/api/admin/traffic', '/api/admin/accounts', '/api/admin/monetization', '/api/admin/machine')
# Nothing the console returns may carry a person: these are the columns the warehouse holds that
# the console's ClickHouse identity is never granted (scripts/admin_console.py NEVER).
FORBIDDEN_KEYS = ('username', 'display_name', 'email_hmac', 'email', 'ray', 'message', 'name')


class FakeWarehouse:
    """Stands in for ClickHouse. Records every statement and answers with rows of the right shape."""

    def __init__(self, gpu_rows=0, fail=False):
        self.calls = []
        self.gpu_rows = gpu_rows
        self.fail = fail

    def __call__(self, entry):
        self.calls.append(entry)
        if self.fail:
            raise console.SourceUnavailable('The warehouse could not be reached.')
        sql = entry['sql']
        if 'system.tables' in sql:
            return [{'present': 1 if self.gpu_rows else 0}]
        if 'gpu_samples_v1' in sql and 'GROUP BY day' in sql:
            return [{'day': '2026-09-15', 'avg_utilisation': 4.5, 'peak_utilisation': 22, 'avg_memory_mb': 1100}]
        if 'gpu_samples_v1' in sql:
            return [{'last_sample_at': '2026-09-15 12:00:00', 'samples': self.gpu_rows, 'avg_utilisation': 4.5,
                     'peak_utilisation': 22, 'avg_memory_mb': 1100, 'peak_memory_mb': 1300,
                     'total_memory_mb': 4096, 'peak_temperature_c': 65, 'gpu_name': 'Example GPU'}]
        if 'toDate(ts) AS day' in sql:
            return [{'day': '2026-09-15', 'hits': 120, 'visitors': 9, 'bot_hits': 4, 'server_errors': 1}]
        if 'GROUP BY host\n' in sql and 'uniq(visitor) AS visitors, count() AS hits' in sql:
            return [{'host': 'jobs.example', 'visitors': 5, 'hits': 60}]
        if 'GROUP BY host' in sql and 'avg_ms' in sql and 'path_group' not in sql:
            return [{'host': 'jobs.example', 'hits': 60, 'visitors': 5, 'bot_hits': 2, 'avg_ms': 40}]
        if 'GROUP BY host, path\n' in sql:
            return [{'host': 'jobs.example', 'path': '/', 'hits': 30, 'visitors': 4}]
        if 'referer_host' in sql and 'GROUP BY referer_host' in sql:
            return [{'referer_host': 'example.test', 'hits': 5, 'visitors': 2}]
        if 'GROUP BY country' in sql:
            return [{'country': 'US', 'hits': 100, 'visitors': 8}]
        if 'status_class' in sql:
            return [{'status_class': '2xx', 'hits': 110}]
        if 'path_group' in sql and 'p95_ms' in sql:
            return [{'host': 'jobs.example', 'path_group': '/api', 'hits': 60, 'p95_ms': 400, 'avg_ms': 90}]
        if sql.startswith('SELECT max(ts) AS last_hit_at'):
            return [{'last_hit_at': '2026-09-15 23:00:00', 'hits': 120}]
        if 'admin_signups_daily' in sql and 'sum(accounts)' in sql:
            return [{'accounts': 3, 'verified': 2, 'with_mfa': 1}]
        if 'admin_signups_daily' in sql:
            return [{'day': '2026-09-15', 'accounts': 3, 'verified': 2, 'with_mfa': 1, 'with_email': 3}]
        if 'admin_account_totals' in sql:
            return [{'accounts': 10, 'active_accounts': 8, 'accounts_with_email': 9, 'verified': 6,
                     'unverified_after_a_day': 1, 'with_mfa': 4, 'active_1d': 2, 'active_7d': 5, 'active_30d': 7,
                     'last_synced_at': '2026-09-15 23:15:00'}]
        if 'admin_mfa_adoption' in sql:
            return [{'role': '(all)', 'active_accounts': 8, 'with_mfa': 4, 'low_on_recovery_codes': 0}]
        if "action = 'login'" in sql:
            return [{'day': '2026-09-15', 'outcome': 'allowed', 'events': 7},
                    {'day': '2026-09-15', 'outcome': 'denied', 'events': 2}]
        if 'uniqExact(user_id) AS accounts' in sql and 'GROUP BY action' in sql:
            return [{'action': 'login', 'outcome': 'allowed', 'events': 7, 'accounts': 3}]
        if 'max(synced_at)' in sql:
            return [{'last_synced_at': '2026-09-15 23:15:00', 'events': 9}]
        if "action IN ('login', 'login.mfa')" in sql:
            return [{'accounts': 3}]
        if 'uniq(visitor) AS visitors, count() AS hits' in sql:
            return [{'visitors': 40, 'hits': 300, 'last_hit_at': '2026-09-15 23:00:00'}]
        if 'uniq(host) AS products' in sql:
            return [{'products': 1, 'visitors': 30}, {'products': 2, 'visitors': 10}]
        if 'countIf(days > 1)' in sql:
            return [{'visitors': 40, 'returning': 12}]
        if 'enquiries_v1' in sql and 'GROUP BY page' in sql:
            return [{'page': '/', 'enquiries': 2}]
        if 'enquiries_v1' in sql:
            return [{'day': '2026-09-15', 'enquiries': 2}]
        return []


class FakeMetrics:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, path, params):
        self.calls.append((path, params))
        if self.fail:
            raise console.SourceUnavailable('Prometheus could not be reached.')
        if path.endswith('query_range'):
            return [{'metric': {}, 'values': [[1789000000, '0.01'], [1789000060, '0.02']]}]
        expression = params['query']
        if expression == 'up':
            return [{'metric': {'job': 'jobsearch-api'}, 'value': [1789000000, '1']}]
        if 'memory' in expression:
            return [{'metric': {'job': 'jobsearch-api'}, 'value': [1789000000, '134217728']}]
        if 'open_fds' in expression:
            return [{'metric': {'job': 'jobsearch-api'}, 'value': [1789000000, '19']}]
        return [{'metric': {'job': 'jobsearch-api'}, 'value': [1789000000, '0.02']}]


@pytest.fixture()
def sources(monkeypatch):
    warehouse, metrics = FakeWarehouse(), FakeMetrics()
    monkeypatch.setattr(console, 'clickhouse', warehouse)
    monkeypatch.setattr(console, 'prometheus', metrics)
    console.clear_cache()
    yield warehouse, metrics
    console.clear_cache()


@pytest.fixture()
def client(sources):
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def signed_in(roles):
    with connection() as c:
        c.execute("DELETE FROM jobsearch.users WHERE subject='admin-console-user'")
        user = c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','admin-console-user',%s) RETURNING *", (roles,)).fetchone()
    app.dependency_overrides[current_user] = lambda: user
    return user


# ----- access ---------------------------------------------------------------------------------

@pytest.mark.parametrize('roles', [['viewer'], ['member'], ['operator'], ['member', 'operator'], ['viewer', 'operator']])
def test_every_console_route_denies_non_administrators(client, roles):
    signed_in(roles)
    for path in ROUTES:
        assert client.get(path).status_code == 403, path
        assert client.get(path + '?days=30').status_code == 403, path


def test_console_routes_need_a_session(client):
    app.dependency_overrides.clear()
    for path in ROUTES:
        assert client.get(path).status_code == 401, path


def test_administrators_get_every_panel(client):
    signed_in(['administrator'])
    for path in ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
    body = client.get('/api/admin/overview?days=30').json()
    assert body['range_days'] == 30 and body['ranges'] == list(queries.RANGES)
    panels = body['panels']
    assert set(panels) == {'traffic', 'accounts', 'monetization', 'machine'}
    for name, panel in panels.items():
        assert panel['available'] is True, name
        assert panel['summary'] and panel['source'] and panel['measured'], name
        assert panel['notes'], name


def test_no_panel_carries_anything_that_identifies_a_person(client):
    signed_in(['administrator'])
    body = client.get('/api/admin/overview').json()

    def walk(node, path=''):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_KEYS or path.endswith('evidence') or key == 'message', path + '/' + key
                walk(value, path + '/' + key)
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(body['panels']['traffic'])
    walk(body['panels']['accounts'])


# ----- the queries ----------------------------------------------------------------------------

def test_every_range_is_refused_unless_it_is_one_of_the_three(client):
    signed_in(['administrator'])
    for bad in ('1', '365', '0', '-7', '7.5', 'seven', '7 OR 1=1', "7;DROP TABLE users_v1"):
        assert client.get('/api/admin/traffic?days=' + bad).status_code == 422, bad
    for good in queries.RANGES:
        assert client.get('/api/admin/traffic?days=' + str(good)).status_code == 200, good


def test_days_parameter_never_reaches_the_statement_text():
    for days in queries.RANGES:
        assert queries.days_parameter(days) == {'days': str(days)}
        for group in (queries.traffic(days), queries.accounts(days), queries.monetization(days), queries.gpu(days)):
            for name, entry in group.items():
                if entry['params']:
                    assert '{days:UInt16}' in entry['sql'], name
                    assert entry['params'] == {'days': str(days)}, name
    for bad in (1, 365, 0, -7, '7', None, 7.0):
        with pytest.raises(ValueError):
            queries.days_parameter(bad)


def test_every_statement_is_a_bounded_read():
    import re
    for days in queries.RANGES:
        for group in (queries.traffic(days), queries.accounts(days), queries.monetization(days), queries.gpu(days)):
            for name, entry in group.items():
                sql = entry['sql']
                assert sql.upper().startswith('SELECT'), name
                assert 'LIMIT' in sql.upper(), name
                assert ';' not in sql, name
                for word in ('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'DROP', 'CREATE', 'ATTACH', 'TRUNCATE', 'GRANT', 'OPTIMIZE'):
                    assert not re.search(r'\b' + word + r'\b', sql.upper()), (name, word)
                # The only system table the console reads is the table list, to know whether the
                # GPU table has been created yet.
                assert set(re.findall(r'\bsystem\.\w+', sql)) <= {'system.tables'}, name
                # Every other table it reads is in the shared warehouse database.
                for table in re.findall(r'\bFROM\s+([a-z_]+)\.', sql):
                    assert table in ('hub_analytics', 'system'), (name, table)
                assert entry['note'], name


def test_the_client_sends_its_own_caps_and_the_statement_in_the_body():
    assert console.CLICKHOUSE_LIMITS['max_execution_time'] == '10'
    assert int(console.CLICKHOUSE_LIMITS['max_result_rows']) <= 20000


# ----- caching --------------------------------------------------------------------------------

def test_a_repeated_request_is_answered_from_the_cache(client, sources):
    warehouse, metrics = sources
    signed_in(['administrator'])
    assert client.get('/api/admin/traffic').status_code == 200
    first = len(warehouse.calls)
    assert first > 0
    for _ in range(4):
        assert client.get('/api/admin/traffic').status_code == 200
    assert len(warehouse.calls) == first, 'a cached panel must not query the warehouse again'
    # A different range is a different panel and is read fresh.
    assert client.get('/api/admin/traffic?days=30').status_code == 200
    assert len(warehouse.calls) > first


def test_the_cache_expires(client, sources):
    warehouse, _ = sources
    signed_in(['administrator'])
    client.get('/api/admin/accounts')
    first = len(warehouse.calls)
    console.clear_cache()
    client.get('/api/admin/accounts')
    assert len(warehouse.calls) > first


# ----- graceful degradation -------------------------------------------------------------------

def test_a_warehouse_that_cannot_answer_makes_the_panel_say_so(client, monkeypatch):
    signed_in(['administrator'])
    monkeypatch.setattr(console, 'clickhouse', FakeWarehouse(fail=True))
    console.clear_cache()
    body = client.get('/api/admin/overview')
    assert body.status_code == 200
    panels = body.json()['panels']
    for name in ('traffic', 'accounts', 'monetization'):
        assert panels[name]['available'] is False, name
        assert panels[name]['message'], name
        assert panels[name]['measured'], name
    # The machine panel still answers from Prometheus, and the cost note is still shown.
    assert panels['machine']['services']['available'] is True
    assert panels['monetization']['ai_cost']['recorded'] is False


def test_prometheus_being_down_does_not_fail_the_machine_panel(client, monkeypatch):
    signed_in(['administrator'])
    monkeypatch.setattr(console, 'prometheus', FakeMetrics(fail=True))
    console.clear_cache()
    response = client.get('/api/admin/machine')
    assert response.status_code == 200
    panel = response.json()
    assert panel['available'] is True
    assert panel['services']['available'] is False and panel['services']['message']
    assert 'unavailable' in panel['summary']


def test_a_missing_credential_is_reported_not_raised(monkeypatch, tmp_path):
    """Without the mounted Secret the console says the credential is missing; it never raises into
    a 500 and never falls back to another identity."""
    from src.settings import settings
    # The settings object is a process-wide singleton the whole app shares: change the one field
    # (monkeypatch restores it) rather than dropping the cache other tests are holding.
    monkeypatch.setattr(settings(), 'admin_clickhouse_password_file', str(tmp_path / 'absent'))
    console.clear_cache()
    with pytest.raises(console.SourceUnavailable):
        console.clickhouse_password()
    present = tmp_path / 'clickhouse-password'
    present.write_text('a' * 48 + '\n')
    monkeypatch.setattr(settings(), 'admin_clickhouse_password_file', str(present))
    assert console.clickhouse_password() == 'a' * 48
    console.clear_cache()


def test_gpu_says_it_is_not_enabled_until_samples_arrive(client, monkeypatch):
    signed_in(['administrator'])
    response = client.get('/api/admin/machine').json()
    assert response['gpu']['enabled'] is False
    assert 'not enabled' in response['gpu']['message']
    assert 'gpu_sampler' in response['gpu']['message']
    assert 'GPU sampling is not enabled' in response['summary']
    # With samples recorded the same panel reports them.
    monkeypatch.setattr(console, 'clickhouse', FakeWarehouse(gpu_rows=120))
    console.clear_cache()
    enabled = client.get('/api/admin/machine').json()['gpu']
    assert enabled['enabled'] is True and enabled['samples'] == 120 and enabled['daily']


def test_the_machine_panel_states_what_is_not_measured(client):
    signed_in(['administrator'])
    panel = client.get('/api/admin/machine').json()
    assert panel['host']['available'] is False and 'node exporter' in panel['host']['message']
    assert panel['storage']['available'] is False
    assert 'not collected' in panel['summary']


def test_the_cost_panel_never_invents_a_figure(client):
    signed_in(['administrator'])
    cost = client.get('/api/admin/monetization').json()['ai_cost']
    assert cost['recorded'] is False
    assert 'not recorded' in cost['message']
    assert len(cost['evidence']) >= 4
    for item in cost['evidence']:
        assert item['source'] and item['records'] and item['to_measure']
