from fastapi import HTTPException
from src.db.store import audit

def archive_for(c,user_id,job):
    return c.execute("SELECT final_status,archived_at FROM jobsearch.job_archives WHERE user_id=%s AND identity=jobsearch.posting_identity(%s)",(user_id,job['url'])).fetchone()

def require_active(c,user_id,job):
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s || jobsearch.posting_identity(%s),0))",(str(user_id)+':archive:',job['url']))
    if archive_for(c,user_id,job): raise HTTPException(409,'This job is archived. Its final status is locked.')

def archive_if_emailed(c,user_id,job,status,feedback_reason=None):
    if c.execute("SELECT 1 FROM jobsearch.emailed_jobs e JOIN jobsearch.jobs j ON j.id=e.job_id WHERE e.user_id=%s AND e.emailed_at IS NOT NULL AND jobsearch.posting_identity(j.url)=jobsearch.posting_identity(%s) LIMIT 1",(user_id,job['url'])).fetchone():
        c.execute("INSERT INTO jobsearch.job_archives(user_id,identity,job_id,final_status,feedback_reason) VALUES(%s,jobsearch.posting_identity(%s),%s,%s,%s)",(user_id,job['url'],job['id'],status,feedback_reason if status=='not_relevant' else None))
        audit(c,str(user_id),'job.archived',job['id'],details={'final_status':status})
