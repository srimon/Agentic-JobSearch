#!/usr/bin/env python3
"""Jobsearch-only lifecycle management with verified outcomes and JSON logs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import urllib.request

ROOT = Path('/home/srimonadi/Jobsearch')
COMPOSE = ['/usr/bin/docker', 'compose', '--project-directory', str(ROOT), '-p', 'jobsearch', '-f', str(ROOT / 'compose.yaml'), '-f', str(ROOT / 'compose.worker-leases.yaml')]
LOG = logging.getLogger('jobsearch.lifecycle')
RUN_ID = str(uuid.uuid4())


class LifecycleError(Exception):
    pass


def configure_logging():
    os.umask(0o077)
    folder = ROOT / 'logs'
    folder.mkdir(exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(folder / 'lifecycle.jsonl', maxBytes=5*1024*1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(message)s'))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter('%(message)s'))
    LOG.handlers = [handler, console]
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


def event(name, level='info', **fields):
    record = {'at': datetime.now(timezone.utc).isoformat(), 'run_id': RUN_ID, 'event': name, 'level': level, **fields}
    LOG.info(json.dumps(record, sort_keys=True))


def command(args, timeout=15):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LifecycleError('command_timeout') from exc
    if result.returncode:
        # Never include raw command output, environment values or credential-bearing configs.
        raise LifecycleError(f'command_exit_{result.returncode}')
    return result.stdout


def expected_services():
    # Parse locally; never log the resolved config because it contains env secrets.
    config = json.loads(command(COMPOSE + ['config', '--format', 'json']))
    services = config.get('services', {})
    if not services:
        raise LifecycleError('no_configured_services')
    expected = {}
    for name, spec in services.items():
        replicas = spec.get('deploy', {}).get('replicas', 1)
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1:
            raise LifecycleError('invalid_replica_count')
        expected[name] = replicas
    return expected



def inspect_project():
    ids = command(['/usr/bin/docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=jobsearch']).split()
    if not ids:
        return []
    raw = json.loads(command(['/usr/bin/docker', 'inspect', *ids]))
    result = []
    for item in raw:
        labels = item['Config'].get('Labels') or {}
        if str(labels.get('com.docker.compose.oneoff','false')).lower() == 'true':
            continue
        state = item['State']
        result.append({'service': labels.get('com.docker.compose.service', ''), 'container': item['Name'].lstrip('/'),
            'id': item['Id'][:12], 'status': state['Status'], 'running': state['Running'],
            'health': state.get('Health', {}).get('Status', 'not_configured'),
            'exit_code': state['ExitCode'], 'oom_killed': state.get('OOMKilled', False),
            'restart_count': item['RestartCount'], 'started_at': state['StartedAt'], 'finished_at': state['FinishedAt']})
    return sorted(result, key=lambda x: x['service'])


def state_errors(services, expected, desired):
    errors = []
    counts = Counter(x['service'] for x in services)
    if desired == 'running':
        for name in sorted(expected):
            replicas = expected[name] if isinstance(expected, dict) else 1
            if counts[name] != replicas:
                errors.append(f'{name}:expected_{replicas}_containers')
        for item in services:
            if item['service'] not in expected:
                errors.append(item['service']+':unexpected_service')
            if not item['running'] or item['health'] != 'healthy':
                errors.append(item['service']+':not_healthy')
            if item['oom_killed']:
                errors.append(item['service']+':out_of_memory')
    else:
        for item in services:
            if item['running'] or item['status'] not in ('exited', 'created'):
                errors.append(item['service']+':not_stopped')
            if item['oom_killed'] or item['exit_code'] not in (0, 143):
                errors.append(item['service']+':abnormal_exit')
    return errors


def library_snapshot():
    ids = command(['/usr/bin/docker','ps','-aq','--filter','name=mbk-']).split()
    if not ids: return {}
    items = json.loads(command(['/usr/bin/docker','inspect',*ids]))
    return {x['Name']: (x['Id'], x['State']['StartedAt'], x['State']['Running'], x['RestartCount'])
            for x in items if x['Name'].startswith('/mbk-')}


def probes(services):
    names = {x['service']: x['container'] for x in services}
    checked = []
    if 'postgres' in names:
        value = command(['/usr/bin/docker','exec',names['postgres'],'sh','-c',
            'PGPASSWORD=$(cat /run/secrets/postgres_password) psql -h 127.0.0.1 -U jobsearch_owner -d jobsearch -Atc "SELECT 1"'])
        if value.strip() != '1': raise LifecycleError('postgres_query_failed')
        checked.append('postgres_authenticated_query')
    if 'redis' in names:
        value = command(['/usr/bin/docker','exec',names['redis'],'sh','-c',
            "REDISCLI_AUTH=$(sed -n 's/^requirepass //p' /usr/local/etc/redis/redis.conf) redis-cli ping"])
        if value.strip() != 'PONG': raise LifecycleError('redis_ping_failed')
        checked.append('redis_authenticated_ping')
    if 'qdrant' in names:
        value = json.loads(command(['/usr/bin/docker','inspect',names['qdrant']]))[0]
        ip = value['NetworkSettings']['Networks']['jobsearch_data']['IPAddress']
        key = (ROOT/'.secrets/qdrant.yaml').read_text().split('api_key: ',1)[1].strip()
        request = urllib.request.Request(f'http://{ip}:6333/collections', headers={'api-key':key})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=5) as response:
            payload = json.load(response)
            if response.status != 200 or 'collections' not in payload.get('result',{}):
                raise LifecycleError('qdrant_query_failed')
        checked.append('qdrant_authenticated_query')
    return checked


def save_status(record):
    path = ROOT/'logs/status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(record, indent=2)+'\n')
    temp.replace(path)


def execute(action, desired='running'):
    start = time.monotonic()
    before_library = None
    services = []
    try:
        command(['/usr/bin/docker','info','--format','{{.ServerVersion}}'])
        expected = expected_services()
        before_library = library_snapshot()
        services = inspect_project()
        event('precheck', action=action, services=services)
        if action == 'start':
            event('start_requested')
            command(COMPOSE+['up','-d','--wait','--wait-timeout','120'], timeout=140)
            desired = 'running'
        elif action == 'stop':
            event('stop_requested', grace_seconds=75)
            command(COMPOSE+['stop','--timeout','75'], timeout=120)
            desired = 'stopped'
        services = inspect_project()
        errors = state_errors(services, expected, desired)
        if errors:
            event('state_validation_failed', level='error', errors=errors, services=services)
            raise LifecycleError('state_validation_failed')
        checks = probes(services) if desired == 'running' else []
        record = {'at':datetime.now(timezone.utc).isoformat(),'run_id':RUN_ID,'action':action,
            'expected':desired,'verified':True,'services':services,'checks':checks}
        save_status(record)
        event('lifecycle_verified', action=action, expected=desired, checks=checks, services=services,
              duration_seconds=round(time.monotonic()-start,3))
        return 0
    except Exception as exc:
        # Include only our predefined error code, never raw connection/HTTP exceptions.
        code = str(exc) if isinstance(exc,LifecycleError) else type(exc).__name__
        try:
            services = inspect_project()
        except Exception:
            services = []
        save_status({'at':datetime.now(timezone.utc).isoformat(),'run_id':RUN_ID,'action':action,
                     'verified':False,'error':code,'services':services})
        event('lifecycle_failed', level='error', action=action, error=code, services=services,
              duration_seconds=round(time.monotonic()-start,3))
        return 1
    finally:
        if before_library is not None:
            try:
                after = library_snapshot()
                changed = sorted(name for name in before_library.keys() | after.keys() if before_library.get(name)!=after.get(name))
                event('library_comparison', level='warning' if changed else 'info', changed=changed,
                      unchanged=not changed, note='Concurrent library changes are reported, not attributed to Jobsearch')
            except Exception:
                event('library_comparison_unavailable', level='warning')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['start','stop','check'])
    parser.add_argument('--expect',choices=['running','stopped'],default='running')
    args=parser.parse_args()
    if ROOT.resolve()!=ROOT: raise SystemExit('Unexpected project root')
    configure_logging()
    with (ROOT/'logs/lifecycle.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            event('lifecycle_busy',level='error',action=args.action)
            return 2
        event('lifecycle_begin',action=args.action)
        return execute(args.action,args.expect)


if __name__=='__main__':
    sys.exit(main())
