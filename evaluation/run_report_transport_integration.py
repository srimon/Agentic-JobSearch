"""Host harness: ephemeral PostgreSQL and report runner; no external network or secrets."""
import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f'


def run(args, data=None):
    result = subprocess.run(args,input=data,text=True,capture_output=True,timeout=180)
    if result.returncode:
        raise RuntimeError('Synthetic report test subprocess failed: '+result.stderr[-1500:]+result.stdout[-1500:])
    return result.stdout


def main():
    name = 'jbs-report-test-' + uuid.uuid4().hex[:12]
    database = None
    try:
        database = run(['docker','run','-d','--name',name,'--label','jobsearch.synthetic-report='+name,
            '--network','none','--read-only','--user','999:999','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--memory','384m','--cpus','0.5','--tmpfs','/var/lib/postgresql/data:rw,size=192m,uid=999,gid=999',
            '--tmpfs','/var/run/postgresql:rw,size=8m,uid=999,gid=999','--tmpfs','/tmp:rw,size=16m,uid=999,gid=999',
            '-e','POSTGRES_USER=jobsearch_owner','-e','POSTGRES_DB=jobsearch_report_test','-e','POSTGRES_HOST_AUTH_METHOD=trust',IMAGE]).strip()
        for _ in range(60):
            ready = subprocess.run(['docker','exec',database,'pg_isready','-U','jobsearch_owner','-d','jobsearch_report_test'],capture_output=True,timeout=10)
            if ready.returncode == 0: break
            time.sleep(1)
        else: raise RuntimeError('synthetic database readiness timeout')
        sql = 'CREATE ROLE jobsearch_app LOGIN;\n' + '\n'.join(p.read_text() for p in sorted((ROOT/'src/db').glob('[0-9][0-9][0-9]_*.sql')))
        sql += '\nGRANT USAGE ON SCHEMA jobsearch TO jobsearch_app; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA jobsearch TO jobsearch_app; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA jobsearch TO jobsearch_app;'
        run(['docker','exec','-i',database,'psql','-X','-v','ON_ERROR_STOP=1','--single-transaction','-U','jobsearch_owner','-d','jobsearch_report_test'],sql)
        args = ['docker','run','--rm','--network','container:'+database,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','384m','--cpus','0.5','--tmpfs','/tmp:rw,size=32m',
            '-e','JOBSEARCH_DATABASE_URL=postgresql://jobsearch_app@127.0.0.1/jobsearch_report_test','-e','JOBSEARCH_TELEMETRY=false']
        for source, target in [('src/applications/reporting.py','/app/src/applications/reporting.py'),('scripts/email_report.py','/app/scripts/email_report.py'),('evaluation/report_transport_integration.py','/app/report_transport_integration.py')]:
            args += ['--mount',f'type=bind,source={ROOT/source},target={target},readonly']
        image = run(['docker','image','inspect','jobsearch-api:3d48b9b','--format','{{.Id}}']).strip()
        print(run(args + [image,'python','/app/report_transport_integration.py']).strip())
    finally:
        if database:
            info = json.loads(run(['docker','inspect',database]))[0]
            if info['Name'] != '/'+name or info['Config']['Labels'].get('jobsearch.synthetic-report') != name:
                raise RuntimeError('refusing cleanup of an unowned container')
            run(['docker','rm','--force',database])


if __name__ == '__main__': main()
