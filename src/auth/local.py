import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from src.settings import settings
from src.db.store import connection, audit
from src.auth.passwords import verify, username, hasher
from src.auth import context as visitor_context
from src.mail import queue_mail, render_login_code

router = APIRouter()
COOKIE = 'jobsearch_session'
# Carries the pending two-step sign-in between the password and the code; scoped to the auth routes only.
MFA_COOKIE = 'jobsearch_mfa'
MFA_CHALLENGE_SECONDS = 300
EMAIL_CODE_DIGITS = 6
INVALID_LOGIN = 'Invalid username, email or password'

class Credentials(BaseModel):
    # The field keeps its name for existing clients; it accepts a username or an email address.
    username: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

def token_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()

def throttled(conn, buckets):
    """Count one attempt per bucket in a fixed 15-minute window; True as soon as a budget is exhausted.
    PostgreSQL row locks enforce the budgets across processes. Never trust client forwarding headers."""
    for bucket, maximum in buckets:
        row = conn.execute("""INSERT INTO jobsearch.login_limits(bucket,attempts) VALUES(%s,1)
          ON CONFLICT(bucket) DO UPDATE SET
          attempts=CASE WHEN jobsearch.login_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE jobsearch.login_limits.attempts+1 END,
          window_start=CASE WHEN jobsearch.login_limits.window_start < now()-interval '15 minutes' THEN now() ELSE jobsearch.login_limits.window_start END
          RETURNING attempts""", (bucket,)).fetchone()
        if row['attempts'] > maximum:
            return True
    return False

def daily_count(conn, bucket, day):
    """Count one use in a fixed UTC-day window and return the uses so far that day. throttled() keeps a 15-minute
    window, so the day is part of the bucket name instead: each day starts a new row and nothing is ever reset.
    prune() removes a row a day after its first use, which is always after its day has ended."""
    return conn.execute("""INSERT INTO jobsearch.login_limits(bucket,attempts) VALUES(%s,1)
      ON CONFLICT(bucket) DO UPDATE SET attempts=jobsearch.login_limits.attempts+1
      RETURNING attempts""", (bucket + ':' + day.isoformat(),)).fetchone()['attempts']

def login_buckets(identifier):
    """A global budget also bounds attacks using many usernames; the account budget is keyed by the matched account's
    username, so alternating username and email for one account shares a single budget."""
    return [('global', 100), ('user:' + hashlib.sha256(identifier.encode()).hexdigest(), 10)]

def prune(conn):
    """Housekeeping inside the login transaction: stale throttle rows and expired tokens. SKIP LOCKED never waits on
    rows another request is counting or consuming, so bucket lock order stays acyclic."""
    conn.execute("""DELETE FROM jobsearch.login_limits WHERE bucket IN
      (SELECT bucket FROM jobsearch.login_limits WHERE window_start < now()-interval '1 day' FOR UPDATE SKIP LOCKED)""")
    conn.execute("""DELETE FROM jobsearch.auth_tokens WHERE token_hash IN
      (SELECT token_hash FROM jobsearch.auth_tokens WHERE expires_at <= now() FOR UPDATE SKIP LOCKED)""")
    conn.execute("""DELETE FROM jobsearch.mfa_challenges WHERE token_hash IN
      (SELECT token_hash FROM jobsearch.mfa_challenges WHERE expires_at <= now() - interval '1 hour' FOR UPDATE SKIP LOCKED)""")
    from src.auth import scan  # imported here: scan imports this module
    visitor_context.prune(conn)
    scan.prune(conn)

def find_account(conn, value):
    """Local account for a sign-in identifier: an address containing '@' matches the email case-insensitively first,
    then (for older usernames that contain '@') the username. Returns the row without locking it."""
    value = value.strip()
    if '@' in value:
        row = conn.execute("SELECT id,subject FROM jobsearch.users WHERE issuer='local' AND lower(email)=lower(%s)", (value,)).fetchone()
        if row:
            return row
    try:
        name = username(value)
    except ValueError:
        return None
    return conn.execute("SELECT id,subject FROM jobsearch.users WHERE issuer='local' AND subject=%s", (name,)).fetchone()

def request_host(request):
    """The host the visitor used. Browser requests reach the API through the web app's /api rewrite, which proxies
    with changeOrigin (Host becomes api:8100) and always sets X-Forwarded-Host to the incoming Host, overwriting any
    client value; without it every session cookie was host-only on jobs.bagala.ai and the Library and Job Prep never
    saw the sign-in (15 Sep 2026). Direct callers (gateways, tests) send no X-Forwarded-Host and keep Host."""
    forwarded = request.headers.get('x-forwarded-host', '').split(',')[0].strip()
    host = (forwarded or request.headers.get('host', '')).lower()
    return host[1:host.find(']')] if host.startswith('[') else host.split(':')[0]

def on_cookie_domain(request):
    """True when the request host is cookie_domain or a subdomain of it, i.e. it arrived through the public edge."""
    domain = settings().cookie_domain
    host = request_host(request)
    return bool(domain) and (host == domain or host.endswith('.' + domain))

def cookie_options(request):
    """Decided per request because one API serves http://localhost:3105 and https://jobs.bagala.ai: the Domain
    attribute is set only on the public edge, and Secure only when secure_cookies is on and the request arrived
    over HTTPS (directly or via X-Forwarded-Proto from the gateway)."""
    cfg = settings()
    forwarded = request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower()
    secure = bool(cfg.secure_cookies) and (request.url.scheme == 'https' or forwarded == 'https')
    return {'domain': cfg.cookie_domain if on_cookie_domain(request) else None, 'secure': secure,
            'samesite': cfg.cookie_samesite, 'path': '/', 'httponly': True}

# A short-path prefix as the gateway spells it: plain path segments and nothing else, no "." or
# ".." among them, so nothing a browser sends can widen a cookie's path, walk it up to the root
# or move it onto another product's address.
PREFIX = re.compile(r'^(?:/(?!\.{1,2}(?:/|$))[A-Za-z0-9._~-]{1,40}){1,3}$')


def request_prefix(request):
    """The short path this request arrived under, '' at the root shape.

    One deployment answers https://jobs.bagala.ai/ and https://bagala.ai/jobsearch/. The web app
    is built under the prefix and its /api rewrite takes the prefix off before the API sees the
    request, so a cookie scoped to a path has to be told which address the browser is using:
    the gateway names it in X-Forwarded-Prefix, overwriting whatever the visitor sent
    (platform/gateway/nginx.conf). Absent means the root shape, which is what loopback and
    direct callers are."""
    value = request.headers.get('x-forwarded-prefix', '').split(',')[0].strip().rstrip('/')
    return value if PREFIX.match(value) else ''


def mfa_cookie_options(request):
    """The two-step challenge rides only on the account routes of the address in use: that is
    /api/auth at the root and /jobsearch/api/auth on the short path."""
    return {**cookie_options(request), 'path': request_prefix(request) + '/api/auth'}

def mfa_enabled(conn, user_id):
    return conn.execute('SELECT 1 FROM jobsearch.user_mfa WHERE user_id=%s AND enabled_at IS NOT NULL', (user_id,)).fetchone() is not None

def start_session(conn, user, method='password'):
    """The one place a sign-in becomes a session: used by the password step and by the two-step code step."""
    raw = secrets.token_urlsafe(48)
    conn.execute('DELETE FROM jobsearch.sessions WHERE expires_at <= now()')
    conn.execute('INSERT INTO jobsearch.sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',
        (token_hash(raw), user['id'], datetime.now(timezone.utc)+timedelta(hours=settings().session_hours)))
    conn.execute('UPDATE jobsearch.users SET last_login_at=now() WHERE id=%s', (user['id'],))
    audit(conn, str(user['id']), 'login', 'session', details={'method': method} if method != 'password' else None)
    return raw

def session_response(request, raw):
    response = JSONResponse({'ok': True})
    response.set_cookie(COOKIE, raw, max_age=settings().session_hours*3600, **cookie_options(request))
    return response

def new_login_code():
    return '{:0{width}d}'.format(secrets.randbelow(10 ** EMAIL_CODE_DIGITS), width=EMAIL_CODE_DIGITS)

def code_digest(user_id, code):
    """An e-mail code is stored as a digest bound to the account, like a recovery code."""
    return hashlib.sha256((str(user_id) + ':login-code:' + ''.join((code or '').split())).encode()).hexdigest()

def start_challenge(conn, user_id, method='totp', email=None):
    """A short single-use challenge between the password step and the code step. For the e-mail
    method the six-digit code is drawn here, stored as a digest and queued to the verified address;
    the code itself never touches a log or an audit record."""
    raw = secrets.token_urlsafe(32)
    digest = None
    if method == 'email':
        code = new_login_code()
        digest = code_digest(user_id, code)
        queue_mail(conn, 'login_code', email, *render_login_code(code, MFA_CHALLENGE_SECONDS // 60))
    conn.execute('INSERT INTO jobsearch.mfa_challenges(token_hash,user_id,expires_at,method,code_hash) VALUES(%s,%s,%s,%s,%s)',
                 (token_hash(raw), user_id, datetime.now(timezone.utc)+timedelta(seconds=MFA_CHALLENGE_SECONDS), method, digest))
    return raw

@router.post('/api/auth/login')
def login(body: Credentials, request: Request):
    cfg = settings()
    denied = unverified = False
    raw = challenge = None
    method = 'totp'
    with connection() as conn:
        prune(conn)
        match = find_account(conn, body.username)
        denied = throttled(conn, login_buckets(match['subject'] if match else body.username.strip().lower()))
        if denied:
            audit(conn, 'anonymous', 'login', 'local', 'throttled')
        else:
            user = conn.execute('SELECT * FROM jobsearch.users WHERE id=%s FOR UPDATE', (match['id'],)).fetchone() if match else None
            valid = verify(body.password.get_secret_value(), user['password_hash'] if user else None)
            if valid and user['active'] and user['email'] and not user['email_verified_at']:
                # Self-service accounts sign in only after the address is confirmed; console accounts have no email.
                unverified = True
                audit(conn, str(user['id']), 'login', 'local', 'unverified')
            elif valid and user['active']:
                if hasher.check_needs_rehash(user['password_hash']):
                    conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s',
                                 (hasher.hash(body.password.get_secret_value()), user['id']))
                if mfa_enabled(conn, user['id']):
                    # The password alone never yields a session: a short single-use challenge waits for the code.
                    challenge = start_challenge(conn, user['id'])
                    audit(conn, str(user['id']), 'login', 'local', 'mfa_required')
                elif cfg.login_email_code and user['email'] and user['email_verified_at']:
                    # No authenticator app: the second step is a code sent to the verified address.
                    method = 'email'
                    challenge = start_challenge(conn, user['id'], 'email', user['email'])
                    audit(conn, str(user['id']), 'login', 'local', 'mfa_required', details={'method': 'email'})
                else:
                    raw = start_session(conn, user)
                    visitor_context.record(conn, 'signin', visitor_context.visitor(request), user_id=user['id'])
            else:
                audit(conn, 'anonymous', 'login', 'local', 'denied')
    # Errors must be raised after committing counters and audit records.
    if denied:
        raise HTTPException(429, 'Too many sign-in attempts. Try again later.', headers={'Retry-After':'900'})
    if unverified:
        raise HTTPException(403, 'Verify your email address before signing in.')
    if challenge:
        response = JSONResponse({'ok': True, 'mfa_required': True, 'method': method})
        response.set_cookie(MFA_COOKIE, challenge, max_age=MFA_CHALLENGE_SECONDS, **mfa_cookie_options(request))
        return response
    if raw is None:
        raise HTTPException(401, INVALID_LOGIN)
    return session_response(request, raw)
