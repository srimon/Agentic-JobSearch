"""Trusted report-worker database operations; no Docker, HTTP endpoint or SMTP."""
import re
import uuid
from src.db.store import connection
from src.applications.private import private_connection,decrypt
from src.applications.dismissals import dismissal_for
from src.applications.archives import archive_for
from src.applications.learning import current,explain
from src.applications.email_history import record_report
from urllib.parse import urlsplit
from src.settings import settings


def require_app_role():
    if urlsplit(settings().database_url).username != "jobsearch_app":
        raise RuntimeError("Direct reporting requires the scoped jobsearch_app database role")


def export_rows():
    require_app_role()
    with connection() as c:
     u=c.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject=%s AND active",(settings().owner_username,)).fetchone()
     if not u: raise RuntimeError('Active owner missing')
    with private_connection(u['id']) as c:
     model=current(c,u['id'])
     rows=c.execute('SELECT job_id,payload FROM jobsearch.private_applications WHERE user_id=%s ORDER BY job_id',(u['id'],)).fetchall()
     out=[]
     for row in rows:
      p=decrypt(u['id'],'application:'+str(row['job_id']),row['payload'])
      job=c.execute('SELECT id,url,title,level,work_mode,source_id FROM jobsearch.jobs WHERE id=%s',(row['job_id'],)).fetchone()
      if job and archive_for(c,u['id'],job): continue
      dismissed=dismissal_for(c,u['id'],job) if job else None
      ranking=explain(job,model) if job else {'adjustment':0,'reasons':[]}
      p['learning_adjustment']=ranking['adjustment'];p['learning_reasons']=ranking['reasons']
      p['job_id']=str(row['job_id'])
      p['dismissal_reason']=dismissed['reason'] if dismissed else None
      out.append({k:p.get(k) for k in ('job_id','company','title','status','submitted','attempt_finished_at','next_action','url','dismissal_reason','confirmation_source','learning_adjustment','learning_reasons')})
     for row in c.execute("SELECT j.id::text AS job_id,j.company,j.title,j.url FROM jobsearch.saved_jobs s JOIN jobsearch.jobs j ON j.id=s.job_id WHERE s.user_id=%s AND s.stage IN ('applied','interviewing','offer','closed') AND NOT EXISTS(SELECT 1 FROM jobsearch.private_applications a WHERE a.user_id=s.user_id AND a.job_id=s.job_id)",(u['id'],)).fetchall():
      if archive_for(c,u['id'],row): continue
      out.append({**dict(row),'status':'submitted','submitted':True,'confirmation_source':'user_reported','next_action':'Application stage tracked by you. Do not submit again.'})
     out.sort(key=lambda row:-(row.get('learning_adjustment') or 0))
     return out


def record_report_data(data):
    require_app_role()
    if not isinstance(data.get("accepted"), bool):
        raise ValueError("accepted must be a boolean")
    if not re.fullmatch('[0-9a-f]{64}',data['report_hash']): raise ValueError('Invalid report identity')
    ids=[str(uuid.UUID(x)) for x in data['job_ids']]
    with connection() as c:
     u=c.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject=%s AND active",(settings().owner_username,)).fetchone()
    if not u: raise RuntimeError('Active owner missing')
    with private_connection(u['id']) as c:
     record_report(c,u['id'],data['report_hash'],ids,accepted=data['accepted'])
