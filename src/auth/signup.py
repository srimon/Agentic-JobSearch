"""Self-service accounts (ADR 0004): sign-up, email verification, password reset and profile endpoints.
Anonymous endpoints answer identically whether or not an account exists; only audit_events records the difference."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import psycopg.errors
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr
from src.settings import settings
from src.db.store import connection, audit
from src.auth.passwords import password_hash, verify, username, email_address
from src.auth.local import throttled, token_hash, mfa_enabled, on_cookie_domain, COOKIE
from src.auth import context, scan
# Imported by name: the Signup field below is called consent, and the class body would shadow a module of that name.
from src.auth.consent import Choice as ConsentChoice, record as record_consent
from src.mail import queue_mail, render_verification, render_reset, render_account_exists

ACCEPTED = {'detail': 'check your email'}
INVALID_TOKEN = 'invalid or expired token'
TOKEN_HOURS = {'verify': 24, 'reset': 1}
RETRY_LATER = HTTPException(429, 'Too many requests. Try again later.', headers={'Retry-After': '900'})


class Signup(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)
    display_name: str = Field(default='', max_length=120)
    # The consent choice the form showed (src/auth/consent.py); absent from older clients, which records nothing.
    consent: ConsentChoice | None = None
    # The desktop secret of a phone-scan attempt (src/auth/scan.py), when the form showed a code.
    attempt: str | None = Field(default=None, max_length=64)
    # A honeypot: the form renders this field out of sight and people leave it empty; a filled one
    # is answered exactly like a sign-up and creates nothing (the enquiry form does the same).
    website: str = Field(default='', max_length=1000)

class Token(BaseModel):
    token: str = Field(min_length=1, max_length=128)

class Email(BaseModel):
    email: str = Field(min_length=1, max_length=254)

class Reset(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)

class Profile(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)

class PasswordChange(BaseModel):
    current: SecretStr = Field(min_length=1, max_length=128)
    new: SecretStr = Field(min_length=1, max_length=128)


def checked(rule, value):
    try:
        return rule(value)
    except ValueError as error:
        raise HTTPException(422, str(error))

def email_bucket(prefix, email):
    return prefix + ':' + hashlib.sha256(email.lower().encode()).hexdigest()

def issue_token(conn, user_id, purpose):
    """32 random bytes, stored as a SHA-256 digest like sessions. One live token per purpose: a new link retires the old."""
    raw = secrets.token_urlsafe(32)
    conn.execute('DELETE FROM jobsearch.auth_tokens WHERE user_id=%s AND purpose=%s', (user_id, purpose))
    conn.execute('INSERT INTO jobsearch.auth_tokens(token_hash,user_id,purpose,expires_at) VALUES(%s,%s,%s,%s)',
                 (token_hash(raw), user_id, purpose, datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS[purpose])))
    return raw

def consume_token(conn, raw, purpose):
    row = conn.execute('UPDATE jobsearch.auth_tokens SET used_at=now() WHERE token_hash=%s AND purpose=%s AND used_at IS NULL AND expires_at>now() RETURNING user_id',
                       (token_hash(raw), purpose)).fetchone()
    return row['user_id'] if row else None

def account_screen(request):
    """The hub's account screen (settings.account_screen) for a request that arrived through the public edge, where
    the emailed links land on its verify and reset pages; '' for the loopback name and console callers, where the
    screen is not served and this product's own page keeps the landings."""
    cfg = settings()
    return cfg.account_screen if request is not None and on_cookie_domain(request) else ''

def send_verification(conn, user_id, email, request=None):
    queue_mail(conn, 'verify', email, *render_verification(settings().public_origin, issue_token(conn, user_id, 'verify'), account_screen(request)))

def send_reset(conn, user_id, email, name=None, request=None):
    queue_mail(conn, 'reset', email, *render_reset(settings().public_origin, issue_token(conn, user_id, 'reset'), name, account_screen(request)))

def send_account_exists(conn, email, name):
    queue_mail(conn, 'account_exists', email, *render_account_exists(settings().public_origin, name))

def session_hash(request):
    return token_hash(request.cookies.get(COOKIE, ''))


def create_router(current_user):
    router = APIRouter(prefix='/api/auth')

    @router.post('/signup', status_code=202)
    def signup(body: Signup, request: Request):
        cfg = settings()
        if not cfg.signup_enabled:
            raise HTTPException(404, 'Not Found')
        if body.website.strip():
            with connection() as conn:
                audit(conn, 'anonymous', 'account.signup', 'local', 'honeypot')
            return ACCEPTED
        name = checked(username, body.username)
        email = checked(email_address, body.email)
        encoded = checked(password_hash, body.password.get_secret_value())
        display = ' '.join(body.display_name.split()) or name
        username_taken = False
        seen = context.visitor(request)
        with connection() as conn:
            throttle = throttled(conn, [('signup', 30), (email_bucket('signup', email), 5)])
            if throttle:
                audit(conn, 'anonymous', 'account.signup', 'local', 'throttled')
            else:
                # The unique constraints decide: ON CONFLICT covers the username key and the case-insensitive email index.
                row = conn.execute("""INSERT INTO jobsearch.users(issuer,subject,display_name,roles,active,password_hash,email)
                    VALUES('local',%s,%s,%s,true,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
                    (name, display, cfg.signup_default_roles, encoded, email)).fetchone()
                if row:
                    send_verification(conn, row['id'], email, request)
                    # The sign-up record: the phone's rows first (they key the attempt to the account and
                    # carry the phone's consent), then this request's own row, then the choice made on
                    # this form, which is the latest and therefore the current one.
                    attempt_id, scanned = scan.complete(conn, body.attempt, row['id'])
                    context.record(conn, 'desktop', seen, user_id=row['id'], attempt_id=attempt_id)
                    regime = context.regime(seen['country'], seen['region_code'])
                    if body.consent is not None:
                        record_consent(conn, row['id'], body.consent.model_dump(), 'signup', regime, seen['ip'], seen['country'])
                    audit(conn, str(row['id']), 'account.signup', 'local',
                          details={'scan_verified': scanned, 'consent': body.consent is not None, 'regime': regime})
                else:
                    # Nothing was inserted, so at least one key already existed; find out which after the fact.
                    owner = conn.execute('SELECT id,subject,email,active FROM jobsearch.users WHERE lower(email)=lower(%s)', (email,)).fetchone()
                    username_taken = conn.execute("SELECT 1 FROM jobsearch.users WHERE issuer='local' AND subject=%s", (name,)).fetchone() is not None
                    mail = 'none'
                    if owner and owner['active']:
                        # The address owner hears about it (budget shared with resend and reset mail); the reply never says.
                        if throttled(conn, [(email_bucket('mail', email), 3)]):
                            mail = 'throttled'
                        else:
                            send_account_exists(conn, owner['email'], owner['subject'])
                            mail = 'queued'
                    audit(conn, 'anonymous', 'account.signup', 'local', 'username_taken' if username_taken else 'duplicate',
                          details={'email_in_use': owner is not None, 'mail': mail})
        if throttle:
            raise RETRY_LATER
        if username_taken:
            # Usernames are public; this reply is the same whether or not the email is also in use.
            raise HTTPException(409, 'That username is taken')
        return ACCEPTED

    @router.post('/verify')
    def verify_email(body: Token):
        with connection() as conn:
            uid = consume_token(conn, body.token, 'verify')
            if uid:
                conn.execute('UPDATE jobsearch.users SET email_verified_at=coalesce(email_verified_at,now()) WHERE id=%s', (uid,))
                audit(conn, str(uid), 'account.verify', 'local')
            else:
                audit(conn, 'anonymous', 'account.verify', 'local', 'denied')
        if not uid:
            raise HTTPException(400, INVALID_TOKEN)
        return {'ok': True}

    def mail_request(body, action, wanted):
        """Shared by resend and reset-request: always 202, throttled per address and globally, queued only when wanted."""
        email = checked(email_address, body.email)
        with connection() as conn:
            throttle = throttled(conn, [('mail', 60), (email_bucket('mail', email), 3)])
            outcome = 'throttled'
            if not throttle:
                user = conn.execute("SELECT id,subject,email,email_verified_at,active FROM jobsearch.users WHERE issuer='local' AND lower(email)=lower(%s) FOR UPDATE", (email,)).fetchone()
                outcome = 'queued' if user and user['active'] and wanted(user, conn) else 'ignored'
            audit(conn, 'anonymous', action, 'local', outcome)
        if throttle:
            raise RETRY_LATER
        return ACCEPTED

    @router.post('/resend', status_code=202)
    def resend(body: Email, request: Request):
        def wanted(user, conn):
            if user['email_verified_at']:
                return False
            send_verification(conn, user['id'], user['email'], request)
            return True
        return mail_request(body, 'account.resend', wanted)

    @router.post('/reset-request', status_code=202)
    def reset_request(body: Email, request: Request):
        def wanted(user, conn):
            send_reset(conn, user['id'], user['email'], user['subject'], request)
            return True
        return mail_request(body, 'account.reset_request', wanted)

    @router.post('/reset')
    def reset(body: Reset):
        encoded = checked(password_hash, body.password.get_secret_value())
        with connection() as conn:
            uid = consume_token(conn, body.token, 'reset')
            if uid:
                conn.execute('UPDATE jobsearch.users SET password_hash=%s,email_verified_at=coalesce(email_verified_at,now()) WHERE id=%s', (encoded, uid))
                conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s', (uid,))
                conn.execute("DELETE FROM jobsearch.auth_tokens WHERE user_id=%s AND purpose='reset'", (uid,))
                audit(conn, str(uid), 'account.reset', 'local')
            else:
                audit(conn, 'anonymous', 'account.reset', 'local', 'denied')
        if not uid:
            raise HTTPException(400, INVALID_TOKEN)
        return {'ok': True}

    @router.get('/profile')
    def profile(user=Depends(current_user)):
        with connection() as conn:
            mfa = mfa_enabled(conn, user['id'])
        return {'username': user['subject'], 'display_name': user['display_name'], 'email': user.get('email'),
                'email_verified': user.get('email_verified_at') is not None, 'roles': user['roles'],
                'created_at': user.get('created_at'), 'last_login_at': user.get('last_login_at'), 'mfa_enabled': mfa,
                'scan_verified': user.get('scan_verified_at') is not None}

    @router.patch('/profile')
    def update_profile(body: Profile, request: Request, user=Depends(current_user)):
        fields = []
        display = None
        if body.display_name is not None:
            display = ' '.join(body.display_name.split())
            if not display:
                raise HTTPException(422, 'Display name is required')
        email = checked(email_address, body.email) if body.email is not None else None
        outcome = 'allowed'
        with connection() as conn:
            current = conn.execute('SELECT email FROM jobsearch.users WHERE id=%s FOR UPDATE', (user['id'],)).fetchone()
            if display is not None:
                conn.execute('UPDATE jobsearch.users SET display_name=%s WHERE id=%s', (display, user['id']))
                fields.append('display_name')
            if email is not None and (current['email'] or '').lower() != email.lower():
                # Same reply when another account already uses the address: the profile form is not an enumeration oracle.
                try:
                    with conn.transaction():
                        conn.execute('UPDATE jobsearch.users SET email=%s,email_verified_at=NULL WHERE id=%s', (email, user['id']))
                except psycopg.errors.UniqueViolation:
                    outcome = 'duplicate'
                else:
                    send_verification(conn, user['id'], email, request)
                    fields.append('email')
            audit(conn, str(user['id']), 'account.profile', 'local', outcome, details={'fields': fields})
        return {'ok': True}

    @router.post('/password')
    def change_password(body: PasswordChange, request: Request, user=Depends(current_user)):
        encoded = checked(password_hash, body.new.get_secret_value())
        with connection() as conn:
            throttle = throttled(conn, [('password:' + str(user['id']), 10)])
            valid = not throttle and verify(body.current.get_secret_value(), user.get('password_hash'))
            if valid:
                conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s', (encoded, user['id']))
                conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s AND token_hash<>%s', (user['id'], session_hash(request)))
                conn.execute("DELETE FROM jobsearch.auth_tokens WHERE user_id=%s AND purpose='reset'", (user['id'],))
            audit(conn, str(user['id']), 'account.password', 'local', 'allowed' if valid else ('throttled' if throttle else 'denied'))
        if throttle:
            raise RETRY_LATER
        if not valid:
            raise HTTPException(400, 'Current password is incorrect')
        return {'ok': True}

    @router.get('/sessions')
    def sessions(request: Request, user=Depends(current_user)):
        current = session_hash(request)
        with connection() as conn:
            rows = conn.execute('SELECT token_hash,created_at,expires_at FROM jobsearch.sessions WHERE user_id=%s AND expires_at>now() ORDER BY created_at DESC', (user['id'],)).fetchall()
        return [{'created_at': r['created_at'], 'expires_at': r['expires_at'], 'current': r['token_hash'] == current} for r in rows]

    @router.post('/sessions/revoke-all')
    def revoke_all(request: Request, user=Depends(current_user)):
        # Keeps the calling session so the request does not sign its own caller out.
        with connection() as conn:
            revoked = conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s AND token_hash<>%s', (user['id'], session_hash(request))).rowcount
            audit(conn, str(user['id']), 'account.sessions.revoke_all', 'session', details={'revoked': revoked})
        return {'ok': True, 'revoked': revoked}

    return router
