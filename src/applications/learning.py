"""Bounded preference ranking from explicit decisions; no private intake features."""
import hashlib,json,re
from collections import defaultdict
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from src.db.store import audit

ALGORITHM='feedback-v2'
def features(job):
    title=job['title'].lower()
    result=[]
    for label,pattern in [('Data engineering',r'data (engineering|platform|infrastructure)'),('Data management',r'data (management|governance|quality)'),('Analytics',r'analytics|business intelligence'),('AI',r'\bai\b|artificial intelligence|machine learning')]:
        if re.search(pattern,title):result.append('function:'+label)
    if job.get('level'):result.append('level:'+job['level'])
    if job.get('work_mode') not in (None,'Unknown'):result.append('workplace:'+job['work_mode'])
    return result

def train(rows):
    quality=defaultdict(set);negative=defaultdict(set);positive=defaultdict(set);fresh=defaultdict(set);total=defaultdict(set)
    for row in rows:
        source=str(row['source_id']);total[source].add(row['identity'])
        if row['final_status']=='applied':
            for feature in features(row):positive[feature].add(row['identity'])
        if row['final_status']=='not_relevant':
            dimension={'wrong_function':'function:','wrong_seniority':'level:','wrong_workplace':'workplace:'}.get(row.get('feedback_reason'))
            if dimension:
                for feature in features(row):
                    if feature.startswith(dimension):negative[feature].add(row['identity'])
        if row['final_status'] in ('spam','fake_posting'):quality[source].add(row['identity'])
        if row['final_status'] in ('old_posting','no_longer_available'):fresh[source].add(row['identity'])
    rules=[]
    for feature,ids in sorted(positive.items()):
        if len(ids)>=3:rules.append({'feature':feature,'weight':min(6,len(ids)),'count':len(ids),'reason':f'{len(ids)} applied decisions share {feature.split(":",1)[1]}.'})
    for feature,ids in sorted(negative.items()):
        if len(ids)>=3:rules.append({'feature':feature,'weight':-min(6,len(ids)),'count':len(ids),'reason':f'{len(ids)} explicit rejection reasons concern {feature.split(":",1)[1]}.'})
    for source,ids in sorted(fresh.items()):
        if len(ids)>=3:rules.append({'feature':'source:'+source,'weight':-min(6,len(ids)),'count':len(ids),'reason':f'{len(ids)} reviewed listings from this source were flagged old or unavailable; freshness penalty only.'})
    for source,ids in sorted(quality.items()):
        if len(ids)>=3:rules.append({'feature':'source:'+source,'weight':-min(6,len(ids)),'count':len(ids),'reason':f'{len(ids)} listings from this source were flagged by you as spam or suspected fake postings; these are unverified user reports.'})
    return {'algorithm':ALGORITHM,'decisions':len(rows),'rules':rules,'minimum_evidence':3,'max_adjustment':15,
      'limitations':['Generic not-relevant and dismissed flags do not imply a broader preference.','Applied is a weak preference signal, not employer confirmation or match quality.','Source penalties use reviewed listings only and are not source-wide failure rates.']}

def current(c,uid):
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(uid)+':learning',))
    cfg=c.execute('SELECT * FROM jobsearch.learning_settings WHERE user_id=%s',(uid,)).fetchone() or {'enabled':True,'since':None,'pinned_version':None}
    if cfg['pinned_version']:
        row=c.execute('SELECT * FROM jobsearch.learning_versions WHERE user_id=%s AND id=%s',(uid,cfg['pinned_version'])).fetchone()
    else:
        rows=c.execute('SELECT a.identity,a.final_status,a.feedback_reason,a.archived_at,j.title,j.level,j.work_mode,j.source_id FROM jobsearch.job_archives a JOIN jobsearch.jobs j ON j.id=a.job_id WHERE a.user_id=%s AND (%s::timestamptz IS NULL OR a.archived_at>%s) ORDER BY a.identity',(uid,cfg['since'],cfg['since'])).fetchall()
        model=train(rows)
        digest=hashlib.sha256(json.dumps({'model':model,'evidence':rows,'since':cfg['since']},sort_keys=True,default=str).encode()).hexdigest()
        row=c.execute('SELECT * FROM jobsearch.learning_versions WHERE user_id=%s AND fingerprint=%s',(uid,digest)).fetchone()
        if not row:
            row=c.execute('INSERT INTO jobsearch.learning_versions(user_id,fingerprint,model) VALUES(%s,%s,%s) RETURNING *',(uid,digest,Jsonb(model))).fetchone()
            audit(c,str(uid),'learning.version.created',row['id'],details={'algorithm':ALGORITHM,'decisions':len(rows),'rules':len(model['rules'])})
    return {**row['model'],'version':row['id'],'enabled':cfg['enabled'],'pinned':bool(cfg['pinned_version'])}

def explain(job,model):
    keys=set(features(job)+['source:'+str(job['source_id'])])
    rules=[r for r in model['rules'] if r['feature'] in keys] if model['enabled'] else []
    return {'adjustment':max(-15,min(15,sum(r['weight'] for r in rules))),'reasons':[r['reason'] for r in rules],'version':model['version'],'enabled':model['enabled']}

def configure(c,uid,action,version=None):
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(uid)+':learning',))
    c.execute('INSERT INTO jobsearch.learning_settings(user_id) VALUES(%s) ON CONFLICT DO NOTHING',(uid,))
    if action=='restore':
        if not c.execute('SELECT 1 FROM jobsearch.learning_versions WHERE id=%s AND user_id=%s',(version,uid)).fetchone():raise HTTPException(404,'Learning version not found')
        c.execute('UPDATE jobsearch.learning_settings SET pinned_version=%s,enabled=true WHERE user_id=%s',(version,uid))
    elif action=='reset':c.execute('UPDATE jobsearch.learning_settings SET since=now(),pinned_version=NULL WHERE user_id=%s',(uid,))
    elif action=='resume':c.execute('UPDATE jobsearch.learning_settings SET enabled=true,pinned_version=NULL WHERE user_id=%s',(uid,))
    else:c.execute('UPDATE jobsearch.learning_settings SET enabled=false WHERE user_id=%s',(uid,))
    audit(c,str(uid),'learning.'+action,str(version or 'settings'))
