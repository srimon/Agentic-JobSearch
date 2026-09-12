import pytest
from ai_core.tools.public_feeds import collect_public
from src.pipelines.classification import classify

@pytest.mark.parametrize('provider',['jobicy','remotive'])
def test_feed_mapping_and_missing_timezone(provider,monkeypatch):
    job={'id':1,'url':'https://example.com/job','jobTitle':'Director Data','title':'Director Data','companyName':'Employer','company_name':'Employer','jobGeo':'USA','candidate_required_location':'USA','jobDescription':'<p>Data</p>','description':'<p>Data</p>','pubDate':'2026-01-01 01:00:00','publication_date':'2026-01-01 01:00:00'}
    monkeypatch.setattr('ai_core.tools.public_feeds.fetch_json',lambda url:{'jobs':[job]})
    row=collect_public(provider)[0]
    assert row['posted_at'] is None
    assert row['description']=='Data'
    assert row['evidence']['provider']==provider
    assert classify(row)['match_status']=='match'
