"""Explicit staging-only public data ingestion; no shared service reconfiguration."""
import fcntl,json,os,tempfile,time,uuid
from pathlib import Path
from scripts.jobsearch_staging import api_python,clickhouse,kubectl
from src.pipelines.analytics import changes
from scripts.slack_analytics import report_run
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/analytics'
EXPORT="""import json
from src.db.store import connection
from src.settings import settings
from urllib.parse import urlsplit
assert urlsplit(settings().database_url).path=='/jobsearch_staging'
with connection() as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
 c.execute("SET LOCAL statement_timeout='15s'")
 rows=c.execute("SELECT j.id,s.company AS source,s.provider,j.level,j.match_status,j.availability,j.posted_at,j.last_seen_at,j.url FROM jobsearch.jobs j JOIN jobsearch.sources s ON s.id=j.source_id WHERE j.evidence->>'discovery_scope'='staging_public_feed' ORDER BY j.id LIMIT 100001").fetchall()
 source=c.execute("SELECT count(*) AS total,count(*) FILTER(WHERE last_error IS NOT NULL) AS errors,count(*) FILTER(WHERE last_success_at IS NULL OR last_success_at<now()-interval '7 days') AS stale,max(last_success_at) AS last_success FROM jobsearch.sources").fetchone()
 print(json.dumps({'rows':rows,'sources':source},default=str))
"""
def persist(report):
 payload=json.dumps(report).replace("'","''")
 statement="BEGIN; SET LOCAL statement_timeout='15s'; CREATE TABLE IF NOT EXISTS jobsearch.analytics_snapshot(id boolean PRIMARY KEY DEFAULT true CHECK(id),generated_at timestamptz NOT NULL,report jsonb NOT NULL); REVOKE ALL ON jobsearch.analytics_snapshot FROM PUBLIC; GRANT SELECT ON jobsearch.analytics_snapshot TO jobsearch_app; INSERT INTO jobsearch.analytics_snapshot VALUES(true,now(),'"+payload+"'::jsonb) ON CONFLICT(id) DO UPDATE SET generated_at=excluded.generated_at,report=excluded.report; COMMIT;"
 kubectl('exec','-i','-n','jobsearch-pilot','deployment/postgres','--','psql','-X','-v','ON_ERROR_STOP=1','-U','jobsearch_owner','-d','jobsearch_staging','-At',input_text=statement)
@report_run('jobsearch_analytics')
def run():
 STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (STATE/'lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  exported=json.loads(api_python(EXPORT));rows=exported['rows']
  if len(rows)>100000:raise RuntimeError('Staging row safety cap exceeded')
  file=STATE/'state.json';previous=json.loads(file.read_text()) if file.exists() else {}
  current,delta=changes(rows,previous,time.time_ns())
  clickhouse((ROOT/'config/jobsearch_analytics.sql').read_text(),admin=True)
  for start in range(0,len(delta),10000):
   clickhouse('INSERT INTO hub_analytics.jobsearch_listings_v1 FORMAT JSONEachRow\n'+'\n'.join(json.dumps(x) for x in delta[start:start+10000]),admin=True)
  base="FROM hub_analytics.jobsearch_listings_v1 FINAL WHERE scope='jobsearch_staging' AND deleted=0"
  totals=clickhouse('SELECT count() AS listings,uniqExact(url_hash) AS unique_urls,countIf(isNull(posted_at)) AS unknown_dates '+base+' LIMIT 1')['data'][0]
  if int(totals['listings'])!=len(rows):raise RuntimeError('ClickHouse reconciliation mismatch; previous dashboard retained')
  windows={}
  for key,hours in [('24h',24),('7d',168),('all',None)]:
   where=base+(f' AND posted_at>=now()-INTERVAL {hours} HOUR AND posted_at<=now()' if hours else '')
   windows[key]={
    'total':clickhouse('SELECT count() AS listings '+where+' LIMIT 1')['data'][0]['listings'],
    'sources':clickhouse('SELECT source AS label,count() AS count '+where+' GROUP BY source ORDER BY count DESC,label LIMIT 100')['data'],
    'roles':clickhouse('SELECT level AS label,count() AS count '+where+' GROUP BY level ORDER BY count DESC,label LIMIT 100')['data'],
    'dates':clickhouse("SELECT toString(toDate(posted_at)) AS label,count() AS count "+where+" AND isNotNull(posted_at) GROUP BY label ORDER BY label DESC LIMIT 31")['data']}
  report={'engine':'ClickHouse','scope':'Public staging listings; match and review classifications','totals':totals,'windows':windows,'sources':exported['sources'],'changed_rows':len(delta),'reconciled_rows':len(rows),'checks':'passed'}
  persist(report)
  fd,name=tempfile.mkstemp(dir=STATE,prefix='.state-')
  with os.fdopen(fd,'w') as f:json.dump(current,f)
  os.replace(name,file)
  print(json.dumps({'status':'completed','rows':len(rows),'changed_rows':len(delta),'checks':'passed'}))
  return report
if __name__=='__main__':run()
