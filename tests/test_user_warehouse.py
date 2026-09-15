"""The user warehouse sync: pure transforms and the pass logic against in-memory fakes; no network, no database."""
import io
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from scripts import user_warehouse as uw

KEY = bytes.fromhex('11' * 32)
NOW = datetime(2026, 9, 15, 12, 0, 0, 123000, tzinfo=timezone.utc)
FORBIDDEN_KEYS = {'password_hash', 'secret_enc', 'code_hash', 'token_hash', 'email', 'name', 'message', 'client_hash', 'last_used_step'}
SECRET_WORDS = ('argon2', 'totp-secret', 'person@example.com', 'Private Person', 'hello there, a private message')


def account(**overrides):
    row = {'id': 7, 'issuer': 'local', 'subject': 'alice', 'display_name': 'Alice A', 'roles': ['member', 'bogus', 'viewer'],
           'active': True, 'email': ' Person@Example.COM ', 'email_verified_at': NOW - timedelta(days=1),
           'created_at': NOW - timedelta(days=2), 'last_login_at': NOW - timedelta(hours=3), 'mfa_enabled_at': None,
           'recovery_codes_remaining': 0, 'active_sessions': 2,
           # columns the warehouse role cannot read; present here to prove the transform ignores them anyway
           'password_hash': '$argon2id$v=19$secret', 'secret_enc': b'totp-secret', 'token_hash': 'abc'}
    row.update(overrides)
    return row


def audit(id, action, actor='7', outcome='allowed', resource='local', details=None, at=None):
    return {'id': id, 'at': at or NOW, 'actor': actor, 'action': action, 'resource': resource, 'outcome': outcome, 'details': details or {}}


# ----- transforms -------------------------------------------------------------------------------

def test_user_row_has_exactly_the_warehouse_columns_and_no_secret_or_address():
    row = uw.user_row(account(), KEY, uw.timestamp(NOW))
    assert set(row) == {'user_id', 'issuer', 'username', 'display_name', 'email_hmac', 'email_domain', 'roles', 'active',
                        'email_verified', 'email_verified_at', 'mfa_enabled', 'mfa_enabled_at', 'recovery_codes_remaining',
                        'active_sessions', 'created_at', 'last_login_at', 'synced_at', 'is_deleted'}
    assert not FORBIDDEN_KEYS & set(row)
    text = json.dumps(row).lower()
    assert 'person@example.com' not in text and 'argon2' not in text and 'totp' not in text
    assert row['email_domain'] == 'example.com' and row['roles'] == ['viewer', 'member']
    assert row['email_verified'] == 1 and row['mfa_enabled'] == 0 and row['mfa_enabled_at'] is None
    assert row['active_sessions'] == 2 and row['is_deleted'] == 0
    assert row['created_at'] == '2026-09-13 12:00:00.123'


def test_email_hmac_is_keyed_normalised_and_zero_without_an_address():
    a = uw.email_hmac(KEY, ' Person@Example.COM ')
    assert a == uw.email_hmac(KEY, 'person@example.com') and re.fullmatch('[0-9a-f]{32}', a)
    assert a != uw.email_hmac(bytes.fromhex('22' * 32), 'person@example.com')
    import hashlib
    assert a != hashlib.sha256(b'person@example.com').hexdigest()[:32]  # not a plain, linkable digest
    assert uw.email_hmac(KEY, None) == uw.email_hmac(KEY, '  ') == '0' * 32


@pytest.mark.parametrize('value,expected', [('a@Mail.Example.org', 'mail.example.org'), ('example.org', 'example.org'),
                                             (None, ''), ('', ''), ('a@localhost', '(invalid)'), ('a@exa mple.org', '(invalid)'),
                                             ('a@b@example.org', 'example.org')])
def test_email_domain(value, expected):
    assert uw.email_domain(value) == expected


def test_timestamps_are_utc_milliseconds():
    assert uw.timestamp(None) is None
    assert uw.timestamp(datetime(2026, 1, 2, 3, 4, 5, 678901)) == '2026-01-02 03:04:05.678'
    plus_two = timezone(timedelta(hours=2))
    assert uw.timestamp(datetime(2026, 1, 2, 5, 4, 5, tzinfo=plus_two)) == '2026-01-02 03:04:05.000'


def test_event_rows_resolve_the_account_and_keep_only_allowlisted_details():
    synced = uw.timestamp(NOW)
    login = uw.event_row(audit(1, 'login', resource='session'), synced)
    assert login['actor_kind'] == 'user' and login['user_id'] == 7 and login['method'] == 'password'
    mfa = uw.event_row(audit(2, 'login', details={'method': 'mfa-totp'}), synced)
    assert mfa['method'] == 'mfa-totp'
    anonymous = uw.event_row(audit(3, 'account.signup', actor='anonymous', outcome='duplicate',
                                   details={'email_in_use': True, 'mail': 'queued', 'email': 'person@example.com', 'name': 'Private Person'}), synced)
    assert anonymous['user_id'] is None and anonymous['actor_kind'] == 'anonymous'
    assert anonymous['email_in_use'] == 1 and anonymous['mail'] == 'queued' and anonymous['method'] == ''
    console = uw.event_row(audit(4, 'account.disable', actor='local-console', resource='42'), synced)
    assert console['actor_kind'] == 'console' and console['user_id'] == 42
    profile = uw.event_row(audit(5, 'account.profile', details={'fields': ['email', 'display_name', 'password', 'x']}), synced)
    assert profile['profile_fields'] == ['display_name', 'email']
    revoke = uw.event_row(audit(6, 'account.sessions.revoke_all', details={'revoked': 3}), synced)
    assert revoke['sessions_revoked'] == 3
    enable = uw.event_row(audit(7, 'account.mfa.enable', details={'revoked_sessions': True}), synced)
    assert enable['sessions_revoked'] is None  # a boolean is not a count
    odd = uw.event_row(audit(8, 'Login; DROP', actor='collector', outcome='<script>', details={'method': 'Person@Example.com'}), synced)
    assert odd['action'] == '(other)' and odd['outcome'] == '(other)' and odd['actor_kind'] == 'system' and odd['method'] == ''
    for row in (login, mfa, anonymous, console, profile, revoke, enable, odd):
        text = json.dumps(row)
        assert all(word not in text for word in SECRET_WORDS)


def test_enquiry_rows_keep_the_path_domain_and_length_only():
    row = uw.enquiry_row({'id': 9, 'created_at': NOW, 'page': 'https://jobs.bagala.ai/pricing?ref=someone@example.com#top',
                          'email_domain': 'Example.ORG', 'message_length': 123}, uw.timestamp(NOW))
    assert row == {'enquiry_id': 9, 'created_at': '2026-09-15 12:00:00.123', 'page': '/pricing', 'email_domain': 'example.org',
                   'message_length': 123, 'synced_at': '2026-09-15 12:00:00.123'}
    assert uw.page_path(None) == '' and uw.page_path('/a/b?x=1') == '/a/b' and len(uw.page_path('/' + 'p' * 500)) == 200


def test_postgres_queries_never_select_secret_columns_or_enquiry_text():
    text = (uw.USERS_SQL + uw.EVENTS_SQL + uw.ENQUIRIES_SQL).lower()
    for column in ('password_hash', 'secret_enc', 'code_hash', 'token_hash', 'client_hash', 'last_used_step'):
        assert column not in text
    select = uw.ENQUIRIES_SQL.lower().split('from jobsearch.enquiries')[0]
    assert 'name' not in select and re.search(r'(?<!char_length\()\bmessage\b', select) is None
    assert re.search(r'(?<!\()\bemail\b(?! from)', select) is None  # only inside substring(email from ...)


def test_json_lines_and_batches():
    body = uw.json_lines([{'a': 1}, {'b': None}])
    assert body == b'{"a":1}\n{"b":null}\n'
    assert [len(b) for b in uw.batches(list(range(5)), 2)] == [2, 2, 1]


# ----- the pass against fakes -------------------------------------------------------------------

class FakePostgres:
    def __init__(self, users=(), events=(), enquiries=None):
        self.users, self.events, self.enquiries = list(users), list(events), enquiries
        self.calls = []

    def __call__(self, sql, params):
        self.calls.append((sql, params))
        if sql == uw.ENQUIRIES_READY_SQL:
            return [{'ready': self.enquiries is not None}]
        after, limit = params
        source = {uw.USERS_SQL: self.users, uw.EVENTS_SQL: self.events, uw.ENQUIRIES_SQL: self.enquiries or []}[sql]
        if sql == uw.EVENTS_SQL:
            source = [r for r in source if r['action'] in ('login', 'logout') or r['action'].startswith(('login.', 'account.'))]
        return [r for r in sorted(source, key=lambda r: r['id']) if r['id'] > after][:limit]


class FakeClickHouse:
    def __init__(self):
        self.tables = {uw.USERS: [], uw.EVENTS: [], uw.ENQUIRIES: []}
        self.inserts = []

    def insert(self, table, rows):
        if rows:
            self.inserts.append((table, len(rows)))
            self.tables[table].extend(json.loads(json.dumps(rows)))

    def current_users(self):
        latest = {}
        for row in self.tables[uw.USERS]:  # the last insert wins at equal versions
            if row['user_id'] not in latest or row['synced_at'] >= latest[row['user_id']]['synced_at']:
                latest[row['user_id']] = row
        return {uid: r for uid, r in latest.items() if not r['is_deleted']}

    def ids(self, sql):
        if 'FROM hub_analytics.users_v1 FINAL' in sql:
            return set(self.current_users())
        column, table, above = re.search(r'SELECT (\w+) FROM hub_analytics\.(\w+) WHERE \w+ > (\d+)', sql).groups()
        return {r[column] for r in self.tables[table] if r[column] > int(above)}

    def scalar(self, sql):
        column, table = re.search(r'max\((\w+)\) FROM hub_analytics\.(\w+)', sql).groups()
        return max((r[column] for r in self.tables[table]), default=0)


def test_a_pass_loads_everything_and_a_second_pass_adds_no_events():
    pg = FakePostgres(users=[account(id=i, subject='u%d' % i, email='u%d@example.com' % i) for i in range(1, 6)],
                      events=[audit(i, 'login', actor=str(i % 5 + 1)) for i in range(1, 8)] + [audit(20, 'job.save'), audit(21, 'logout')],
                      enquiries=[{'id': 1, 'created_at': NOW, 'page': '/', 'email_domain': 'example.org', 'message_length': 20}])
    ch = FakeClickHouse()
    first = uw.sync(pg, ch, KEY, now=NOW, size=2)
    assert first == {'users': 5, 'users_retired': 0, 'events': 8, 'enquiries': 1}
    assert all(n <= 2 for _, n in ch.inserts)
    assert {r['action'] for r in ch.tables[uw.EVENTS]} == {'login', 'logout'}
    second = uw.sync(pg, ch, KEY, now=NOW + timedelta(minutes=15), size=2)
    assert second == {'users': 5, 'users_retired': 0, 'events': 0, 'enquiries': 0}
    assert len(ch.tables[uw.EVENTS]) == 8 and len(ch.current_users()) == 5


def test_a_late_committed_event_below_the_high_water_mark_is_still_loaded_once():
    pg = FakePostgres(users=[account()], events=[audit(10, 'login'), audit(12, 'logout')])
    ch = FakeClickHouse()
    uw.sync(pg, ch, KEY, now=NOW)
    pg.events.append(audit(11, 'account.password'))  # an identity value handed out earlier, committed later
    assert uw.sync(pg, ch, KEY, now=NOW + timedelta(minutes=15))['events'] == 1
    assert sorted(r['event_id'] for r in ch.tables[uw.EVENTS]) == [10, 11, 12]


def test_deleted_accounts_get_a_tombstone_and_an_empty_snapshot_is_refused():
    pg = FakePostgres(users=[account(id=1), account(id=2, email='b@example.com')])
    ch = FakeClickHouse()
    uw.sync(pg, ch, KEY, now=NOW)
    pg.users = [account(id=1)]
    assert uw.sync(pg, ch, KEY, now=NOW + timedelta(minutes=15))['users_retired'] == 1
    assert set(ch.current_users()) == {1}
    pg.users = []
    with pytest.raises(uw.WarehouseError, match='empty_user_snapshot'):
        uw.sync(pg, ch, KEY, now=NOW + timedelta(minutes=30))
    assert set(ch.current_users()) == {1}


def test_enquiries_are_skipped_until_the_table_is_there_and_granted():
    pg = FakePostgres(users=[account()])
    ch = FakeClickHouse()
    assert uw.sync(pg, ch, KEY, now=NOW)['enquiries'] is None
    assert not any(sql == uw.ENQUIRIES_SQL for sql, _ in pg.calls)


def test_nothing_secret_reaches_clickhouse_in_a_full_pass():
    pg = FakePostgres(users=[account(display_name='Shown Name')],
                      events=[audit(1, 'account.signup', actor='anonymous', outcome='duplicate', details={'email': 'person@example.com'})],
                      enquiries=[{'id': 1, 'created_at': NOW, 'page': '/?email=person@example.com', 'email_domain': 'example.com', 'message_length': 30}])
    ch = FakeClickHouse()
    uw.sync(pg, ch, KEY, now=NOW)
    text = json.dumps(ch.tables)
    assert all(word not in text for word in SECRET_WORDS)


# ----- ClickHouse client, configuration and entry point ----------------------------------------

class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_clickhouse_credentials_travel_in_headers_and_error_bodies_are_not_repeated():
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return Response(b'41\n')

    ch = uw.ClickHouse('http://clickhouse:8123', 'hub_user_warehouse', 'pw-value-123', opener=opener)
    assert ch.scalar('SELECT max(event_id) FROM hub_analytics.account_events_v1 FORMAT TSV') == 41
    ch.insert(uw.EVENTS, [{'event_id': 1}])
    ch.insert(uw.EVENTS, [])
    assert len(seen) == 2
    for request in seen:
        assert 'pw-value-123' not in request.full_url and request.get_header('X-clickhouse-key') == 'pw-value-123'
        assert 'database=hub_analytics' in request.full_url
    assert 'INSERT+INTO+hub_analytics.account_events_v1+FORMAT+JSONEachRow' in seen[1].full_url and seen[1].data == b'{"event_id":1}\n'

    def failing(request, timeout):
        import urllib.error
        from email.message import Message
        headers = Message()
        headers['X-ClickHouse-Exception-Code'] = '27'
        raise urllib.error.HTTPError(request.full_url, 400, 'Cannot parse input: person@example.com', headers, io.BytesIO(b'row person@example.com'))

    with pytest.raises(uw.WarehouseError) as error:
        uw.ClickHouse('http://clickhouse:8123', 'u', 'p', opener=failing).insert(uw.USERS, [{'user_id': 1}])
    assert str(error.value) == 'clickhouse_http_400:27'


def test_config_reads_mounted_files_and_hides_values(tmp_path):
    (tmp_path / 'database-url').write_text('postgresql://hub_user_warehouse:dbpass@postgres:5432/jobsearch_production\n')
    (tmp_path / 'clickhouse-password').write_text('chpass\n')
    (tmp_path / 'email-key').write_text('ab' * 32 + '\n')
    config = uw.load_config({'USER_WAREHOUSE_SECRETS_DIR': str(tmp_path)})
    assert config.email_key == bytes.fromhex('ab' * 32) and config.clickhouse_user == 'hub_user_warehouse'
    assert config.clickhouse_url == uw.DEFAULT_CLICKHOUSE
    assert 'dbpass' not in repr(config) and 'chpass' not in repr(config)
    (tmp_path / 'email-key').write_text('short')
    with pytest.raises(uw.WarehouseError, match='email_key_format'):
        uw.load_config({'USER_WAREHOUSE_SECRETS_DIR': str(tmp_path)})
    with pytest.raises(uw.WarehouseError, match='secret_file_unreadable:email-key'):
        uw.load_config({'USER_WAREHOUSE_SECRETS_DIR': str(tmp_path / 'missing')})


def test_once_exits_non_zero_with_only_an_error_class(monkeypatch, capsys):
    def broken(config, size):
        raise RuntimeError('connection to postgresql://hub_user_warehouse:dbpass@postgres failed for person@example.com')

    monkeypatch.setattr(uw, 'load_config', lambda: object())
    monkeypatch.setattr(uw, 'run_pass', broken)
    assert uw.main(['--once']) == 1
    out = capsys.readouterr().out
    record = json.loads(out.strip().splitlines()[-1])
    assert record['event'] == 'user_warehouse_pass_failed' and record['error_class'] == 'RuntimeError'
    assert 'dbpass' not in out and 'example.com' not in out

    monkeypatch.setattr(uw, 'run_pass', lambda config, size: {'users': 3, 'users_retired': 0, 'events': 4, 'enquiries': None})
    assert uw.main(['--once', '--batch', '100']) == 0
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record['event'] == 'user_warehouse_pass_completed' and record['users'] == 3 and record['events'] == 4
    with pytest.raises(SystemExit):
        uw.main(['--once', '--batch', '0'])
