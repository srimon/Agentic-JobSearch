import os
import pytest
from src.db.store import connection
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
