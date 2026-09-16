"""The fixed queries behind the administrator console. Text and parameters only, no I/O.

Rules every statement here keeps, because the console is the only thing in Job Search that reads
the shared warehouse:

* read-only: each one starts with SELECT, and the ClickHouse identity the API uses
  (hub_admin_console, scripts/admin_console.py) has readonly=2 with SELECT on nothing else;
* parameterised: a caller's date range never reaches the text. It travels as a ClickHouse query
  parameter ({days:UInt16}), so a value can only ever be read as a number, and RANGES is the
  closed set of values a route accepts;
* bounded: every statement ends in a LIMIT, and the identity carries max_execution_time,
  max_result_rows and max_rows_to_read caps it cannot raise;
* aggregate: no statement selects a raw account, an address, an enquiry message or a question.
  The account views it reads (platform/analytics/admin_console.sql) cannot even see the account
  name, display name or e-mail HMAC.

Each entry carries the sentence the console shows under "How this is measured", so the wording on
screen and the statement that produced the number live in the same place.
"""

# The date ranges the console offers. A route rejects anything else, so no other value is ever built.
RANGES = (7, 30, 90)
# web_hits_v1 keeps 90 days (platform/analytics/web_hits.sql); the daily aggregate keeps two years.
RAW_TRAFFIC_DAYS = 90
# The visitor column is HMAC(address, key || ISO week): not reversible, and a different value each
# ISO week. Counting distinct visitors over more than a week therefore counts a returning person
# again, so every "visitors" number over a longer range is an upper bound. Said on screen too.
VISITOR_WEEK_NOTE = ('Visitors are counted from a hashed address that is re-keyed every ISO week, so a count '
                     'over more than 7 days is an upper bound: someone returning in a later week counts twice.')
NO_VISITOR = "repeat('0', 32)"  # web_hits_v1.visitor when the edge reported no address
HUMAN = "ua_class != 'bot'"


def _query(sql, note, **params):
    return {'sql': sql.strip(), 'params': params, 'note': note}


def days_parameter(days):
    """The only place a caller's range becomes a value. Anything that is not exactly one of the
    three whole numbers is refused here rather than clamped, so a wrong value can never silently
    produce a different panel - and a float, a bool or a string never reaches the warehouse."""
    if type(days) is not int or days not in RANGES:
        raise ValueError('Unsupported range')
    return {'days': str(days)}


# ----- traffic (source: hub_analytics.web_hits_v1, the public edge) --------------------------------

TRAFFIC_DAILY = """
SELECT toDate(ts) AS day,
       count() AS hits,
       uniq(visitor) AS visitors,
       countIf(ua_class = 'bot') AS bot_hits,
       countIf(status >= 500) AS server_errors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY day
ORDER BY day
LIMIT 100
"""

TRAFFIC_BY_HOST = """
SELECT host,
       count() AS hits,
       uniq(visitor) AS visitors,
       countIf(ua_class = 'bot') AS bot_hits,
       round(avg(duration_ms)) AS avg_ms
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY host
ORDER BY hits DESC
LIMIT 20
"""

TRAFFIC_TOP_PAGES = """
SELECT host, path, count() AS hits, uniq(visitor) AS visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND status < 400
GROUP BY host, path
ORDER BY hits DESC
LIMIT 15
"""

TRAFFIC_REFERRERS = """
SELECT referer_host, count() AS hits, uniq(visitor) AS visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND referer_host != '' AND """ + HUMAN + """
GROUP BY referer_host
ORDER BY hits DESC
LIMIT 12
"""

TRAFFIC_COUNTRIES = """
SELECT if(country = '', '(not reported)', country) AS country, count() AS hits, uniq(visitor) AS visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """
GROUP BY country
ORDER BY hits DESC
LIMIT 12
"""

TRAFFIC_STATUS = """
SELECT multiIf(status < 200, '1xx', status < 300, '2xx', status < 400, '3xx', status < 500, '4xx', '5xx') AS status_class,
       count() AS hits
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY status_class
ORDER BY status_class
LIMIT 10
"""

TRAFFIC_SLOWEST = """
SELECT host, path_group, count() AS hits,
       round(quantile(0.95)(duration_ms)) AS p95_ms,
       round(avg(duration_ms)) AS avg_ms
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY host, path_group
HAVING hits >= 5
ORDER BY p95_ms DESC
LIMIT 10
"""

TRAFFIC_FRESHNESS = """
SELECT max(ts) AS last_hit_at, count() AS hits
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
LIMIT 1
"""


def traffic(days):
    values = days_parameter(days)
    edge = 'One row per request that reached the public edge (Cloudflare tunnel to platform/gateway), delivered to ClickHouse by Vector.'
    return {
        'daily': _query(TRAFFIC_DAILY, edge + ' Grouped by UTC day over the chosen range. ' + VISITOR_WEEK_NOTE, **values),
        'by_host': _query(TRAFFIC_BY_HOST, edge + ' Grouped by the public name served, so each product is its own row.', **values),
        'top_pages': _query(TRAFFIC_TOP_PAGES, 'Successful (status below 400) non-bot requests grouped by host and path. The path never carries a query string.', **values),
        'referrers': _query(TRAFFIC_REFERRERS, 'The host part of the Referer header, which is all the edge keeps; requests without one are left out.', **values),
        'countries': _query(TRAFFIC_COUNTRIES, 'CF-IPCountry as Cloudflare reported it on each non-bot request.', **values),
        'status': _query(TRAFFIC_STATUS, 'Every request in the range by response class, bots included.', **values),
        'slowest': _query(TRAFFIC_SLOWEST, 'Edge-measured request duration per host and first path segment, 95th percentile, for groups with at least five requests.', **values),
        'freshness': _query(TRAFFIC_FRESHNESS, 'The most recent request recorded in the range.', **values),
    }


# ----- accounts (source: the account sync, every 15 minutes) ---------------------------------------

ACCOUNTS_DAILY = """
SELECT day, accounts, verified, with_mfa, with_email
FROM hub_analytics.admin_signups_daily
WHERE day >= today() - {days:UInt16}
ORDER BY day
LIMIT 100
"""

ACCOUNTS_TOTALS = """
SELECT accounts, active_accounts, accounts_with_email, verified, unverified_after_a_day,
       with_mfa, active_1d, active_7d, active_30d, last_synced_at
FROM hub_analytics.admin_account_totals
LIMIT 1
"""

ACCOUNTS_MFA = """
SELECT role, active_accounts, with_mfa, low_on_recovery_codes
FROM hub_analytics.admin_mfa_adoption
ORDER BY role
LIMIT 20
"""

ACCOUNTS_SIGNIN_DAILY = """
SELECT event_date AS day, outcome, count() AS events
FROM hub_analytics.account_events_v1
WHERE event_date >= today() - {days:UInt16} AND (action = 'login' OR action = 'login.mfa')
GROUP BY day, outcome
ORDER BY day, outcome
LIMIT 500
"""

ACCOUNTS_EVENT_MIX = """
SELECT action, outcome, count() AS events, uniqExact(user_id) AS accounts
FROM hub_analytics.account_events_v1
WHERE event_date >= today() - {days:UInt16}
GROUP BY action, outcome
ORDER BY events DESC
LIMIT 25
"""

ACCOUNTS_FRESHNESS = """
SELECT max(synced_at) AS last_synced_at, count() AS events
FROM hub_analytics.account_events_v1
WHERE event_date >= today() - {days:UInt16}
LIMIT 1
"""


def accounts(days):
    values = days_parameter(days)
    sync = 'Copied from the Job Search account service every 15 minutes by the user-warehouse CronJob (docs/runbooks/user-warehouse.md).'
    return {
        'daily': _query(ACCOUNTS_DAILY, sync + ' Accounts that still exist, by the day they were created.', **values),
        'totals': _query(ACCOUNTS_TOTALS, sync + ' Totals over every account that still exists; "active" here means the account is not disabled.'),
        'mfa': _query(ACCOUNTS_MFA, 'Two-step sign-in among accounts that are not disabled, counted once per role and once under "(all)".'),
        'signins': _query(ACCOUNTS_SIGNIN_DAILY, 'Recorded sign-in attempts (login and login.mfa) by day and outcome: allowed, denied, throttled, mfa_required, expired.', **values),
        'events': _query(ACCOUNTS_EVENT_MIX, 'Every recorded account event in the range by action and outcome, with how many distinct accounts each covers.', **values),
        'freshness': _query(ACCOUNTS_FRESHNESS, 'When the sync last wrote an account event.', **values),
    }


# ----- conversion, usage and enquiries -------------------------------------------------------------

FUNNEL_VISITORS = """
SELECT uniq(visitor) AS visitors, count() AS hits, max(ts) AS last_hit_at
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """
LIMIT 1
"""

FUNNEL_SIGNUPS = """
SELECT sum(accounts) AS accounts, sum(verified) AS verified, sum(with_mfa) AS with_mfa
FROM hub_analytics.admin_signups_daily
WHERE day >= today() - {days:UInt16}
LIMIT 1
"""

FUNNEL_ACTIVE = """
SELECT uniqExact(user_id) AS accounts
FROM hub_analytics.account_events_v1
WHERE event_date >= today() - {days:UInt16} AND action IN ('login', 'login.mfa') AND outcome = 'allowed' AND user_id IS NOT NULL
LIMIT 1
"""

PRODUCT_REACH = """
SELECT host, uniq(visitor) AS visitors, count() AS hits
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """
GROUP BY host
ORDER BY visitors DESC
LIMIT 20
"""

PRODUCT_SPREAD = """
SELECT products, count() AS visitors
FROM (SELECT visitor, uniq(host) AS products
      FROM hub_analytics.web_hits_v1
      WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """
      GROUP BY visitor
      LIMIT 1000000)
GROUP BY products
ORDER BY products
LIMIT 12
"""

REPEAT_VISITS = """
SELECT count() AS visitors, countIf(days > 1) AS returning
FROM (SELECT visitor, uniq(toDate(ts)) AS days
      FROM hub_analytics.web_hits_v1
      WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """
      GROUP BY visitor
      LIMIT 1000000)
LIMIT 1
"""

ENQUIRIES_DAILY = """
SELECT toDate(created_at) AS day, count() AS enquiries
FROM hub_analytics.enquiries_v1
WHERE created_at >= now() - toIntervalDay({days:UInt16})
GROUP BY day
ORDER BY day
LIMIT 100
"""

ENQUIRIES_PAGES = """
SELECT page, count() AS enquiries
FROM hub_analytics.enquiries_v1
WHERE created_at >= now() - toIntervalDay({days:UInt16})
GROUP BY page
ORDER BY enquiries DESC
LIMIT 10
"""


def monetization(days):
    values = days_parameter(days)
    return {
        'visitors': _query(FUNNEL_VISITORS, 'Distinct non-bot visitors at the edge over the range. ' + VISITOR_WEEK_NOTE, **values),
        'signups': _query(FUNNEL_SIGNUPS, 'Accounts created inside the range, and how many of those are verified or use two-step.', **values),
        'active': _query(FUNNEL_ACTIVE, 'Distinct accounts with at least one allowed sign-in inside the range.', **values),
        'reach': _query(PRODUCT_REACH, 'Distinct non-bot visitors per product host. A visitor who uses two products is counted in both rows.', **values),
        'spread': _query(PRODUCT_SPREAD, 'How many different product hosts each visitor touched, counted over visitors, not over requests.', **values),
        'repeat': _query(REPEAT_VISITS, 'Share of visitors seen on more than one day. The weekly re-keying means a visitor cannot be followed past an ISO week boundary, so this is a floor.', **values),
        'enquiries': _query(ENQUIRIES_DAILY, 'Footer "Email Admin" messages per day. Only the day, the page and the message length are copied to the warehouse; no name, address or text.', **values),
        'enquiry_pages': _query(ENQUIRIES_PAGES, 'Which page each enquiry was sent from.', **values),
    }


# ----- machine -------------------------------------------------------------------------------------

GPU_TABLE = 'gpu_samples_v1'

GPU_PRESENT = """
SELECT count() AS present
FROM system.tables
WHERE database = 'hub_analytics' AND name = '""" + GPU_TABLE + """'
LIMIT 1
"""

GPU_RECENT = """
SELECT max(ts) AS last_sample_at,
       count() AS samples,
       round(avg(utilisation_percent), 1) AS avg_utilisation,
       max(utilisation_percent) AS peak_utilisation,
       round(avg(memory_used_mb)) AS avg_memory_mb,
       max(memory_used_mb) AS peak_memory_mb,
       max(memory_total_mb) AS total_memory_mb,
       max(temperature_c) AS peak_temperature_c,
       any(gpu_name) AS gpu_name
FROM hub_analytics.gpu_samples_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
LIMIT 1
"""

GPU_DAILY = """
SELECT toDate(ts) AS day,
       round(avg(utilisation_percent), 1) AS avg_utilisation,
       max(utilisation_percent) AS peak_utilisation,
       round(avg(memory_used_mb)) AS avg_memory_mb
FROM hub_analytics.gpu_samples_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY day
ORDER BY day
LIMIT 100
"""


def gpu(days):
    values = days_parameter(days)
    sampled = ('Samples written by scripts/gpu_sampler.py on the machine that owns the card. The GPU is not '
               'exposed to the cluster, so no exporter can see it and nothing is recorded until the sampler runs.')
    return {
        'present': _query(GPU_PRESENT, sampled),
        'recent': _query(GPU_RECENT, sampled, **values),
        'daily': _query(GPU_DAILY, sampled, **values),
    }


# Prometheus. Only these expressions are ever sent; a caller cannot supply one.
# What this instance scrapes, checked on 15 Sep 2026: the application metric endpoints of
# jobsearch api/worker/scheduler, Job Prep and Prometheus itself. There is no node exporter,
# no cAdvisor and no kube-state-metrics, so host and container CPU, memory and disk are not
# collected anywhere. The console says that instead of showing a machine figure it cannot get.
PROMETHEUS_QUERIES = {
    'cpu_cores': 'sum by (job) (rate(process_cpu_seconds_total[5m])) or sum by (job) (rate(prep_process_cpu_seconds_total[5m]))',
    'memory_bytes': 'sum by (job) (process_resident_memory_bytes) or sum by (job) (prep_process_resident_memory_bytes)',
    'open_files': 'sum by (job) (process_open_fds) or sum by (job) (prep_process_open_fds)',
    'up': 'up',
}
PROMETHEUS_RANGE = 'sum(rate(process_cpu_seconds_total[5m])) + sum(rate(prep_process_cpu_seconds_total[5m]))'
PROMETHEUS_NOTE = ('Prometheus in hub-observability, scraped every 15 seconds. It scrapes the five application '
                   'metric endpoints only (Job Search api, worker and scheduler, Job Prep, Prometheus itself): '
                   'CPU is the rate of each process\'s own CPU seconds and memory is its resident set. No node '
                   'exporter, cAdvisor or kube-state-metrics is installed, so whole-machine CPU, memory and disk '
                   'are not collected by anything and are not shown.')
