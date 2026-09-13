import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_production_baseline_cannot_start_writers_or_expose_a_service():
 items=json.loads((ROOT/'infra/kubernetes/production/namespace.json').read_text())['items']
 assert {i['kind'] for i in items}=={'Namespace','NetworkPolicy','ResourceQuota'}
 assert items[0]['metadata']['name']=='jobsearch-production'
 assert items[0]['metadata']['labels']['pod-security.kubernetes.io/enforce']=='restricted'
 deny=next(i for i in items if i['kind']=='NetworkPolicy')
 assert set(deny['spec']['policyTypes'])=={'Ingress','Egress'} and not deny['spec'].get('ingress') and not deny['spec'].get('egress')
 assert all(i['metadata'].get('namespace','jobsearch-production')=='jobsearch-production' for i in items)
