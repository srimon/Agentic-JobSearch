"""Bounded preference ranking from explicit decisions; no private intake features."""
import hashlib,json,re
from collections import defaultdict
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from src.db.store import audit

ALGORITHM='feedback-v2'
FUNCTIONS = [
    ('Data engineering', r'data (engineering|platform|infrastructure)'),
    ('Data management', r'data (management|governance|quality)'),
    ('Analytics', r'analytics|business intelligence'),
    ('AI', r'\bai\b|artificial intelligence|machine learning'),
]


def empty_model():
    return {'algorithm':ALGORITHM,'decisions':0,'rules':[],'minimum_evidence':3,'max_adjustment':15,
      'limitations':['Generic not-relevant and dismissed flags do not imply a broader preference.','Applied is a weak preference signal, not employer confirmation or match quality.','Source penalties use reviewed listings only and are not source-wide failure rates.']}


def features(job):
    title=job['title'].lower()
    result=[]
    for label,pattern in FUNCTIONS:
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
    return {**empty_model(), 'decisions':len(rows), 'rules':rules}

def current(c,uid):
    """Read an immutable snapshot. GET/report reads never train, lock or write."""
    # Settings and model are read in one statement snapshot, including during
    # concurrent pause/reset/restore operations.
    row=c.execute('''SELECT coalesce(s.enabled,true) AS enabled,s.pinned_version,v.id,v.model
        FROM (SELECT %s::bigint AS user_id) owner
        LEFT JOIN jobsearch.learning_settings s ON s.user_id=owner.user_id
        LEFT JOIN LATERAL (SELECT id,model FROM jobsearch.learning_versions v
          WHERE v.user_id=owner.user_id AND (s.pinned_version IS NULL OR v.id=s.pinned_version)
          ORDER BY v.id DESC LIMIT 1) v ON true''',(uid,)).fetchone()
    # Version zero is the neutral, unsaved baseline for an owner without history.
    return {**(row['model'] or empty_model()),'version':row['id'] or 0,'enabled':row['enabled'],'pinned':bool(row['pinned_version'])}


def refresh(c,uid):
    """Publish after an owner mutation, serialized with learning controls.

    Caller owns the transaction and private owner context. No new worker or
    elevated identity is needed; failure rolls back the associated decision.
    """
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(uid)+':learning',))
    cfg=c.execute('SELECT * FROM jobsearch.learning_settings WHERE user_id=%s',(uid,)).fetchone() or {'enabled':True,'since':None,'pinned_version':None}
    if cfg['pinned_version']:
        return current(c,uid)
    rows=c.execute('SELECT a.identity,a.final_status,a.feedback_reason,a.archived_at,j.title,j.level,j.work_mode,j.source_id FROM jobsearch.job_archives a JOIN jobsearch.jobs j ON j.id=a.job_id WHERE a.user_id=%s AND (%s::timestamptz IS NULL OR a.archived_at>%s) ORDER BY a.identity',(uid,cfg['since'],cfg['since'])).fetchall()
    model=train(rows)
    digest=hashlib.sha256(json.dumps({'model':model,'evidence':rows,'since':cfg['since']},sort_keys=True,default=str).encode()).hexdigest()
    latest=c.execute('SELECT * FROM jobsearch.learning_versions WHERE user_id=%s ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
    if latest and latest['model'].get('evidence_fingerprint',latest['fingerprint'])==digest:
        row=latest
    else:
        # Revisited evidence may equal an older snapshot. Link to the latest
        # version so the newly active snapshot has the newest ID, while repeated
        # refreshes of unchanged evidence remain idempotent. Old rows stay immutable.
        fingerprint=hashlib.sha256(json.dumps([digest,latest['id'] if latest else None]).encode()).hexdigest()
        model['evidence_fingerprint']=digest
        row=c.execute('INSERT INTO jobsearch.learning_versions(user_id,fingerprint,model) VALUES(%s,%s,%s) RETURNING *',(uid,fingerprint,Jsonb(model))).fetchone()
        audit(c,str(uid),'learning.version.created',row['id'],details={'algorithm':ALGORITHM,'decisions':len(rows),'rules':len(model['rules'])})
    return {**row['model'],'version':row['id'],'enabled':cfg['enabled'],'pinned':bool(cfg['pinned_version'])}


def ranking_sql(model):
    """Fixed feature expressions with bound values; matches explain() scoring.

    Source/level/workplace weights are lookup maps, keeping query size bounded
    by feature families rather than generating one CASE for every source rule.
    Database scoring still examines eligible jobs; only the page leaves SQL.
    """
    if not model['enabled']:
        return '0::integer', []
    weights=defaultdict(int)
    for rule in model['rules']:
        weights[rule['feature']]+=rule['weight']
    terms=['0']; params=[]
    for label,pattern in FUNCTIONS:
        weight=weights.get('function:'+label,0)
        if weight:
            terms.append('CASE WHEN lower(j.title) ~ %s THEN %s ELSE 0 END')
            params.extend([pattern.replace(r'\bai\b',r'\mai\M'),weight])
    for dimension,column in [('level','level'),('workplace','work_mode'),('source','source_id')]:
        lookup={key.split(':',1)[1]:value for key,value in weights.items() if key.startswith(dimension+':') and value}
        if dimension=='level': lookup.pop('',None)
        if dimension=='workplace': lookup.pop('Unknown',None)
        if lookup:
            terms.append(f'coalesce((%s::jsonb ->> j.{column}::text)::integer,0)')
            params.append(Jsonb(lookup))
    return 'greatest(-15,least(15,'+' + '.join(terms)+'))',params

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
    if action in ('reset','resume'):
        refresh(c,uid)
