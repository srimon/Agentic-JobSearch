"""API keys: a program's credential for the three products (stage 2 of the hub's docs/plans/api-gateway-and-mcp.md).

A key is "hub_<id>_<secret>", sent as "Authorization: Bearer hub_<id>_<secret>". The id is the public prefix
(12 hex characters, the row's primary key, what the hub's API gateway keys its rate limit on before the secret
is ever checked); the secret is 32 random bytes shown once at creation and stored as its SHA-256 digest, like a
session token, and compared in constant time. A key belongs to one account and carries that account's roles at
the time of the call, never roles of its own; several named keys per account; revocation keeps the row.

Where it is honoured: src/api/main.py current_user accepts a key beside the session cookie, so every Job Search
route, the Library's authorization call and Job Prep's identity call resolve it in one place. A request that
carries both a cookie and a key is refused. A key never manages the account (nothing under /api/auth/) and is
never itself created with a key: the management routes below take a signed-in browser session and, to create
one, the password again.

Quotas and the audit of use: daily_quota calls per UTC day per key (0 = unlimited), counted in api_key_days,
one row per key and day (calls made, calls refused over the quota); api_keys.last_used_at is refreshed when it
is older than ACTIVITY_REFRESH_SECONDS, so a busy key is one write per call for the counter and not two. Over
the quota a Job Search route answers 429 with Retry-After to midnight UTC; the gateways' auth_request callers
(library-authorize, prep-identity, key-authorize) get the same as a 403 marked X-Hub-Limit: key-daily, which
nginx's auth_request can pass on (main.py). Audit rows: account.api_key.create/rename/revoke, and
api_key.limited once per key per day when the quota is first exceeded. The secret never appears in any of them.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, time, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr
from src.settings import settings
from src.db.store import connection, audit
from src.auth.passwords import verify
from src.auth.local import throttled

PRODUCTS = ('jobsearch', 'library', 'prep')
PREFIX = 'hub_'
ID_LENGTH = 12
KEY_SHAPE = re.compile(r'^hub_(?P<id>[0-9a-f]{12})_(?P<secret>[A-Za-z0-9_-]{32,64})$')
NAME_CHARS = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._@+-]{0,59}$')
LIMIT_HEADER = 'key-daily'
# The order matters: the strongest role names the class.
LIMIT_CLASSES = (('administrator', 'administrator'), ('operator', 'operator'))
DEFAULT_CLASS = 'member'
ACTIVITY_REFRESH_SECONDS = 30
INVALID = 'Invalid API key'
DISABLED = 'API keys are not enabled on this server'
BOTH = 'Send either a session cookie or an API key, not both'
NOT_FOR_ACCOUNT = 'An API key cannot manage the account; sign in with a browser'
# The paths nginx's auth_request reaches: only 2xx, 401 and 403 can pass through it.
GATEWAY_PATHS = frozenset({'/api/hub/library-authorize', '/api/hub/prep-identity', '/api/hub/key-authorize'})
PRODUCT_PATHS = {'/api/hub/library-authorize': 'library', '/api/hub/prep-identity': 'prep'}
PRODUCT_HEADER = 'x-original-product'
# What an unmatched id is compared against, so an unknown id costs the same as a wrong secret.
_ABSENT = hashlib.sha256(b'no such key').hexdigest()


def now():
    """The clock the daily quota reads; tests replace it."""
    return datetime.now(timezone.utc)


def seconds_to_utc_midnight(moment):
    tomorrow = datetime.combine(moment.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return max(1, int((tomorrow - moment).total_seconds() + 0.999))


def secret_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def new_key():
    """(id, secret, the key as the person will send it)."""
    key_id = secrets.token_hex(ID_LENGTH // 2)
    secret = secrets.token_urlsafe(32)
    return key_id, secret, '{}{}_{}'.format(PREFIX, key_id, secret)


def bearer(request):
    """The key in the Authorization header, or '' when the request carries none of ours."""
    value = request.headers.get('authorization', '')
    scheme, _, token = value.partition(' ')
    token = token.strip()
    return token if scheme.lower() == 'bearer' and token.startswith(PREFIX) else ''


def limit_class(roles):
    for role, name in LIMIT_CLASSES:
        if role in (roles or ()):
            return name
    return DEFAULT_CLASS


def product_for(request):
    """Which product the request is for: the gateway paths name theirs, the key check reads the header the
    API gateway sends, and everything else is Job Search's own API."""
    path = request.url.path
    if path in PRODUCT_PATHS:
        return PRODUCT_PATHS[path]
    if path == '/api/hub/key-authorize':
        return request.headers.get(PRODUCT_HEADER, '').strip().lower()
    return 'jobsearch'


def refusal(status, detail, request, retry_after=None):
    """A refusal the caller can pass on: 429 becomes a 403 marked X-Hub-Limit on the gateway paths, because
    nginx's auth_request passes only 2xx, 401 and 403 (the Reader's daily limit takes the same road)."""
    headers = {'Cache-Control': 'no-store'}
    if retry_after is not None:
        headers['Retry-After'] = str(retry_after)
    if status == 429 and request.url.path in GATEWAY_PATHS:
        status = 403
        headers['X-Hub-Limit'] = LIMIT_HEADER
    return HTTPException(status, detail, headers=headers)


def authenticate(request, count=True):
    """The account behind the key in the request, with the key's own record under user['api_key'].

    count=True (every Job Search route, library-authorize and prep-identity) counts the call against the
    day's quota and refreshes last_used_at; count=False (the API gateway's key-authorize, which precedes the
    product's own check) only reads the count, so one call through the gateway is counted once."""
    cfg = settings()
    token = bearer(request)
    if not cfg.api_keys_enabled:
        raise refusal(401, DISABLED, request)
    if request.cookies.get('jobsearch_session'):
        raise refusal(401, BOTH, request)
    match = KEY_SHAPE.match(token)
    key_id = match.group('id') if match else ''
    if request.url.path.startswith('/api/auth/'):
        raise refusal(403, NOT_FOR_ACCOUNT, request)
    product = product_for(request)
    if product not in PRODUCTS:
        raise refusal(403, 'Unknown product', request)
    moment = now()
    day = moment.date()
    limited = first_over = False
    used = 0
    with connection() as conn:
        row = conn.execute("""SELECT u.*, k.id AS key_id, k.name AS key_name, k.secret_hash, k.products AS key_products,
                                     k.daily_quota, k.revoked_at
                              FROM jobsearch.api_keys k JOIN jobsearch.users u ON u.id=k.user_id WHERE k.id=%s""",
                           (key_id,)).fetchone() if match else None
        expected = row['secret_hash'] if row else _ABSENT
        if not hmac.compare_digest(expected, secret_hash(match.group('secret') if match else '')):
            row = None
        if row is None:
            raise refusal(401, INVALID, request)
        if row['revoked_at'] is not None:
            raise refusal(401, 'This API key was revoked', request)
        if not row['active'] or (row['email'] and not row['email_verified_at']):
            raise refusal(401, 'Session expired or access revoked', request)
        if product not in row['key_products']:
            raise refusal(403, 'This API key does not cover {}'.format(product), request)
        quota = row['daily_quota']
        if count:
            used = conn.execute("""INSERT INTO jobsearch.api_key_days(key_id,day,calls) VALUES(%s,%s,1)
                                   ON CONFLICT(key_id,day) DO UPDATE SET calls=jobsearch.api_key_days.calls+1 RETURNING calls""",
                                (key_id, day)).fetchone()['calls']
            limited = quota > 0 and used > quota
            if limited:
                conn.execute('UPDATE jobsearch.api_key_days SET refused=refused+1 WHERE key_id=%s AND day=%s', (key_id, day))
                first_over = used == quota + 1
                if first_over:
                    audit(conn, str(row['id']), 'api_key.limited', key_id, 'limited', details={'limit': quota, 'product': product})
            else:
                conn.execute("""UPDATE jobsearch.api_keys SET last_used_at=now() WHERE id=%s
                                AND (last_used_at IS NULL OR last_used_at < now()-(%s * interval '1 second'))""",
                             (key_id, ACTIVITY_REFRESH_SECONDS))
        else:
            counted = conn.execute('SELECT calls FROM jobsearch.api_key_days WHERE key_id=%s AND day=%s', (key_id, day)).fetchone()
            used = counted['calls'] if counted else 0
            limited = quota > 0 and used >= quota
    # Raised after the counter and audit rows are committed.
    if limited:
        raise refusal(429, "This API key has reached today's call limit. It resets at midnight UTC.", request,
                      seconds_to_utc_midnight(moment))
    user = {k: v for k, v in row.items() if k not in ('key_id', 'key_name', 'secret_hash', 'key_products', 'daily_quota', 'revoked_at')}
    user['api_key'] = {'id': row['key_id'], 'name': row['key_name'], 'products': list(row['key_products']),
                       'daily_quota': quota, 'used_today': used, 'limit_class': limit_class(user.get('roles'))}
    return user


def keyed(user):
    return isinstance(user, dict) and 'api_key' in user


# ----- management, from a signed-in browser session -------------------------------------------------------

class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    password: SecretStr = Field(min_length=1, max_length=128)
    products: list[str] | None = None
    daily_quota: int | None = Field(default=None, ge=0)


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def clean_name(value):
    name = ' '.join((value or '').split())
    if not NAME_CHARS.match(name):
        raise HTTPException(422, 'Name the key with 1-60 letters, digits, spaces or ._@+-')
    return name


def clean_products(values):
    if values is None:
        return list(PRODUCTS)
    chosen = [p for p in PRODUCTS if p in {str(v).strip().lower() for v in values}]
    if not chosen:
        raise HTTPException(422, 'Choose at least one product: ' + ', '.join(PRODUCTS))
    return chosen


def summary(row, used_today=0):
    return {'id': row['id'], 'name': row['name'], 'products': list(row['products']), 'daily_quota': row['daily_quota'],
            'created_at': row['created_at'], 'last_used_at': row['last_used_at'], 'revoked_at': row['revoked_at'],
            'used_today': used_today}


def api_base():
    """Where a key is used: the hub's API gateway on the public host of Job Search's own public address, so the
    domain lives in one setting (JOBSEARCH_PUBLIC_ORIGIN) and a rename is mechanical."""
    from src.settings import origin_of
    public = origin_of(settings().public_origin)
    return public + '/api/v1' if public.startswith('https://') else ''


def create_router(current_user):
    router = APIRouter(prefix='/api/auth/keys')

    def session_only(user):
        if not settings().api_keys_enabled:
            raise HTTPException(404, 'Not Found')
        if keyed(user):
            raise HTTPException(403, NOT_FOR_ACCOUNT)
        return user

    @router.get('')
    def list_keys(user=Depends(current_user)):
        session_only(user)
        cfg = settings()
        with connection() as conn:
            rows = conn.execute("""SELECT k.*, coalesce(d.calls,0) AS used_today FROM jobsearch.api_keys k
                                   LEFT JOIN jobsearch.api_key_days d ON d.key_id=k.id AND d.day=%s
                                   WHERE k.user_id=%s ORDER BY k.created_at, k.id""", (now().date(), user['id'])).fetchall()
        return {'keys': [summary(r, r['used_today']) for r in rows], 'products': list(PRODUCTS), 'daily_quota_max': cfg.api_key_daily_quota,
                'limit': cfg.api_keys_per_account, 'api_base': api_base(), 'limit_class': limit_class(user.get('roles'))}

    @router.post('', status_code=201)
    def create_key(body: NewKey, user=Depends(current_user)):
        session_only(user)
        cfg = settings()
        name = clean_name(body.name)
        products = clean_products(body.products)
        quota = cfg.api_key_daily_quota if body.daily_quota is None else min(body.daily_quota, cfg.api_key_daily_quota)
        outcome = 'allowed'
        created = None
        with connection() as conn:
            if throttled(conn, [('api-keys:' + str(user['id']), 10)]):
                outcome = 'throttled'
            elif not verify(body.password.get_secret_value(), user.get('password_hash')):
                outcome = 'denied'
            else:
                live = conn.execute('SELECT count(*) AS n FROM jobsearch.api_keys WHERE user_id=%s AND revoked_at IS NULL', (user['id'],)).fetchone()['n']
                taken = conn.execute('SELECT 1 FROM jobsearch.api_keys WHERE user_id=%s AND name=%s', (user['id'], name)).fetchone()
                if live >= cfg.api_keys_per_account:
                    outcome = 'limit'
                elif taken:
                    outcome = 'duplicate'
                else:
                    key_id, secret, token = new_key()
                    row = conn.execute("""INSERT INTO jobsearch.api_keys(id,user_id,name,secret_hash,products,daily_quota)
                                          VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
                                       (key_id, user['id'], name, secret_hash(secret), products, quota)).fetchone()
                    created = {**summary(row), 'key': token}
            audit(conn, str(user['id']), 'account.api_key.create', created['id'] if created else 'local', outcome,
                  details={'products': products, 'daily_quota': quota} if created else None)
        if outcome == 'throttled':
            raise HTTPException(429, 'Too many attempts. Try again later.', headers={'Retry-After': '900'})
        if outcome == 'denied':
            raise HTTPException(400, 'Password is incorrect')
        if outcome == 'limit':
            raise HTTPException(409, 'You already have {} active keys; revoke one first'.format(cfg.api_keys_per_account))
        if outcome == 'duplicate':
            raise HTTPException(409, 'You already have a key with that name')
        # The one time the secret is shown (every answer of this API is Cache-Control: no-store).
        return created

    @router.patch('/{key_id}')
    def rename_key(key_id: str, body: Rename, user=Depends(current_user)):
        session_only(user)
        name = clean_name(body.name)
        with connection() as conn:
            row = conn.execute('SELECT id FROM jobsearch.api_keys WHERE id=%s AND user_id=%s FOR UPDATE', (key_id, user['id'])).fetchone()
            if not row:
                raise HTTPException(404, 'No such key')
            if conn.execute('SELECT 1 FROM jobsearch.api_keys WHERE user_id=%s AND name=%s AND id<>%s', (user['id'], name, key_id)).fetchone():
                raise HTTPException(409, 'You already have a key with that name')
            conn.execute('UPDATE jobsearch.api_keys SET name=%s WHERE id=%s', (name, key_id))
            audit(conn, str(user['id']), 'account.api_key.rename', key_id)
        return {'ok': True}

    @router.delete('/{key_id}')
    def revoke_key(key_id: str, user=Depends(current_user)):
        session_only(user)
        with connection() as conn:
            row = conn.execute('UPDATE jobsearch.api_keys SET revoked_at=coalesce(revoked_at,now()) WHERE id=%s AND user_id=%s RETURNING revoked_at',
                               (key_id, user['id'])).fetchone()
            if not row:
                raise HTTPException(404, 'No such key')
            audit(conn, str(user['id']), 'account.api_key.revoke', key_id)
        return {'ok': True, 'revoked_at': row['revoked_at']}

    return router
