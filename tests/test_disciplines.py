"""The Discipline filter (the owner, 18 Sep 2026): the ten disciplines, their keywords, the ``?discipline=``
parameter and the listings the query keeps.

The words live in two places on purpose - ``src/applications/disciplines.py`` for the query and
``frontend/app/disciplines.mjs`` for the screen - so the first test here reads the module's JSON literal and
refuses any difference between them. The rest need the disposable test database, like the other route tests.
"""
import json
import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, current_user
from src.applications.disciplines import DISCIPLINES, DISCIPLINE_IDS, KEYWORDS, LABELS, matches, parse, pattern_for
from src.db.store import connection

MODULE = Path(__file__).resolve().parents[1] / 'frontend/app/disciplines.mjs'


def test_the_ten_are_the_owners_in_the_owners_order():
    assert [label for _, label, _ in DISCIPLINES] == [
        'Software Engineering', 'AI Engineering', 'Data Engineering', 'Data Governance', 'Data Ingestion',
        'Data loading', 'Data lineage', 'Data Quality', 'Technical Program Management',
        'Technical Project Management']
    assert len(DISCIPLINE_IDS) == len(set(DISCIPLINE_IDS)) == 10
    for identifier, label, keywords in DISCIPLINES:
        assert re.fullmatch(r'[a-z][a-z0-9-]*', identifier), identifier
        assert len(keywords) >= 5, identifier
        for keyword in keywords:
            assert re.fullmatch(r'[a-z0-9]+( [a-z0-9]+)*', keyword), identifier + ': ' + keyword


def test_the_screen_and_the_query_use_the_same_words():
    """The module the opportunities screen imports carries exactly these ten with exactly these keywords."""
    source = MODULE.read_text(encoding='utf-8')
    literal = re.search(r'export const DISCIPLINES = (\[.*?\n\]);', source, re.S)
    assert literal, 'frontend/app/disciplines.mjs writes its data as a JSON literal so it can be read here'
    written = json.loads(literal.group(1))
    assert [item['id'] for item in written] == DISCIPLINE_IDS
    assert {item['id']: item['label'] for item in written} == LABELS
    assert {item['id']: item['keywords'] for item in written} == KEYWORDS


def test_the_parameter_takes_the_ten_and_nothing_else():
    assert parse('') == [] and parse(None) == []
    assert parse('data-quality') == ['data-quality']
    assert parse('data-quality,ai-engineering') == ['data-quality', 'ai-engineering']
    assert parse(' data-quality , data-quality ') == ['data-quality'], 'a repeat is not a second filter'
    for wrong in ('nope', 'data-quality,nope', 'DATA-QUALITY', 'data quality'):
        with pytest.raises(ValueError):
            parse(wrong)


def test_matching_is_case_insensitive_and_word_boundary_aware():
    assert matches('data-lineage', 'Data Lineage Architect')
    assert matches('data-lineage', 'We own data-lineage end to end')
    assert not matches('data-lineage', 'A lineage-free tooling stack')
    assert not matches('data-lineage', 'lineage'), 'the keyword is the phrase, never the bare noun'
    assert matches('software-engineering', 'SENIOR SOFTWARE ENGINEERS')
    assert not matches('ai-engineering', 'Said engineer, said the chair')
    assert not matches('data-engineering', 'Sparkling water sales')
    with pytest.raises(ValueError):
        pattern_for(['nope'])
    with pytest.raises(ValueError):
        pattern_for([])


JOBS = [
    ('VP, Data Engineering', 'Own the Snowflake warehouse and its pipelines.'),
    ('Director, AI Engineering', 'Ship agentic AI products with the platform team.'),
    ('Director, Data Governance', 'Chair the stewardship council.'),
    ('Head of Data Quality', 'Great Expectations and SODA across the estate.'),
    ('Senior Technical Program Manager', 'Run the delivery programme.'),
    ('Chef de cuisine', 'A kitchen, and a lineage-free tooling stack in the back office.'),
    ('Director, Analytics', 'You will own data lineage and column level lineage for the warehouse.'),
]


@pytest.fixture()
def client():
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1', 'Use a dedicated test database'
    with connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d'] == 'jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.users,jobsearch.jobs,jobsearch.sources CASCADE')
        member = c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','member',ARRAY['member']) RETURNING *").fetchone()
        source = c.execute("INSERT INTO jobsearch.sources(company,provider,board) VALUES('Example','lever','example') RETURNING id").fetchone()['id']
        for n, (title, description) in enumerate(JOBS):
            c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,
                reason,description,url,content_hash,posted_at) VALUES(%s,%s,%s,'Example Co',%s,'Remote - US','Remote','us_based','Director','match',
                'test',%s,%s,%s,now()-(%s*interval '1 minute'))""",
                      (uuid.uuid4(), source, 'disc-' + str(n), title, description,
                       'https://example.com/disciplines/' + str(n), 'hash-disc-' + str(n), n))
    app.dependency_overrides[current_user] = lambda: member
    with TestClient(app) as t:
        yield t
    app.dependency_overrides.clear()


def titles(response):
    assert response.status_code == 200, response.text
    return sorted(job['title'] for job in response.json()['items'])


def test_a_chosen_discipline_reads_the_title_and_the_description(client):
    assert titles(client.get('/api/jobs?discipline=data-engineering')) == ['VP, Data Engineering']
    assert titles(client.get('/api/jobs?discipline=ai-engineering')) == ['Director, AI Engineering']
    assert titles(client.get('/api/jobs?discipline=data-quality')) == ['Head of Data Quality']
    assert titles(client.get('/api/jobs?discipline=technical-program-management')) == ['Senior Technical Program Manager']
    # the description alone is enough, and "lineage-free" is not Data lineage
    assert titles(client.get('/api/jobs?discipline=data-lineage')) == ['Director, Analytics']


def test_several_disciplines_are_an_or_and_compose_with_the_other_filters(client):
    both = titles(client.get('/api/jobs?discipline=data-engineering,data-quality'))
    assert both == ['Head of Data Quality', 'VP, Data Engineering']
    # composed with the search box, the level and the state filter beside it
    assert titles(client.get('/api/jobs', params={'discipline': 'data-engineering,data-quality', 'q': 'VP'})) == ['VP, Data Engineering']
    assert titles(client.get('/api/jobs', params={'discipline': 'data-engineering', 'level': 'Director'})) == ['VP, Data Engineering']
    assert client.get('/api/jobs', params={'discipline': 'data-engineering', 'state': 'TX'}).json()['total'] == 0
    assert client.get('/api/jobs', params={'discipline': 'data-engineering', 'q': 'kitchen'}).json()['total'] == 0
    # nothing chosen leaves the list as it was
    assert client.get('/api/jobs').json()['total'] == len(JOBS)


def test_the_state_and_title_facets_are_counted_under_the_chosen_disciplines(client):
    body = client.get('/api/jobs', params={'discipline': 'data-quality'}).json()
    assert body['total'] == 1
    assert [f['value'] for f in body['facets']['states']] == ['remote']
    assert [f['count'] for f in body['facets']['states']] == [1]


def test_an_unknown_discipline_is_refused(client):
    assert client.get('/api/jobs?discipline=nope').status_code == 422
    assert client.get('/api/jobs?discipline=data-quality,nope').status_code == 422
    assert client.get('/api/jobs?discipline=' + 'x' * 500).status_code == 422


def test_the_filter_paginates_in_sql(client):
    with connection() as c:
        source = c.execute('SELECT id FROM jobsearch.sources LIMIT 1').fetchone()['id']
        for n in range(30):
            c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,
                reason,description,url,content_hash,posted_at) VALUES(%s,%s,%s,'Example Co','Staff Software Engineer','Remote - US','Remote','us_based',
                'Director','match','test','Build the product.',%s,%s,now())""",
                      (uuid.uuid4(), source, 'page-disc-' + str(n), 'https://example.com/page-disc/' + str(n), 'hash-page-disc-' + str(n)))
    first = client.get('/api/jobs?discipline=software-engineering&page=1').json()
    second = client.get('/api/jobs?discipline=software-engineering&page=2').json()
    assert first['total'] == second['total'] == 30
    assert len(first['items']) == 25 and len(second['items']) == 5
    assert not {job['id'] for job in first['items']} & {job['id'] for job in second['items']}
