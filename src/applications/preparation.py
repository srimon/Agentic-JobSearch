"""Owner-scoped local preparation shared by the API and daily runner. No external submission."""
from fastapi import HTTPException
from src.applications.archives import require_active
from src.applications.dismissals import dismissal_for
from src.applications.private import encrypt,decrypt
from src.applications.intake_models import Intake,capital_one
from src.applications.assessment import assess
from src.db.store import audit

def prepare_application(c,user_id,job_id,reuse=False):
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user_id)+':'+str(job_id),))
    dismissal_job=c.execute('SELECT id,url FROM jobsearch.jobs WHERE id=%s',(job_id,)).fetchone()
    if dismissal_job: require_active(c,user_id,dismissal_job)
    if dismissal_job and dismissal_for(c,user_id,dismissal_job):
        raise HTTPException(409,'This job is dismissed. Restore it before preparing an application.')
    if c.execute("SELECT 1 FROM jobsearch.saved_jobs WHERE user_id=%s AND job_id=%s AND stage IN ('applied','interviewing','offer','closed')",(user_id,job_id)).fetchone():
        raise HTTPException(409,'Application completion is already recorded; do not prepare again.')
    existing=c.execute('SELECT payload FROM jobsearch.private_applications WHERE user_id=%s AND job_id=%s FOR UPDATE',(user_id,job_id)).fetchone()
    if existing:
        previous=decrypt(user_id,'application:'+str(job_id),existing['payload'])
        if previous.get('submitted') or previous.get('status') in ('submitting','submission_unknown'):
            return previous
    job=c.execute('SELECT * FROM jobsearch.jobs WHERE id=%s',(job_id,)).fetchone()
    if not job: raise HTTPException(404,'Job not found')
    if job['match_status']!='match' or job['country_status'] not in ('us_based','us_remote_eligible') or job['availability']!='observed_open':
        raise HTTPException(409,'Only current matching US listings can enter application preparation')
    variant='capital_one' if capital_one(job['company']) else 'default'
    r=c.execute('SELECT * FROM jobsearch.private_resume WHERE user_id=%s AND variant=%s',(user_id,variant)).fetchone()
    if not r: raise HTTPException(409,'Upload the '+('Capital One' if variant=='capital_one' else 'default')+' resume in Resume & profile first')
    resume=decrypt(user_id,'resume:'+variant,r['payload'])
    row=c.execute('SELECT * FROM jobsearch.private_intake WHERE user_id=%s',(user_id,)).fetchone()
    profile=decrypt(user_id,'profile',row['payload']) if row else Intake().model_dump()
    missing=[k for k in ('full_name','email','phone','location') if not profile[k]]
    missing += [k for k in ('authorized_us','sponsorship') if profile[k]=='unknown']
    if not profile['confirmed']: missing.append('confirmed profile')
    excluded=[x.strip().casefold() for x in profile['excluded_companies'].split(',') if x.strip()]
    if job['company'].casefold() in excluded: raise HTTPException(409,'Employer is excluded by your profile')
    if reuse and existing and previous.get('resume_version')==str(r['version']) and previous.get('profile_version')==(str(row['version']) if row else None) and previous.get('job_hash')==job['content_hash']:
        return previous
    report=assess(resume['text'],job)
    status='needs_information' if missing else 'needs_site_access'
    if report.get('blocked'): status='content_review'
    result={'job_id':str(job_id),'title':job['title'],'company':job['company'],'url':job['url'],
            'resume_variant':variant,'resume_filename':resume['filename'],'resume_version':str(r['version']),
            'profile_version':str(row['version']) if row else None,'job_hash':job['content_hash'],
            'missing_fields':missing,'assessment':report,'status':status,'submitted':False,
            'next_action':'Complete missing profile fields, review the requirements, and use the employer application form. Direct submission access is not configured.'}
    c.execute('INSERT INTO jobsearch.private_applications(user_id,job_id,payload) VALUES(%s,%s,%s) ON CONFLICT(user_id,job_id) DO UPDATE SET payload=excluded.payload,updated_at=now()',
              (user_id,job_id,encrypt(user_id,'application:'+str(job_id),result)))
    audit(c,str(user_id),'application.checked',job_id,details={'status':status})
    return result
