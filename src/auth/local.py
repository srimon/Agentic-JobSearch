import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from src.settings import settings
from src.db.store import connection, audit
from src.auth.passwords import verify, username, hasher

router = APIRouter()
COOKIE = 'jobsearch_session'
# Carries the pending two-step sign-in between the password and the code; scoped to the auth routes only.
MFA_COOKIE = 'jobsearch_mfa'
MFA_CHALLENGE_SECONDS = 300
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
    host = request.headers.get('host', '').lower()
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

def mfa_cookie_options(request):
    return {**cookie_options(request), 'path': '/api/auth'}

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

def start_challenge(conn, user_id):
    raw = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO jobsearch.mfa_challenges(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',
                 (token_hash(raw), user_id, datetime.now(timezone.utc)+timedelta(seconds=MFA_CHALLENGE_SECONDS)))
    return raw

@router.post('/api/auth/login')
def login(body: Credentials, request: Request):
    denied = unverified = False
    raw = challenge = None
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
                else:
                    raw = start_session(conn, user)
            else:
                audit(conn, 'anonymous', 'login', 'local', 'denied')
    # Errors must be raised after committing counters and audit records.
    if denied:
        raise HTTPException(429, 'Too many sign-in attempts. Try again later.', headers={'Retry-After':'900'})
    if unverified:
        raise HTTPException(403, 'Verify your email address before signing in.')
    if challenge:
        response = JSONResponse({'ok': True, 'mfa_required': True})
        response.set_cookie(MFA_COOKIE, challenge, max_age=MFA_CHALLENGE_SECONDS, **mfa_cookie_options(request))
        return response
    if raw is None:
        raise HTTPException(401, INVALID_LOGIN)
    return session_response(request, raw)
