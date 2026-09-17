"""Approve a sign-in from a phone that is already signed in (QR flow 2 of the hub's
docs/plans/account-creation-options.md; the owner's decision of 17 Sep 2026).

The two-step page of a sign-in (the challenge cookie between the password and the code) asks for
a code: 128 random bits, stored as a SHA-256 digest bound to that challenge, valid for
settings.login_scan_seconds, single use, drawn as a QR code of the account screen's approve page
(https://bagala.ai/account/approve?code=<code>). A phone that opens it signed in as the same
account is shown what is asking (the desktop's device class, browser, system, city and country,
never its address) and approves; the desktop, polling, then gets its session. A phone that is not
signed in is sent to sign in first by the page and comes back.

Who approved, from which device and address, and when: the approving request leaves its own row
in the sign-up record (source 'approve', keyed to the account, address purged after the retention
window) and the audit row names the account, the device classes and that row. Limits: three
codes per challenge, ten per account per quarter hour, the same for approvals; the desktop's poll
is bound to its cookie and sits outside the credential budgets on purpose (see the edge).
"""
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb
from src.settings import settings
from src.db.store import connection, audit
from src.auth import context, totp
from src.auth.local import MFA_COOKIE, throttled, token_hash, start_session, session_response, mfa_cookie_options
from src.auth.mfa import MAX_CHALLENGE_ATTEMPTS, EXPIRED, RETRY_LATER

MAX_CODES_PER_CHALLENGE = 3
DEVICE_KEYS = ('device_class', 'browser', 'os', 'city', 'region', 'country')
NOT_YOURS = 'This code has expired, or it is not for your account. Ask for a new one on the device that is signing in.'


class Code(BaseModel):
    code: str = Field(min_length=1, max_length=64)


def enabled():
    return settings().login_scan_approval


def approve_url(raw):
    cfg = settings()
    if cfg.account_screen:
        return cfg.account_screen.rstrip('/') + '/approve?code=' + raw
    return cfg.origin.rstrip('/') + '/?approve=' + raw


def live_challenge(conn, raw, lock=False):
    """The challenge the two-step page holds, while it can still be answered."""
    if not raw:
        return None
    return conn.execute("""SELECT c.*, u.subject FROM jobsearch.mfa_challenges c JOIN jobsearch.users u ON u.id=c.user_id
                           WHERE c.token_hash=%s AND c.consumed_at IS NULL AND c.expires_at>now() AND c.attempts<%s AND u.active"""
                        + (' FOR UPDATE OF c' if lock else ''), (token_hash(raw), MAX_CHALLENGE_ATTEMPTS)).fetchone()


def live_code(conn, raw, lock=False):
    """A code that can still be approved or completed: unexpired, unconsumed, on a live challenge."""
    return conn.execute("""SELECT s.* FROM jobsearch.mfa_scan_codes s JOIN jobsearch.mfa_challenges c ON c.token_hash=s.challenge_hash
                           WHERE s.code_hash=%s AND s.expires_at>now() AND s.consumed_at IS NULL
                           AND c.consumed_at IS NULL AND c.expires_at>now()""" + (' FOR UPDATE OF s' if lock else ''),
                        (token_hash(raw),)).fetchone()


def device_summary(seen):
    return {key: seen.get(key) for key in DEVICE_KEYS}


def create_router(current_user):
    router = APIRouter(prefix='/api/auth/mfa/scan')

    @router.post('')
    def new_code(request: Request):
        """A code for the challenge in the cookie, drawn as a QR of the approve page."""
        if not enabled():
            raise HTTPException(404, 'Not Found')
        cfg = settings()
        raw = secrets.token_urlsafe(16)
        outcome = 'expired'
        with connection() as conn:
            challenge = live_challenge(conn, request.cookies.get(MFA_COOKIE, ''))
            if challenge:
                issued = conn.execute('SELECT count(*) n FROM jobsearch.mfa_scan_codes WHERE challenge_hash=%s', (challenge['token_hash'],)).fetchone()['n']
                if issued >= MAX_CODES_PER_CHALLENGE or throttled(conn, [('scan-signin:' + str(challenge['user_id']), 10)]):
                    outcome = 'throttled'
                else:
                    conn.execute("""INSERT INTO jobsearch.mfa_scan_codes(code_hash,challenge_hash,user_id,device,expires_at) VALUES(%s,%s,%s,%s,%s)""",
                                 (token_hash(raw), challenge['token_hash'], challenge['user_id'], Jsonb(device_summary(context.visitor(request))),
                                  datetime.now(timezone.utc) + timedelta(seconds=cfg.login_scan_seconds)))
                    outcome = 'allowed'
            audit(conn, str(challenge['user_id']) if challenge else 'anonymous', 'login.mfa.scan', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'expired':
            raise HTTPException(400, EXPIRED)
        url = approve_url(raw)
        return {'scan_url': url, 'qr_svg': totp.qr_svg(url), 'expires_in': cfg.login_scan_seconds}

    @router.post('/status')
    def status(request: Request):
        """The desktop's poll. Once the phone has approved, this call is the sign-in: the challenge
        and the code are spent and the session cookie is set, exactly as a correct code would."""
        if not enabled():
            raise HTTPException(404, 'Not Found')
        raw = request.cookies.get(MFA_COOKIE, '')
        session = None
        answer = {'approved': False, 'expired': True}
        with connection() as conn:
            challenge = live_challenge(conn, raw, lock=True)
            if challenge:
                code = conn.execute("""SELECT * FROM jobsearch.mfa_scan_codes WHERE challenge_hash=%s ORDER BY id DESC LIMIT 1 FOR UPDATE""",
                                    (challenge['token_hash'],)).fetchone()
                if code and code['approved_at'] and not code['consumed_at']:
                    conn.execute('UPDATE jobsearch.mfa_scan_codes SET consumed_at=now() WHERE id=%s', (code['id'],))
                    conn.execute('UPDATE jobsearch.mfa_challenges SET consumed_at=now() WHERE token_hash=%s', (challenge['token_hash'],))
                    user = conn.execute('SELECT * FROM jobsearch.users WHERE id=%s', (challenge['user_id'],)).fetchone()
                    session = start_session(conn, user, 'mfa-scan')
                    context.record(conn, 'signin', context.visitor(request), user_id=user['id'])
                    audit(conn, str(user['id']), 'login.mfa', 'local', 'allowed', details={'method': 'scan', 'approved_from': code['approver_context_id']})
                    answer = {'approved': True, 'expired': False}
                else:
                    answer = {'approved': False, 'expired': not code or code['expires_at'] <= datetime.now(timezone.utc)}
        if session:
            response = session_response(request, session)
            response.delete_cookie(MFA_COOKIE, **mfa_cookie_options(request))
            response.body = response.render({'ok': True, **answer})
            response.headers['content-length'] = str(len(response.body))
            return response
        return answer

    @router.post('/describe')
    def describe(body: Code, request: Request, user=Depends(current_user)):
        """What the phone shows before approving: the asking device, and how long the code lasts."""
        if not enabled():
            raise HTTPException(404, 'Not Found')
        with connection() as conn:
            code = live_code(conn, body.code)
        if not code or code['user_id'] != user['id'] or code['approved_at']:
            raise HTTPException(400, NOT_YOURS)
        return {'device': code['device'], 'expires_in': max(0, int((code['expires_at'] - datetime.now(timezone.utc)).total_seconds())),
                'account': user['subject']}

    @router.post('/approve')
    def approve(body: Code, request: Request, user=Depends(current_user)):
        """The phone's approval: the code must be live, unapproved and for this very account."""
        if not enabled():
            raise HTTPException(404, 'Not Found')
        seen = context.visitor(request)
        outcome = 'denied'
        details = None
        with connection() as conn:
            if throttled(conn, [('scan-approve:' + str(user['id']), 10)]):
                outcome = 'throttled'
            else:
                code = live_code(conn, body.code, lock=True)
                if code and code['user_id'] == user['id'] and not code['approved_at']:
                    row_id = context.record(conn, 'approve', seen, user_id=user['id'])
                    conn.execute('UPDATE jobsearch.mfa_scan_codes SET approved_at=now(),approver_context_id=%s WHERE id=%s', (row_id, code['id']))
                    outcome = 'allowed'
                    details = {'device_class': seen['device_class'], 'browser': seen['browser'], 'os': seen['os'], 'context_id': row_id,
                               'asking': code['device'].get('device_class')}
            audit(conn, str(user['id']), 'login.mfa.approve', 'local', outcome, details=details)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'denied':
            raise HTTPException(400, NOT_YOURS)
        return {'ok': True, 'message': 'Approved. The device that showed the code is signing in now.'}

    return router
