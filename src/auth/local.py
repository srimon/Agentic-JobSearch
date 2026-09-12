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
class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)

@router.post('/api/auth/login')
def login(body: Credentials, request: Request):
    cfg = settings()
    try:
        name = username(body.username)
    except ValueError:
        name = ''
    # A global budget also bounds attacks using many usernames. PostgreSQL row locks
    # enforce both budgets across processes. Never trust client forwarding headers.
    buckets = [('global', 100), ('user:' + hashlib.sha256(name.encode()).hexdigest(), 10)]
    denied = False
    raw = None
    with connection() as conn:
        for bucket, maximum in buckets:
            row = conn.execute("""INSERT INTO jobsearch.login_limits(bucket,attempts) VALUES(%s,1)
              ON CONFLICT(bucket) DO UPDATE SET
              attempts=CASE WHEN jobsearch.login_limits.window_start < now()-interval '15 minutes' THEN 1 ELSE jobsearch.login_limits.attempts+1 END,
              window_start=CASE WHEN jobsearch.login_limits.window_start < now()-interval '15 minutes' THEN now() ELSE jobsearch.login_limits.window_start END
              RETURNING attempts""", (bucket,)).fetchone()
            if row['attempts'] > maximum:
                denied = True
                break
        if denied:
            audit(conn, 'anonymous', 'login', 'local', 'throttled')
        else:
            user = conn.execute("SELECT * FROM jobsearch.users WHERE issuer='local' AND subject=%s FOR UPDATE", (name,)).fetchone()
            valid = verify(body.password.get_secret_value(), user['password_hash'] if user else None)
            if valid and user['active']:
                if hasher.check_needs_rehash(user['password_hash']):
                    conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s',
                                 (hasher.hash(body.password.get_secret_value()), user['id']))
                raw = secrets.token_urlsafe(48)
                conn.execute('DELETE FROM jobsearch.sessions WHERE expires_at <= now()')
                conn.execute('INSERT INTO jobsearch.sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',
                    (hashlib.sha256(raw.encode()).hexdigest(), user['id'], datetime.now(timezone.utc)+timedelta(hours=cfg.session_hours)))
                audit(conn, str(user['id']), 'login', 'session')
            else:
                audit(conn, 'anonymous', 'login', 'local', 'denied')
    # Errors must be raised after committing counters and audit records.
    if denied:
        raise HTTPException(429, 'Too many sign-in attempts. Try again later.', headers={'Retry-After':'900'})
    if raw is None:
        raise HTTPException(401, 'Invalid username or password')
    response = JSONResponse({'ok': True})
    response.set_cookie('jobsearch_session', raw, httponly=True, secure=cfg.secure_cookies,
                        samesite='strict', max_age=cfg.session_hours*3600, path='/')
    return response
