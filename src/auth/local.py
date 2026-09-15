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
class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
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

def prune(conn):
    """Housekeeping inside the login transaction: stale throttle rows and expired tokens. SKIP LOCKED never waits on
    rows another request is counting or consuming, so bucket lock order stays acyclic."""
    conn.execute("""DELETE FROM jobsearch.login_limits WHERE bucket IN
      (SELECT bucket FROM jobsearch.login_limits WHERE window_start < now()-interval '1 day' FOR UPDATE SKIP LOCKED)""")
    conn.execute("""DELETE FROM jobsearch.auth_tokens WHERE token_hash IN
      (SELECT token_hash FROM jobsearch.auth_tokens WHERE expires_at <= now() FOR UPDATE SKIP LOCKED)""")

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

@router.post('/api/auth/login')
def login(body: Credentials, request: Request):
    cfg = settings()
    try:
        name = username(body.username)
    except ValueError:
        name = ''
    # A global budget also bounds attacks using many usernames.
    denied = unverified = False
    raw = None
    with connection() as conn:
        prune(conn)
        denied = throttled(conn, [('global', 100), ('user:' + hashlib.sha256(name.encode()).hexdigest(), 10)])
        if denied:
            audit(conn, 'anonymous', 'login', 'local', 'throttled')
        else:
            user = conn.execute("SELECT * FROM jobsearch.users WHERE issuer='local' AND subject=%s FOR UPDATE", (name,)).fetchone()
            valid = verify(body.password.get_secret_value(), user['password_hash'] if user else None)
            if valid and user['active'] and user['email'] and not user['email_verified_at']:
                # Self-service accounts sign in only after the address is confirmed; console accounts have no email.
                unverified = True
                audit(conn, str(user['id']), 'login', 'local', 'unverified')
            elif valid and user['active']:
                if hasher.check_needs_rehash(user['password_hash']):
                    conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s',
                                 (hasher.hash(body.password.get_secret_value()), user['id']))
                raw = secrets.token_urlsafe(48)
                conn.execute('DELETE FROM jobsearch.sessions WHERE expires_at <= now()')
                conn.execute('INSERT INTO jobsearch.sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',
                    (token_hash(raw), user['id'], datetime.now(timezone.utc)+timedelta(hours=cfg.session_hours)))
                conn.execute('UPDATE jobsearch.users SET last_login_at=now() WHERE id=%s', (user['id'],))
                audit(conn, str(user['id']), 'login', 'session')
            else:
                audit(conn, 'anonymous', 'login', 'local', 'denied')
    # Errors must be raised after committing counters and audit records.
    if denied:
        raise HTTPException(429, 'Too many sign-in attempts. Try again later.', headers={'Retry-After':'900'})
    if unverified:
        raise HTTPException(403, 'Verify your email address before signing in.')
    if raw is None:
        raise HTTPException(401, 'Invalid username or password')
    response = JSONResponse({'ok': True})
    response.set_cookie(COOKIE, raw, max_age=cfg.session_hours*3600, **cookie_options(request))
    return response
