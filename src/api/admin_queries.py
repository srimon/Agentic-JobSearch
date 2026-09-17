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
# The two names that serve the welcome site. They are not a product, and nearly all of the visitor
# codes at the edge are theirs, so every headline that means "someone used a product" leaves them
# out and says so. Both are kept as their own rows in every per-product chart.
WELCOME_HOSTS = "('bagala.ai', 'www.bagala.ai')"
NOT_WELCOME = 'host NOT IN ' + WELCOME_HOSTS
BOT_NOTE = ('Requests whose user agent the edge classed as a bot are left out of every headline visit and '
            'visitor figure; they are kept as their own series so the crawl load is still visible.')
PRODUCT_VISITOR_NOTE = ('"Product visitors" are the visitors of the product hosts only (Job Search, Job Prep, '
                        'Library and the Products page). The welcome site is counted separately, because a visit '
                        'to the front page is not use of a product.')
# What counts as a sign-up. jobsearch.users also holds the accounts the acceptance script and the
# operator create, which carry no address; counting those as sign-ups is what made the console read
# 98 sign-ups when four people had signed up.
SELF_SERVICE = "issuer = 'local' AND email_domain != ''"
SELF_SERVICE_NOTE = ('A sign-up is a self-service account: made through the public sign-up form (issuer "local") '
                     'with an e-mail address on it. Console and seed accounts - the ones the acceptance script and '
                     'the operator create, which carry no address - are counted separately under "console and seed" '
                     'and are never counted as sign-ups, accounts or conversion.')


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

# ----- the same traffic, split per product ---------------------------------------------------------
# Added for the charts-first console: a line per product needs a day/host series, and a per-product
# response, country or referrer chart needs the host on the row. The all-product statements above are
# untouched, and are still what the all-product view charts, so no total is ever a sum of uniq().

TRAFFIC_DAILY_BY_HOST = """
SELECT toDate(ts) AS day,
       host,
       countIf(""" + HUMAN + """) AS human_hits,
       uniqIf(visitor, """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """) AS human_visitors,
       countIf(ua_class = 'bot') AS bot_hits,
       countIf(status >= 500) AS server_errors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY day, host
ORDER BY day, host
LIMIT 800
"""

TRAFFIC_DAILY_VISITORS = """
SELECT toDate(ts) AS day,
       uniqIf(visitor, """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """) AS human_visitors,
       uniqIf(visitor, """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """ AND """ + NOT_WELCOME + """) AS product_visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY day
ORDER BY day
LIMIT 100
"""

TRAFFIC_STATUS_BY_HOST = """
SELECT host,
       multiIf(status < 200, '1xx', status < 300, '2xx', status < 400, '3xx', status < 500, '4xx', '5xx') AS status_class,
       count() AS hits,
       countIf(ua_class = 'bot') AS bot_hits
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16})
GROUP BY host, status_class
ORDER BY host, status_class
LIMIT 60
"""

TRAFFIC_COUNTRIES_BY_HOST = """
SELECT host, if(country = '', '(not reported)', country) AS country, count() AS hits, uniq(visitor) AS visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """
GROUP BY host, country
ORDER BY hits DESC
LIMIT 120
"""

TRAFFIC_REFERRERS_BY_HOST = """
SELECT host, referer_host, count() AS hits, uniq(visitor) AS visitors
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND referer_host != '' AND """ + HUMAN + """
GROUP BY host, referer_host
ORDER BY hits DESC
LIMIT 120
"""


def traffic(days):
    values = days_parameter(days)
    edge = 'One row per request that reached the public edge (Cloudflare tunnel to platform/gateway), delivered to ClickHouse by Vector.'
    return {
        'daily': _query(TRAFFIC_DAILY, edge + ' Grouped by UTC day over the chosen range. ' + VISITOR_WEEK_NOTE, **values),
        'daily_by_host': _query(TRAFFIC_DAILY_BY_HOST, edge + ' Grouped by UTC day and by the public name served, so each '
                                'product is its own line. Bot-classed requests are their own column, never part of the '
                                'hit or visitor figure. ' + VISITOR_WEEK_NOTE, **values),
        'daily_visitors': _query(TRAFFIC_DAILY_VISITORS, 'Distinct non-bot visitors per UTC day, counted once over all '
                                 'hosts and once over the product hosts only, because a visitor who used two products '
                                 'cannot be counted twice by adding the per-product rows. ' + PRODUCT_VISITOR_NOTE + ' '
                                 + VISITOR_WEEK_NOTE, **values),
        'status_by_host': _query(TRAFFIC_STATUS_BY_HOST, 'Every request in the range by product host and response class, '
                                 'bots included and counted separately.', **values),
        'countries_by_host': _query(TRAFFIC_COUNTRIES_BY_HOST, 'CF-IPCountry as Cloudflare reported it on each non-bot '
                                    'request, per product host; the top 120 host and country pairs in the range.', **values),
        'referrers_by_host': _query(TRAFFIC_REFERRERS_BY_HOST, 'The host part of the Referer header per product host; '
                                    'the top 120 pairs in the range, and requests without one are left out.', **values),
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

# ----- the same accounts, counted honestly ----------------------------------------------------------
# admin_signups_daily and admin_account_totals count every row in jobsearch.users, console and seed
# accounts included, which is why the console read 98 sign-ups. These two statements count the
# self-service population on its own and the console and seed accounts beside it, never inside it.
# Both read users_v1 the way the platform's own views do: FINAL, is_deleted = 0.

SELF_SERVICE_TOTALS = """
SELECT countIf(self = 1) AS accounts,
       countIf(self = 1 AND active = 1) AS active_accounts,
       countIf(self = 1 AND active = 0) AS disabled_accounts,
       countIf(self = 1 AND email_verified = 1) AS verified,
       countIf(self = 1 AND mfa_enabled = 1) AS with_mfa,
       countIf(self = 1 AND email_verified = 0 AND created_at < now64(3) - toIntervalDay(1)) AS unverified_after_a_day,
       countIf(self = 1 AND last_login_at >= now64(3) - toIntervalDay({days:UInt16})) AS signed_in_in_range,
       countIf(self = 1 AND last_login_at IS NOT NULL) AS ever_signed_in,
       countIf(self = 0) AS internal_accounts,
       countIf(self = 0 AND active = 1) AS internal_active,
       max(synced_at) AS last_synced_at
FROM (SELECT (""" + SELF_SERVICE + """) AS self, active, email_verified, mfa_enabled, created_at, last_login_at, synced_at
      FROM hub_analytics.users_v1 FINAL
      WHERE is_deleted = 0
      LIMIT 1000000)
LIMIT 1
"""

SELF_SERVICE_DAILY = """
SELECT toDate(created_at) AS day,
       count() AS accounts,
       countIf(email_verified = 1) AS verified,
       countIf(mfa_enabled = 1) AS with_mfa
FROM hub_analytics.users_v1 FINAL
WHERE is_deleted = 0 AND """ + SELF_SERVICE + """ AND toDate(created_at) >= today() - {days:UInt16}
GROUP BY day
ORDER BY day
LIMIT 100
"""

SELF_SERVICE_FUNNEL = """
SELECT countIf(toDate(created_at) >= today() - {days:UInt16}) AS accounts,
       countIf(toDate(created_at) >= today() - {days:UInt16} AND email_verified = 1) AS verified,
       countIf(last_login_at >= now64(3) - toIntervalDay({days:UInt16})) AS signed_in,
       count() AS self_service_accounts
FROM hub_analytics.users_v1 FINAL
WHERE is_deleted = 0 AND """ + SELF_SERVICE + """
LIMIT 1
"""


def accounts(days):
    values = days_parameter(days)
    sync = 'Copied from the Job Search account service every 15 minutes by the user-warehouse CronJob (docs/runbooks/user-warehouse.md).'
    return {
        'daily': _query(ACCOUNTS_DAILY, sync + ' Every account that still exists, by the day it was created, console and '
                        'seed accounts included. The console charts this only as the labelled comparison line.', **values),
        'self_daily': _query(SELF_SERVICE_DAILY, sync + ' Sign-ups by the day the account was created. ' + SELF_SERVICE_NOTE, **values),
        'self_totals': _query(SELF_SERVICE_TOTALS, sync + ' Totals over the self-service population, with the console and '
                              'seed accounts counted beside it. ' + SELF_SERVICE_NOTE, **values),
        'totals': _query(ACCOUNTS_TOTALS, sync + ' Totals over every account that still exists; "active" here means the account is not disabled.'),
        'mfa': _query(ACCOUNTS_MFA, 'Two-step sign-in among accounts that are not disabled, counted once per role and once '
                      'under "(all)". This one covers every enabled account, console and seed accounts included, and the '
                      'console labels it as such; the two-step share of sign-ups is the one above it.'),
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

# The funnel's own two statements. Step one is the product hosts only, bots and address-less requests
# excluded; the rest of the funnel is the self-service population, so no step counts a crawler, a
# front-page reader or a seed account.
FUNNEL_PRODUCT_VISITORS = """
SELECT uniq(visitor) AS visitors, count() AS hits, max(ts) AS last_hit_at
FROM hub_analytics.web_hits_v1
WHERE ts >= now() - toIntervalDay({days:UInt16}) AND """ + HUMAN + """ AND visitor != """ + NO_VISITOR + """ AND """ + NOT_WELCOME + """
LIMIT 1
"""


def monetization(days):
    values = days_parameter(days)
    return {
        'visitors': _query(FUNNEL_VISITORS, 'Distinct non-bot visitors at the edge over the range, welcome site included. ' + VISITOR_WEEK_NOTE, **values),
        'product_visitors': _query(FUNNEL_PRODUCT_VISITORS, 'Distinct non-bot visitors of the product hosts over the range: '
                                   'the first step of the funnel. ' + PRODUCT_VISITOR_NOTE + ' ' + VISITOR_WEEK_NOTE, **values),
        'signups': _query(FUNNEL_SIGNUPS, 'Every account created inside the range, console and seed accounts included. '
                          'Shown only as the labelled comparison beside the sign-up figure.', **values),
        'self_signups': _query(SELF_SERVICE_FUNNEL, 'The funnel below its first step: sign-ups made inside the range, how '
                               'many of those are verified, and how many self-service accounts signed in inside the '
                               'range (their last sign-in falls in it). ' + SELF_SERVICE_NOTE, **values),
        'active': _query(FUNNEL_ACTIVE, 'Distinct accounts with at least one allowed sign-in inside the range, console and '
                         'seed accounts included. Shown only as the labelled comparison.', **values),
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
# Each API copy is scraped as its own instance: usage sums across a job's copies, and a job counts as
# up only when every copy is (the console keeps one row per job).
PROMETHEUS_QUERIES = {
    'cpu_cores': 'sum by (job) (rate(process_cpu_seconds_total[5m])) or sum by (job) (rate(prep_process_cpu_seconds_total[5m]))',
    'memory_bytes': 'sum by (job) (process_resident_memory_bytes) or sum by (job) (prep_process_resident_memory_bytes)',
    'open_files': 'sum by (job) (process_open_fds) or sum by (job) (prep_process_open_fds)',
    'up': 'min by (job) (up)',
}
PROMETHEUS_RANGE = 'sum(rate(process_cpu_seconds_total[5m])) + sum(rate(prep_process_cpu_seconds_total[5m]))'
PROMETHEUS_NOTE = ('Prometheus in hub-observability, scraped every 15 seconds. It scrapes the five application '
                   'metric endpoints only (Job Search api, worker and scheduler, Job Prep, Prometheus itself): '
                   'CPU is the rate of each process\'s own CPU seconds and memory is its resident set. No node '
                   'exporter, cAdvisor or kube-state-metrics is installed, so whole-machine CPU, memory and disk '
                   'are not collected by anything and are not shown.')
