import os
import pytest
from src.db.store import connection, direct_connection
from ai_core.agents.supervisor import enqueue,run_one

@pytest.fixture
def source():
    assert os.environ.get('JOBSEARCH_AUTH_TEST')=='1'
    with connection() as c:
        assert c.execute('SELECT current_database() name').fetchone()['name']=='jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.sources,jobsearch.runs,jobsearch.jobs,jobsearch.observations,jobsearch.saved_jobs CASCADE')
        row=c.execute("INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Example','ashby','example',true) RETURNING id").fetchone()
        enqueue(c,row['id'],'test')
    return row['id']

def sample(key,country='US',title='Director Data Engineering'):
    return dict(source_job_id=key,company='Example',title=title,location='United States',country=country,work_mode='Remote',description='Data leadership',url='https://example.com/job',posted_at=None,evidence={})

def test_decision_totals_and_duplicates(source,monkeypatch):
    monkeypatch.setattr('ai_core.agents.supervisor.collect',lambda run:[sample('1'),sample('1'),sample('2','CA'),sample('3',title='Sales representative')])
    assert run_one()
    with connection() as c:
        row=c.execute('SELECT * FROM jobsearch.runs WHERE source_id=%s',(source,)).fetchone()
        assert row['status']=='completed'
        assert row['decision_counts']=={'match':1,'duplicate':1,'outside_us':1,'outside_role':1}
        assert sum(row['decision_counts'].values())==row['fetched']==4
        assert c.execute('SELECT count(*) n FROM jobsearch.jobs').fetchone()['n']==1

def test_failed_run_does_not_invent_totals(source,monkeypatch):
    def fail(run): raise ValueError('sensitive upstream body')
    monkeypatch.setattr('ai_core.agents.supervisor.collect',fail)
    run_one()
    with connection() as c:
        row=c.execute('SELECT * FROM jobsearch.runs WHERE source_id=%s',(source,)).fetchone()
        assert row['status']=='failed' and row['error']=='ValueError'
        assert row['decision_counts'] is None


def test_public_source_cooldown(source):
    with connection() as c:
        row=c.execute("INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Remotive','remotive','remote',true) RETURNING id").fetchone()
        assert enqueue(c,row['id'],'test')
        c.execute("UPDATE jobsearch.runs SET status='failed',error='FetchError' WHERE source_id=%s",(row['id'],))
        assert enqueue(c,row['id'],'test') is None


@pytest.mark.parametrize('provider', ['ashby', 'dice'])
@pytest.mark.parametrize('rejected', [
    {'title': 'Manager, CIO Advisory'},
    {'country': 'CA'},
    {'title': 'Director Data sk-' + 'a' * 30},
])
def test_observed_exclusion_retires_old_match_without_changing_owner_state(source, monkeypatch, provider, rejected):
    import uuid
    from contextlib import contextmanager
    from ai_core.agents import leases, supervisor

    with connection() as c:
        c.execute('UPDATE jobsearch.sources SET provider=%s WHERE id=%s', (provider, source))
    monkeypatch.setattr(supervisor, 'collect', lambda run: [sample('one')])
    assert run_one()
    with connection() as c:
        old = c.execute('SELECT * FROM jobsearch.jobs').fetchone()
        uid = c.execute("INSERT INTO jobsearch.users(issuer,subject) VALUES('local',%s) RETURNING id", (str(uuid.uuid4()),)).fetchone()['id']
        c.execute("INSERT INTO jobsearch.saved_jobs(user_id,job_id,stage) VALUES(%s,%s,'applied')", (uid, old['id']))
        c.execute("INSERT INTO jobsearch.job_archives(user_id,identity,job_id,final_status) VALUES(%s,%s,%s,'applied')", (uid, old['url'], old['id']))
        # Opaque fixture: collector must neither read nor modify private bytes.
        c.execute('INSERT INTO jobsearch.private_applications(user_id,job_id,payload) VALUES(%s,%s,%s)', (uid, old['id'], os.urandom(32)))
        tables = ('saved_jobs', 'job_archives', 'private_applications')
        before = {t: c.execute('SELECT * FROM jobsearch.' + t + ' WHERE user_id=%s', (uid,)).fetchall() for t in tables}
        assert enqueue(c, source, 'test')

    @contextmanager
    def restricted():
        # SET ROLE lasts for the session, so it only ever goes on a connection that closes after use.
        with direct_connection() as c:
            c.autocommit = True
            c.execute('SET ROLE jobsearch_worker')
            c.autocommit = False
            yield c

    monkeypatch.setattr(supervisor, 'connection', restricted)
    monkeypatch.setattr(leases, 'connection', restricted)
    monkeypatch.setattr(leases, 'direct_connection', restricted)
    monkeypatch.setattr(supervisor, 'collect', lambda run: [sample('one', **rejected), sample('never-stored', **rejected)])
    assert run_one()
    with connection() as c:
        rows = c.execute('SELECT * FROM jobsearch.jobs').fetchall()
        assert len(rows) == 1
        actual = rows[0]
        assert actual['match_status'] == 'exclude'
        assert actual['last_seen_at'] >= old['last_seen_at']
        for field in ('id', 'title', 'description', 'evidence', 'content_hash', 'url'):
            assert actual[field] == old[field]
        after = {t: c.execute('SELECT * FROM jobsearch.' + t + ' WHERE user_id=%s', (uid,)).fetchall() for t in tables}
        assert after == before
        runs = c.execute('SELECT status,decision_counts FROM jobsearch.runs WHERE source_id=%s ORDER BY created_at DESC', (source,)).fetchall()
        assert runs[0]['status'] == 'completed'
        assert sum(runs[0]['decision_counts'].values()) == 2
