"""Copy user-management facts into the hub's ClickHouse warehouse: python -m scripts.user_warehouse [--once].

Runs as the CronJob jbs-production/user-warehouse (every 15 minutes, --once) in the api image; without --once
it repeats every --interval seconds. Each pass, in one read-only REPEATABLE READ transaction on PostgreSQL:

  users      every account, rebuilt from jobsearch.users, user_mfa, mfa_recovery_codes and sessions, inserted
             whole into hub_analytics.users_v1 (ReplacingMergeTree by synced_at); an account ClickHouse still
             lists but PostgreSQL no longer has gets a tombstone row (is_deleted = 1).
  events     account-related rows of jobsearch.audit_events (login, login.*, logout, account.*) newer than the
             highest event id already in hub_analytics.account_events_v1, re-reading an overlap of OVERLAP ids
             below it (identity values are not committed in order) and skipping ids ClickHouse already has.
  enquiries  jobsearch.enquiries the same way into hub_analytics.enquiries_v1; skipped while the table is absent
             or not yet granted.

What never leaves PostgreSQL: password hashes, TOTP secrets, recovery code and token hashes (the warehouse role
cannot read those columns), enquiry names, addresses and messages (only the domain and the length are selected).
The account address reaches this process only to be replaced by HMAC-SHA256 with the key in the mounted Secret.

Inserts go to ClickHouse's HTTP interface as JSONEachRow in batches of at most --batch rows. Logs are JSON lines
with counts and error classes only (no names, addresses or query text). Exit status 1 when a pass fails.

Inputs (files from the Secret user-warehouse, mounted at USER_WAREHOUSE_SECRETS_DIR, default
/run/secrets/user-warehouse): database-url, clickhouse-password, email-key (hex, at least 32 bytes).
USER_WAREHOUSE_CLICKHOUSE_URL (default http://clickhouse.hub-data.svc.cluster.local:8123) and
USER_WAREHOUSE_CLICKHOUSE_USER (default hub_user_warehouse) are plain settings.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DATABASE = 'hub_analytics'
USERS, EVENTS, ENQUIRIES = 'users_v1', 'account_events_v1', 'enquiries_v1'
DEFAULT_SECRETS = '/run/secrets/user-warehouse'
DEFAULT_CLICKHOUSE = 'http://clickhouse.hub-data.svc.cluster.local:8123'
DEFAULT_USER = 'hub_user_warehouse'
BATCH = 2000
MAX_BATCH = 10000
OVERLAP = 500  # event / enquiry ids re-read below the high-water mark
ROLES = ('viewer', 'member', 'operator', 'administrator')
PROFILE_FIELDS = ('display_name', 'email')
TOKEN = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}')
DOMAIN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)+')
NO_EMAIL = '0' * 32

USERS_SQL = """SELECT u.id, u.issuer, u.subject, u.display_name, u.roles, u.active, u.email, u.email_verified_at,
 u.created_at, u.last_login_at, m.enabled_at AS mfa_enabled_at,
 (SELECT count(*) FROM jobsearch.mfa_recovery_codes r WHERE r.user_id = u.id AND r.used_at IS NULL) AS recovery_codes_remaining,
 (SELECT count(*) FROM jobsearch.sessions s WHERE s.user_id = u.id AND s.expires_at > now()) AS active_sessions
FROM jobsearch.users u LEFT JOIN jobsearch.user_mfa m ON m.user_id = u.id
WHERE u.id > %s ORDER BY u.id LIMIT %s"""

EVENTS_SQL = """SELECT id, at, actor, action, resource, outcome, details FROM jobsearch.audit_events
WHERE id > %s AND (action IN ('login', 'logout') OR action LIKE 'login.%%' OR action LIKE 'account.%%')
ORDER BY id LIMIT %s"""

# CASE, not AND: the privilege function errors on a table that does not exist (migration 017 not applied yet).
ENQUIRIES_READY_SQL = """SELECT CASE WHEN to_regclass('jobsearch.enquiries') IS NULL THEN false
 ELSE has_any_column_privilege('jobsearch.enquiries', 'SELECT') END AS ready"""

# The address and the message stay in PostgreSQL: only the domain and the length are selected.
ENQUIRIES_SQL = """SELECT id, created_at, page, lower(substring(email from '@([^@]*)$')) AS email_domain,
 char_length(message) AS message_length
FROM jobsearch.enquiries WHERE id > %s ORDER BY id LIMIT %s"""


class WarehouseError(RuntimeError):
    """A failure whose message is safe to log: a class of problem, never data."""


# ----- logging --------------------------------------------------------------------------------

def log(event, level='info', stream=None, **fields):
    """One JSON line. Callers pass counts, table names and error classes only."""
    record = {'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'level': level,
              'logger': 'jobsearch.user_warehouse', 'event': event}
    record.update(fields)
    print(json.dumps(record, sort_keys=True), file=stream or sys.stdout, flush=True)


# ----- pure transforms ------------------------------------------------------------------------

def timestamp(value):
    """DateTime64(3,'UTC') text for ClickHouse, or None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def email_hmac(key, email):
    """32 hex characters of HMAC-SHA256 over the normalised address; all zeros without one."""
    if not email or not email.strip():
        return NO_EMAIL
    return hmac.new(key, email.strip().lower().encode('utf-8'), hashlib.sha256).hexdigest()[:32]


def email_domain(value):
    """The lower-cased domain of an address (or a bare domain); '(invalid)' when it does not look like one."""
    if not value or not value.strip():
        return ''
    domain = value.strip().lower().rsplit('@', 1)[-1]
    return domain if len(domain) <= 253 and DOMAIN.fullmatch(domain) else '(invalid)'


def roles(values):
    return sorted({r for r in (values or []) if r in ROLES}, key=ROLES.index)


def token(value, default=''):
    return value if isinstance(value, str) and TOKEN.fullmatch(value) else default


def count(value, ceiling):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, min(value, ceiling))


def user_row(row, key, synced_at):
    """users_v1 from one joined account row. Only the columns named here are ever sent."""
    return {
        'user_id': int(row['id']),
        'issuer': token(row['issuer'], '(other)'),
        'username': str(row['subject'] or '')[:128],
        'display_name': str(row['display_name'] or '')[:120],
        'email_hmac': email_hmac(key, row['email']),
        'email_domain': email_domain(row['email']),
        'roles': roles(row['roles']),
        'active': int(bool(row['active'])),
        'email_verified': int(row['email_verified_at'] is not None),
        'email_verified_at': timestamp(row['email_verified_at']),
        'mfa_enabled': int(row['mfa_enabled_at'] is not None),
        'mfa_enabled_at': timestamp(row['mfa_enabled_at']),
        'recovery_codes_remaining': count(int(row['recovery_codes_remaining'] or 0), 65535),
        'active_sessions': count(int(row['active_sessions'] or 0), 4294967295),
        'created_at': timestamp(row['created_at']),
        'last_login_at': timestamp(row['last_login_at']),
        'synced_at': synced_at,
        'is_deleted': 0,
    }


def tombstone(user_id, synced_at):
    """The row that retires an account PostgreSQL no longer has; FINAL reads drop it."""
    return {'user_id': int(user_id), 'issuer': '', 'username': '', 'display_name': '', 'email_hmac': NO_EMAIL,
            'email_domain': '', 'roles': [], 'active': 0, 'email_verified': 0, 'email_verified_at': None,
            'mfa_enabled': 0, 'mfa_enabled_at': None, 'recovery_codes_remaining': 0, 'active_sessions': 0,
            'created_at': synced_at, 'last_login_at': None, 'synced_at': synced_at, 'is_deleted': 1}


def actor(row):
    """(actor_kind, user_id): numeric actors are accounts; console actions name the account in resource."""
    name, resource = str(row['actor'] or ''), str(row['resource'] or '')
    if name.isdigit():
        return 'user', int(name)
    if name == 'anonymous':
        return 'anonymous', None
    if name == 'local-console':
        return 'console', int(resource) if resource.isdigit() else None
    return 'system', None


def event_row(row, synced_at):
    """account_events_v1 from one audit row; details are reduced to an allowlist of non-identifying keys."""
    details = row['details'] if isinstance(row['details'], dict) else {}
    kind, user_id = actor(row)
    action = token(row['action'], '(other)')
    outcome = token(row['outcome'], '(other)')
    method = token(details.get('method'))
    if action == 'login' and outcome == 'allowed' and not method:
        method = 'password'  # the service records a method only when it is not the password
    fields = details.get('fields')
    in_use = details.get('email_in_use')
    revoked = next((details[k] for k in ('revoked', 'revoked_sessions') if k in details), None)
    return {
        'event_id': int(row['id']),
        'ts': timestamp(row['at']),
        'action': action,
        'outcome': outcome,
        'actor_kind': kind,
        'user_id': user_id,
        'method': method if action == 'login' else '',
        'profile_fields': sorted({f for f in fields if f in PROFILE_FIELDS}) if isinstance(fields, list) else [],
        'sessions_revoked': count(revoked, 4294967295),
        'email_in_use': int(in_use) if isinstance(in_use, bool) else None,
        'mail': token(details.get('mail')),
        'synced_at': synced_at,
    }


def page_path(value):
    """The path of the page an enquiry came from: no scheme, host, query string or fragment."""
    if not value or not str(value).strip():
        return ''
    path = urllib.parse.urlsplit(str(value).strip()).path or '/'
    return path[:200]


def enquiry_row(row, synced_at):
    return {
        'enquiry_id': int(row['id']),
        'created_at': timestamp(row['created_at']),
        'page': page_path(row['page']),
        'email_domain': email_domain(row['email_domain']),
        'message_length': count(int(row['message_length'] or 0), 65535),
        'synced_at': synced_at,
    }


def json_lines(rows):
    return ''.join(json.dumps(r, separators=(',', ':'), ensure_ascii=False) + '\n' for r in rows).encode('utf-8')


def batches(rows, size):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


# ----- configuration --------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    database_url: str
    clickhouse_url: str
    clickhouse_user: str
    clickhouse_password: str
    email_key: bytes

    def __repr__(self):  # never show the values
        return 'Config(clickhouse_url={!r}, clickhouse_user={!r})'.format(self.clickhouse_url, self.clickhouse_user)


def read_secret(directory, name):
    path = Path(directory) / name
    try:
        value = path.read_text(encoding='utf-8').strip()
    except OSError:
        raise WarehouseError('secret_file_unreadable:' + name)
    if not value:
        raise WarehouseError('secret_file_empty:' + name)
    return value


def load_config(env=None):
    env = os.environ if env is None else env
    directory = env.get('USER_WAREHOUSE_SECRETS_DIR', DEFAULT_SECRETS)
    key = read_secret(directory, 'email-key')
    if not re.fullmatch(r'(?:[0-9a-f]{2}){32,}', key):
        raise WarehouseError('email_key_format')
    url = env.get('USER_WAREHOUSE_CLICKHOUSE_URL', DEFAULT_CLICKHOUSE).rstrip('/')
    if urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise WarehouseError('clickhouse_url_scheme')
    user = env.get('USER_WAREHOUSE_CLICKHOUSE_USER', DEFAULT_USER)
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', user):
        raise WarehouseError('clickhouse_user_format')
    return Config(read_secret(directory, 'database-url'), url, user, read_secret(directory, 'clickhouse-password'), bytes.fromhex(key))


# ----- ClickHouse over HTTP -------------------------------------------------------------------

class ClickHouse:
    """The native HTTP interface with the writer's credentials in headers (never in the URL). Error bodies can
    quote rows, so they are not read; only the status and ClickHouse's exception code are reported."""

    def __init__(self, url, user, password, timeout=60, opener=None):
        self.url, self.user, self.password, self.timeout = url, user, password, timeout
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    def _post(self, params, body):
        query = urllib.parse.urlencode(dict(params, database=DATABASE, wait_end_of_query=1))
        request = urllib.request.Request(self.url + '/?' + query, data=body, method='POST',
                                         headers={'X-ClickHouse-User': self.user, 'X-ClickHouse-Key': self.password,
                                                  'Content-Type': 'text/plain; charset=utf-8'})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            code = error.headers.get('X-ClickHouse-Exception-Code', '') if error.headers else ''
            raise WarehouseError('clickhouse_http_{}{}'.format(error.code, ':' + code if re.fullmatch(r'\d{1,4}', code or '') else ''))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise WarehouseError('clickhouse_unreachable:' + type(error).__name__)

    def select(self, sql):
        return self._post({}, sql.encode('utf-8'))

    def insert(self, table, rows):
        if rows:
            self._post({'query': 'INSERT INTO {}.{} FORMAT JSONEachRow'.format(DATABASE, table)}, json_lines(rows))

    def ids(self, sql):
        return {int(line) for line in self.select(sql).split() if line.strip()}

    def scalar(self, sql):
        text = self.select(sql).strip()
        return int(text) if text else 0


# ----- one pass -------------------------------------------------------------------------------

def paged(fetch, sql, size, first=0, cursor=lambda row: row['id']):
    """Keyset pages of at most size rows, ascending by id."""
    after = first
    while True:
        rows = fetch(sql, (after, size))
        if not rows:
            return
        yield rows
        if len(rows) < size:
            return
        after = cursor(rows[-1])


def sync_users(fetch, ch, key, synced_at, size):
    known = ch.ids('SELECT user_id FROM {}.{} FINAL WHERE is_deleted = 0 FORMAT TSV'.format(DATABASE, USERS))
    seen = set()
    for page in paged(fetch, USERS_SQL, size):
        rows = [user_row(r, key, synced_at) for r in page]
        ch.insert(USERS, rows)
        seen.update(r['user_id'] for r in rows)
    gone = sorted(known - seen)
    if gone and not seen:
        # An empty account list against a populated warehouse is far more likely a wrong database than a real
        # deletion of every account; refuse to retire them all.
        raise WarehouseError('empty_user_snapshot')
    for page in batches([tombstone(uid, synced_at) for uid in gone], size):
        ch.insert(USERS, page)
    return {'users': len(seen), 'users_retired': len(gone)}


def sync_incremental(fetch, ch, table, id_column, sql, transform, synced_at, size):
    """Rows above (high-water mark - OVERLAP) whose ids ClickHouse does not have yet."""
    high = ch.scalar('SELECT max({}) FROM {}.{} FORMAT TSV'.format(id_column, DATABASE, table))
    start = max(0, high - OVERLAP)
    present = ch.ids('SELECT {0} FROM {1}.{2} WHERE {0} > {3} FORMAT TSV'.format(id_column, DATABASE, table, start))
    added = 0
    for page in paged(fetch, sql, size, first=start):
        rows = [transform(r, synced_at) for r in page if int(r['id']) not in present]
        ch.insert(table, rows)
        present.update(r[id_column] for r in rows)
        added += len(rows)
    return added


def sync(fetch, ch, key, now=None, size=BATCH):
    """One pass over already-open sources: fetch(sql, params) -> list of dict rows; ch a ClickHouse."""
    synced_at = timestamp(now or datetime.now(timezone.utc))
    summary = sync_users(fetch, ch, key, synced_at, size)
    summary['events'] = sync_incremental(fetch, ch, EVENTS, 'event_id', EVENTS_SQL, event_row, synced_at, size)
    ready = fetch(ENQUIRIES_READY_SQL, ())
    if ready and ready[0]['ready']:
        summary['enquiries'] = sync_incremental(fetch, ch, ENQUIRIES, 'enquiry_id', ENQUIRIES_SQL, enquiry_row, synced_at, size)
    else:
        summary['enquiries'] = None
    return summary


def run_pass(config, size, connect=None):
    import psycopg
    from psycopg.rows import dict_row
    connect = connect or psycopg.connect
    ch = ClickHouse(config.clickhouse_url, config.clickhouse_user, config.clickhouse_password)
    options = '-c default_transaction_read_only=on -c statement_timeout=60000 -c application_name=user_warehouse'
    with connect(config.database_url, row_factory=dict_row, connect_timeout=10, options=options) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True

        def fetch(sql, params):
            return conn.execute(sql, params).fetchall()

        summary = sync(fetch, ch, config.email_key, size=size)
        conn.rollback()  # nothing was written; end the snapshot explicitly
    return summary


def error_class(error):
    if isinstance(error, WarehouseError):
        return str(error)
    return type(error).__name__  # a driver message can quote data or the connection string, so only the class


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--once', action='store_true', help='One pass, then exit (CronJob)')
    parser.add_argument('--interval', type=float, default=900.0, help='Seconds between passes without --once')
    parser.add_argument('--batch', type=int, default=BATCH, help='Rows per read and per insert (1-{})'.format(MAX_BATCH))
    args = parser.parse_args(argv)
    if not 1 <= args.batch <= MAX_BATCH:
        parser.error('--batch must be between 1 and {}'.format(MAX_BATCH))
    stop = threading.Event()
    if not args.once:  # a single pass keeps the default: SIGTERM ends it, and the next run starts over safely
        try:
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
        except ValueError:
            pass  # only the main thread may register handlers
    while True:
        started = time.monotonic()
        try:
            summary = run_pass(load_config(), args.batch)
        except Exception as error:
            log('user_warehouse_pass_failed', level='error', error_class=error_class(error))
            if args.once:
                return 1
        else:
            log('user_warehouse_pass_completed', duration_ms=int((time.monotonic() - started) * 1000), **summary)
        if args.once or stop.wait(max(args.interval, 1.0)):
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
