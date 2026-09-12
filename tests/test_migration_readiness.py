from scripts import migration_readiness as readiness


def test_unavailable_or_empty_docker_is_not_healthy():
    assert readiness.assess(None)['status'] == 'unknown'
    assert readiness.assess([])['status'] == 'attention'
    assert readiness.assess([{'name':'jobsearch-api-1','status':'Up 1 hour (unhealthy)'}])['status']=='attention'


def test_running_without_healthcheck_is_not_healthy():
    assert readiness.assess([{'name':'jobsearch-worker-1','status':'Up 1 hour'}])['status']=='attention'
    assert readiness.assess([{'name':'jobsearch-api-1','status':'Up 1 hour (healthy)'}])['status']=='healthy'


def test_inventory_has_no_cluster_contact_or_private_data(monkeypatch,tmp_path):
    calls=[]
    def query(args):
        calls.append(args)
        if args[1]=='info':return [{'cpus':16,'memory_bytes':32000000000}]
        return [{'Names':'jobsearch-api-1','Status':'Up 1 hour (healthy)','Labels':'private','Mounts':'private'}]
    monkeypatch.setattr(readiness,'run_json',query)
    result=readiness.collect(tmp_path)
    assert all(c[0]=='docker' and c[1] in ('info','ps') for c in calls)
    assert 'label=com.docker.compose.project=jobsearch' in calls[1]
    assert 'private' not in str(result['jobsearch_containers'])
    assert result['production_migration_ready'] is False
    assert result['pilot_readiness']=='not_verified'


def test_command_failure_redacted(monkeypatch):
    def fail(*args,**kwargs):raise readiness.subprocess.CalledProcessError(1,args,stderr='secret')
    monkeypatch.setattr(readiness.subprocess,'run',fail)
    assert readiness.run_json(['docker','info']) is None
