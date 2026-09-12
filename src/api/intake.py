from src.applications.archives import require_active
from src.applications.dismissals import dismissal_for
import asyncio
import base64
import hashlib
import re
import subprocess
import sys
import threading
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.applications.private import private_connection, encrypt, decrypt
from src.applications.assessment import assess
from src.applications.resume_fields import linkedin_links
from src.applications.parse_resume import MAX_BYTES
from src.db.store import audit
from src.guardrails.content import findings, safe_link

Variant=Literal['default','capital_one']
PARSER_SLOTS=threading.BoundedSemaphore(2)

class Demographics(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    race_ethnicity:str=Field('',max_length=240)
    gender_sex:str=Field('',max_length=120)
    pronouns:str=Field('',max_length=120)
    gender_identity:str=Field('',max_length=120)
    sexual_orientation:str=Field('',max_length=120)
    veteran_status:Literal['not_provided','protected_veteran','not_protected_veteran','prefer_not_to_disclose']='not_provided'
    disability_status:Literal['not_provided','yes','no','prefer_not_to_disclose']='not_provided'
    use_for_applications:bool=False

class Intake(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    full_name:str=Field('',max_length=160)
    email:str=Field('',max_length=254)
    phone:str=Field('',max_length=40)
    location:str=Field('',max_length=160)
    linkedin_url:str=Field('',max_length=400)
    portfolio_url:str=Field('',max_length=400)
    authorized_us:Literal['unknown','yes','no']='unknown'
    sponsorship:Literal['unknown','yes','no']='unknown'
    relocate:Literal['unknown','yes','no']='unknown'
    workplace:list[Literal['Remote','Hybrid','On-site']]=Field(default_factory=list,max_length=3)
    desired_base_usd:int|None=Field(None,ge=0,le=10000000)
    notice_period:str=Field('',max_length=160)
    excluded_companies:str=Field('',max_length=1000)
    demographics:Demographics=Field(default_factory=Demographics)
    confirmed:bool=False

    @field_validator('email')
    @classmethod
    def valid_email(cls,value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value): raise ValueError('Invalid email')
        return value

    @field_validator('linkedin_url','portfolio_url')
    @classmethod
    def valid_url(cls,value):
        if value and not safe_link(value): raise ValueError('HTTPS URL required')
        return value

def capital_one(company):
    name=re.sub(r'[^a-z0-9]+',' ',company.lower()).strip()
    return name in {'capital one','capital one financial','capital one financial corporation','capital one financial corp','capital one services','capital one services llc','capital one national association'}

def parse_upload(raw,extension):
    if not PARSER_SLOTS.acquire(blocking=False): raise HTTPException(429,'Resume parser busy. Try again shortly.')
    try:
        p=subprocess.run([sys.executable,'-m','src.applications.parse_resume',extension],input=raw,
                         stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12)
        if p.returncode: raise HTTPException(422,'Unable to read this file safely. Use a text PDF, DOCX or UTF-8 TXT resume; scanned, protected or active documents are not supported.')
        text=p.stdout.decode('utf-8')
        if findings(text): raise HTTPException(422,'Resume contains content requiring review. Remove embedded credentials or instruction-like content before upload.')
        return text
    except subprocess.TimeoutExpired:
        raise HTTPException(422,'Resume parsing exceeded the limit. Try a simpler document.')
    finally: PARSER_SLOTS.release()

def store_resume(c,user_id,variant,raw,extension,text,filename):
    version=uuid.uuid4()
    payload={'filename':filename,'extension':extension,'text':text,'data':base64.b64encode(raw).decode(),
             'sha256':hashlib.sha256(raw).hexdigest()}
    c.execute('INSERT INTO jobsearch.private_resume(user_id,variant,payload,version) VALUES(%s,%s,%s,%s) ON CONFLICT(user_id,variant) DO UPDATE SET payload=excluded.payload,version=excluded.version,updated_at=now()',
              (user_id,variant,encrypt(user_id,'resume:'+variant,payload),version))
    audit(c,str(user_id),'resume.updated',variant)
    return {'filename':filename,'version':str(version),'characters':len(text)}

def create_router(current_user):
    router=APIRouter(prefix='/api')

    def member(user=Depends(current_user)):
        if not set(user['roles'])&{'member','administrator'}: raise HTTPException(403,'Member role required')
        return user

    @router.get('/intake')
    def get_intake(user=Depends(member)):
        with private_connection(user['id']) as c:
            row=c.execute('SELECT * FROM jobsearch.private_intake WHERE user_id=%s',(user['id'],)).fetchone()
            resumes=[]
            links=set()
            for r in c.execute('SELECT * FROM jobsearch.private_resume WHERE user_id=%s',(user['id'],)).fetchall():
                value=decrypt(user['id'],'resume:'+r['variant'],r['payload'])
                links.update(linkedin_links(value['text']))
                resumes.append({'variant':r['variant'],'filename':value['filename'],'version':str(r['version']),'characters':len(value['text'])})
            return {'profile':Intake.model_validate(decrypt(user['id'],'profile',row['payload'])).model_dump() if row else Intake().model_dump(),
                    'resumes':resumes,'linkedin_suggestions':sorted(links),'version':str(row['version']) if row else None}

    @router.put('/intake')
    def put_intake(body:Intake,user=Depends(member)):
        if re.search(r'\b\d{3}-\d{2}-\d{4}\b',body.model_dump_json()): raise HTTPException(422,'Do not store Social Security numbers in the intake.')
        if findings(body.model_dump_json()): raise HTTPException(422,'Content requires review; do not include credentials or agent instructions.')
        with private_connection(user['id']) as c:
            c.execute('INSERT INTO jobsearch.private_intake(user_id,payload,version) VALUES(%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload,version=excluded.version,updated_at=now()',
                      (user['id'],encrypt(user['id'],'profile',body.model_dump()),uuid.uuid4()))
            audit(c,str(user['id']),'intake.updated','own_profile')
        return {'ok':True}

    @router.put('/intake/resume/{variant}')
    async def upload(variant:Variant,request:Request,user=Depends(member)):
        extension=request.headers.get('x-resume-format','').lower()
        if extension not in ('pdf','docx','txt'): raise HTTPException(415,'Use PDF, DOCX or TXT')
        filename=request.headers.get('x-resume-name','resume.'+extension)
        if not re.fullmatch(r'[A-Za-z0-9_. -]{1,120}',filename) or not filename.lower().endswith('.'+extension):
            raise HTTPException(422,'Use a simple filename ending in the selected format')
        raw=await request.body()
        if len(raw)>MAX_BYTES: raise HTTPException(413,'Resume exceeds 5 MiB')
        text=await asyncio.to_thread(parse_upload,raw,extension)
        with private_connection(user['id']) as c:
            return store_resume(c,user['id'],variant,raw,extension,text,filename)

    @router.get('/intake/resume/{variant}')
    def resume(variant:Variant,download:bool=False,user=Depends(member)):
        with private_connection(user['id']) as c:
            row=c.execute('SELECT payload FROM jobsearch.private_resume WHERE user_id=%s AND variant=%s',(user['id'],variant)).fetchone()
            if not row: raise HTTPException(404,'Resume not uploaded')
            value=decrypt(user['id'],'resume:'+variant,row['payload'])
            if download:
                audit(c,str(user['id']),'resume.downloaded',variant)
                return Response(base64.b64decode(value['data']),media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{value["filename"]}"'})
            return {'filename':value['filename'],'text':value['text']}

    @router.delete('/intake/resume/{variant}')
    def delete_resume(variant:Variant,user=Depends(member)):
        with private_connection(user['id']) as c:
            c.execute('DELETE FROM jobsearch.private_resume WHERE user_id=%s AND variant=%s',(user['id'],variant))
            c.execute('DELETE FROM jobsearch.private_applications WHERE user_id=%s',(user['id'],))
            audit(c,str(user['id']),'resume.deleted',variant)
        return {'ok':True}

    @router.delete('/intake')
    def delete_intake(user=Depends(member)):
        with private_connection(user['id']) as c:
            for table in ('private_intake','private_resume','private_applications'):
                c.execute('DELETE FROM jobsearch.'+table+' WHERE user_id=%s',(user['id'],))
            audit(c,str(user['id']),'intake.deleted','own_profile_and_resumes')
        return {'ok':True}

    @router.post('/jobs/{job_id}/application-check')
    def check(job_id:uuid.UUID,user=Depends(member)):
        with private_connection(user['id']) as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user['id'])+':'+str(job_id),))
            dismissal_job=c.execute('SELECT id,url FROM jobsearch.jobs WHERE id=%s',(job_id,)).fetchone()
            if dismissal_job: require_active(c,user['id'],dismissal_job)
            if dismissal_job and dismissal_for(c,user['id'],dismissal_job):
                raise HTTPException(409,'This job is dismissed. Restore it before preparing an application.')
            existing=c.execute('SELECT payload FROM jobsearch.private_applications WHERE user_id=%s AND job_id=%s FOR UPDATE',(user['id'],job_id)).fetchone()
            if existing:
                previous=decrypt(user['id'],'application:'+str(job_id),existing['payload'])
                if previous.get('submitted') or previous.get('status') in ('submitting','submission_unknown'):
                    return previous
            job=c.execute('SELECT * FROM jobsearch.jobs WHERE id=%s',(job_id,)).fetchone()
            if not job: raise HTTPException(404,'Job not found')
            if job['match_status']!='match' or job['country_status'] not in ('us_based','us_remote_eligible') or job['availability']!='observed_open':
                raise HTTPException(409,'Only current matching US listings can enter application preparation')
            variant='capital_one' if capital_one(job['company']) else 'default'
            r=c.execute('SELECT * FROM jobsearch.private_resume WHERE user_id=%s AND variant=%s',(user['id'],variant)).fetchone()
            if not r: raise HTTPException(409,'Upload the '+('Capital One' if variant=='capital_one' else 'default')+' resume in Resume & profile first')
            resume=decrypt(user['id'],'resume:'+variant,r['payload'])
            row=c.execute('SELECT * FROM jobsearch.private_intake WHERE user_id=%s',(user['id'],)).fetchone()
            profile=decrypt(user['id'],'profile',row['payload']) if row else Intake().model_dump()
            missing=[k for k in ('full_name','email','phone','location') if not profile[k]]
            missing += [k for k in ('authorized_us','sponsorship') if profile[k]=='unknown']
            if not profile['confirmed']: missing.append('confirmed profile')
            excluded=[x.strip().casefold() for x in profile['excluded_companies'].split(',') if x.strip()]
            if job['company'].casefold() in excluded: raise HTTPException(409,'Employer is excluded by your profile')
            report=assess(resume['text'],job)
            status='needs_information' if missing else 'needs_site_access'
            if report.get('blocked'): status='content_review'
            result={'job_id':str(job_id),'title':job['title'],'company':job['company'],'url':job['url'],
                    'resume_variant':variant,'resume_filename':resume['filename'],'resume_version':str(r['version']),
                    'profile_version':str(row['version']) if row else None,'job_hash':job['content_hash'],
                    'missing_fields':missing,'assessment':report,'status':status,'submitted':False,
                    'next_action':'Complete missing profile fields, review the requirements, and use the employer application form. Direct submission access is not configured.'}
            c.execute('INSERT INTO jobsearch.private_applications(user_id,job_id,payload) VALUES(%s,%s,%s) ON CONFLICT(user_id,job_id) DO UPDATE SET payload=excluded.payload,updated_at=now()',
                      (user['id'],job_id,encrypt(user['id'],'application:'+str(job_id),result)))
            audit(c,str(user['id']),'application.checked',job_id,details={'status':status})
            return result

    @router.get('/applications')
    def applications(user=Depends(member)):
        with private_connection(user['id']) as c:
            result=[]
            profile=c.execute('SELECT version FROM jobsearch.private_intake WHERE user_id=%s',(user['id'],)).fetchone()
            versions={r['variant']:str(r['version']) for r in c.execute('SELECT variant,version FROM jobsearch.private_resume WHERE user_id=%s',(user['id'],)).fetchall()}
            for row in c.execute('SELECT a.*,j.content_hash,j.match_status,j.availability FROM jobsearch.private_applications a JOIN jobsearch.jobs j ON j.id=a.job_id WHERE a.user_id=%s AND NOT EXISTS(SELECT 1 FROM jobsearch.job_archives z WHERE z.user_id=a.user_id AND z.identity=jobsearch.posting_identity(j.url)) ORDER BY a.updated_at DESC LIMIT 100',(user['id'],)).fetchall():
                value=decrypt(user['id'],'application:'+str(row['job_id']),row['payload'])
                value['stale']=value['resume_version']!=versions.get(value['resume_variant']) or value['profile_version']!=(str(profile['version']) if profile else None) or value['job_hash']!=row['content_hash'] or row['match_status']!='match' or row['availability']!='observed_open'
                result.append(value)
            return result
    return router
