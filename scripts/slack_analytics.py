"""Bounded operational Slack summaries with durable at-most-once dispatch."""
import functools,json,sqlite3,uuid
from pathlib import Path
from urllib.request import Request,build_opener
import re
from urllib.request import HTTPRedirectHandler
SECRET=Path('/home/srimonadi/Enterprise-AI-Hub/.secrets/slack/config.json')  # the hub's one Slack configuration, in the canonical root since 14 Sep 2026
def valid_url(value):return bool(re.fullmatch(r'https://hooks\.slack\.com/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+',value))
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
JOURNAL=Path(__file__).resolve().parents[1]/'.runtime/slack/delivery.sqlite'
COMPONENTS={'jobsearch_analytics'}
def deliver(event_id,component,outcome,findings=0):
 if component not in COMPONENTS or outcome not in {'success','failure','findings'}:raise ValueError('Unsupported operational event')
 uuid.UUID(event_id)
 if type(findings) is not int or not 0<=findings<=100000:raise ValueError('Invalid aggregate count')
 config=json.loads(SECRET.read_text()) if SECRET.exists() else {}
 if not config.get('automatic_delivery'):return 'disabled'
 if config.get('policy')=='failures' and outcome=='success':return 'filtered'
 if not valid_url(config.get('webhook','')):raise ValueError('Invalid webhook configuration')
 JOURNAL.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with sqlite3.connect(JOURNAL,timeout=5) as db:
  JOURNAL.chmod(0o600)
  db.execute('CREATE TABLE IF NOT EXISTS delivery (event_id TEXT PRIMARY KEY, component TEXT, outcome TEXT, state TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
  db.execute('BEGIN IMMEDIATE')
  if db.execute('SELECT 1 FROM delivery WHERE event_id=?',(event_id,)).fetchone():return 'already_recorded'
  db.execute('INSERT INTO delivery(event_id,component,outcome,state) VALUES(?,?,?,?)',(event_id,component,outcome,'sending'))
  db.commit()
  text=f'Enterprise AI Hub | staging | {component} | {outcome} | findings: {findings} | run: {event_id}'
  request=Request(config['webhook'],data=json.dumps({'text':text}).encode(),headers={'Content-Type':'application/json'},method='POST')
  state='unknown'
  try:
   with build_opener(NoRedirect).open(request,timeout=10) as response:
    if response.status==200 and response.read(100).strip()==b'ok':state='accepted'
  except Exception:pass # Never expose a credential-bearing exception or retry an uncertain send.
  db.execute('UPDATE delivery SET state=? WHERE event_id=?',(state,event_id))
  db.commit()
  return state

def report_run(component):
 def decorate(function):
  @functools.wraps(function)
  def wrapped(*args,**kwargs):
   ident=str(uuid.uuid4());outcome='failure';findings=0
   try:
    result=function(*args,**kwargs)
    findings=result.get('findings',0) if isinstance(result,dict) else 0
    outcome='findings' if findings else 'success'
    return result
   finally:
    try:state=deliver(ident,component,outcome,findings)
    except Exception:state='notification_error'
    print(json.dumps({'slack_delivery':state,'component':component,'run_id':ident}),flush=True)
  return wrapped
 return decorate
