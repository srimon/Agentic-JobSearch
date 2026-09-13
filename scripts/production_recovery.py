"""Explicitly authorized local-only production backup and disconnected restore test."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
import zlib
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
IMAGE='pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f'
LABEL='jobsearch.production-recovery'
def production_snapshot():
 ids=subprocess.check_output(['docker','ps','-aq','--filter','label=com.docker.compose.project=jobsearch'],text=True).split()
 if not ids:raise RuntimeError('Jobsearch production is missing')
 items=json.loads(subprocess.check_output(['docker','inspect',*ids]))
 return {i['Config']['Labels']['com.docker.compose.service']:{'id':i['Id'],'image':i['Image'],'status':i['State']['Status'],'started':i['State']['StartedAt']} for i in items}
def private_write(path,content):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
def verify_isolation(item,name):
 host=item['HostConfig']
 if item['Name']!='/'+name or item['Config']['Labels'].get(LABEL)!=name:raise RuntimeError('Recovery ownership mismatch')
 if host['NetworkMode']!='none' or host.get('PortBindings') or host.get('Binds'):raise RuntimeError('Recovery isolation mismatch')
 if any(m['Type']!='tmpfs' for m in item.get('Mounts',[])):raise RuntimeError('Recovery storage must be temporary')
stage=SimpleNamespace(ROOT=ROOT,SOURCE=ROOT,production_snapshot=production_snapshot)
backup=SimpleNamespace(KEY=Path('/home/srimonadi/Enterprise-AI-Hub-jobsearch/.secrets/staging-backup.key'),private_write=private_write)

AAD = b'jobsearch-production-local-rehearsal-v1'
FOLDER = ROOT / '.runtime/production-recovery'
PHASE = 'preflight'


def command(args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=180, check=False)
    if result.returncode:
        # Database stderr can include failing rows. Never surface it or commands.
        raise RuntimeError('A rehearsal subprocess failed; private output was suppressed')
    return result.stdout


def contents(dump):
    blocks = {}
    current = None
    rows = []
    for line in dump.splitlines():
        if current:
            if line == r'\.':
                blocks[current] = (len(rows), hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest())
                current, rows = None, []
            else:
                rows.append(line)
        else:
            match = re.fullmatch(r'COPY ([a-z_]+\.[a-z_]+) \(([^)]+)\) FROM stdin;', line)
            if match:
                current = match.group(1) + '(' + match.group(2) + ')'
                if current in blocks:
                    raise ValueError('duplicate COPY table')
    if current or not blocks:
        raise ValueError('incomplete or empty table snapshot')
    return blocks


def sequence_values(dump):
    values={}
    for line in dump.splitlines():
        if line.startswith('SELECT pg_catalog.setval('):
            match=re.fullmatch(r"SELECT pg_catalog.setval\('([^']+)', (-?\d+), (true|false)\);",line)
            if not match or match[1] in values:raise ValueError('Unexpected sequence statement')
            values[match[1]]=(int(match[2]),match[3]=='true')
    return values


def privilege_statements(dump):
    return sorted(line for line in dump.splitlines() if line.startswith(('GRANT ', 'REVOKE ', 'ALTER DEFAULT PRIVILEGES ')))


def run():
    global PHASE
    before = stage.production_snapshot()
    source = before['postgres']['id']
    info = json.loads(command(['docker', 'inspect', source]))[0]
    labels = info['Config']['Labels']
    if labels.get('com.docker.compose.project') != 'jobsearch' or labels.get('com.docker.compose.service') != 'postgres':
        raise RuntimeError('production source ownership mismatch')
    def source_sql(query):
        return command(['docker', 'exec', '-i', source, 'psql', '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-U', 'jobsearch_owner', '-d', 'jobsearch'], query.encode()).decode().strip()
    if int(source_sql('SELECT pg_database_size(current_database());')) > 128 * 1024 * 1024:
        raise RuntimeError('database exceeds bounded rehearsal capacity')
    if source_sql('SELECT count(*) FROM pg_largeobject_metadata;') != '0':
        raise RuntimeError('large objects require additional validation')
    if len(list(FOLDER.glob('*.aesgcm'))) >= 3:
        raise RuntimeError('three local production recovery points already retained; review retention')
    wrapper = backup.KEY.read_bytes()
    if len(wrapper) != 32 or backup.KEY.stat().st_mode & 0o077:
        raise RuntimeError('protected recovery wrapping key required')
    intake_path = stage.SOURCE / '.secrets/intake_key'
    intake = intake_path.read_bytes()
    if len(intake) != 32:
        raise RuntimeError('unexpected production intake key size')
    dump = command(['docker', 'exec', source, 'pg_dump', '-U', 'jobsearch_owner', '-d', 'jobsearch', '--no-owner', '--lock-wait-timeout=10s']).decode()
    expected = contents(dump)
    expected_sequences=sequence_values(dump)
    expected_grants=privilege_statements(dump)
    if not expected_sequences or not expected_grants:raise RuntimeError('Recovery metadata missing')
    if int(source_sql("SELECT pg_database_size('jobsearch_phoenix');"))>128*1024*1024:raise RuntimeError('Phoenix exceeds rehearsal capacity')
    phoenix_dump=command(['docker','exec',source,'pg_dump','-U','jobsearch_owner','-d','jobsearch_phoenix','--no-owner','--lock-wait-timeout=10s']).decode()
    phoenix_expected=contents(phoenix_dump)
    record = {'scope': 'production-local-rehearsal', 'format': 2, 'dump': dump, 'phoenix_dump':phoenix_dump,
              'intake_key': base64.b64encode(intake).decode(),
              'dump_sha256': hashlib.sha256(dump.encode()).hexdigest()}
    nonce = os.urandom(12)
    path = FOLDER / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8] + '.aesgcm')
    backup.private_write(path, nonce + AESGCM(wrapper).encrypt(nonce, zlib.compress(json.dumps(record).encode()), AAD))
    archive = path.read_bytes()
    recovered = json.loads(zlib.decompress(AESGCM(wrapper).decrypt(archive[:12], archive[12:], AAD)))
    if recovered['scope'] != 'production-local-rehearsal' or hashlib.sha256(recovered['dump'].encode()).hexdigest() != recovered['dump_sha256']:
        raise RuntimeError('retained backup integrity failure')
    recovered_key = base64.b64decode(recovered['intake_key'])
    name = 'jobsearch-production-restore-' + uuid.uuid4().hex[:12]
    container = None
    checked = 0
    try:
        PHASE = 'isolated server startup'
        container = command(['docker', 'run', '-d', '--name', name, '--label', LABEL + '=' + name,
            '--network', 'none', '--log-driver', 'none', '--read-only', '--user', '999:999',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '768m', '--cpus', '0.5', '--pids-limit', '100',
            '--tmpfs', '/var/lib/postgresql/data:rw,size=512m,uid=999,gid=999,mode=0700',
            '--tmpfs', '/var/run/postgresql:rw,size=8m,uid=999,gid=999', '--tmpfs', '/tmp:rw,size=16m,uid=999,gid=999',
            '-e', 'POSTGRES_USER=jobsearch_owner', '-e', 'POSTGRES_DB=jobsearch_restore',
            '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', IMAGE]).decode().strip()
        verify_isolation(json.loads(command(['docker', 'inspect', container]))[0], name)
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', container, 'pg_isready', '-U', 'jobsearch_owner', '-d', 'jobsearch_restore'], capture_output=True, timeout=10)
            if ready.returncode == 0: break
            time.sleep(1)
        else: raise RuntimeError('restore server readiness timeout')
        def target_sql(query,database='jobsearch_restore'):
            return command(['docker', 'exec', '-i', container, 'psql', '-X', '-At', '-v', 'ON_ERROR_STOP=1', '--single-transaction', '-U', 'jobsearch_owner', '-d', database], query.encode()).decode().strip()
        PHASE = 'roles and transactional restore'
        target_sql('CREATE ROLE jobsearch_app NOLOGIN; CREATE ROLE jobsearch_worker NOLOGIN; CREATE ROLE jobsearch_phoenix NOLOGIN;')
        target_sql(recovered['dump'])
        PHASE = 'table content comparison'
        roundtrip = command(['docker', 'exec', container, 'pg_dump', '-U', 'jobsearch_owner', '-d', 'jobsearch_restore', '--data-only', '--no-owner']).decode()
        if contents(roundtrip) != expected:
            raise RuntimeError('restored table contents differ from snapshot')
        if sequence_values(roundtrip)!=expected_sequences:raise RuntimeError('Sequence state mismatch')
        restored_schema=command(['docker','exec',container,'pg_dump','-U','jobsearch_owner','-d','jobsearch_restore','--schema-only','--no-owner']).decode()
        if privilege_statements(restored_schema)!=expected_grants:raise RuntimeError('Restored privilege mismatch')
        versions = target_sql("SELECT string_agg(version::text,',' ORDER BY version) FROM jobsearch.schema_versions;")
        if versions != ','.join(map(str, range(1,14))): raise RuntimeError('schema version mismatch')
        query = "SELECT user_id::text || '|' || 'profile' || '|' || encode(payload,'hex') FROM jobsearch.private_intake UNION ALL SELECT user_id::text || '|resume:' || variant || '|' || encode(payload,'hex') FROM jobsearch.private_resume UNION ALL SELECT user_id::text || '|application:' || job_id::text || '|' || encode(payload,'hex') FROM jobsearch.private_applications;"
        PHASE = 'encrypted record verification'
        for row in target_sql(query).splitlines():
            uid, kind, encoded = row.split('|', 2)
            encrypted = bytes.fromhex(encoded)
            json.loads(AESGCM(recovered_key).decrypt(encrypted[:12], encrypted[12:], f'{uid}:{kind}:v1'.encode()))
            checked += 1
        if not checked: raise RuntimeError('no encrypted records available to validate')
        hidden = target_sql('SET ROLE jobsearch_app; SELECT (SELECT count(*) FROM jobsearch.private_intake)+(SELECT count(*) FROM jobsearch.private_resume)+(SELECT count(*) FROM jobsearch.private_applications)+(SELECT count(*) FROM jobsearch.job_archives);').splitlines()[-1]
        if hidden != '0': raise RuntimeError('restored owner isolation failed')
        PHASE='Phoenix transactional restore'
        command(['docker','exec',container,'psql','-X','-v','ON_ERROR_STOP=1','-U','jobsearch_owner','-d','postgres','-c','CREATE DATABASE phoenix_restore;'])
        target_sql(recovered['phoenix_dump'],'phoenix_restore')
        phoenix_roundtrip=command(['docker','exec',container,'pg_dump','-U','jobsearch_owner','-d','phoenix_restore','--no-owner']).decode()
        if contents(phoenix_roundtrip)!=phoenix_expected:raise RuntimeError('Phoenix snapshot content mismatch')
        if sequence_values(phoenix_roundtrip)!=sequence_values(recovered['phoenix_dump']):raise RuntimeError('Phoenix sequences mismatch')
        if privilege_statements(phoenix_roundtrip)!=privilege_statements(recovered['phoenix_dump']):raise RuntimeError('Phoenix privileges mismatch')
    finally:
        if container:
            verify_isolation(json.loads(command(['docker', 'inspect', container]))[0], name)
            command(['docker', 'rm', '--force', container])
    if stage.production_snapshot() != before:
        raise RuntimeError('production container state changed during rehearsal')
    return {'production_snapshot_restore': 'passed', 'all_table_contents': 'matched snapshot',
            'schema_versions': 13, 'sequence_state':'matched snapshot', 'database_grants':'matched snapshot', 'phoenix_database':'contents, sequences and grants matched snapshot', 'encrypted_records': 'all decrypted successfully',
            'unauthenticated_owner_row_access': 'denied', 'local_encrypted_backup_retained': True,
            'cloud_upload': False, 'temporary_server_removed': True, 'production_container_state': 'unchanged'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-production-rehearsal', action='store_true', required=True)
    parser.parse_args()
    try:
        print(json.dumps(run(), indent=2))
    except Exception as error:
        print(f'Production rehearsal failed during {PHASE} ({type(error).__name__}). Private output suppressed; check isolated resource state before retrying.')
        raise SystemExit(1)
