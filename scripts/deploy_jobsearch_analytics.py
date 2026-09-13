"""Only Jobsearch API/web deployment mutations; no portal or library lifecycle."""
import json,os,signal,subprocess,time
from pathlib import Path
from urllib.request import urlopen
from scripts.jobsearch_staging import kubectl,TOOLS,KUBE
ROOT=Path(__file__).resolve().parents[1]
TARGETS={'api':('jobsearch-api:10f7ba7-governance','jobsearch-api:analytics-20260913'),'web':('jobsearch-web:slack-nav-20260913','jobsearch-web:analytics-20260913')}
def run(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=300)
 if r.returncode:raise RuntimeError('Jobsearch build/import failed: '+r.stdout[-1800:]+r.stderr[-600:])
def unchanged_targets():
 return json.loads(kubectl('get','deployments,statefulsets','-A','-o','json'))['items']
def protected():
 return {(x['metadata']['namespace'],x['kind'],x['metadata']['name']):x['spec'] for x in unchanged_targets() if not(x['metadata']['namespace']=='jobsearch-pilot' and x['kind']=='Deployment' and x['metadata']['name'] in TARGETS)}
def forward():
 # Stop only an exactly matching Jobsearch forwarding process; never the Hub.
 for entry in Path('/proc').iterdir():
  if not entry.name.isdigit():continue
  try:args=(entry/'cmdline').read_bytes().decode().split('\0')
  except (OSError,UnicodeError):continue
  if all(s in args for s in ('port-forward','jobsearch-pilot','service/jobsearch-web','3185:3105')):os.kill(int(entry.name),signal.SIGTERM)
 time.sleep(1)
 runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
 with (runtime/'jobsearch-forward.log').open('ab') as log:
  p=subprocess.Popen([str(TOOLS/'kubectl'),'--kubeconfig',str(KUBE),'port-forward','--address','127.0.0.1','-n','jobsearch-pilot','service/jobsearch-web','3185:3105'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 for _ in range(30):
  if p.poll() is not None:raise RuntimeError('Jobsearch port-forward exited')
  try:
   if urlopen('http://127.0.0.1:3185',timeout=2).status==200:return
  except OSError:pass
  time.sleep(1)
 raise RuntimeError('Jobsearch frontend did not become reachable')
def main():
 before=protected()
 for component,(old,new) in TARGETS.items():
  d=json.loads(kubectl('get','deployment',component,'-n','jobsearch-pilot','-o','json'))
  if d['spec']['template']['spec']['containers'][0]['image'] not in (old,new):raise RuntimeError('Concurrent Jobsearch rollout')
 for component,(old,new) in TARGETS.items():
  args=['docker','build','-t',new,'-f',str(ROOT/('infra/Dockerfile.'+component))]
  if component=='web':args+=['--build-arg','NEXT_PUBLIC_JOBSEARCH_ENVIRONMENT=staging']
  run(args+[str(ROOT)])
  run([str(TOOLS/'k3d'),'image','import',new,'--cluster','ai-hub-pilot'])
  d=json.loads(kubectl('get','deployment',component,'-n','jobsearch-pilot','-o','json'))
  current=d['spec']['template']['spec']['containers'][0]['image']
  if current not in (old,new):raise RuntimeError('Concurrent Jobsearch rollout')
  path='/spec/template/spec/containers/0/image'
  kubectl('patch','deployment',component,'-n','jobsearch-pilot','--type=json','-p',json.dumps([{'op':'test','path':path,'value':current},{'op':'replace','path':path,'value':new}]))
  kubectl('rollout','status','deployment/'+component,'-n','jobsearch-pilot','--timeout=180s',timeout=200)
 forward()
 if protected()!=before:raise RuntimeError('A protected workload changed concurrently; inspect before continuing')
 print('Jobsearch API/web ready at 3185; protected workload specifications unchanged')
if __name__=='__main__':main()
