"""Real PostgreSQL concurrency tests; never use the application database."""
import os
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event

import pytest
from src.db.store import connection, direct_connection
from src.settings import settings, Settings
from ai_core.agents import supervisor, scheduler, leases


@pytest.fixture(autouse=True)
def isolated_db():
    if os.environ.get('JOBSEARCH_AUTH_TEST')!='1':
        pytest.skip('Requires explicitly enabled disposable PostgreSQL database')
    with connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d']=='jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.sources CASCADE')
    yield


def source(provider='ashby'):
    with connection() as c:
        s=c.execute("INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Example',%s,%s,true) RETURNING id",(provider,uuid.uuid4().hex)).fetchone()['id']
        row=supervisor.enqueue(c,s,'test')
    return s,row['id']


def row(jid):
    with connection() as c:
        return c.execute('SELECT * FROM jobsearch.runs WHERE id=%s',(jid,)).fetchone()


def expire(jid):
    with connection() as c:
        c.execute("UPDATE jobsearch.runs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(jid,))


def sample(key='one'):
    return dict(source_job_id=key,company='Example',title='Director Data Engineering',
        location='United States',country='US',work_mode='Remote',description='Data leadership',
        url='https://example.com/jobs/'+key,posted_at=None,evidence={})


def test_parallel_providers_actually_collect_concurrently(monkeypatch):
    a=source('ashby');b=source('greenhouse');barrier=Barrier(2)
    def collect(run):
        barrier.wait(timeout=8)
        return [sample()]
    monkeypatch.setattr(supervisor,'collect',collect)
    with ThreadPoolExecutor(2) as pool:
        tasks=[pool.submit(supervisor.run_one) for _ in range(2)]
        assert all(f.result(timeout=15) for f in tasks)
    assert row(a[1])['status']==row(b[1])['status']=='completed'


def test_provider_serialization_and_source_exclusion():
    a=source();source()
    with leases.claim('first') as claim:
        assert claim
        with leases.claim('second') as other:assert other is None
        with connection() as c:assert supervisor.enqueue(c,a[0],'test') is None


def test_only_expired_task_is_reclaimed_and_stale_fenced():
    a=source('ashby');b=source('greenhouse')
    with leases.claim('old') as old:pass
    with leases.claim('live') as live:
        assert live['id']==b[1]
        expire(a[1])
        with leases.claim('replacement') as new:
            assert new['id']==a[1] and new['lease_token']!=old['lease_token']
            assert new['attempts']==2
            assert row(b[1])['lease_token']==live['lease_token']
            assert not leases.renew(old)
            with connection() as c:
                with pytest.raises(leases.LeaseLost):leases.require_lease(c,old)
            with pytest.raises(leases.LeaseLost):leases.fail(old,'StaleError')
            assert row(a[1])['lease_token']==new['lease_token']


def test_success_transaction_prevents_reclaim(monkeypatch):
    _,jid=source()
    with leases.claim('old') as old:pass
    with connection() as c:
        leases.require_lease(c,old)
        c.execute("UPDATE jobsearch.runs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(jid,))
        # Another connection skips the row locked by a valid completion transaction.
        with leases.claim('other') as other:assert other is None
        c.execute("UPDATE jobsearch.runs SET status='completed' WHERE id=%s",(jid,))
    assert row(jid)['status']=='completed'


def test_expired_worker_cannot_persist_job(monkeypatch):
    _,jid=source()
    def collect(run):
        expire(jid)
        return [sample()]
    monkeypatch.setattr(supervisor,'collect',collect)
    assert supervisor.run_one()
    with connection() as c:assert c.execute('SELECT count(*) n FROM jobsearch.jobs').fetchone()['n']==0
    assert row(jid)['status']=='running'


def test_renewal_and_expiration():
    _,jid=source()
    with leases.claim('worker') as run:
        before=row(jid)['lease_expires_at']
        assert leases.renew(run)
        assert row(jid)['lease_expires_at']>before
        expire(jid)
        assert not leases.renew(run)


def test_background_heartbeat(monkeypatch):
    source();called=Event();original=leases.renew
    monkeypatch.setattr(settings(),'worker_heartbeat_seconds',1)
    def renew(run):
        result=original(run);called.set();return result
    monkeypatch.setattr(leases,'renew',renew)
    with leases.claim('worker') as run:
        with leases.heartbeat(run) as lost:
            assert called.wait(4)
            assert not lost.is_set()


def test_bounded_crash_retries():
    _,jid=source()
    for attempt in range(1,settings().worker_max_attempts+1):
        with leases.claim('worker') as run:assert run['attempts']==attempt
        expire(jid)
    with leases.claim('worker') as run:assert run is None
    assert row(jid)['status']=='failed' and row(jid)['error']=='Lease retries exhausted'


@pytest.mark.parametrize('provider,hours',[('remotive',6),('jobicy',1)])
def test_crash_reclaim_preserves_feed_cooldown(provider,hours):
    _,jid=source(provider)
    with leases.claim('worker') as run:assert run
    expire(jid)
    with leases.claim('worker') as run:assert run is None
    with connection() as c:c.execute("UPDATE jobsearch.runs SET started_at=clock_timestamp()-(%s * interval '1 hour')-interval '1 second' WHERE id=%s",(hours,jid))
    with leases.claim('worker') as run:assert run and run['attempts']==2


def test_failure_is_redacted_and_does_not_close_previous_jobs(monkeypatch):
    sid,jid=source()
    monkeypatch.setattr(supervisor,'collect',lambda run:[sample()])
    supervisor.run_one()
    with connection() as c:next_id=supervisor.enqueue(c,sid,'test')['id']
    def fail(run):raise ValueError('private untrusted body')
    monkeypatch.setattr(supervisor,'collect',fail)
    supervisor.run_one()
    assert row(next_id)['error']=='ValueError'
    with connection() as c:assert c.execute('SELECT availability FROM jobsearch.jobs').fetchone()['availability']=='observed_open'


def test_disabled_source_not_collected(monkeypatch):
    sid,jid=source()
    with connection() as c:c.execute('UPDATE jobsearch.sources SET enabled=false WHERE id=%s',(sid,))
    monkeypatch.setattr(supervisor,'collect',lambda run:pytest.fail('Disabled source fetched'))
    assert not supervisor.run_one()
    assert row(jid)['status']=='failed'
    with connection() as c:assert supervisor.enqueue(c,sid,'test') is None


def test_concurrent_schedulers_create_one_run_per_source():
    sid,jid=source()
    with connection() as c:c.execute('DELETE FROM jobsearch.runs')
    after_boundary=datetime(2026,1,15,16,0,tzinfo=timezone.utc)
    with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:scheduler.schedule(after_boundary),range(4)))
    assert sum(results)==1
    with connection() as c:assert c.execute('SELECT count(*) n FROM jobsearch.runs').fetchone()['n']==1


def test_daily_scheduler_waits_until_eight_am_pacific(monkeypatch):
    monkeypatch.setattr(scheduler,'connection',lambda:pytest.fail('Database checked before daily boundary'))
    # 15:59 UTC is 07:59 PST in January.
    assert scheduler.schedule(datetime(2026,1,15,15,59,tzinfo=timezone.utc))==0


def test_daily_scheduler_boundary_and_next_run():
    # Pacific standard time is UTC-8 in January; daylight time is UTC-7 in July.
    assert scheduler.due_boundary(datetime(2026,1,15,16,0,tzinfo=timezone.utc))==datetime(2026,1,15,16,0,tzinfo=timezone.utc)
    assert scheduler.due_boundary(datetime(2026,7,15,15,0,tzinfo=timezone.utc))==datetime(2026,7,15,15,0,tzinfo=timezone.utc)
    assert scheduler.next_run_at(datetime(2026,7,15,14,0,tzinfo=timezone.utc))==datetime(2026,7,15,15,0,tzinfo=timezone.utc)


def test_worker_does_not_schedule(monkeypatch):
    sid,jid=source()
    with connection() as c:c.execute('DELETE FROM jobsearch.runs')
    assert not supervisor.run_one()
    with connection() as c:assert c.execute('SELECT count(*) n FROM jobsearch.runs').fetchone()['n']==0


@pytest.mark.parametrize('termination',['kill','term'])
def test_process_death_releases_provider_and_recoverable_claim(tmp_path,termination):
    _,jid=source();marker=tmp_path/'started'
    code="""from pathlib import Path
import sys,time
from ai_core.agents import supervisor
def collect(run):
 Path(sys.argv[1]).touch()
 time.sleep(60)
 return []
supervisor.collect=collect
sys.argv=['worker','--once']
raise SystemExit(supervisor.main())
"""
    # Preserve marker argument for the patched collector after main parses argv.
    code=code.replace("def collect(run):", "marker=sys.argv[1]\ndef collect(run):").replace('Path(sys.argv[1]).touch()','Path(marker).touch()')
    env={**os.environ,'JOBSEARCH_TELEMETRY':'false','JOBSEARCH_WORKER_SHUTDOWN_SECONDS':'1'}
    child=subprocess.Popen([sys.executable,'-c',code,str(marker)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+8
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert marker.exists()
        child.send_signal(signal.SIGKILL if termination=='kill' else signal.SIGTERM)
        child.wait(timeout=8)
        assert child.returncode==(-signal.SIGKILL if termination=='kill' else 143)
        expire(jid)
        with leases.claim('replacement') as run:assert run and run['attempts']==2
    finally:
        if child.poll() is None:child.kill();child.wait()


def test_bad_timing_rejected():
    with pytest.raises(ValueError):Settings(worker_lease_seconds=10,worker_heartbeat_seconds=9)


def test_restricted_worker_role_can_claim_and_finish_without_private_access(monkeypatch):
    from contextlib import contextmanager
    source()
    with connection() as c:
        c.execute('GRANT USAGE ON SCHEMA jobsearch TO jobsearch_worker')
        c.execute('GRANT SELECT,INSERT,UPDATE ON jobsearch.sources,jobsearch.runs,jobsearch.jobs,jobsearch.observations TO jobsearch_worker')
        c.execute('GRANT INSERT ON jobsearch.audit_events TO jobsearch_worker')
        c.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA jobsearch TO jobsearch_worker')
    @contextmanager
    def restricted():
        # SET ROLE lasts for the session, so it only ever goes on a connection that closes after use.
        with direct_connection() as c:
            c.autocommit=True
            c.execute('SET ROLE jobsearch_worker')
            c.autocommit=False
            yield c
    monkeypatch.setattr(leases,'connection',restricted)
    monkeypatch.setattr(leases,'direct_connection',restricted)
    monkeypatch.setattr(supervisor,'connection',restricted)
    monkeypatch.setattr(supervisor,'collect',lambda run:[sample()])
    assert supervisor.run_one()
    with restricted() as c:
        assert c.execute("SELECT status FROM jobsearch.runs").fetchone()['status']=='completed'
        assert not c.execute("SELECT has_table_privilege(current_user,'jobsearch.private_intake','SELECT') allowed").fetchone()['allowed']


def test_queue_metrics_distinguish_waiting_and_running():
    from src.observability import DatabaseMetrics
    source()
    def metrics():
        return {sample.name:sample.value for metric in DatabaseMetrics().collect() for sample in metric.samples}
    values=metrics()
    assert values['jobsearch_database_metrics_up']==1
    assert values['jobsearch_queue_ready']==1 and values['jobsearch_queue_running']==0
    assert values['jobsearch_queue_oldest_seconds']>=0
    with leases.claim('worker'):
        values=metrics()
        assert values['jobsearch_queue_ready']==0 and values['jobsearch_queue_running']==1


def test_run_budget_prevents_indefinite_renewal():
    _,jid=source()
    with leases.claim('worker') as run:
        with connection() as c:
            c.execute("UPDATE jobsearch.runs SET started_at=clock_timestamp()-interval '3 hours' WHERE id=%s",(jid,))
        assert not leases.renew(run)
        with connection() as c:
            with pytest.raises(leases.LeaseLost):leases.require_lease(c,run)
