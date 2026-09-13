"""Jobsearch-only staging transport; never deploys Hub or library resources."""
import subprocess
from pathlib import Path
TOOLS=Path('/home/srimonadi/Enterprise-AI-Hub-jobsearch/.tools/bin')
KUBE=Path('/home/srimonadi/Enterprise-AI-Hub-jobsearch/.secrets/ai-hub-pilot.kubeconfig')
def kubectl(*args,input_text=None,timeout=120):
 result=subprocess.run([str(TOOLS/'kubectl'),'--kubeconfig',str(KUBE),*args],input=input_text,text=True,capture_output=True,timeout=timeout)
 if result.returncode:raise RuntimeError('Staging command failed; output withheld to protect credentials')
 return result.stdout

def api_python(code):
 return kubectl('exec','-i','-n','jobsearch-pilot','deployment/api','--','python','-',input_text=code)

def clickhouse(statement,admin=False):
 import json
 role='admin' if admin else 'reader'
 output=kubectl('exec','-i','-n','hub-analytics','statefulset/clickhouse','--','clickhouse-client','--config-file=/run/clickhouse/'+role+'.xml',input_text=statement)
 return json.loads(output) if output.strip() else {}
