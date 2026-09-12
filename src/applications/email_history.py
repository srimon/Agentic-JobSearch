"""Durable report membership; prepared reports are not shown as emailed."""
from src.db.store import audit

def record_report(c,user_id,report_hash,job_ids,accepted=False):
    for job_id in set(job_ids):
        c.execute("INSERT INTO jobsearch.emailed_jobs(user_id,report_hash,job_id) SELECT %s,%s,id FROM jobsearch.jobs WHERE id=%s ON CONFLICT DO NOTHING",(user_id,report_hash,job_id))
    if accepted:
        c.execute('UPDATE jobsearch.emailed_jobs SET emailed_at=coalesce(emailed_at,now()) WHERE user_id=%s AND report_hash=%s',(user_id,report_hash))
    audit(c,str(user_id),'email.report.accepted' if accepted else 'email.report.prepared',report_hash,details={'job_count':len(set(job_ids))})
