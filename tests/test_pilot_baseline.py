"""Static safety invariants; runtime network enforcement requires a real cluster."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'infra/kubernetes/pilot'

def test_cluster_cannot_attach_existing_state_or_publish_apps():
    c=json.loads((ROOT/'cluster.yaml').read_text())
    assert c['metadata']['name']=='ai-hub-pilot'
    assert c['servers']==1 and c['agents']==0
    assert c['kubeAPI']=={'host':'127.0.0.1','hostIP':'127.0.0.1','hostPort':'6447'}
    assert not any(c.get(k) for k in ('volumes','ports','network','registries','token'))
    assert c['options']['runtime']['serversMemory']=='4g'
    assert c['options']['runtime']['hostPidMode'] is False
    assert c['options']['kubeconfig']=={'updateDefaultKubeconfig':False,'switchCurrentContext':False}
    assert c['options']['k3d']['disableLoadbalancer'] is True
    assert '--disable-network-policy' not in json.dumps(c)

def test_every_pilot_namespace_has_default_deny_and_restricted_admission():
    items=json.loads((ROOT/'baseline.json').read_text())['items']
    spaces=[i for i in items if i['kind']=='Namespace']
    assert {n['metadata']['name'] for n in spaces}=={'ai-hub-pilot','jobsearch-pilot'}
    for ns in spaces:
        name=ns['metadata']['name']
        assert ns['metadata']['labels']['pod-security.kubernetes.io/enforce']=='restricted'
        resources=[i for i in items if i['metadata'].get('namespace')==name]
        policy=next(i for i in resources if i['kind']=='NetworkPolicy')['spec']
        assert policy=={'podSelector':{},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[]}
        for sa in [i for i in resources if i['kind']=='ServiceAccount']:
            assert sa['automountServiceAccountToken'] is False
        assert len([i for i in resources if i['kind']=='ServiceAccount'])==2

def test_baseline_cannot_deploy_apps_grant_rbac_or_claim_storage():
    items=json.loads((ROOT/'baseline.json').read_text())['items']
    assert {i['kind'] for i in items}=={'Namespace','ServiceAccount','NetworkPolicy','ResourceQuota','LimitRange'}
    quotas=[i['spec']['hard'] for i in items if i['kind']=='ResourceQuota']
    assert len(quotas)==2
    for q in quotas:
        assert q['limits.memory']=='1Gi' and q['limits.cpu']=='1'
        assert q['persistentvolumeclaims']=='0'
        assert q['services.loadbalancers']=='0' and q['services.nodeports']=='0'
