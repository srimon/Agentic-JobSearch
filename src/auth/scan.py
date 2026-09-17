"""The phone-scan check of a sign-up (the hub's docs/plans/account-creation-options.md).

The sign-up form on a computer asks for an attempt: two 128-bit secrets, one it keeps (to poll and
to submit with) and one drawn as a QR code. A phone that scans the code opens this product's
sign-in page with ?scan=<secret>, which posts back what the phone is (screen, touch points,
language, time zone) together with the request's own context (address, Cloudflare location, agent).
That row is kept against the attempt until the sign-up completes, then keyed to the account, and
the account is marked scan-verified when the scanning device was a handheld one. The desktop learns
of the scan by polling; the poll is not a credential and sits outside the sign-in budget.

Secrets are stored as SHA-256 digests, live for settings.signup_scan_seconds, are spent once and
never appear in logs or audit records. Nothing here changes what the sign-up form answers, so the
form stays as enumeration-safe as before.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb
from src.settings import settings
from src.db.store import connection, audit
from src.auth.local import throttled, token_hash, on_cookie_domain
from src.auth import context, totp
# Imported by name: a Pydantic field below is called consent, and the class body would shadow a module of that name.
from src.auth.consent import Choice as ConsentChoice, as_choice, record as record_consent

# A scanned attempt may still complete its sign-up this long after it was made: the QR code
# itself is only valid for signup_scan_seconds, the form may take longer to fill in.
COMPLETION_MINUTES = 30
E164 = re.compile(r'\+[1-9][0-9]{7,14}')
RETRY_LATER = HTTPException(429, 'Too many requests. Try again later.', headers={'Retry-After': '900'})
EXPIRED = 'This code has expired. Ask for a new one on your computer.'


class Attempt(BaseModel):
    attempt: str = Field(min_length=1, max_length=64)


class Scan(BaseModel):
    scan: str = Field(min_length=1, max_length=64)
    screen_width: int | None = Field(default=None, ge=0, le=20000)
    screen_height: int | None = Field(default=None, ge=0, le=20000)
    pixel_ratio: float | None = Field(default=None, ge=0, le=16)
    touch_points: int | None = Field(default=None, ge=0, le=64)
    language: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    consent: ConsentChoice | None = None
    phone: str = Field(default='', max_length=40)


def client_hash(values):
    return hashlib.sha256(('client:' + (values.get('ip') or '')).encode()).hexdigest()


def scan_url(request, raw):
    """The address the phone opens: the public one when the form was reached through the edge."""
    cfg = settings()
    origin = cfg.public_origin if on_cookie_domain(request) else cfg.origin
    return origin.rstrip('/') + '/?scan=' + raw


def phone_number(value):
    digits = re.sub(r'[\s().-]', '', value or '')
    if not digits:
        return None
    if not E164.fullmatch(digits):
        raise HTTPException(422, 'Enter the number in international form, for example +14155550123.')
    return digits


def enabled():
    cfg = settings()
    return cfg.signup_enabled and cfg.signup_scan_enabled


def complete(conn, raw, user_id):
    """Called by the sign-up once its account row exists: keys the attempt and every context row
    it collected to the account, and marks the account scan-verified when a handheld device
    scanned in time. Returns (attempt id, scanned); (None, False) when the attempt is unknown,
    spent or too old, which the sign-up treats as no attempt at all."""
    if not raw:
        return None, False
    row = conn.execute("""SELECT * FROM jobsearch.signup_attempts WHERE desktop_hash=%s AND consumed_at IS NULL
                          AND created_at > now()-(%s * interval '1 minute') FOR UPDATE""", (token_hash(raw), COMPLETION_MINUTES)).fetchone()
    if not row:
        return None, False
    conn.execute('UPDATE jobsearch.signup_attempts SET consumed_at=now(),user_id=%s WHERE id=%s', (user_id, row['id']))
    conn.execute('UPDATE jobsearch.account_context SET user_id=%s WHERE attempt_id=%s AND user_id IS NULL', (user_id, row['id']))
    if not row['scanned_at']:
        return row['id'], False
    conn.execute('UPDATE jobsearch.users SET scan_verified_at=coalesce(scan_verified_at,now()) WHERE id=%s', (user_id,))
    if row['consent'] is not None:
        phone = conn.execute("SELECT country,region_code,ip FROM jobsearch.account_context WHERE attempt_id=%s AND source='qr-phone' ORDER BY id DESC LIMIT 1", (row['id'],)).fetchone() or {}
        record_consent(conn, user_id, row['consent'], 'qr-phone', context.regime(phone.get('country'), phone.get('region_code')),
                       str(phone['ip']) if phone.get('ip') else None, phone.get('country'))
    return row['id'], True


def prune(conn):
    """Attempts a day past their expiry, and the phone rows of attempts that never became accounts."""
    conn.execute("""DELETE FROM jobsearch.account_context WHERE id IN
      (SELECT id FROM jobsearch.account_context WHERE user_id IS NULL AND recorded_at < now()-interval '1 day' FOR UPDATE SKIP LOCKED)""")
    conn.execute("""DELETE FROM jobsearch.signup_attempts WHERE id IN
      (SELECT id FROM jobsearch.signup_attempts WHERE expires_at < now()-interval '1 day' FOR UPDATE SKIP LOCKED)""")


def create_router():
    router = APIRouter(prefix='/api/auth/signup')

    @router.post('/attempt')
    def new_attempt(request: Request):
        if not enabled():
            raise HTTPException(404, 'Not Found')
        cfg = settings()
        seen = context.visitor(request)
        desktop, scan = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
        with connection() as conn:
            throttle = throttled(conn, [('scan', 300), ('scan:client:' + client_hash(seen), 10)])
            if throttle:
                audit(conn, 'anonymous', 'account.signup.attempt', 'local', 'throttled')
            else:
                conn.execute("""INSERT INTO jobsearch.signup_attempts(desktop_hash,scan_hash,client_hash,ip,expires_at) VALUES(%s,%s,%s,%s,%s)""",
                             (token_hash(desktop), token_hash(scan), client_hash(seen), seen['ip'],
                              datetime.now(timezone.utc) + timedelta(seconds=cfg.signup_scan_seconds)))
                audit(conn, 'anonymous', 'account.signup.attempt', 'local')
        if throttle:
            raise RETRY_LATER
        url = scan_url(request, scan)
        return {'attempt': desktop, 'scan_url': url, 'qr_svg': totp.qr_svg(url), 'expires_in': cfg.signup_scan_seconds}

    @router.post('/attempt/status')
    def status(body: Attempt):
        if not enabled():
            raise HTTPException(404, 'Not Found')
        with connection() as conn:
            row = conn.execute("""SELECT scanned_at,expires_at<=now() AS expired,consent FROM jobsearch.signup_attempts
                                  WHERE desktop_hash=%s AND consumed_at IS NULL""", (token_hash(body.attempt),)).fetchone()
        if not row:
            return {'scanned': False, 'expired': True, 'consent': None}
        return {'scanned': row['scanned_at'] is not None, 'expired': bool(row['expired']) and row['scanned_at'] is None,
                'consent': as_choice(row['consent']) if row['consent'] is not None else None}

    @router.post('/scan')
    def scan(body: Scan, request: Request):
        """The phone's report. Recorded whatever the device turns out to be; the attempt counts as
        scanned only for a handheld device with a touch screen."""
        if not enabled():
            raise HTTPException(404, 'Not Found')
        cfg = settings()
        seen = context.visitor(request)
        number = phone_number(body.phone) if cfg.phone_collection_enabled else None
        outcome = 'expired'
        handheld = False
        with connection() as conn:
            throttle = throttled(conn, [('scan', 300), ('scan:client:' + client_hash(seen), 10)])
            if throttle:
                outcome = 'throttled'
            else:
                row = conn.execute("""SELECT * FROM jobsearch.signup_attempts WHERE scan_hash=%s AND consumed_at IS NULL
                                      AND scanned_at IS NULL AND expires_at>now() FOR UPDATE""", (token_hash(body.scan),)).fetchone()
                if row:
                    values = dict(seen, screen_width=body.screen_width, screen_height=body.screen_height, pixel_ratio=body.pixel_ratio,
                                  touch_points=body.touch_points, language=context.clip(body.language, 32),
                                  client_timezone=context.clip(body.timezone, 64), phone_e164=number,
                                  scan_seconds=(datetime.now(timezone.utc) - row['created_at']).total_seconds(),
                                  same_network=(seen['ip'] == str(row['ip'])) if seen['ip'] and row['ip'] else None)
                    handheld = values['device_class'] in ('phone', 'tablet') and (body.touch_points or 0) > 0
                    context.record(conn, 'qr-phone', values, attempt_id=row['id'])
                    if handheld:
                        conn.execute('UPDATE jobsearch.signup_attempts SET scanned_at=now(),consent=%s WHERE id=%s',
                                     (Jsonb(body.consent.model_dump()) if body.consent else None, row['id']))
                    outcome = 'allowed' if handheld else 'not_handheld'
            # Device class and outcome only: never the address, the agent or the number.
            audit(conn, 'anonymous', 'account.signup.scan', 'local', outcome, details={'device_class': seen['device_class']} if outcome != 'throttled' else None)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'expired':
            raise HTTPException(400, EXPIRED)
        return {'ok': True, 'handheld': handheld,
                'message': 'Thank you. Go back to your computer to finish creating your account.' if handheld else
                           'This does not look like a phone or tablet. Scan the code with a phone camera to confirm your sign-up.'}

    return router
