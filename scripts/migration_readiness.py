"""Read-only local pilot inventory. Never contacts a Kubernetes context or reads secrets."""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_json(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=20, check=True)
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return None  # Do not expose daemon errors, environment values or credentials.


def assess(containers):
    if containers is None:
        return {'status': 'unknown', 'reason': 'Docker inventory unavailable'}
    if not containers:
        return {'status': 'attention', 'reason': 'No running Jobsearch containers found'}
    unhealthy = [c['name'] for c in containers if '(healthy)' not in c['status']]
    return {'status': 'attention' if unhealthy else 'healthy', 'unverified_or_unhealthy': unhealthy}


def collect(root=ROOT):
    engine = run_json(['docker', 'info', '--format', '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}'])
    rows = run_json(['docker', 'ps', '--all', '--filter', 'label=com.docker.compose.project=jobsearch', '--format', '{{json .}}'])
    containers = None if rows is None else [{'name': r['Names'], 'status': r['Status']} for r in rows]
    free = shutil.disk_usage(root).free
    tools = {name: shutil.which(name) is not None for name in ('docker', 'kubectl', 'kind', 'k3d', 'k3s', 'helm')}
    return {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Local Jobsearch inventory; no cluster API, library service, database or secret access',
        'tools_on_path': tools,
        'docker_capacity': engine[0] if engine else None,
        'wsl_filesystem_free_bytes': free,
        'capacity_note': 'Docker limits and filesystem availability are not Windows physical free capacity or workload measurements.',
        'jobsearch_containers': containers,
        'jobsearch_health': assess(containers),
        'pilot_readiness': 'not_verified',
        'production_migration_ready': False,
        'remaining_gates': [
            'Select and validate a local cluster, enforcing CNI and storage/restore design.',
            'Measure representative workload capacity and verify Windows host free memory/disk.',
            'Reserve pilot ports and confirm no conflict with either running application.',
            'Implement portable reporting and durable delivery ownership before migrating reports.',
            'Run synthetic staging, network isolation, lease/failure and private-state restore tests.',
            'Define RPO/RTO, rollback window and one authoritative production schedule at cutover.',
        ],
        'safety': 'No resources installed, created, restarted, scaled or modified; no notifications sent.',
    }


if __name__ == '__main__':
    print(json.dumps(collect(), indent=2))
