"""Durable PostgreSQL queue and idempotent source refresh worker."""
import argparse
import signal
import threading
import hashlib
import json
import time
import uuid
from pathlib import Path
from collections import Counter
from src.observability import setup,event,collection_span,RUNS,DECISIONS,HEARTBEAT
import os
import socket
from ai_core.agents.leases import claim, heartbeat, require_lease, fail, LeaseLost
from psycopg.types.json import Jsonb
from ai_core.agents.researcher import collect
from src.db.store import connection, audit
from src.pipelines.classification import classify
from src.settings import settings


def enqueue(conn, source_id, actor):
    source=conn.execute('SELECT provider,enabled FROM jobsearch.sources WHERE id=%s FOR UPDATE',(source_id,)).fetchone()
    if not source or not source['enabled']: return None
    cooldown={'remotive':6,'jobicy':1}.get(source['provider'],0) if source else 0
    if cooldown and conn.execute("SELECT 1 FROM jobsearch.runs WHERE source_id=%s AND created_at>now()-(%s * interval '1 hour') LIMIT 1",(source_id,cooldown)).fetchone():
        return None
    run_id=uuid.uuid4()
    row=conn.execute("INSERT INTO jobsearch.runs(id,source_id,status,requested_by) VALUES(%s,%s,'queued',%s) ON CONFLICT DO NOTHING RETURNING id",
                     (run_id,source_id,actor)).fetchone()
    if row: audit(conn,actor,'source.refresh.requested',source_id,details={'run_id':str(run_id)})
    return row


def run_one(worker_id=None):
    worker_id=worker_id or (socket.gethostname()+':'+str(os.getpid()))
    with claim(worker_id) as run:
        if run is None: return False
        with heartbeat(run) as lost:
            try:
                with collection_span(run) as span:
                    jobs=collect(run)
                    run_trace_id=format(span.get_span_context().trace_id,'032x')
                if lost.is_set(): raise LeaseLost()
                decisions=Counter()
                seen=set()
                count=0
                with connection() as conn:
                    require_lease(conn, run)
                    for raw in jobs:
                        key=raw['source_job_id']
                        if key in seen:
                            decisions['duplicate']+=1
                            continue
                        seen.add(key)
                        job=classify(raw)
                        bucket=job['match_status']
                        if bucket=='exclude':
                            bucket='sensitive_content' if job.get('reason')=='Sensitive content rejected' else ('outside_us' if job.get('country_status')=='outside_us' else 'outside_role')
                        elif bucket=='review':
                            bucket='guardrail_review' if job.get('reason','').startswith('Content quarantined') else ('unknown_location' if job.get('country_status')=='unknown' else 'title_review')
                        decisions[bucket]+=1
                        if job['match_status']=='exclude': continue
                        count+=1
                        job_id=uuid.uuid5(uuid.NAMESPACE_URL,f'{run["source_id"]}:{job["source_job_id"]}')
                        digest=hashlib.sha256(json.dumps(job,sort_keys=True,default=str).encode()).hexdigest()
                        fields=['source_job_id','company','title','location','work_mode','country_status','level','match_status','reason','description','url','posted_at']
                        conn.execute('INSERT INTO jobsearch.jobs(id,source_id,'+','.join(fields)+',content_hash,evidence) VALUES('+','.join(['%s']*16)+") ON CONFLICT(source_id,source_job_id) DO UPDATE SET "+','.join(f'{x}=excluded.{x}' for x in fields[1:])+",content_hash=excluded.content_hash,evidence=excluded.evidence,last_seen_at=now(),availability='observed_open'",
                            [job_id,run['source_id']]+[job[x] for x in fields]+[digest,Jsonb(job['evidence'])])
                        conn.execute('INSERT INTO jobsearch.observations(job_id,run_id,content_hash,evidence) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(job_id,run['id'],digest,Jsonb(job['evidence'])))
                    conn.execute("UPDATE jobsearch.jobs SET availability='not_observed' WHERE source_id=%s AND last_seen_at < %s",(run['source_id'],run['created_at']))
                    conn.execute("UPDATE jobsearch.runs SET status='completed',finished_at=now(),lease_token=NULL,lease_expires_at=NULL,fetched=%s,matched=%s WHERE id=%s",(len(jobs),count,run['id']))
                    conn.execute('UPDATE jobsearch.runs SET decision_counts=%s,trace_id=%s WHERE id=%s',(Jsonb(dict(decisions)),run_trace_id,run['id']))
                    conn.execute('UPDATE jobsearch.sources SET last_success_at=now(),last_error=NULL WHERE id=%s',(run['source_id'],))
                    audit(conn,'collector','tool.fetch.complete',run['source_id'],details={'run_id':str(run['id']),'fetched':len(jobs),'candidates':count})
                RUNS.labels(run['provider'],'completed').inc()
                for decision,n in decisions.items(): DECISIONS.labels(decision).inc(n)
                event('collection.completed',run_id=str(run['id']),source_id=run['source_id'],fetched=len(jobs),accepted=decisions['match'])

            except LeaseLost:
                event('collection.lease_lost',run_id=str(run['id']),source_id=run['source_id'])
            except Exception as error:
                kind=type(error).__name__
                try:
                    fail(run,kind)
                except LeaseLost:
                    event('collection.lease_lost',run_id=str(run['id']),source_id=run['source_id'])
                else:
                    RUNS.labels(run['provider'],'failed').inc()
                    event('collection.failed',run_id=str(run['id']),source_id=run['source_id'],error_class=kind)
    return True


def main():
    stop=threading.Event()
    shutdown_timer=None
    def shutdown(*_):
        nonlocal shutdown_timer
        if not stop.is_set():
            stop.set()
            shutdown_timer=threading.Timer(settings().worker_shutdown_seconds,lambda:os._exit(143))
            shutdown_timer.daemon=True
            shutdown_timer.start()
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    setup('jobsearch-worker')
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    try:
        while not stop.is_set():
            deadline=threading.Timer(settings().worker_max_run_seconds,lambda:os._exit(1))
            deadline.daemon=True
            deadline.start()
            try:
                worked=run_one()
                Path('/tmp/jobsearch-worker-heartbeat').touch()
                HEARTBEAT.set(time.time())
            except Exception as error:
                event('worker.failed',error_class=type(error).__name__)
                if args.once: return 1
                worked=False
            finally:
                deadline.cancel()
            if args.once: break
            if not worked: stop.wait(30)
    finally:
        if shutdown_timer: shutdown_timer.cancel()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
