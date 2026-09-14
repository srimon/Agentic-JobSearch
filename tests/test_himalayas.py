from datetime import datetime,timedelta,timezone
import pytest
from ai_core.tools.himalayas import collect_himalayas
from ai_core.tools.web_search import FetchError
from ai_core.agents.researcher import collect_snapshot
from src.pipelines.classification import classify

def job(**changes):
    now=datetime.now(timezone.utc)
    return {'guid':'https://himalayas.app/companies/example/jobs/director-data','title':'Director, Data Engineering','companyName':'Example','locationRestrictions':['United States'],'description':'<p>Data leadership</p>','pubDate':int((now-timedelta(days=1)).timestamp()),'expiryDate':int((now+timedelta(days=1)).timestamp()),**changes}
def test_maps_attributed_job_without_inventing_geography(monkeypatch):
    monkeypatch.setattr('ai_core.tools.himalayas.fetch_json',lambda *a,**k:{'jobs':[job(),job(guid='https://himalayas.app/companies/example/jobs/another',locationRestrictions=[])]})
    rows=collect_himalayas();assert len(rows)==2
    assert classify(rows[0])['match_status']=='match';assert rows[0]['description']=='Data leadership'
    assert rows[0]['evidence']['attribution']=='Himalayas';assert rows[0]['url']==rows[0]['source_job_id']
    assert rows[1]['country']=='';assert classify(rows[1])['country_status']=='unknown'
    assert not collect_snapshot({'provider':'himalayas'},collector=lambda _:rows).complete_board
def test_expired_and_duplicate_rows_are_not_imported(monkeypatch):
    monkeypatch.setattr('ai_core.tools.himalayas.fetch_json',lambda *a,**k:{'jobs':[job(),job(),job(guid='https://himalayas.app/companies/example/jobs/expired',expiryDate=1)]})
    assert len(collect_himalayas())==1
@pytest.mark.parametrize('url',['http://himalayas.app/companies/a/jobs/b','https://himalayas.app.evil.test/companies/a/jobs/b','https://secret@himalayas.app/companies/a/jobs/b','https://himalayas.app:444/companies/a/jobs/b','https://himalayas.app/profile'])
def test_unapproved_links_are_rejected(url,monkeypatch):
    monkeypatch.setattr('ai_core.tools.himalayas.fetch_json',lambda *a,**k:{'jobs':[job(guid=url)]})
    with pytest.raises(FetchError):collect_himalayas()
def test_bounded_pagination_never_means_complete_board(monkeypatch):
    calls=[]
    def fetch(url,**_):
        calls.append(url);return {'jobs':[job(guid=f'https://himalayas.app/companies/example/jobs/{len(calls)}-{i}') for i in range(20)]}
    monkeypatch.setattr('ai_core.tools.himalayas.fetch_json',fetch);monkeypatch.setattr('ai_core.tools.himalayas.time.sleep',lambda _:None)
    assert len(collect_himalayas())==100;assert len(calls)==5
    assert 'country=US' in calls[0] and 'seniority=Director%2CExecutive' in calls[0]
