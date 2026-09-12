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
from opentelemetry import trace
from psycopg.types.json import Jsonb
from ai_core.agents.researcher import collect
from src.db.store import connection, audit
from src.pipelines.classification import classify
from src.settings import settings


def enqueue(conn, source_id, actor):
    source=conn.execute('SELECT provider FROM jobsearch.sources WHERE id=%s FOR UPDATE',(source_id,)).fetchone()
    cooldown={'remotive':6,'jobicy':1}.get(source['provider'],0) if source else 0
    if cooldown and conn.execute("SELECT 1 FROM jobsearch.runs WHERE source_id=%s AND created_at>now()-(%s * interval '1 hour') LIMIT 1",(source_id,cooldown)).fetchone():
        return None
    run_id=uuid.uuid4()
    row=conn.execute("INSERT INTO jobsearch.runs(id,source_id,status,requested_by) VALUES(%s,%s,'queued',%s) ON CONFLICT DO NOTHING RETURNING id",
                     (run_id,source_id,actor)).fetchone()
    if row: audit(conn,actor,'source.refresh.requested',source_id,details={'run_id':str(run_id)})
    return row


def run_one():
    # Session advisory lock prevents overlapping workers and permits crash recovery.
    with connection() as lock:
        if not lock.execute('SELECT pg_try_advisory_lock(74190315) AS acquired').fetchone()['acquired']: return False
        try:
            with connection() as conn:
                conn.execute("UPDATE jobsearch.runs SET status='failed',finished_at=now(),error='Worker interrupted; retry allowed' WHERE status='running'")
                run=conn.execute("SELECT r.*,s.company,s.provider,s.board,s.enabled FROM jobsearch.runs r JOIN jobsearch.sources s ON s.id=r.source_id WHERE r.status='queued' ORDER BY r.created_at FOR UPDATE OF r SKIP LOCKED LIMIT 1").fetchone()
                if not run: return False
                if not run['enabled']:
                    conn.execute("UPDATE jobsearch.runs SET status='failed',finished_at=now(),error='Source disabled' WHERE id=%s",(run['id'],)); return True
                conn.execute("UPDATE jobsearch.runs SET status='running',started_at=now() WHERE id=%s",(run['id'],))
                audit(conn,'collector','tool.fetch.start',run['source_id'],details={'run_id':str(run['id'])})
            try:
                with collection_span(run) as span:
                    jobs=collect(run)
                    run_trace_id=format(span.get_span_context().trace_id,'032x')
                decisions=Counter()
                seen=set()
                count=0
                with connection() as conn:
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
                    conn.execute("UPDATE jobsearch.runs SET status='completed',finished_at=now(),fetched=%s,matched=%s WHERE id=%s",(len(jobs),count,run['id']))
                    conn.execute('UPDATE jobsearch.runs SET decision_counts=%s,trace_id=%s WHERE id=%s',(Jsonb(dict(decisions)),run_trace_id,run['id']))
                    conn.execute('UPDATE jobsearch.sources SET last_success_at=now(),last_error=NULL WHERE id=%s',(run['source_id'],))
                    audit(conn,'collector','tool.fetch.complete',run['source_id'],details={'run_id':str(run['id']),'fetched':len(jobs),'candidates':count})
                RUNS.labels(run['provider'],'completed').inc()
                for decision,n in decisions.items(): DECISIONS.labels(decision).inc(n)
                event('collection.completed',run_id=str(run['id']),source_id=run['source_id'],fetched=len(jobs),accepted=decisions['match'])
            except Exception as error:
                with connection() as conn:
                    # Do not persist arbitrary upstream text, credentials or body fragments.
                    kind=type(error).__name__
                    conn.execute("UPDATE jobsearch.runs SET status='failed',finished_at=now(),error=%s WHERE id=%s",(kind,run['id']))
                    conn.execute('UPDATE jobsearch.sources SET last_error=%s WHERE id=%s',(kind,run['source_id']))
                    audit(conn,'collector','tool.fetch.failed',run['source_id'],'error',{'run_id':str(run['id']),'error_class':kind})
                RUNS.labels(run['provider'],'failed').inc()
                event('collection.failed',run_id=str(run['id']),source_id=run['source_id'],error_class=kind)
            return True
        finally:
            lock.execute('SELECT pg_advisory_unlock(74190315)')


def schedule():
    with connection() as conn:
        rows=conn.execute("SELECT s.id FROM jobsearch.sources s WHERE s.enabled AND NOT EXISTS(SELECT 1 FROM jobsearch.runs r WHERE r.source_id=s.id AND r.created_at > now()-(%s * interval '1 hour'))",(settings().schedule_hours,)).fetchall()
        for row in rows: enqueue(conn,row['id'],'scheduler')


if __name__=='__main__':
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    setup('jobsearch-worker')
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    while not stop.is_set():
        Path('/tmp/jobsearch-worker-heartbeat').touch()
        HEARTBEAT.set(time.time())
        schedule()
        while not stop.is_set() and run_one():
            Path('/tmp/jobsearch-worker-heartbeat').touch()
        if args.once: break
        stop.wait(30)
