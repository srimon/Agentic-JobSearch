"""Deterministic local preparation and daily reporting. Never contacts employers."""
import hashlib
import os
import time
from collections import Counter
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from src.db.store import connection,audit
from src.settings import settings
from src.applications.private import private_connection,decrypt
from src.applications.preparation import prepare_application
from src.applications.learning import current,ranking_sql
from src.applications.delivery_state import exclusive,read_json,atomic_json,journal_states,require_known_deliveries
from src.applications.reporting import require_app_role,export_rows,record_report_data

PUBLIC_FIELDS={'day','phase','updated_at','started_at','source_counts','counts','reason','error_class','delivery','next_run_at'}

def now_utc():return datetime.now(timezone.utc)

def boundary(now):
    local=now.astimezone(ZoneInfo(settings().schedule_timezone))
    return local.replace(hour=settings().schedule_hour,minute=0,second=0,microsecond=0)

def next_run(now):
    start=boundary(now)
    return (start if now<start else start+timedelta(days=1)).astimezone(timezone.utc).isoformat()

def owner_id():
    require_app_role()
    with connection() as c:
        row=c.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject='admin' AND active AND 'administrator'=ANY(roles)").fetchone()
    if not row:raise RuntimeError('Active report owner unavailable')
    return row['id']

def collection(start):
    with connection() as c:
        c.execute('SET LOCAL transaction_read_only=on')
        rows=c.execute("""SELECT s.id,r.status,r.error FROM jobsearch.sources s
          LEFT JOIN LATERAL (SELECT status,error FROM jobsearch.runs WHERE source_id=s.id AND created_at>=%s
            ORDER BY created_at DESC,id DESC LIMIT 1) r ON true WHERE s.enabled""",(start,)).fetchall()
        active=c.execute("SELECT count(*) n FROM jobsearch.runs WHERE status IN ('queued','running')").fetchone()['n']
    counts={state:sum(r['status']==state for r in rows) for state in ('completed','failed','queued','running')}
    counts.update(enabled=len(rows),missing=sum(r['status'] is None for r in rows),active=active)
    return counts

def complete(counts):return counts['enabled']>0 and counts['missing']==0 and counts['active']==0

def selected_jobs(uid,limit=100):
    if not 1<=limit<=250:raise ValueError('Invalid preparation limit')
    with private_connection(uid) as c:
        score,params=ranking_sql(current(c,uid))
        rows=c.execute("""SELECT j.id,j.company,j.title,j.url,canonical.identity,"""+score+""" AS score
          FROM jobsearch.jobs j CROSS JOIN LATERAL (SELECT jobsearch.posting_identity(j.url) identity OFFSET 0) canonical
          WHERE j.match_status='match' AND j.country_status IN ('us_based','us_remote_eligible') AND j.availability='observed_open'
          AND NOT EXISTS(SELECT 1 FROM jobsearch.job_archives a WHERE a.user_id=%s AND a.identity=canonical.identity)
          AND NOT EXISTS(SELECT 1 FROM jobsearch.job_dismissals d WHERE d.user_id=%s AND (d.job_id=j.id OR d.identity=canonical.identity))
          AND NOT EXISTS(SELECT 1 FROM jobsearch.saved_jobs s JOIN jobsearch.jobs other ON other.id=s.job_id
            WHERE s.user_id=%s AND s.stage IN ('applied','interviewing','offer','closed') AND jobsearch.posting_identity(other.url)=canonical.identity)
          ORDER BY score DESC,j.posted_at DESC NULLS LAST,j.id LIMIT 1000""",params+[uid,uid,uid]).fetchall()
        locked=set()
        for row in c.execute('SELECT a.job_id,a.payload,jobsearch.posting_identity(j.url) identity FROM jobsearch.private_applications a JOIN jobsearch.jobs j ON j.id=a.job_id WHERE a.user_id=%s',(uid,)).fetchall():
            value=decrypt(uid,'application:'+str(row['job_id']),row['payload'])
            if value.get('submitted') or value.get('status') in ('submitted','submitting','submission_unknown'):
                locked.add(row['identity'])
    seen=set(locked);result=[]
    for row in rows:
        if row['identity'] in seen:continue
        seen.add(row['identity']);result.append(row)
    return result[:limit],len(result)>limit or len(rows)==1000

def prepare(uid,limit=100):
    jobs,capped=selected_jobs(uid,limit);counts=Counter();blockers=[]
    for job in jobs:
        try:
            with private_connection(uid) as c:
                result=prepare_application(c,uid,job['id'],reuse=True)
            counts[result['status']]+=1
        except HTTPException as error:
            if error.status_code not in (404,409):raise
            counts['blocked']+=1
            # Error details come only from fixed local guards, never source responses.
            if str(error.detail).startswith('Upload the '):
                blockers.append({**{k:str(job[k]) for k in ('company','title','url')},
                    'job_id':str(job['id']),'status':'needs_information','submitted':False,'next_action':str(error.detail)})
    counts.update({'reviewed':len(jobs),'capped':int(capped)})
    return dict(counts),blockers

def public_record(record):return {k:record[k] for k in PUBLIC_FIELDS if k in record}

def publish(uid,record):
    with connection() as c:audit(c,'daily-workflow','workflow.progress',uid,details=public_record(record))

def status(uid):
    with connection() as c:
        rows=c.execute("SELECT details FROM jobsearch.audit_events WHERE actor='daily-workflow' AND action='workflow.progress' AND resource=%s ORDER BY id DESC LIMIT 30",(str(uid),)).fetchall()
    return {'next_run_at':next_run(now_utc()),'schedule':'08:00 America/Los_Angeles',
            'latest':public_record(rows[0]['details']) if rows else None,
            'history':[public_record(r['details']) for r in rows]}

def reconcile(entries,journal):
    states=journal_states(journal)
    for entry in entries.values():
        if entry.get('phase') not in ('sending','blocked') or not entry.get('report_hash'):continue
        if states.get(entry['report_hash'])=='smtp_accepted':
            record_report_data({'report_hash':entry['report_hash'],'job_ids':entry['job_ids'],'accepted':True})
            entry.update(phase='completed',delivery='smtp_accepted',requires_reconciliation=False,
                         reason='Accepted report history reconciled without resending.')
    if any(e.get('requires_reconciliation') or e.get('phase')=='sending' for e in entries.values()):
        raise RuntimeError('A previous daily dispatch requires reconciliation.')
    require_known_deliveries(journal)

def run(directory,*,check=False,wait_seconds=3600,poll_seconds=30,limit=100):
    config=read_json(directory/'daily-owner.json')
    if not config or config.get('owner')!='kubernetes' or config.get('version')!=1:
        raise RuntimeError('Daily workflow ownership has not been activated.')
    if not (directory/'daily-workflow.json').is_file() or not (directory/'email-delivery.jsonl').is_file():
        raise RuntimeError('Required persistent workflow or SMTP journal is missing; restore and reconcile before dispatch.')
    uid=owner_id();now=now_utc();start=boundary(now);day=start.date().isoformat()
    if check:
        return {'ownership':'kubernetes','next_run_at':next_run(now),'collection':collection(start),
                'days':{d:public_record(e) for d,e in read_json(directory/'daily-workflow.json',{}).items()}}
    if now<start or now<datetime.fromisoformat(config['not_before']) or now>start+timedelta(hours=1):
        return {'phase':'outside_start_window','next_run_at':next_run(now)}
    with exclusive(directory,'daily-workflow.lock'):
        entries=read_json(directory/'daily-workflow.json',{});journal=directory/'email-delivery.jsonl'
        reconcile(entries,journal)
        atomic_json(directory/'daily-workflow.json',entries)
        if entries.get(day,{}).get('phase')=='completed':
            publish(uid,entries[day]);return public_record(entries[day])
        record={'day':day,'phase':'waiting','started_at':now.isoformat(),'updated_at':now.isoformat(),'next_run_at':next_run(now)}
        def save(**values):
            record.update(values,updated_at=now_utc().isoformat());entries[day]=record
            atomic_json(directory/'daily-workflow.json',entries);publish(uid,record)
        save(reason='Waiting for enabled source collection to finish.')
        try:
            deadline=time.monotonic()+wait_seconds
            while True:
                counts=collection(start);save(source_counts=counts)
                if complete(counts):break
                if time.monotonic()>=deadline:raise RuntimeError('Collection did not finish before the workflow deadline.')
                time.sleep(poll_seconds)
            save(phase='preparing',reason='Checking current jobs against saved resumes and intake.')
            prepared,blockers=prepare(uid,limit)
            from scripts import email_report as email
            # Only whitelisted public listing fields and status metadata enter the report.
            rows=[r for r in export_rows() if not r.get('dismissal_reason')]
            ids={r['job_id'] for r in rows if r.get('job_id')}
            with private_connection(uid) as c:
                for row in blockers:
                    from src.applications.archives import archive_for
                    from src.applications.dismissals import dismissal_for
                    if row['job_id'] not in ids and not archive_for(c,uid,row) and not dismissal_for(c,uid,{'id':row['job_id'],'url':row['url']}):
                        rows.append(row);ids.add(row['job_id'])
            summary={'jobs':[f"Reviewed {prepared.get('reviewed',0)} eligible listings; bounded batch capped: {bool(prepared.get('capped'))}."],
                'sources':[f"{counts['completed']} completed; {counts['failed']} failed. No new source was enabled by this workflow."],
                'applications':[f"Local preparation outcomes: {json_counts(prepared)}. No employer submissions were attempted."],
                'failures':[f"{counts['failed']} source runs failed; inspect collection runs for recorded error classes."] if counts['failed'] else []}
            atomic_json(directory/'scheduled-run-summary.json',summary)
            body='Daily workflow: '+day+' America/Los_Angeles\n\n'+email.scheduled_body(email.render(rows))
            digest=hashlib.sha256((email.ADDRESS+'\n'+body).encode()).hexdigest()
            password=email.load_password()
            if password is None:raise RuntimeError('Report credential is unavailable.')
            # Durable intent precedes SMTP; interruption cannot create another daily sender.
            save(phase='sending',counts=prepared,report_hash=digest,job_ids=sorted(ids),requires_reconciliation=True,reason='Submitting report to SMTP.')
            email.send_tracked(body,rows,password,journal)
            password=None
            save(phase='completed',delivery='smtp_accepted',requires_reconciliation=False,reason='SMTP accepted the report; inbox delivery is not independently verified.')
            return public_record(record)
        except Exception as error:
            ambiguous=record.get('phase')=='sending'
            save(phase='blocked' if ambiguous else 'failed',requires_reconciliation=ambiguous,
                 error_class=type(error).__name__,reason='Inspect the delivery journal before retrying.' if ambiguous else 'Workflow stopped before email dispatch; inspect phase and collection status.')
            raise

def json_counts(counts):
    return ', '.join(f'{key}={value}' for key,value in sorted(counts.items()) if key not in ('reviewed','capped')) or 'none'
