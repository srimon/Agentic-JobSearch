from src.applications.archives import archive_for

def dismissal_for(c,user_id,job):
    archived=archive_for(c,user_id,job)
    if archived: return {'reason':archived['final_status']}
    return c.execute("SELECT reason FROM jobsearch.job_dismissals WHERE user_id=%s AND (job_id=%s OR identity=jobsearch.posting_identity(%s)) ORDER BY updated_at DESC LIMIT 1",(user_id,job['id'],job['url'])).fetchone()
