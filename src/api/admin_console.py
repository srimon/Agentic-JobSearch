"""The administrator console: web traffic, accounts, conversion and machine load in one screen.

Administrators only (every route depends on the `administrator` dependency in src/api/main.py, the
same gate as every other operational display in Job Search).

Where the numbers come from, and what this module is careful about:

* ClickHouse (hub-data) answers the traffic, account, conversion and GPU panels. The API reads it
  as hub_admin_console: readonly=2, SELECT on the console's tables and views only, and column-level
  grants that leave out the account name, display name and e-mail HMAC (scripts/admin_console.py).
  Only the statements in admin_queries.py are ever sent, each parameterised and LIMITed, with a
  server-side execution cap the identity cannot raise.
* Prometheus (hub-observability, reached through the ExternalName service the API already has
  egress to) answers the service CPU and memory panel, from a fixed set of expressions.
* Nothing here reads the Job Search database, so a console refresh cannot slow the product down.

Each answer carries its source, its freshness, a plain-language summary and, per panel, the
sentence that says how it was measured. A source that is unavailable, unconfigured or empty makes
its panel say so - it never makes the route fail and it never produces an invented number.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from src.settings import settings
from src.api import admin_queries as queries

log = logging.getLogger('jobsearch.admin_console')

CLICKHOUSE_SOURCE = 'ClickHouse hub_analytics in hub-data, read as hub_admin_console'
PROMETHEUS_SOURCE = 'Prometheus in hub-observability, scraped every 15 seconds'


def warehouse_source(*tables):
    return CLICKHOUSE_SOURCE + ' (' + ', '.join(tables) + ')'


def plural(value, one, many=None):
    return '{:,} {}'.format(int(value or 0), one if int(value or 0) == 1 else (many or one + 's'))
# Kept small so a refresh cannot hammer the warehouse, and short enough that a panel is never
# more than a minute behind what the warehouse itself holds (the account sync runs every 15).
CACHE_SECONDS = 45
CLICKHOUSE_TIMEOUT = (3, 20)
PROMETHEUS_TIMEOUT = (2, 8)
MAX_RESPONSE = 4 * 1024 * 1024
# Sent with every statement; the identity's own SETTINGS ... MAX caps mean a larger value would be
# refused by the server, so this can only ever narrow what the console is allowed to do.
CLICKHOUSE_LIMITS = {'max_execution_time': '10', 'max_result_rows': '5000', 'max_rows_to_read': '20000000'}

_cache = {}
_cache_lock = threading.Lock()
_password = {}


def now():
    return datetime.now(timezone.utc)


def cached(key, producer, seconds=None):
    """Short server-side memo: the same panel and range asked for again inside the window gets the
    answer already computed instead of another round of warehouse queries."""
    ttl = CACHE_SECONDS if seconds is None else seconds
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
    value = producer()
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, value)
    return value


def clear_cache():
    with _cache_lock:
        _cache.clear()
    _password.clear()


class SourceUnavailable(RuntimeError):
    """An upstream that could not answer. The message is a class of problem, never data."""


# ----- ClickHouse -----------------------------------------------------------------------------

def clickhouse_password():
    path = settings().admin_clickhouse_password_file
    if _password.get('path') != path:
        try:
            _password.update(path=path, value=open(path, encoding='utf-8').read().strip())
        except OSError:
            _password.update(path=path, value='')
    if not _password.get('value'):
        raise SourceUnavailable('The warehouse credential is not mounted on this API pod.')
    return _password['value']


def clickhouse(entry):
    """One fixed statement with its parameters. The text is a constant in admin_queries; the
    caller's range travels as a ClickHouse query parameter, so it is read as a number."""
    params = {'database': 'hub_analytics', 'default_format': 'JSONCompact', **CLICKHOUSE_LIMITS}
    params.update({'param_' + name: value for name, value in entry['params'].items()})
    cfg = settings()
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.post(cfg.admin_clickhouse_url + '/', params=params, data=entry['sql'].encode('utf-8'),
                              headers={'X-ClickHouse-User': cfg.admin_clickhouse_user,
                                       'X-ClickHouse-Key': clickhouse_password()},
                              timeout=CLICKHOUSE_TIMEOUT, allow_redirects=False, stream=True) as response:
                raw = bytearray()
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE:
                        raise SourceUnavailable('The warehouse answer was too large.')
                if response.status_code != 200:
                    raise SourceUnavailable('The warehouse refused a query.')
                payload = response.json() if raw else {}
    except SourceUnavailable:
        raise
    except Exception as exc:
        log.warning('clickhouse_unavailable error_class=%s', type(exc).__name__)
        raise SourceUnavailable('The warehouse could not be reached.') from None
    names = [column['name'] for column in payload.get('meta', [])]
    return [dict(zip(names, row)) for row in payload.get('data', [])]


def rows(entry):
    return clickhouse(entry)


def first(entry, default=None):
    found = clickhouse(entry)
    return found[0] if found else (default if default is not None else {})


# ----- Prometheus -----------------------------------------------------------------------------

def prometheus(path, params):
    cfg = settings()
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(cfg.admin_prometheus_url + path, params=params, timeout=PROMETHEUS_TIMEOUT,
                             allow_redirects=False) as response:
                if response.status_code != 200:
                    raise SourceUnavailable('Prometheus refused a query.')
                payload = response.json()
    except SourceUnavailable:
        raise
    except Exception as exc:
        log.warning('prometheus_unavailable error_class=%s', type(exc).__name__)
        raise SourceUnavailable('Prometheus could not be reached.') from None
    if payload.get('status') != 'success':
        raise SourceUnavailable('Prometheus returned no result.')
    return payload['data']['result']


def number(value, digits=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float('inf'), float('-inf')):
        return None
    return round(result, digits) if digits is not None else result


# ----- shaping --------------------------------------------------------------------------------

def envelope(name, source, note=''):
    return {'panel': name, 'source': source, 'generated_at': now().isoformat(timespec='seconds'),
            'available': True, 'message': '', 'summary': '', 'measured': note, 'notes': {}}


def unavailable(name, source, reason, note=''):
    body = envelope(name, source, note)
    body.update(available=False, message=reason, summary='No numbers are shown for this panel while its source is unavailable.')
    return body


def collect(entries, wanted):
    """Runs the statements a panel needs, a few at a time so the first load is not eight round
    trips end to end, and keeps each one's "how this is measured" sentence. One statement that
    cannot be answered fails the whole panel, which is what makes it say so rather than show a
    half-filled screen."""
    notes = {key: entries[key]['note'] for key in wanted}

    def run(item):
        key, single = item
        entry = entries[key]
        return key, (first(entry) if single else rows(entry))

    with ThreadPoolExecutor(max_workers=4) as pool:
        data = dict(pool.map(run, list(wanted.items())))
    return data, notes


def share(part, whole):
    return round(part / whole, 4) if whole else None


def percent(part, whole):
    value = share(part, whole)
    return '—' if value is None else '{:.0f}%'.format(value * 100)


def count(value):
    return '{:,}'.format(int(value or 0))


# ----- panels ---------------------------------------------------------------------------------

def traffic_panel(days):
    entries = queries.traffic(days)
    try:
        data, notes = collect(entries, {'daily': False, 'by_host': False, 'top_pages': False, 'referrers': False,
                                        'countries': False, 'status': False, 'slowest': False, 'freshness': True})
    except SourceUnavailable as exc:
        return unavailable('traffic', warehouse_source('web_hits_v1'), str(exc), entries['daily']['note'])
    body = envelope('traffic', warehouse_source('web_hits_v1'), entries['daily']['note'])
    body['notes'] = notes
    body.update(data)
    hits = sum(int(row['hits']) for row in data['daily'])
    bots = sum(int(row['bot_hits']) for row in data['daily'])
    errors = sum(int(row['server_errors']) for row in data['daily'])
    top = data['by_host'][0]['host'] if data['by_host'] else '—'
    body['totals'] = {'hits': hits, 'bot_hits': bots, 'server_errors': errors, 'days_with_traffic': len(data['daily']),
                      'visitors_peak_day': max((int(row['visitors']) for row in data['daily']), default=0)}
    body['fresh_at'] = data['freshness'].get('last_hit_at')
    body['retention_days'] = queries.RAW_TRAFFIC_DAYS
    if not hits:
        body['summary'] = 'No requests reached the public edge in the last {} days.'.format(days)
    else:
        body['summary'] = ('{} over {} days, {} of them from bots; {} was the busiest product host, and {} '
                           'came back as a server error.').format(plural(hits, 'request'), days, percent(bots, hits),
                                                                  top, plural(errors, 'request'))
    return body


def accounts_panel(days):
    entries = queries.accounts(days)
    try:
        data, notes = collect(entries, {'daily': False, 'totals': True, 'mfa': False, 'signins': False,
                                        'events': False, 'freshness': True})
    except SourceUnavailable as exc:
        return unavailable('accounts', warehouse_source('users_v1', 'account_events_v1'), str(exc), entries['daily']['note'])
    body = envelope('accounts', warehouse_source('users_v1', 'account_events_v1'), entries['daily']['note'])
    body['notes'] = notes
    body.update(data)
    totals = data['totals'] or {}
    new_accounts = sum(int(row['accounts']) for row in data['daily'])
    allowed = sum(int(row['events']) for row in data['signins'] if row['outcome'] == 'allowed')
    refused = sum(int(row['events']) for row in data['signins'] if row['outcome'] != 'allowed')
    body['totals_summary'] = {
        'new_accounts': new_accounts, 'accounts': int(totals.get('accounts') or 0),
        'active_accounts': int(totals.get('active_accounts') or 0),
        'verified_share': share(int(totals.get('verified') or 0), int(totals.get('accounts_with_email') or 0)),
        'mfa_share': share(int(totals.get('with_mfa') or 0), int(totals.get('active_accounts') or 0)),
        'signins_allowed': allowed, 'signins_refused': refused,
    }
    body['fresh_at'] = data['freshness'].get('last_synced_at') or totals.get('last_synced_at')
    body['summary'] = ('{} accounts exist, {} of them enabled; {} were created in the last {} days. {} of accounts '
                       'with an address are verified and {} of enabled accounts use two-step. {} sign-ins were '
                       'allowed and {} refused in the range.').format(
        count(totals.get('accounts')), count(totals.get('active_accounts')), count(new_accounts), days,
        percent(int(totals.get('verified') or 0), int(totals.get('accounts_with_email') or 0)),
        percent(int(totals.get('with_mfa') or 0), int(totals.get('active_accounts') or 0)),
        count(allowed), count(refused))
    return body


# What is recorded about model calls today, checked on 15 Sep 2026, and what each would need.
# Nothing here is estimated: the console shows this list instead of a cost.
AI_COST_EVIDENCE = [
    {'source': 'Model proxy (hub-system/model-egress)',
     'records': 'Nothing per call. Its squid configuration sets "access_log none" (scripts/model_egress.py), and it '
                'only ever sees an encrypted CONNECT tunnel to api.openai.com, so it could not see a model, a token '
                'count or a price even with logging on.',
     'to_measure': 'Turn its access log on for a per-call count of tunnels per product, which still carries no token '
                   'or cost figure.'},
    {'source': 'Job Prep (prep-production)',
     'records': 'Request counts only: prep_operations_total by operation and outcome in Prometheus, and prep.request '
                'log lines. No model, prompt, token count or price.',
     'to_measure': 'Record the usage block the model API already returns (prompt and completion tokens, model name) '
                   'on each answer and copy it to the warehouse the way the account sync does.'},
    {'source': 'Library (mbk-production)',
     'records': 'Reader runs and their outcome in its own database, and traces in Phoenix. No per-call token count '
                'reaches the shared warehouse.',
     'to_measure': 'Same: store the returned usage per run, then add a warehouse table for it.'},
    {'source': 'Job Search (jbs-production)',
     'records': 'Collection and HTTP counters in Prometheus, and traces in Phoenix. Its own agent work goes through '
                'the same proxy, so the same gap applies.',
     'to_measure': 'Same.'},
    {'source': 'Vendor invoice',
     'records': 'The only place a real spend figure exists today is the model vendor\'s own billing page.',
     'to_measure': 'Enter the monthly invoice by hand, or pull the vendor usage API, to divide a known spend across '
                   'the recorded per-product call counts.'},
]


def monetization_panel(days):
    entries = queries.monetization(days)
    try:
        data, notes = collect(entries, {'visitors': True, 'signups': True, 'active': True, 'reach': False,
                                        'spread': False, 'repeat': True, 'enquiries': False, 'enquiry_pages': False})
    except SourceUnavailable as exc:
        body = unavailable('monetization', warehouse_source('web_hits_v1', 'users_v1', 'enquiries_v1'), str(exc), entries['visitors']['note'])
        body['ai_cost'] = {'recorded': False, 'message': AI_COST_MESSAGE, 'evidence': AI_COST_EVIDENCE}
        return body
    body = envelope('monetization', warehouse_source('web_hits_v1', 'users_v1', 'enquiries_v1'), entries['visitors']['note'])
    body['notes'] = notes
    body.update(data)
    visitors = int(data['visitors'].get('visitors') or 0)
    signups = int(data['signups'].get('accounts') or 0)
    verified = int(data['signups'].get('verified') or 0)
    active = int(data['active'].get('accounts') or 0)
    repeat_total = int(data['repeat'].get('visitors') or 0)
    returning = int(data['repeat'].get('returning') or 0)
    body['funnel'] = [
        {'step': 'Visitors', 'value': visitors, 'of_previous': None},
        {'step': 'Sign-ups', 'value': signups, 'of_previous': share(signups, visitors)},
        {'step': 'Verified', 'value': verified, 'of_previous': share(verified, signups)},
        {'step': 'Signed in', 'value': active, 'of_previous': share(active, verified)},
    ]
    body['repeat_rate'] = share(returning, repeat_total)
    body['fresh_at'] = data['visitors'].get('last_hit_at')
    body['enquiry_total'] = sum(int(row['enquiries']) for row in data['enquiries'])
    body['visitor_caveat'] = queries.VISITOR_WEEK_NOTE
    body['ai_cost'] = {'recorded': False, 'message': AI_COST_MESSAGE, 'evidence': AI_COST_EVIDENCE}
    body['summary'] = ('{} visitors in {} days became {} sign-ups ({}), {} verified and {} signed in at least once. '
                       '{} of visitors came back on another day and {} enquiries arrived.').format(
        count(visitors), days, count(signups), percent(signups, visitors), count(verified), count(active),
        percent(returning, repeat_total), count(body['enquiry_total']))
    return body


AI_COST_MESSAGE = ('Per-call model cost is not recorded anywhere yet, so no cost or revenue figure is shown. '
                   'The products call the model vendor through an encrypted tunnel that logs nothing, and no '
                   'product stores the token counts the vendor returns.')


def machine_panel(days):
    body = envelope('machine', PROMETHEUS_SOURCE + ', and ' + warehouse_source('gpu_samples_v1'), queries.PROMETHEUS_NOTE)
    body['notes'] = {'services': queries.PROMETHEUS_NOTE, 'gpu': queries.gpu(days)['recent']['note'],
                     'host': HOST_METRICS_NOTE, 'storage': STORAGE_NOTE}
    body['services'] = services_section()
    body['gpu'] = gpu_section(days)
    body['host'] = {'available': False, 'message': HOST_METRICS_NOTE}
    body['storage'] = {'available': False, 'message': STORAGE_NOTE}
    parts = []
    if body['services']['available']:
        parts.append('{} of {} scrape targets are up and the services are using {} CPU cores and {} MB of memory between them.'.format(
            body['services']['targets_up'], body['services']['targets'],
            body['services']['total_cpu_cores'], body['services']['total_memory_mb']))
    else:
        parts.append('Service CPU and memory are unavailable: ' + body['services']['message'])
    parts.append('GPU sampling is ' + ('on: ' + body['gpu']['summary'] if body['gpu']['available'] else 'not enabled, so no GPU number is shown.'))
    parts.append('Whole-machine CPU, memory and disk are not collected by anything on this cluster.')
    body['summary'] = ' '.join(parts)
    return body


HOST_METRICS_NOTE = ('Whole-machine CPU, memory and disk are not measured: this Prometheus scrapes application '
                     'metric endpoints only, with no node exporter, no cAdvisor and no kube-state-metrics '
                     'installed. Installing any one of those would fill this panel.')
STORAGE_NOTE = ('Disk and volume use are not scraped either, for the same reason. ClickHouse and PostgreSQL sizes '
                'could be read directly, but only a node or kube-state exporter gives free space on the machine.')


def services_section():
    try:
        instant = {name: prometheus('/api/v1/query', {'query': expression})
                   for name, expression in queries.PROMETHEUS_QUERIES.items()}
    except SourceUnavailable as exc:
        return {'available': False, 'message': str(exc), 'services': [], 'samples': []}
    by_job = {}
    for name, result in instant.items():
        for item in result:
            job = str(item.get('metric', {}).get('job', ''))[:60]
            if not job:
                continue
            by_job.setdefault(job, {'job': job})[name] = number(item['value'][1], 4)
    services = []
    for job in sorted(by_job):
        entry = by_job[job]
        memory = entry.get('memory_bytes')
        services.append({'job': job, 'cpu_cores': entry.get('cpu_cores'),
                         'memory_mb': round(memory / (1024 * 1024), 1) if memory else None,
                         'open_files': entry.get('open_files'), 'up': entry.get('up') == 1})
    end = int(time.time())
    samples = []
    try:
        history = prometheus('/api/v1/query_range', {'query': queries.PROMETHEUS_RANGE, 'start': end - 3600,
                                                     'end': end, 'step': 60})
        if history:
            samples = [{'at': number(point[0]), 'value': number(point[1], 4)} for point in history[0].get('values', [])][-61:]
    except SourceUnavailable:
        samples = []
    return {'available': True, 'message': '', 'services': services, 'samples': samples,
            'targets': len(services), 'targets_up': sum(1 for s in services if s['up']),
            'total_cpu_cores': round(sum(s['cpu_cores'] or 0 for s in services), 3),
            'total_memory_mb': round(sum(s['memory_mb'] or 0 for s in services), 1)}


GPU_ENABLE_MESSAGE = ('GPU sampling is not enabled. The machine has one NVIDIA card, but it is not exposed to the '
                      'cluster and nothing in Kubernetes can see it, so no exporter can collect it. To turn this '
                      'panel on, run scripts/gpu_sampler.py on the host from cron or systemd; '
                      'docs/runbooks/admin-console.md has the one command.')


def gpu_section(days):
    entries = queries.gpu(days)
    try:
        if int(first(entries['present']).get('present') or 0) == 0:
            return {'available': False, 'enabled': False, 'message': GPU_ENABLE_MESSAGE, 'daily': []}
        recent = first(entries['recent'])
        if int(recent.get('samples') or 0) == 0:
            return {'available': False, 'enabled': False, 'message': GPU_ENABLE_MESSAGE, 'daily': []}
        daily = rows(entries['daily'])
    except SourceUnavailable as exc:
        return {'available': False, 'enabled': False, 'message': str(exc), 'daily': []}
    total = number(recent.get('total_memory_mb')) or 0
    used = number(recent.get('avg_memory_mb')) or 0
    return {'available': True, 'enabled': True, 'message': '', 'daily': daily, **recent,
            'memory_share': share(used, total),
            'summary': '{} averaged {}% use over {} samples, peaking at {}%.'.format(
                recent.get('gpu_name') or 'The card', recent.get('avg_utilisation'),
                count(recent.get('samples')), recent.get('peak_utilisation'))}


# ----- routes ---------------------------------------------------------------------------------

PANELS = {'traffic': traffic_panel, 'accounts': accounts_panel, 'monetization': monetization_panel,
          'machine': machine_panel}


def create_router(administrator):
    router = APIRouter(prefix='/api/admin')

    def range_days(days):
        if days not in queries.RANGES:
            raise HTTPException(422, 'Range must be one of ' + ', '.join(str(value) for value in queries.RANGES) + ' days')
        return days

    async def panel(name, days):
        range_days(days)
        return await run_in_threadpool(cached, (name, days), lambda: PANELS[name](days))

    @router.get('/traffic', dependencies=[Depends(administrator)])
    async def traffic(days: int = Query(7)):
        return await panel('traffic', days)

    @router.get('/accounts', dependencies=[Depends(administrator)])
    async def accounts(days: int = Query(7)):
        return await panel('accounts', days)

    @router.get('/monetization', dependencies=[Depends(administrator)])
    async def monetization(days: int = Query(7)):
        return await panel('monetization', days)

    @router.get('/machine', dependencies=[Depends(administrator)])
    async def machine(days: int = Query(7)):
        return await panel('machine', days)

    @router.get('/overview', dependencies=[Depends(administrator)])
    async def overview(days: int = Query(7)):
        """Every panel in one answer, so the screen makes one request and each panel keeps its own
        source, freshness and caveats."""
        range_days(days)
        panels = await run_in_threadpool(lambda: {name: cached((name, days), lambda name=name: PANELS[name](days))
                                                  for name in PANELS})
        return {'range_days': days, 'ranges': list(queries.RANGES),
                'generated_at': now().isoformat(timespec='seconds'),
                'cache_seconds': CACHE_SECONDS, 'panels': panels}

    return router
