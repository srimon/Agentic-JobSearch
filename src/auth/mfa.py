"""Optional two-step sign-in: an authenticator app (TOTP, RFC 6238) with single-use recovery codes.
The TOTP secret is AES-GCM encrypted with the intake key, bound to the account and purpose; recovery codes are stored
as SHA-256 digests. Audit records name outcomes only, never codes or secrets."""
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from src.db.store import connection, audit
from src.applications.private import encrypt, decrypt
from src.auth import totp
from src.auth import context as visitor_context
from src.auth.passwords import verify
from src.auth.local import (COOKIE, MFA_COOKIE, MFA_CHALLENGE_SECONDS, throttled, token_hash, login_buckets, start_session,
                            session_response, mfa_cookie_options, code_digest, new_login_code)
from src.auth.signup import email_bucket
from src.mail import queue_mail, render_login_code

KIND = 'mfa-totp'  # associated data: f'{user_id}:mfa-totp:v1'
MAX_CHALLENGE_ATTEMPTS = 5
# An e-mail code may be sent again this many times per challenge, within the address's mail budget.
MAX_RESENDS = 2
RETRY_LATER = HTTPException(429, 'Too many attempts. Try again later.', headers={'Retry-After': '900'})
UNAVAILABLE = HTTPException(503, 'Two-step sign-in is not available right now.')
WRONG_CODE = 'That code did not work. Check Microsoft Authenticator (or your authenticator app) and try again.'
EXPIRED = 'Your sign-in attempt expired. Enter your password again.'


class Password(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=128)

class Code(BaseModel):
    code: str = Field(min_length=1, max_length=32)

class Disable(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=32)

class Verify(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    recovery_code: str | None = Field(default=None, max_length=32)


def seal(user_id, secret):
    try:
        return encrypt(user_id, KIND, secret)
    except (OSError, ValueError):
        raise UNAVAILABLE

def unseal(user_id, value):
    try:
        return decrypt(user_id, KIND, value)
    except (OSError, ValueError):
        raise UNAVAILABLE

def replace_recovery_codes(conn, user_id):
    codes = totp.new_recovery_codes()
    conn.execute('DELETE FROM jobsearch.mfa_recovery_codes WHERE user_id=%s', (user_id,))
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO jobsearch.mfa_recovery_codes(user_id,code_hash) VALUES(%s,%s)',
                        [(user_id, totp.recovery_hash(user_id, code)) for code in codes])
    return codes

def second_factor(conn, mfa, code, allow_recovery=True):
    """Checks an authenticator code (six digits) or, when allowed, a recovery code against a row locked FOR UPDATE.
    Returns 'totp', 'recovery' or None; an accepted code is spent immediately."""
    if totp.is_totp_code(code):
        step = totp.matching_step(unseal(mfa['user_id'], mfa['secret_enc']), code, mfa['last_used_step'])
        if step is None:
            return None
        conn.execute('UPDATE jobsearch.user_mfa SET last_used_step=%s WHERE user_id=%s', (step, mfa['user_id']))
        return 'totp'
    if allow_recovery and len(totp.normalize_recovery(code)) == 10:
        used = conn.execute('UPDATE jobsearch.mfa_recovery_codes SET used_at=now() WHERE user_id=%s AND code_hash=%s AND used_at IS NULL RETURNING id',
                            (mfa['user_id'], totp.recovery_hash(mfa['user_id'], code))).fetchone()
        return 'recovery' if used else None
    return None

def remaining_codes(conn, user_id):
    return conn.execute('SELECT count(*) n FROM jobsearch.mfa_recovery_codes WHERE user_id=%s AND used_at IS NULL', (user_id,)).fetchone()['n']

def clear_mfa(conn, user_id):
    conn.execute('DELETE FROM jobsearch.mfa_recovery_codes WHERE user_id=%s', (user_id,))
    conn.execute('DELETE FROM jobsearch.mfa_challenges WHERE user_id=%s', (user_id,))
    return conn.execute('DELETE FROM jobsearch.user_mfa WHERE user_id=%s', (user_id,)).rowcount

def session_hash(request):
    return token_hash(request.cookies.get(COOKIE, ''))

def account_bucket(user):
    return [('mfa:' + str(user['id']), 10)]


def create_router(current_user):
    router = APIRouter(prefix='/api/auth/mfa')

    @router.get('')
    def status(user=Depends(current_user)):
        with connection() as conn:
            row = conn.execute('SELECT enabled_at FROM jobsearch.user_mfa WHERE user_id=%s', (user['id'],)).fetchone()
            enabled = bool(row and row['enabled_at'])
            return {'enabled': enabled, 'recovery_codes_remaining': remaining_codes(conn, user['id']) if enabled else 0}

    @router.post('/setup')
    def setup(body: Password, user=Depends(current_user)):
        outcome = 'allowed'
        result = None
        with connection() as conn:
            if throttled(conn, account_bucket(user)):
                outcome = 'throttled'
            elif not verify(body.password.get_secret_value(), user.get('password_hash')):
                outcome = 'denied'
            else:
                row = conn.execute('SELECT enabled_at FROM jobsearch.user_mfa WHERE user_id=%s FOR UPDATE', (user['id'],)).fetchone()
                if row and row['enabled_at']:
                    outcome = 'already_enabled'
                else:
                    secret = totp.new_secret()
                    # A new setup replaces an earlier pending secret; an enabled one is never overwritten here.
                    conn.execute("""INSERT INTO jobsearch.user_mfa(user_id,secret_enc) VALUES(%s,%s)
                        ON CONFLICT(user_id) DO UPDATE SET secret_enc=EXCLUDED.secret_enc,last_used_step=NULL,created_at=now()
                        WHERE jobsearch.user_mfa.enabled_at IS NULL""", (user['id'], seal(user['id'], secret)))
                    uri = totp.provisioning_uri(user['subject'], secret)
                    result = {'secret': secret, 'otpauth_uri': uri, 'qr_svg': totp.qr_svg(uri)}
            audit(conn, str(user['id']), 'account.mfa.setup', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'denied':
            raise HTTPException(400, 'Password is incorrect')
        if outcome == 'already_enabled':
            raise HTTPException(409, 'Two-step sign-in is already on')
        return result

    @router.post('/enable')
    def enable(body: Code, request: Request, user=Depends(current_user)):
        outcome = 'allowed'
        codes = None
        details = None
        with connection() as conn:
            if throttled(conn, account_bucket(user)):
                outcome = 'throttled'
            else:
                mfa = conn.execute('SELECT * FROM jobsearch.user_mfa WHERE user_id=%s FOR UPDATE', (user['id'],)).fetchone()
                if not mfa or mfa['enabled_at']:
                    outcome = 'no_pending_setup' if not mfa else 'already_enabled'
                elif not second_factor(conn, mfa, body.code, allow_recovery=False):
                    outcome = 'denied'
                else:
                    conn.execute('UPDATE jobsearch.user_mfa SET enabled_at=now() WHERE user_id=%s', (user['id'],))
                    codes = replace_recovery_codes(conn, user['id'])
                    # Sessions that signed in with the password alone end; this one continues.
                    revoked = conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s AND token_hash<>%s', (user['id'], session_hash(request))).rowcount
                    details = {'revoked_sessions': revoked}
            audit(conn, str(user['id']), 'account.mfa.enable', 'local', outcome, details=details)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome in ('no_pending_setup', 'already_enabled'):
            raise HTTPException(409, 'Start two-step sign-in setup first' if outcome == 'no_pending_setup' else 'Two-step sign-in is already on')
        if outcome == 'denied':
            raise HTTPException(400, WRONG_CODE)
        return {'recovery_codes': codes}

    @router.post('/disable')
    def disable(body: Disable, user=Depends(current_user)):
        outcome = 'allowed'
        with connection() as conn:
            if throttled(conn, account_bucket(user)):
                outcome = 'throttled'
            else:
                mfa = conn.execute('SELECT * FROM jobsearch.user_mfa WHERE user_id=%s AND enabled_at IS NOT NULL FOR UPDATE', (user['id'],)).fetchone()
                password_ok = verify(body.password.get_secret_value(), user.get('password_hash'))
                if not mfa:
                    outcome = 'not_enabled'
                # The code is checked (and spent) only after the password matches.
                elif not password_ok or not second_factor(conn, mfa, body.code):
                    outcome = 'denied'
                else:
                    clear_mfa(conn, user['id'])
            audit(conn, str(user['id']), 'account.mfa.disable', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'not_enabled':
            raise HTTPException(409, 'Two-step sign-in is not on')
        if outcome == 'denied':
            raise HTTPException(400, 'The password or code is incorrect')
        return {'ok': True}

    @router.post('/recovery-codes')
    def regenerate(body: Code, user=Depends(current_user)):
        outcome = 'allowed'
        codes = None
        with connection() as conn:
            if throttled(conn, account_bucket(user)):
                outcome = 'throttled'
            else:
                mfa = conn.execute('SELECT * FROM jobsearch.user_mfa WHERE user_id=%s AND enabled_at IS NOT NULL FOR UPDATE', (user['id'],)).fetchone()
                if not mfa:
                    outcome = 'not_enabled'
                elif not second_factor(conn, mfa, body.code):
                    outcome = 'denied'
                else:
                    codes = replace_recovery_codes(conn, user['id'])
            audit(conn, str(user['id']), 'account.mfa.recovery_codes', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'not_enabled':
            raise HTTPException(409, 'Two-step sign-in is not on')
        if outcome == 'denied':
            raise HTTPException(400, WRONG_CODE)
        return {'recovery_codes': codes}

    @router.post('/verify')
    def verify_challenge(body: Verify, request: Request):
        """Second sign-in step: consumes the challenge cookie set by /api/auth/login and issues the session."""
        raw = request.cookies.get(MFA_COOKIE, '')
        code = body.recovery_code if body.recovery_code else body.code
        outcome = 'expired'
        session = None
        actor = 'anonymous'
        with connection() as conn:
            found = conn.execute("""SELECT c.user_id,u.subject FROM jobsearch.mfa_challenges c JOIN jobsearch.users u ON u.id=c.user_id
                WHERE c.token_hash=%s AND c.consumed_at IS NULL AND c.expires_at>now() AND c.attempts<%s""",
                (token_hash(raw), MAX_CHALLENGE_ATTEMPTS)).fetchone() if raw else None
            if found:
                actor = str(found['user_id'])
                # The same per-account budget as the password step, plus the global one.
                if throttled(conn, login_buckets(found['subject'])):
                    outcome = 'throttled'
                else:
                    challenge = conn.execute("""SELECT * FROM jobsearch.mfa_challenges WHERE token_hash=%s AND consumed_at IS NULL
                        AND expires_at>now() AND attempts<%s FOR UPDATE""", (token_hash(raw), MAX_CHALLENGE_ATTEMPTS)).fetchone()
                    user = conn.execute('SELECT * FROM jobsearch.users WHERE id=%s', (found['user_id'],)).fetchone()
                    # An e-mail challenge is answered by the code it was sent with; an authenticator challenge by the app.
                    by_email = bool(challenge and challenge['method'] == 'email')
                    mfa = None if by_email else conn.execute('SELECT * FROM jobsearch.user_mfa WHERE user_id=%s AND enabled_at IS NOT NULL FOR UPDATE', (found['user_id'],)).fetchone()
                    usable = challenge and user and user['active'] and (not user['email'] or user['email_verified_at'])
                    if not usable or (not by_email and not mfa):
                        outcome = 'expired'
                        if challenge:
                            conn.execute('UPDATE jobsearch.mfa_challenges SET consumed_at=now() WHERE token_hash=%s', (challenge['token_hash'],))
                    else:
                        if by_email:
                            method = 'email' if code and hmac.compare_digest(challenge['code_hash'] or '', code_digest(user['id'], code)) else None
                        else:
                            method = second_factor(conn, mfa, code or '', allow_recovery=True) if code else None
                        if method:
                            conn.execute('UPDATE jobsearch.mfa_challenges SET consumed_at=now() WHERE token_hash=%s', (challenge['token_hash'],))
                            session = start_session(conn, user, 'mfa-' + method)
                            visitor_context.record(conn, 'signin', visitor_context.visitor(request), user_id=user['id'])
                            outcome = 'recovery_code' if method == 'recovery' else 'allowed'
                        else:
                            attempts = conn.execute('UPDATE jobsearch.mfa_challenges SET attempts=attempts+1 WHERE token_hash=%s RETURNING attempts',
                                                    (challenge['token_hash'],)).fetchone()['attempts']
                            outcome = 'locked' if attempts >= MAX_CHALLENGE_ATTEMPTS else 'denied'
            audit(conn, actor, 'login.mfa', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if session:
            response = session_response(request, session)
            response.delete_cookie(MFA_COOKIE, **mfa_cookie_options(request))
            return response
        if outcome == 'denied':
            raise HTTPException(401, WRONG_CODE)
        # Expired, used up or unknown: the person starts again from the password.
        response = JSONResponse({'detail': EXPIRED}, status_code=400)
        response.delete_cookie(MFA_COOKIE, **mfa_cookie_options(request))
        return response

    @router.post('/resend', status_code=202)
    def resend(request: Request):
        """A fresh e-mail code for the challenge in the cookie, replacing the last one: at most
        MAX_RESENDS times per challenge and within the address's mail budget (shared with
        verification and reset mail)."""
        raw = request.cookies.get(MFA_COOKIE, '')
        outcome = 'expired'
        row = None
        with connection() as conn:
            row = conn.execute("""SELECT c.token_hash,c.user_id,c.resends,u.email FROM jobsearch.mfa_challenges c JOIN jobsearch.users u ON u.id=c.user_id
                WHERE c.token_hash=%s AND c.method='email' AND c.consumed_at IS NULL AND c.expires_at>now() AND c.attempts<%s
                AND u.active AND u.email IS NOT NULL FOR UPDATE OF c""", (token_hash(raw), MAX_CHALLENGE_ATTEMPTS)).fetchone() if raw else None
            if row:
                if row['resends'] >= MAX_RESENDS:
                    outcome = 'exhausted'
                elif throttled(conn, [(email_bucket('mail', row['email']), 3)]):
                    outcome = 'throttled'
                else:
                    code = new_login_code()
                    conn.execute('UPDATE jobsearch.mfa_challenges SET code_hash=%s,resends=resends+1 WHERE token_hash=%s',
                                 (code_digest(row['user_id'], code), row['token_hash']))
                    queue_mail(conn, 'login_code', row['email'], *render_login_code(code, MFA_CHALLENGE_SECONDS // 60))
                    outcome = 'queued'
            audit(conn, str(row['user_id']) if row else 'anonymous', 'login.mfa.resend', 'local', outcome)
        if outcome == 'throttled':
            raise RETRY_LATER
        if outcome == 'exhausted':
            raise HTTPException(429, 'No more codes can be sent for this sign-in. Enter your password again.', headers={'Retry-After': '300'})
        if outcome == 'expired':
            raise HTTPException(400, EXPIRED)
        return {'detail': 'check your email'}

    return router
