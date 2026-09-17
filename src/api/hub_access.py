"""Authorization for the private Library gateway (platform/gateway/mbk-production.conf, auth_request), and the
key check for the hub's API gateway front (platform/gateway/api-front.conf, auth_request).

Every active, verified account may use the Reader; every other Library path is administrator-only
(src/api/library_policy.py). Refusals of a signed-in visitor are 403, never 401, so the gateway shows its no-access
page instead of sending them back to sign-in. nginx's auth_request passes only 2xx, 401 and 403, so the Reader's
daily question limit is a 403 carrying X-Hub-Limit: reader-daily and Retry-After, which the gateway turns into a
JSON 429 for the browser.

An allowed request answers 204 with X-Hub-User and X-Hub-Roles. The gateway copies the roles onto the request it
proxies to the Library, overwriting anything the visitor sent under that name, and the Library API shows another
reader's question, exception text and the rendered prompt only when that header says administrator.

A program comes with an API key instead of the cookie (src/auth/api_keys.py; current_user resolves both). A keyed
request is not a browser's, so the Origin check does not apply to it; a key of a member may read the Reader but
not ask a question, because a question spends model tokens and the owner keeps model-spending calls to operator
and administrator keys (17 Sep 2026). The key's daily quota, counted in current_user, arrives here as a 403 marked
X-Hub-Limit: key-daily.

/api/hub/key-authorize is what the API gateway front asks before it routes a call to a product: it verifies the
key without counting it (the product's own check counts it once) and answers 204 with the key id, the account,
its roles, its rate-limit class and the products it covers, or 401/403; over the quota, 403 marked key-daily."""
from datetime import datetime, time, timedelta, timezone
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from src.db.store import connection,audit
from src.settings import settings
from src.auth.local import daily_count
from src.auth import api_keys
from src.api import library_policy

SAFE_METHODS={'GET','HEAD','OPTIONS'}
DAILY_LIMIT_HEADER='reader-daily'
ROLE_HEADER='X-Hub-Roles'
MODEL_SPENDING_ROLES={'operator','administrator'}
# A role name as a header value: letters, digits, dash and underscore, so nothing a role could be
# named can fold a header or add one of its own.
ROLE_CHARS=set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_')

def role_header(user):
    """The account's roles for the gateway to copy onto the proxied request, comma separated.
    The Library API shows another reader's question, exception text and the prompt only to an administrator, and this
    is how it is told which one this is; the gateway overwrites whatever the visitor sent under the same name."""
    roles=[r for r in (user.get('roles') or ()) if isinstance(r,str) and r and set(r)<=ROLE_CHARS]
    return ','.join(sorted(set(roles)))[:200]

def now():
    """The clock the daily limit reads; tests replace it."""
    return datetime.now(timezone.utc)

def seconds_to_utc_midnight(moment):
    tomorrow=datetime.combine(moment.date()+timedelta(days=1),time.min,tzinfo=timezone.utc)
    return max(1,int((tomorrow-moment).total_seconds()+0.999))

def is_administrator(user):
    return 'administrator' in (user.get('roles') or ())

def verified(user):
    # current_user already requires an active account; accounts with an email (self-service) must have confirmed it,
    # console accounts have none.
    return bool(user.get('active',True)) and not (user.get('email') and not user.get('email_verified_at'))

def create_router(current_user):
    router=APIRouter()
    @router.get('/api/hub/library-authorize')
    def authorize(request:Request,user=Depends(current_user)):
        method=request.headers.get('x-original-method','GET').upper()
        if method not in {'GET','HEAD','OPTIONS','POST','PUT','PATCH','DELETE'}:raise HTTPException(403,'Unsupported method')
        kind=library_policy.classify(method,request.headers.get('x-original-uri'))
        if kind==library_policy.INVALID:raise HTTPException(403,'Invalid path')
        if not verified(user):raise HTTPException(403,'Verify your email address to use the Library')
        admin=is_administrator(user)
        keyed=api_keys.keyed(user)
        if kind==library_policy.ADMINISTRATOR and not admin:raise HTTPException(403,'Administrator role required')
        if kind==library_policy.QUESTION and keyed and not MODEL_SPENDING_ROLES&set(user.get('roles') or ()):
            raise HTTPException(403,'A question spends model tokens: it needs an operator or administrator key')
        limit=settings().reader_daily_question_limit
        counted=kind==library_policy.QUESTION and not admin and limit>0
        limited=False
        if method not in SAFE_METHODS:
            # The Origin check is against a browser's ambient cookie; a key is sent on purpose and carries no cookie.
            if not keyed and request.headers.get('x-original-origin') not in settings().library_origins:raise HTTPException(403,'Origin rejected')
            with connection() as conn:
                details={'method':method}
                if keyed:details['key']=user['api_key']['id']
                audit(conn,str(user['id']),'hub.library.authorize','library',details=details)
                if counted:
                    moment=now()
                    used=daily_count(conn,'reader-questions:'+str(user['id']),moment.date())
                    limited=used>limit
                    if used==limit+1:
                        # Once per user per day, when the limit is first reached; the question text is never seen here.
                        audit(conn,str(user['id']),'hub.library.reader_question','library','limited',details={'limit':limit})
        # Raised after the counter and audit rows are committed.
        if limited:
            raise HTTPException(403,"You have reached today's Reader question limit. It resets at midnight UTC.",
                                headers={'X-Hub-Limit':DAILY_LIMIT_HEADER,'Retry-After':str(seconds_to_utc_midnight(moment)),'Cache-Control':'no-store'})
        return Response(status_code=204,headers={'X-Hub-User':str(user['id']),ROLE_HEADER:role_header(user),'Cache-Control':'no-store'})

    @router.get('/api/hub/key-authorize')
    def key_authorize(request:Request):
        """The API gateway front's check (auth_request /_api/key): the key alone, verified but not counted, with
        X-Original-Product naming the product the call is for. The product's own gateway or route checks and
        counts the same key once more on the call itself."""
        if not api_keys.bearer(request):raise HTTPException(401,'API key required',headers={'Cache-Control':'no-store'})
        user=api_keys.authenticate(request,count=False)
        key=user['api_key']
        if not verified(user):raise HTTPException(403,'Verify your email address first')
        return Response(status_code=204,headers={'X-Hub-Key-Id':key['id'],'X-Hub-User':str(user['id']),ROLE_HEADER:role_header(user),
                                                 'X-Hub-Limit-Class':key['limit_class'],'X-Hub-Products':','.join(key['products']),
                                                 'Cache-Control':'no-store'})
    return router
