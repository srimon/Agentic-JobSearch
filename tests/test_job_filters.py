"""State and job-title-family filters: the location normaliser, title families and the /api/jobs parameters."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from src.api.main import app, current_user
from src.db.store import connection
from src.applications.job_filters import location_states, title_family, facet_summary, STATES, REMOTE, OUTSIDE, OTHER_TITLES


@pytest.mark.parametrize('location,expected', [
    # City, full state name, country (the dominant production format)
    ('New York, New York, USA', {'NY'}),
    ('Boston, Massachusetts, USA', {'MA'}),
    ('Renton, Washington, United States', {'WA'}),
    ('Parsippany-Troy Hills, New Jersey, USA', {'NJ'}),
    ('King of Prussia, Pennsylvania, USA', {'PA'}),
    # City, ST
    ('San Mateo, CA, United States', {'CA'}),
    ('San Francisco, CA', {'CA'}),
    ('Chicago, IL 60601', {'IL'}),
    ('Portland, OR', {'OR'}),
    ('Indianapolis, IN', {'IN'}),
    # State only
    ('Texas, USA', {'TX'}),
    ('Pennsylvania', {'PA'}),
    ('West Virginia, USA', {'WV'}),
    ('Virginia, USA', {'VA'}),
    # City names that contain another state's name
    ('Kansas City, Missouri, USA', {'MO'}),
    ('Kansas City, Kansas, USA', {'KS'}),
    ('Canada, Kentucky, USA', {'KY'}),
    ('Manhattan, Kansas, USA', {'KS'}),
    # District of Columbia
    ('Washington, District of Columbia, USA', {'DC'}),
    ('Washington, D.C.', {'DC'}),
    ('Washington DC', {'DC'}),
    # Multi-location strings: a job matches every listed state
    ('San Francisco, CA • New York, NY • United States', {'CA', 'NY'}),
    ('Mountain View, California; San Francisco, California', {'CA'}),
    ('New York, NY, USA; San Francisco, CA, USA', {'NY', 'CA'}),
    ('Maryland; Virginia; Washington, D.C.', {'MD', 'VA', 'DC'}),
    ('Austin; New York City; San Francisco', {'TX', 'NY', 'CA'}),
    ('Palo Alto; San Francisco', {'CA'}),
    # Known major city without a state
    ('San Francisco', {'CA'}),
    ('Seattle', {'WA'}),
    # US or remote without a state
    ('United States', {REMOTE}),
    ('USA', {REMOTE}),
    ('Remote - US', {REMOTE}),
    ('United States - Remote', {REMOTE}),
    ('Remote, United States', {REMOTE}),
    ('US-based remote', {REMOTE}),
    ('Remote', {REMOTE}),
    ('Hybrid', {REMOTE}),
    ('Distributed', {REMOTE}),
    ('', {REMOTE}),
    (None, {REMOTE}),
    ('Ramblewood', {REMOTE}),
    ('Remote - California', {'CA'}),
    # Outside the US, alone or alongside a US option
    ('Tokyo, Japan', {OUTSIDE}),
    ('Bengaluru, India', {OUTSIDE}),
    ('India', {OUTSIDE}),
    ('Toronto, ON', {OUTSIDE}),
    ('Remote (United States | Canada)', {REMOTE, OUTSIDE}),
    ('UK,  USA', {REMOTE, OUTSIDE}),
    ('Toronto; San Francisco, CA', {OUTSIDE, 'CA'}),
])
def test_location_states(location, expected):
    assert location_states(location) == expected


def test_every_state_name_and_code_maps_to_itself():
    for code, name in STATES.items():
        assert location_states(f'Somewhere, {name}, USA') == {code}
        assert location_states(f'Somewhere, {code}') == {code}


def test_lowercase_two_letter_words_are_not_states():
    assert location_states('Boston, ma') == {'MA'}  # "ma" is not read as a code; the known city still maps
    assert location_states('Anywhere, me') == {REMOTE}


@pytest.mark.parametrize('title,expected', [
    ('VP, Data Engineering', 'Data Engineering & Platforms'),
    ('Director of Engineering, Data', 'Data Engineering & Platforms'),
    ('Data Platform Engineer, VP II - State Street Investment Management', 'Data Engineering & Platforms'),
    ('Director, AI Engineering (Remote - eligible)', 'AI Engineering'),
    ('Gen AI Engineering Analyst - Vice President', 'AI Engineering'),
    ('Director, AI Platform', 'AI Platforms & Infrastructure'),
    ('Director, Data Governance & Compliance', 'Data & AI Governance and Risk'),
    ('Executive Director, Technology Business Risk and Controls - Data and AI', 'Data & AI Governance and Risk'),
    ('AI Security Architecture- VP', 'Security'),
    ('Director of Product, Growth/AI', 'Product Management'),
    ('Applied AIML Data Scientist Lead - Vice President', 'Data Science & Machine Learning'),
    ('Director AI/ML Engineering', 'Data Science & Machine Learning'),
    ('IT Director, Data & AI Architecture', 'Architecture'),
    ('Senior Director, Business Intelligence & Analytics', 'Analytics & Business Intelligence'),
    ('Director of Data Management and Operations', 'Data Management & Strategy'),
    ('Vice President, AI Strategy Lead', 'AI Strategy & Transformation'),
    ('Chief Data Officer', 'Chief Data / AI / Technology Officer'),
    ('CTO', 'Chief Data / AI / Technology Officer'),
    ('Data Platform Technical Program Director', 'Data Engineering & Platforms'),
    ('Director, Finance', OTHER_TITLES),
    ('', OTHER_TITLES),
])
def test_title_family(title, expected):
    assert title_family(title) == expected


def test_facets_respect_the_other_filter():
    rows = [{'location': 'Austin, Texas, USA', 'title': 'VP, Data Engineering', 'n': 2},
            {'location': 'Boston, MA', 'title': 'Director, Data Analytics', 'n': 1},
            {'location': 'Remote - US', 'title': 'VP, Data Engineering', 'n': 1}]
    facets, locations, titles = facet_summary(rows, 'TX', '')
    assert locations == ['Austin, Texas, USA'] and titles == []
    assert {f['value']: f['count'] for f in facets['states']} == {'MA': 1, 'TX': 2, REMOTE: 1}
    assert facets['titles'] == [{'value': 'Data Engineering & Platforms', 'label': 'Data Engineering & Platforms', 'count': 2}]
    facets, _, titles = facet_summary(rows, '', 'Analytics & Business Intelligence')
    assert titles == ['Director, Data Analytics']
    assert [f['value'] for f in facets['states']] == ['MA']
    facets, _, _ = facet_summary([], 'WY', OTHER_TITLES)
    assert facets['states'] == [{'value': 'WY', 'label': 'Wyoming', 'count': 0}]
    assert facets['titles'] == [{'value': OTHER_TITLES, 'label': OTHER_TITLES, 'count': 0}]


JOBS = [
    ('New York, New York, USA', 'VP, Data Engineering', 'match'),
    ('Jersey City, New Jersey, USA', 'Director, Data Governance & Compliance', 'match'),
    ('San Francisco, CA • New York, NY • United States', 'Director, AI Engineering', 'match'),
    ('Austin, Texas, USA', 'Senior Director, Data Engineering', 'match'),
    ('Remote - US', 'Director, Data Analytics', 'match'),
    ('Boston, Massachusetts, USA', 'Director, Data Governance', 'review'),
]


@pytest.fixture()
def client():
    assert os.environ.get('JOBSEARCH_AUTH_TEST') == '1'
    with connection() as c:
        assert c.execute('SELECT current_database() d').fetchone()['d'] == 'jobsearch_auth_test'
        c.execute('TRUNCATE jobsearch.users,jobsearch.jobs,jobsearch.sources CASCADE')
        users = {role: c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local',%s,%s) RETURNING *", (role, [role])).fetchone()
                 for role in ('member', 'administrator')}
        source = c.execute("INSERT INTO jobsearch.sources(company,provider,board) VALUES('Example','lever','example') RETURNING id").fetchone()['id']
        for n, (location, title, status) in enumerate(JOBS):
            c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,
                reason,description,url,content_hash,posted_at) VALUES(%s,%s,%s,'Example Co',%s,%s,'Remote','us_based','Director',%s,'test','d',%s,'h',now()-(%s*interval '1 minute'))""",
                      (uuid.uuid4(), source, 'filter-' + str(n), title, location, status, 'https://example.com/filters/' + str(n), n))
    app.dependency_overrides[current_user] = lambda: users['member']
    with TestClient(app) as t:
        t.users = users
        yield t
    app.dependency_overrides.clear()


def titles(response):
    assert response.status_code == 200, response.text
    return sorted(job['title'] for job in response.json()['items'])


def test_state_filter_matches_any_listed_location(client):
    assert titles(client.get('/api/jobs?state=NY')) == ['Director, AI Engineering', 'VP, Data Engineering']
    assert titles(client.get('/api/jobs?state=CA')) == ['Director, AI Engineering']
    assert titles(client.get('/api/jobs?state=remote')) == ['Director, Data Analytics']
    assert client.get('/api/jobs?state=WY').json()['total'] == 0
    body = client.get('/api/jobs').json()
    assert {f['value']: f['count'] for f in body['facets']['states']} == {'CA': 1, 'NJ': 1, 'NY': 2, 'TX': 1, 'remote': 1}


def test_title_filter_search_and_state_combine(client):
    family = 'Data Engineering & Platforms'
    assert titles(client.get('/api/jobs', params={'title': family})) == ['Senior Director, Data Engineering', 'VP, Data Engineering']
    assert titles(client.get('/api/jobs', params={'title': family, 'state': 'TX'})) == ['Senior Director, Data Engineering']
    assert titles(client.get('/api/jobs', params={'title': family, 'q': 'VP'})) == ['VP, Data Engineering']
    body = client.get('/api/jobs', params={'state': 'NY', 'sort': 'recommended'}).json()
    assert {f['value']: f['count'] for f in body['facets']['titles']} == {family: 1, 'AI Engineering': 1}
    # The state facet is counted under the chosen title, and the chosen state stays offered.
    body = client.get('/api/jobs', params={'title': family, 'state': 'CA'}).json()
    assert body['total'] == 0 and {f['value'] for f in body['facets']['states']} == {'NY', 'TX', 'CA'}


def test_unknown_values_are_rejected(client):
    assert client.get('/api/jobs?state=ZZ').status_code == 422
    assert client.get('/api/jobs', params={'title': 'Anything'}).status_code == 422


def test_facets_follow_role_visibility(client):
    member = client.get('/api/jobs').json()
    assert 'MA' not in {f['value'] for f in member['facets']['states']}
    assert client.get('/api/jobs?view=review&state=MA').status_code == 403
    app.dependency_overrides[current_user] = lambda: client.users['administrator']
    review = client.get('/api/jobs?view=review&state=MA').json()
    assert review['total'] == 1 and [f['value'] for f in review['facets']['states']] == ['MA']


def test_state_filter_paginates_in_sql(client):
    with connection() as c:
        source = c.execute('SELECT id FROM jobsearch.sources LIMIT 1').fetchone()['id']
        for n in range(30):
            c.execute("""INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,
                reason,description,url,content_hash,posted_at) VALUES(%s,%s,%s,'Example Co','VP, Data Engineering',%s,'Remote','us_based','Director','match','test','d',%s,'h',now())""",
                      (uuid.uuid4(), source, 'page-' + str(n), 'Dallas, TX' if n % 2 else 'Plano, Texas, USA', 'https://example.com/page/' + str(n)))
    first = client.get('/api/jobs?state=TX&page=1').json()
    second = client.get('/api/jobs?state=TX&page=2').json()
    assert first['total'] == second['total'] == 31
    assert len(first['items']) == 25 and len(second['items']) == 6
    assert not {j['id'] for j in first['items']} & {j['id'] for j in second['items']}
