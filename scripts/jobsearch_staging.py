"""Retired staging transport. Explicit staging credentials required; never production."""
import os
import subprocess
from pathlib import Path
TOOLS=Path('/home/srimonadi/Enterprise-AI-Hub/.tools/bin')
def staging_config():
 value=os.environ.get('JOBSEARCH_RETIRED_STAGING_KUBECONFIG')
 if not value:raise RuntimeError('Staging is retired. Use Hub production helpers; historical replay requires an explicit isolated staging kubeconfig.')
 path=Path(value)
 if not path.is_absolute() or not path.is_file():raise RuntimeError('An existing absolute staging kubeconfig is required')
 base=[str(TOOLS/'kubectl'),'--kubeconfig',str(path),'--context','k3d-ai-hub-pilot']
 result=subprocess.run(base+['config','current-context'],text=True,capture_output=True,timeout=10)
 if result.returncode or result.stdout.strip()!='k3d-ai-hub-pilot':raise RuntimeError('Retired staging context required; production is prohibited')
 return base
def kubectl(*args,input_text=None,timeout=120):
 result=subprocess.run([*staging_config(),*args],input=input_text,text=True,capture_output=True,timeout=timeout)
 if result.returncode:raise RuntimeError('Staging command failed; output withheld to protect credentials')
 return result.stdout

def api_python(code):
 return kubectl('exec','-i','-n','jobsearch-pilot','deployment/api','--','python','-',input_text=code)

def clickhouse(statement,admin=False):
 import json
 role='admin' if admin else 'reader'
 output=kubectl('exec','-i','-n','hub-analytics','statefulset/clickhouse','--','clickhouse-client','--config-file=/run/clickhouse/'+role+'.xml',input_text=statement)
 return json.loads(output) if output.strip() else {}
