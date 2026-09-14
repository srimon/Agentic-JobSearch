"""Jobsearch analytics notifications; credentials arrive only through its pod Secret.

At-most-once delivery intentionally favours a missed alert over a duplicate after
an uncertain network outcome. No listing text or exception message enters Slack.
"""
import json
import os
import re
import uuid
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROXY = 'http://jobsearch-slack-egress.hub-system.svc.cluster.local:3128'
WEBHOOK = re.compile(r'https://hooks\.slack\.com/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+')
TABLE = 'jobsearch.analytics_notifications'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def configuration(env):
    enabled = env.get('JOBSEARCH_SLACK_ENABLED', 'false')
    if enabled not in {'true', 'false'}:
        raise ValueError('Invalid notification switch')
    if enabled == 'false':
        return None
    policy = env.get('JOBSEARCH_SLACK_POLICY')
    webhook = env.get('JOBSEARCH_SLACK_WEBHOOK', '')
    if policy not in {'all', 'failures'} or not WEBHOOK.fullmatch(webhook):
        raise ValueError('Invalid notification configuration')
    return webhook, policy


def deliver(connection, event_id, outcome, rows=0, error_class=None, env=None, opener=None):
    """Caller supplies a dedicated autocommit connection and stable Kubernetes Job UID."""
    if not connection.autocommit:
        raise ValueError('Notification journal must commit before delivery')
    event_id = str(uuid.UUID(str(event_id)))
    if outcome not in {'success', 'failure'} or type(rows) is not int or not 0 <= rows <= 100000:
        raise ValueError('Invalid notification event')
    # Error classes are bounded identifiers, never exception messages or URLs.
    if error_class is not None and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', error_class):
        raise ValueError('Invalid failure class')
    config = configuration(os.environ if env is None else env)
    if config is None:
        return 'disabled'
    webhook, policy = config
    if policy == 'failures' and outcome == 'success':
        return 'filtered'
    claim = connection.execute(
        f"INSERT INTO {TABLE}(event_id,outcome,state) VALUES(%s,%s,'sending') "
        "ON CONFLICT(event_id) DO NOTHING RETURNING event_id", (event_id, outcome)).fetchone()
    if claim is None:
        return 'already_recorded'
    text = f'Enterprise AI Hub | production | Jobsearch analytics | {outcome} | rows: {rows} | run: {event_id}'
    if error_class:
        text += f' | error class: {error_class}; inspect the scoped analytics Job/load record'
    request = Request(webhook, data=json.dumps({'text': text}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    state = 'unknown'
    try:
        client = opener or build_opener(ProxyHandler({'https': PROXY}), NoRedirect())
        with client.open(request, timeout=10) as response:
            if response.status == 200 and response.read(101).strip() == b'ok':
                state = 'accepted'
    except Exception:
        pass  # Credential-bearing exception details must never be printed or retried.
    connection.execute(f'UPDATE {TABLE} SET state=%s,finished_at=now() WHERE event_id=%s', (state, event_id))
    return state


def notify(outcome, rows=0, error_class=None):
    """Do not change analytics completion when notification infrastructure fails."""
    try:
        if configuration(os.environ) is None:
            return 'disabled'
        import psycopg
        from urllib.parse import urlsplit
        dsn = os.environ['ANALYTICS_DATABASE_URL']
        parsed = urlsplit(dsn)
        if parsed.username != 'hub_jbs_analytics' or parsed.path != '/jobsearch_production':
            raise ValueError('Wrong notification journal identity')
        # Job controller UID is shared by any replacement pod; no random fallback.
        event_id = str(uuid.UUID(os.environ['ANALYTICS_JOB_UID']))
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as connection:
            return deliver(connection, event_id, outcome, rows, error_class)
    except Exception:
        return 'notification_error'
