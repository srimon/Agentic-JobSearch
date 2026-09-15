"""Outbound account mail: a durable queue in PostgreSQL and two transports. Nothing here logs an address's local
part, a token or the provider key; failures are recorded as an error class or HTTP status only."""
import html
import json
import urllib.error
import urllib.request
from pathlib import Path
from src.settings import settings

RESEND_URL = 'https://api.resend.com/emails'
# Resend's edge refuses urllib's default "Python-urllib/x.y" agent with Cloudflare error 1010 (HTTP 403),
# measured 15 Sep 2026; every request names this client instead.
USER_AGENT = 'bagala-mailer/1.0 (+https://www.bagala.ai)'
MAX_ATTEMPTS = 5


def queue_mail(conn, purpose, to, subject, text, html_body=None):
    return conn.execute('INSERT INTO jobsearch.outbound_mail(purpose,to_address,subject,text_body,html_body) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                        (purpose, to, subject, text, html_body)).fetchone()['id']


def _message(title, lines, link, expiry):
    text = title + '\n\n' + '\n'.join(lines) + '\n\n' + link + '\n\n' + expiry + '\nIf you did not request this, ignore this message; nothing changes without the link.\n'
    body = ''.join('<p>' + html.escape(line) + '</p>' for line in lines)
    page = ('<!doctype html><html><body style="font-family:sans-serif"><h2>' + html.escape(title) + '</h2>' + body +
            '<p><a href="' + html.escape(link, quote=True) + '">' + html.escape(link) + '</a></p><p>' + html.escape(expiry) +
            '</p><p>If you did not request this, ignore this message; nothing changes without the link.</p></body></html>')
    return text, page


def render_verification(public_origin, token):
    link = public_origin.rstrip('/') + '/?verify=' + token
    text, page = _message('Confirm your Bagala account', ['Open the link below to verify your email address and activate sign-in.'], link, 'The link works once and expires in 24 hours.')
    return 'Confirm your Bagala account', text, page


def render_reset(public_origin, token):
    link = public_origin.rstrip('/') + '/?reset=' + token
    text, page = _message('Reset your Bagala password', ['Open the link below to choose a new password. All existing sessions are signed out when it is used.'], link, 'The link works once and expires in 1 hour.')
    return 'Reset your Bagala password', text, page


def to_domain(address):
    return address.rsplit('@', 1)[-1].lower() if '@' in address else ''


def send_resend(row, cfg):
    """POST to Resend with the key read at call time; urllib honours HTTPS_PROXY from the environment."""
    key = Path(cfg.resend_api_key_file).read_text(encoding='utf-8').strip()
    if not key:
        raise RuntimeError('Resend key file is empty')
    payload = {'from': cfg.mail_from, 'to': [row['to_address']], 'subject': row['subject'], 'text': row['text_body']}
    if row['html_body']:
        payload['html'] = row['html_body']
    request = urllib.request.Request(RESEND_URL, data=json.dumps(payload).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': USER_AGENT,
        'Idempotency-Key': 'jobsearch-outbound-mail/' + str(row['id'])})
    with urllib.request.urlopen(request, timeout=20) as response:
        try:
            return str(json.loads(response.read().decode() or '{}').get('id') or '')
        except ValueError:
            return ''


def send(row, transport, cfg):
    if transport == 'log':
        return ''
    if transport == 'resend':
        return send_resend(row, cfg)
    raise RuntimeError('Unsupported mail transport')


def failure_text(error):
    # Provider bodies can echo the recipient; keep only a status or an error class.
    if isinstance(error, urllib.error.HTTPError):
        return 'HTTP ' + str(error.code)
    return type(error).__name__


def deliver_pending(conn, transport, limit=50, backoff_seconds=60):
    """Send queued rows oldest first, committing each outcome on its own so a crash cannot resend accepted mail.
    A failed attempt is retried after attempts x backoff_seconds from creation; the fifth failure marks the row failed."""
    cfg = settings()
    ids = [r['id'] for r in conn.execute("""SELECT id FROM jobsearch.outbound_mail WHERE status='queued'
        AND created_at + attempts * (%s * interval '1 second') <= now() ORDER BY id LIMIT %s""", (backoff_seconds, limit)).fetchall()]
    sent = 0
    for mail_id in ids:
        row = conn.execute("SELECT * FROM jobsearch.outbound_mail WHERE id=%s AND status='queued' FOR UPDATE SKIP LOCKED", (mail_id,)).fetchone()
        if not row:
            continue
        try:
            provider_id = send(row, transport, cfg)
        except Exception as error:
            attempts = row['attempts'] + 1
            conn.execute("UPDATE jobsearch.outbound_mail SET attempts=%s,last_error=%s,status=CASE WHEN %s>=%s THEN 'failed' ELSE status END WHERE id=%s",
                         (attempts, failure_text(error), attempts, MAX_ATTEMPTS, row['id']))
            print(json.dumps({'event': 'mail.failed', 'purpose': row['purpose'], 'to_domain': to_domain(row['to_address']), 'attempts': attempts, 'error': failure_text(error)}), flush=True)
        else:
            conn.execute("UPDATE jobsearch.outbound_mail SET status='sent',sent_at=now(),attempts=attempts+1,last_error=NULL,provider_id=%s WHERE id=%s", (provider_id or None, row['id']))
            print(json.dumps({'event': 'mail.sent', 'purpose': row['purpose'], 'to_domain': to_domain(row['to_address']), 'transport': transport}), flush=True)
            sent += 1
        conn.commit()
    return sent
