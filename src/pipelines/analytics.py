"""Allowlisted public-listing projections and deterministic incremental deltas."""
import hashlib,json,uuid
from datetime import datetime,timezone
FIELDS=('id','source','provider','level','match_status','availability','posted_at','last_seen_at','url')
def project(row):
 uuid.UUID(str(row['id']))
 def stamp(value):
  if not value:return None
  date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
  if date.tzinfo is None:raise ValueError('Timezone required')
  return date.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
 return {'scope':'jobsearch_staging','job_id':str(row['id']),
  **{k:str(row.get(k) or 'unknown')[:200] for k in ('source','provider','level','match_status','availability')},
  'posted_at':stamp(row.get('posted_at')),'last_seen_at':stamp(row['last_seen_at']),
  'url_hash':hashlib.sha256(str(row['url']).encode()).hexdigest(),'deleted':0}
def changes(rows,previous,version):
 current={};delta=[]
 for row in rows:
  item=project(row);key=item['job_id']
  if key in current:raise ValueError('Duplicate listing identity')
  fingerprint=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
  current[key]={'hash':fingerprint,'row':item}
  if previous.get(key,{}).get('hash')!=fingerprint:delta.append({**item,'version':version})
 for key,old in previous.items():
  if key not in current:delta.append({**old['row'],'deleted':1,'version':version})
 return current,delta
