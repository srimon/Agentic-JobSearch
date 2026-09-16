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

How the figures are counted, so that none of them flatters the products (15 Sep 2026):

* bots are never a visit. Requests the edge classed as a bot are left out of every headline hit and
  visitor figure and kept as their own series;
* a sign-up is a self-service account: made through the public sign-up form with an address on it.
  The console and seed accounts the acceptance script creates carry no address, and they are
  reported as their own figure - counting them is what made this panel read 98 sign-ups;
* the funnel starts at the product hosts. The welcome site holds nearly every visitor code the edge
  sees, so it is charted beside the products and never inside the conversion figure;
* the wider numbers are still sent, each labelled with what it includes, so the two can be compared
  rather than one quietly replacing the other.
"""
import json
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

# Every public name the edge serves, in the order the console shows them (platform/brand/BRAND.md).
# The console charts each of these on its own, so the welcome site - which carries nearly every
# visitor code at the edge - is never mistaken for use of a product.
PRODUCTS = [
    {'host': 'jobs.bagala.ai', 'name': 'Job Search', 'kind': 'product'},
    {'host': 'prep.bagala.ai', 'name': 'Job Prep', 'kind': 'product'},
    {'host': 'library.bagala.ai', 'name': 'Library', 'kind': 'product'},
    {'host': 'hub.bagala.ai', 'name': 'Products page', 'kind': 'product'},
    {'host': 'www.bagala.ai', 'name': 'Welcome site', 'kind': 'site'},
    {'host': 'bagala.ai', 'name': 'Welcome site (bare domain)', 'kind': 'site'},
]
# The screen says this before any number, so nobody reads the console as a marketing figure.
DATA_QUALITY = [
    'Bot-classed requests are left out of every visit and visitor figure. Turn on "Show bots" to see them as their own series.',
    'Sign-ups are self-service accounts only: made through the sign-up form with an address on them. Console and seed accounts - the ones the acceptance script and the operator create - are counted separately and are never sign-ups.',
    'The funnel starts at the product hosts (Job Search, Job Prep, Library, Products page). A visit to the welcome site is counted, and charted, on its own.',
    'A visitor is a hashed address re-keyed every ISO week, so a visitor count over more than 7 days is an upper bound and the repeat-visit rate is a floor.',
]
# How often the screen refetches every panel by itself. The server cache (45 s) is far shorter, so a
# refresh - scheduled or by hand - always reads the warehouse again.
REFRESH_MINUTES = 120


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
                # The body is already in `raw`: response.json() would re-read a consumed stream
                # and raise, which is how every panel reported an unreachable warehouse.
                payload = json.loads(bytes(raw)) if raw else {}
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
        data, notes = collect(entries, {'daily': False, 'daily_by_host': False, 'daily_visitors': False,
                                        'by_host': False, 'top_pages': False, 'referrers': False,
                                        'referrers_by_host': False, 'countries': False, 'countries_by_host': False,
                                        'status': False, 'status_by_host': False, 'slowest': False, 'freshness': True})
    except SourceUnavailable as exc:
        return unavailable('traffic', warehouse_source('web_hits_v1'), str(exc), entries['daily']['note'])
    body = envelope('traffic', warehouse_source('web_hits_v1'), entries['daily']['note'])
    body['notes'] = notes
    body.update(data)
    all_hits = sum(int(row['hits']) for row in data['daily'])
    bots = sum(int(row['bot_hits']) for row in data['daily'])
    human = all_hits - bots
    errors = sum(int(row['server_errors']) for row in data['daily'])
    ranked = sorted(data['by_host'], key=lambda row: int(row['hits']) - int(row['bot_hits']), reverse=True)
    top = ranked[0]['host'] if ranked else '—'
    body['totals'] = {'human_hits': human, 'all_hits': all_hits, 'bot_hits': bots, 'server_errors': errors,
                      'days_with_traffic': len(data['daily']),
                      'visitors_peak_day': max((int(row['human_visitors']) for row in data['daily_visitors']), default=0),
                      'product_visitors_peak_day': max((int(row['product_visitors']) for row in data['daily_visitors']), default=0)}
    body['fresh_at'] = data['freshness'].get('last_hit_at')
    body['retention_days'] = queries.RAW_TRAFFIC_DAYS
    body['bot_note'] = queries.BOT_NOTE
    body['visitor_caveat'] = queries.VISITOR_WEEK_NOTE
    body['product_note'] = queries.PRODUCT_VISITOR_NOTE
    if not all_hits:
        body['summary'] = 'No requests reached the public edge in the last {} days.'.format(days)
    else:
        body['summary'] = ('{} from people over {} days, and {} more from bots that every figure here leaves out; '
                           '{} was the busiest host, and {} came back as a server error.').format(
            plural(human, 'request'), days, plural(bots, 'request'), top, plural(errors, 'request'))
    return body


def accounts_panel(days):
    """Accounts, counted as people rather than as rows.

    Everything headline here is the self-service population: an account made through the public
    sign-up form with an address on it. The console and seed accounts the acceptance script creates
    carry no address, and they are shown as their own figure, never as sign-ups - counting them was
    what made this panel claim 98 sign-ups when one person had signed up.
    """
    entries = queries.accounts(days)
    try:
        data, notes = collect(entries, {'daily': False, 'self_daily': False, 'self_totals': True, 'totals': True,
                                        'mfa': False, 'signins': False, 'events': False, 'freshness': True})
    except SourceUnavailable as exc:
        return unavailable('accounts', warehouse_source('users_v1', 'account_events_v1'), str(exc), entries['self_daily']['note'])
    body = envelope('accounts', warehouse_source('users_v1', 'account_events_v1'), entries['self_daily']['note'])
    body['notes'] = notes
    body.update(data)
    own = data['self_totals'] or {}
    totals = data['totals'] or {}
    accounts = int(own.get('accounts') or 0)
    verified = int(own.get('verified') or 0)
    with_mfa = int(own.get('with_mfa') or 0)
    new_accounts = sum(int(row['accounts']) for row in data['self_daily'])
    allowed = sum(int(row['events']) for row in data['signins'] if row['outcome'] == 'allowed')
    refused = sum(int(row['events']) for row in data['signins'] if row['outcome'] != 'allowed')
    body['totals_summary'] = {
        'accounts': accounts, 'new_accounts': new_accounts,
        'active_accounts': int(own.get('active_accounts') or 0),
        'disabled_accounts': int(own.get('disabled_accounts') or 0),
        'verified': verified, 'with_mfa': with_mfa,
        'verified_share': share(verified, accounts), 'mfa_share': share(with_mfa, accounts),
        'unverified_after_a_day': int(own.get('unverified_after_a_day') or 0),
        'signed_in_in_range': int(own.get('signed_in_in_range') or 0),
        'ever_signed_in': int(own.get('ever_signed_in') or 0),
        'internal_accounts': int(own.get('internal_accounts') or 0),
        'internal_active': int(own.get('internal_active') or 0),
        'all_accounts': int(totals.get('accounts') or 0),
        'all_new_accounts': sum(int(row['accounts']) for row in data['daily']),
        'signins_allowed': allowed, 'signins_refused': refused,
    }
    body['counting_rule'] = queries.SELF_SERVICE_NOTE
    body['fresh_at'] = data['freshness'].get('last_synced_at') or own.get('last_synced_at')
    body['summary'] = ('{} sign-ups exist, {} of them enabled, and {} were made in the last {} days. {} are verified '
                       'and {} use two-step. {} console and seed accounts are counted separately and are not sign-ups. '
                       '{} sign-ins were allowed and {} refused in the range.').format(
        count(accounts), count(own.get('active_accounts')), count(new_accounts), days,
        percent(verified, accounts), percent(with_mfa, accounts), count(own.get('internal_accounts')),
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
    """The funnel, counted the way the owner reads it: people using a product, not crawlers on the
    front page, and self-service sign-ups, not the accounts the acceptance script leaves behind.
    The wider figures are kept beside it, each labelled with what it includes."""
    entries = queries.monetization(days)
    try:
        data, notes = collect(entries, {'visitors': True, 'product_visitors': True, 'signups': True,
                                        'self_signups': True, 'active': True, 'reach': False, 'spread': False,
                                        'repeat': True, 'enquiries': False, 'enquiry_pages': False})
    except SourceUnavailable as exc:
        body = unavailable('monetization', warehouse_source('web_hits_v1', 'users_v1', 'enquiries_v1'), str(exc), entries['product_visitors']['note'])
        body['ai_cost'] = {'recorded': False, 'message': AI_COST_MESSAGE, 'evidence': AI_COST_EVIDENCE}
        return body
    body = envelope('monetization', warehouse_source('web_hits_v1', 'users_v1', 'enquiries_v1'), entries['product_visitors']['note'])
    body['notes'] = notes
    body.update(data)
    visitors = int(data['product_visitors'].get('visitors') or 0)
    all_visitors = int(data['visitors'].get('visitors') or 0)
    signups = int(data['self_signups'].get('accounts') or 0)
    verified = int(data['self_signups'].get('verified') or 0)
    signed_in = int(data['self_signups'].get('signed_in') or 0)
    repeat_total = int(data['repeat'].get('visitors') or 0)
    returning = int(data['repeat'].get('returning') or 0)
    body['funnel'] = [
        {'step': 'Product visitors', 'value': visitors, 'of_previous': None},
        {'step': 'Sign-ups', 'value': signups, 'of_previous': share(signups, visitors)},
        {'step': 'Verified', 'value': verified, 'of_previous': share(verified, signups)},
        {'step': 'Signed in', 'value': signed_in, 'of_previous': share(signed_in, verified)},
    ]
    body['funnel_note'] = queries.PRODUCT_VISITOR_NOTE + ' ' + queries.SELF_SERVICE_NOTE
    body['comparison'] = {'all_visitors': all_visitors,
                          'all_new_accounts': int(data['signups'].get('accounts') or 0),
                          'all_signed_in': int(data['active'].get('accounts') or 0)}
    body['attribution'] = {'signups': SIGNUP_ATTRIBUTION_NOTE, 'enquiries': ENQUIRY_ATTRIBUTION_NOTE}
    body['repeat_rate'] = share(returning, repeat_total)
    body['fresh_at'] = data['product_visitors'].get('last_hit_at')
    body['enquiry_total'] = sum(int(row['enquiries']) for row in data['enquiries'])
    body['visitor_caveat'] = queries.VISITOR_WEEK_NOTE
    body['bot_note'] = queries.BOT_NOTE
    body['ai_cost'] = {'recorded': False, 'message': AI_COST_MESSAGE, 'evidence': AI_COST_EVIDENCE}
    body['summary'] = ('{} people used a product in {} days ({} more only saw the welcome site) and {} signed up ({} '
                       'of product visitors), {} verified and {} signed in. {} of visitors came back on another day '
                       'and {} enquiries arrived.').format(
        count(visitors), days, count(max(all_visitors - visitors, 0)), count(signups), percent(signups, visitors),
        count(verified), count(signed_in), percent(returning, repeat_total), count(body['enquiry_total']))
    return body


SIGNUP_ATTRIBUTION_NOTE = ('Sign-ups cannot be split per product: one Bagala account covers every product, and the '
                           'warehouse records no product against an account. They are shown for all products together.')
ENQUIRY_ATTRIBUTION_NOTE = ('Enquiries cannot be split per product either: enquiries_v1 keeps the page path a message '
                            'was sent from, not the host, so they are shown for all products together.')


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
                'cache_seconds': CACHE_SECONDS, 'refresh_minutes': REFRESH_MINUTES,
                'products': PRODUCTS, 'data_quality': DATA_QUALITY, 'panels': panels}

    return router
