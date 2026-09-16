import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import FastAPI, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from src.settings import settings
from src.db.store import connection, audit
from src.applications.private import private_connection, decrypt, encrypt, application_summaries
from src.applications.dismissals import dismissal_for
from src.applications.archives import archive_for,require_active,archive_if_emailed
from ai_core.agents.supervisor import enqueue
from src.applications.learning import current as learning_model,explain as learning_explain,configure as configure_learning,ranking_sql
from src.applications.job_filters import STATE_VALUES,TITLE_VALUES,facet_summary

cfg=settings()
app=FastAPI(title='Jobsearch',docs_url=None,redoc_url=None)
from src.auth.local import router as local_auth, cookie_options, on_cookie_domain
app.include_router(local_auth)
from src.observability import setup,event,HTTP,LATENCY
from opentelemetry import trace
import time
setup('jobsearch-api')


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Do not echo submitted passwords in validation responses.
    return JSONResponse({'detail':'Invalid request'}, status_code=422)


@app.middleware('http')
async def boundaries(request,call_next):
    if cfg.maintenance_mode and request.method not in ('GET','HEAD','OPTIONS') and request.url.path not in ('/api/auth/login','/api/auth/logout','/api/auth/mfa/verify') and not request.url.path.startswith('/api/monitoring/'):
        return JSONResponse({'detail':'Maintenance mode: changes are temporarily disabled.'},status_code=503,headers={'Retry-After':'300','Cache-Control':'no-store'})
    if request.method in ('POST','PUT','PATCH','DELETE'):
        if request.headers.get('origin') not in cfg.allowed_origins:
            return JSONResponse({'detail':'Origin rejected'},status_code=403)
    limit=5*1024*1024 if request.method=='PUT' and request.url.path in ('/api/intake/resume/default','/api/intake/resume/capital_one') else 65536
    if request.headers.get('content-length','').isdigit() and int(request.headers['content-length'])>limit:
        return JSONResponse({'detail':'Request too large'},status_code=413)
    # Enforce actual bytes too, including chunked requests without Content-Length.
    if request.method in ('POST','PUT','PATCH','DELETE'):
        chunks=[]; size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>limit: return JSONResponse({'detail':'Request too large'},status_code=413)
            chunks.append(chunk)
        request._body=b''.join(chunks)

    try:
        response=await call_next(request)
    except Exception as exc:
        logging.getLogger('jobsearch.api').error('request_failed error_class=%s',type(exc).__name__)
        response=JSONResponse({'detail':'Service unavailable. Check the operational logs.'},status_code=503)
    response.headers['Cache-Control']='no-store'
    origin=request.headers.get('origin','')
    if request.url.path=='/api/workflow' and origin and origin in cfg.hub_origins:
        response.headers['Access-Control-Allow-Origin']=origin
        response.headers['Access-Control-Allow-Credentials']='true'
        response.headers['Vary']='Origin'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='SAMEORIGIN' if request.url.path.startswith(('/api/monitoring/','/api/data-model/report/')) else 'DENY'
    return response


def current_user(request:Request):
    token=request.cookies.get('jobsearch_session','')
    if not token: raise HTTPException(401,'Sign in required')
    with connection() as conn:
        user=conn.execute('SELECT u.* FROM jobsearch.sessions s JOIN jobsearch.users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires_at>now() AND u.active',
                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not user: raise HTTPException(401,'Session expired or access revoked')
    return user


def is_administrator(user):
    return 'administrator' in (user.get('roles') or ())


# The per-job ranking explanation ("Why this ranking": learning version, rules, adjustment) is administrator-only.
RANKING_EXPLANATION_FIELDS=('learning',)


def administrator(user=Depends(current_user)):
    # Every monitoring and operational display in Job Search (sources, activity, collection status, workflow detail,
    # observability, monitoring consoles, data management, learning management) is for administrators only.
    if not is_administrator(user): raise HTTPException(403,'Administrator role required')
    return user


@app.get('/api/health')
def health():
    with connection() as conn:
        if not conn.execute('SELECT version FROM jobsearch.schema_versions WHERE version=2').fetchone():
            raise HTTPException(503,'Schema not ready')
    return {'status':'ok'}


@app.get('/api/session')
def session(request:Request):
    try: user=current_user(request)
    except HTTPException: user=None
    # Links follow the request host so the front end never hard-codes localhost or the public edge.
    return {'user': {'name':user['display_name'],'roles':user['roles']} if user else None,
            'identity_ready':True,'provider':'Local','features':{'data_management':cfg.data_management_enabled,'maintenance':cfg.maintenance_mode},
            'links':cfg.hub_links_public if on_cookie_domain(request) else cfg.hub_links_local,'signup_enabled':cfg.signup_enabled}


@app.post('/api/auth/logout')
def logout(request:Request,user=Depends(current_user)):
    with connection() as conn:
        conn.execute('DELETE FROM jobsearch.sessions WHERE token_hash=%s',(hashlib.sha256(request.cookies['jobsearch_session'].encode()).hexdigest(),))
        audit(conn,str(user['id']),'logout','session')
    # The deletion must carry the same Domain/Secure/SameSite decision as the sign-in cookie or browsers keep the old one.
    # Sign-out is also forwarded by the library, Preparation and hub front ends, which pass their own public Host, so a
    # public request deletes the shared Domain cookie and, alongside it, any host-only copy an app host may still hold.
    options=cookie_options(request)
    response=JSONResponse({'ok':True}); response.delete_cookie('jobsearch_session',**options)
    if options['domain']: response.delete_cookie('jobsearch_session',**{**options,'domain':None})
    return response

from src.auth.signup import create_router as signup_router
app.include_router(signup_router(current_user))
from src.auth.mfa import create_router as mfa_router
app.include_router(mfa_router(current_user))


@app.get('/api/hub/prep-identity')
def prep_identity(user=Depends(current_user)):
    if not set(user['roles']) & {'member','operator','administrator'}: raise HTTPException(403,'Member role required')
    return {'subject':'jobsearch:'+str(user['id']),'name':user['display_name'],'roles':user['roles']}


@app.get('/api/jobs')
def jobs(q:str=Query('',max_length=200),date:Literal['any','24h','7d','30d']='any',level:str='',
         mode:Literal['','Remote','Hybrid','On-site','Unknown']='',view:Literal['matches','review','saved','emailed','archive']='matches',
         page:int=Query(1,ge=1),show_dismissed:bool=False,user=Depends(current_user),sort:Literal['newest','recommended']='newest',
         state:str=Query('',max_length=12),title:str=Query('',max_length=80)):
    if view=='review' and not is_administrator(user): raise HTTPException(403,'Administrator role required')
    if state and state not in STATE_VALUES: raise HTTPException(422,'Unknown state')
    if title and title not in TITLE_VALUES: raise HTTPException(422,'Unknown job title')
    clauses=[] if view in ('emailed','archive') else ["j.availability='observed_open'"]; values=[]
    if view=='review': clauses.append("j.match_status='review'")
    elif view not in ('emailed','archive'): clauses.append("j.match_status='match' AND j.country_status IN ('us_based','us_remote_eligible')")
    if view=='emailed': clauses.append('e.last_emailed_at IS NOT NULL')
    if view=='saved': clauses.append('s.user_id IS NOT NULL')
    if q:
        clauses.append("(j.title ILIKE %s OR j.company ILIKE %s)"); values += ['%'+q+'%']*2
    if level: clauses.append('j.level=%s'); values.append(level)
    if mode: clauses.append('j.work_mode=%s'); values.append(mode)
    if date!='any':
        clauses.append("j.posted_at >= now() - (%s * interval '1 hour') AND j.posted_at <= now()")
        values.append({'24h':24,'7d':168,'30d':720}[date])
    clauses.append('a.archived_at IS NOT NULL' if view=='archive' else 'a.archived_at IS NULL')
    if not show_dismissed and view!='archive': clauses.append('d.reason IS NULL')
    # OFFSET 0 keeps this scalar LATERAL result from being flattened back into
    # each dismissal comparison. Reuse the existing canonicalization function;
    # changing URL identity semantics would invalidate owner locks.
    base=''' FROM jobsearch.jobs j
        CROSS JOIN LATERAL (SELECT jobsearch.posting_identity(j.url) AS posting_key OFFSET 0) canonical
        LEFT JOIN jobsearch.saved_jobs s ON s.job_id=j.id AND s.user_id=%s
        LEFT JOIN LATERAL (SELECT reason FROM jobsearch.job_dismissals
            WHERE user_id=%s AND (job_id=j.id OR identity=canonical.posting_key)
            ORDER BY updated_at DESC LIMIT 1) d ON true
        LEFT JOIN LATERAL (SELECT max(emailed_at) AS last_emailed_at FROM jobsearch.emailed_jobs
            WHERE user_id=%s AND job_id=j.id) e ON true
        LEFT JOIN jobsearch.job_archives a ON a.user_id=%s AND a.identity=canonical.posting_key
        WHERE '''+' AND '.join(clauses)
    with private_connection(user['id']) as conn:
        # Facets use the visible list under every other filter; the chosen state/title then narrows it in SQL.
        grouped=conn.execute('SELECT j.location,j.title,count(*) AS n'+base+' GROUP BY j.location,j.title',[user['id']]*4+values).fetchall()
        facets,locations,titles=facet_summary(grouped,state,title)
        if state: base+=' AND j.location = ANY(%s)'; values.append(locations)
        if title: base+=' AND j.title = ANY(%s)'; values.append(titles)
        model=learning_model(conn,user['id'])
        order='e.last_emailed_at DESC,j.id' if view=='emailed' else ('a.archived_at DESC,j.id' if view=='archive' else 'j.posted_at DESC NULLS LAST,j.id')
        ranking_params=[]
        if sort=='recommended' and view!='archive':
            score,ranking_params=ranking_sql(model)
            order=score+' DESC,'+order
        total=conn.execute('SELECT count(*) AS n'+base,[user['id']]*4+values).fetchone()['n']
        rows=conn.execute('SELECT j.id,j.source_id,j.title,j.company,j.location,j.work_mode,j.country_status,j.level,j.match_status,j.reason,j.evidence,j.posted_at,j.first_seen_at,j.last_seen_at,j.url,(s.user_id IS NOT NULL) AS saved,s.stage,d.reason AS dismissal_reason,e.last_emailed_at,a.archived_at,a.final_status'+base+' ORDER BY '+order+' LIMIT 25 OFFSET %s',[user['id']]*4+values+ranking_params+[(page-1)*25]).fetchall()
        # "Why this ranking" (learning version, rules and adjustment) is administrator information; the order is the same for everyone.
        if is_administrator(user):
            for row in rows:row['learning']=learning_explain(row,model)
        summaries=application_summaries(conn,user['id'],[row['id'] for row in rows])
        for row in rows:
            row.update(summaries.get(str(row['id']),{'application_status':None,'next_action':None}))
    return {'items':rows,'total':total,'page':page,'page_size':25,'facets':facets}


@app.get('/api/jobs/{job_id}')
def job_detail(job_id:uuid.UUID,user=Depends(current_user)):
    with private_connection(user['id']) as conn:
        row=conn.execute('SELECT * FROM jobsearch.jobs WHERE id=%s',(job_id,)).fetchone()
        if row:
            archived=archive_for(conn,user['id'],row)
            row.update(archived or {'archived_at':None,'final_status':None})
            dismissed=dismissal_for(conn,user['id'],row)
            row['dismissal_reason']=dismissed['reason'] if dismissed else None
            saved=conn.execute('SELECT stage FROM jobsearch.saved_jobs WHERE user_id=%s AND job_id=%s',(user['id'],job_id)).fetchone()
            row['saved']=bool(saved);row['stage']=saved['stage'] if saved else None
            record=conn.execute('SELECT payload FROM jobsearch.private_applications WHERE user_id=%s AND job_id=%s',(user['id'],job_id)).fetchone()
            row['application_status']=decrypt(user['id'],'application:'+str(job_id),record['payload']).get('status') if record else None
            row['last_emailed_at']=conn.execute('SELECT max(emailed_at) AS at FROM jobsearch.emailed_jobs WHERE user_id=%s AND job_id=%s',(user['id'],job_id)).fetchone()['at']
    if not row: raise HTTPException(404,'Job not found')
    if row['match_status']!='match' and not row.get('last_emailed_at') and not is_administrator(user): raise HTTPException(403,'Administrator role required')
    if not is_administrator(user):
        for field in RANKING_EXPLANATION_FIELDS: row.pop(field,None)
    return row



class Dismissal(BaseModel):
    feedback_reason:Literal['wrong_function','wrong_seniority','wrong_workplace']|None=None
    dismissed:bool=True
    reason:Literal['old_posting','already_applied_elsewhere','not_interested','no_longer_available','not_relevant','dismissed','spam','fake_posting']='old_posting'

@app.put('/api/jobs/{job_id}/dismissal')
def dismiss_job(job_id:uuid.UUID,body:Dismissal,user=Depends(current_user)):
    if not set(user['roles']) & {'member','administrator'}: raise HTTPException(403,'Member role required')
    job=job_detail(job_id,user)
    with private_connection(user['id']) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user['id'])+':'+str(job_id),))
        require_active(conn,user['id'],job)
        if body.dismissed:
            conn.execute("INSERT INTO jobsearch.job_dismissals(user_id,identity,job_id,reason) VALUES(%s,jobsearch.posting_identity(%s),%s,%s) ON CONFLICT(user_id,identity) DO UPDATE SET reason=excluded.reason,updated_at=now()",(user['id'],job['url'],job_id,body.reason))
        else:
            conn.execute('DELETE FROM jobsearch.job_dismissals WHERE user_id=%s AND (job_id=%s OR identity=jobsearch.posting_identity(%s))',(user['id'],job_id,job['url']))
        if body.dismissed: archive_if_emailed(conn,user['id'],job,body.reason,body.feedback_reason)
        audit(conn,str(user['id']),'job.dismiss' if body.dismissed else 'job.restore',job_id,details={'reason':body.reason if body.dismissed else None})
    return {'ok':True}


@app.post('/api/jobs/{job_id}/mark-applied')
def mark_applied(job_id:uuid.UUID,user=Depends(current_user)):
    if not set(user['roles']) & {'member','administrator'}: raise HTTPException(403,'Member role required')
    job=job_detail(job_id,user)
    with private_connection(user['id']) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user['id'])+':'+str(job_id),))
        require_active(conn,user['id'],job)
        conn.execute("INSERT INTO jobsearch.saved_jobs(user_id,job_id,stage) VALUES(%s,%s,'applied') ON CONFLICT(user_id,job_id) DO UPDATE SET stage='applied'",(user['id'],job_id))
        previous=conn.execute('SELECT payload FROM jobsearch.private_applications WHERE user_id=%s AND job_id=%s FOR UPDATE',(user['id'],job_id)).fetchone()
        if previous:
            report=decrypt(user['id'],'application:'+str(job_id),previous['payload'])
            if not report.get('submitted'):
                report['previous_receipt']=report.get('receipt')
                report.update(status='submitted',submitted=True,confirmation_source='user_reported',next_action='Application completion confirmed by you. Do not submit again.',attempt_finished_at=datetime.now(timezone.utc).isoformat())
                report['receipt']={'confirmation_text':'User reported successful application completion.','confirmation_source':'user_reported'}
                conn.execute('UPDATE jobsearch.private_applications SET payload=%s,updated_at=now() WHERE user_id=%s AND job_id=%s',(encrypt(user['id'],'application:'+str(job_id),report),user['id'],job_id))
        conn.execute('DELETE FROM jobsearch.job_dismissals WHERE user_id=%s AND (job_id=%s OR identity=jobsearch.posting_identity(%s))',(user['id'],job_id,job['url']))
        archive_if_emailed(conn,user['id'],job,'applied')
        audit(conn,str(user['id']),'application.user_confirmed',job_id,details={'confirmation_source':'user_reported'})
    return {'ok':True}

class Save(BaseModel):
    saved:bool=True
    stage:Literal['saved','applied','interviewing','offer','closed']='saved'


@app.put('/api/jobs/{job_id}/saved')
def save(job_id:uuid.UUID,body:Save,user=Depends(current_user)):
    if not set(user['roles'])&{'member','administrator'}: raise HTTPException(403,'Member role required')
    job=job_detail(job_id,user)
    with private_connection(user['id']) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user['id'])+':'+str(job_id),))
        require_active(conn,user['id'],job)
        if body.saved:
            conn.execute('INSERT INTO jobsearch.saved_jobs(user_id,job_id,stage) VALUES(%s,%s,%s) ON CONFLICT(user_id,job_id) DO UPDATE SET stage=excluded.stage',(user['id'],job_id,body.stage))
        else: conn.execute('DELETE FROM jobsearch.saved_jobs WHERE user_id=%s AND job_id=%s',(user['id'],job_id))
        if body.saved and body.stage!='saved': archive_if_emailed(conn,user['id'],job,body.stage)
        audit(conn,str(user['id']),'job.save',job_id,details={'saved':body.saved,'stage':body.stage})
    return {'ok':True}


@app.get('/api/sources')
def sources(user=Depends(administrator)):
    # Collection coverage and run counts are administrator information; members, viewers and operators never see them.
    with connection() as conn:
        return conn.execute('SELECT s.*,r.status AS latest_status,r.fetched,r.matched,r.finished_at FROM jobsearch.sources s LEFT JOIN LATERAL (SELECT * FROM jobsearch.runs WHERE source_id=s.id ORDER BY created_at DESC LIMIT 1) r ON true ORDER BY company').fetchall()


class Source(BaseModel):
    company:str=Field(min_length=1,max_length=120)
    provider:Literal['ashby','greenhouse','lever']
    board:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')


@app.post('/api/sources')
def add_source(body:Source,user=Depends(administrator)):
    with connection() as conn:
        row=conn.execute('INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES(%s,%s,%s,true) ON CONFLICT(provider,board) DO UPDATE SET company=excluded.company RETURNING id',(body.company,body.provider,body.board)).fetchone()
        audit(conn,str(user['id']),'source.register',row['id'])
    return row


@app.post('/api/sources/{source_id}/refresh')
def refresh(source_id:int,user=Depends(administrator)):
    with connection() as conn:
        if not conn.execute('SELECT id FROM jobsearch.sources WHERE id=%s AND enabled',(source_id,)).fetchone(): raise HTTPException(404,'Enabled source not found')
        row=enqueue(conn,source_id,str(user['id']))
    return {'queued':bool(row)}


@app.get('/api/runs')
def runs(user=Depends(administrator)):
    with connection() as conn:
        return conn.execute('SELECT r.*,s.company FROM jobsearch.runs r LEFT JOIN jobsearch.sources s ON s.id=r.source_id ORDER BY created_at DESC LIMIT 100').fetchall()


@app.get('/api/audit')
def audit_events(user=Depends(administrator)):
    with connection() as conn:
        return conn.execute('SELECT * FROM jobsearch.audit_events ORDER BY id DESC LIMIT 100').fetchall()


@app.middleware('http')
async def observe(request, call_next):
    # Do not turn every monitoring asset/query into a new Phoenix trace.
    if request.url.path in ('/api/health','/api/session') or request.url.path.startswith(('/api/monitoring/', '/api/monitoring-status/', '/api/observability/', '/api/phoenix-graphql/')):
        return await call_next(request)
    started=time.monotonic()
    with trace.get_tracer('jobsearch').start_as_current_span('http.request',record_exception=False,set_status_on_exception=False) as span:
        response=await call_next(request)
        route=getattr(request.scope.get('route'),'path','unmatched')
        elapsed=time.monotonic()-started
        span.update_name(request.method+' '+route)
        span.set_attribute('http.route',route); span.set_attribute('http.response.status_code',response.status_code)
        HTTP.labels(route,str(response.status_code)).inc(); LATENCY.labels(route).observe(elapsed)
        event('http.completed',route=route,status=response.status_code,duration_seconds=round(elapsed,4))
        return response

@app.get('/api/collection-status')
def collection_status(user=Depends(administrator)):
    from ai_core.agents.scheduler import next_run_at
    with connection() as c:
        sources=c.execute("""SELECT s.company,s.enabled,s.last_success_at,s.last_error,r.status,r.fetched,r.decision_counts,r.trace_id,
         %s::timestamptz AS next_scheduled_at
         FROM jobsearch.sources s LEFT JOIN LATERAL(SELECT * FROM jobsearch.runs WHERE source_id=s.id ORDER BY created_at DESC LIMIT 1) r ON true ORDER BY s.company""",(next_run_at(),)).fetchall()
        matches=c.execute("SELECT count(*) n FROM jobsearch.jobs WHERE availability='observed_open' AND match_status='match'").fetchone()['n']
    return {'sources':sources,'current_matches':matches,'schedule_hours':cfg.schedule_hours,
            'schedule_hour':cfg.schedule_hour,'schedule_timezone':cfg.schedule_timezone}

from src.api.intake import create_router
app.include_router(create_router(current_user))

@app.get('/api/learning')
def learning_settings(user=Depends(administrator)):
    # Learning management is administrator-only. Ranking for every user still reads the model inside /api/jobs.
    with private_connection(user['id']) as c:
        model=learning_model(c,user['id'])
        history=c.execute('SELECT id,created_at,model FROM jobsearch.learning_versions WHERE user_id=%s ORDER BY id DESC LIMIT 20',(user['id'],)).fetchall()
    return {'model':model,'history':[{'id':x['id'],'created_at':x['created_at'],'decisions':x['model']['decisions'],'rules':len(x['model']['rules'])} for x in history]}

class LearningChange(BaseModel):
    action:Literal['pause','resume','reset','restore']
    version:int|None=None

@app.put('/api/learning')
def update_learning(body:LearningChange,user=Depends(administrator)):
    with private_connection(user['id']) as c:configure_learning(c,user['id'],body.action,body.version)
    return {'ok':True}

from src.api.observability import create_router as observability_router
app.include_router(observability_router(administrator))

from src.api.monitoring_ui import create_router as monitoring_ui_router
app.include_router(monitoring_ui_router(administrator))

from src.api.data_quality import create_router as quality_router
app.include_router(quality_router(administrator))

from src.api.data_model import create_router as data_model_router
app.include_router(data_model_router(administrator))

from src.api.analytics import create_router as analytics_router
app.include_router(analytics_router(administrator))

from src.api.admin_console import create_router as admin_console_router
# Web traffic, accounts, conversion and machine load from the shared warehouse and Prometheus.
app.include_router(admin_console_router(administrator))

from src.api.governance import create_router as governance_router
app.include_router(governance_router(administrator))

from src.api.hub_access import create_router as hub_access_router
# Library gateway authorization: the Reader for every verified account, everything else administrators; see hub_access.py.
app.include_router(hub_access_router(current_user))

@app.get('/api/workflow')
def daily_workflow_status(user=Depends(current_user)):
    from src.applications.daily import status
    result=status(user['id'])
    if not is_administrator(user):
        # Per-source collection counts are administrator information; others keep their own preparation progress (the hub reads this).
        for run in [result.get('latest')]+list(result.get('history') or []):
            if isinstance(run,dict): run.pop('source_counts',None)
    return result

from src.api.enquiries import create_router as enquiries_router
app.include_router(enquiries_router())
