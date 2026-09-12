from ai_core.tools.dice import decode,collect_dice
from src.pipelines.classification import classify

def test_mcp_sse():
    assert decode(b'event: message\ndata: {"result":{"data":[]}}\n\n')=={'result':{'data':[]}}

def test_dice_mapping(monkeypatch):
    import ai_core.tools.dice as d
    class Fake:
        def search(self,keyword,page):
            return {'data':[{'guid':'one','title':'Director Data Engineering','companyName':'Actual employer','jobLocation':{'displayName':'Boston, Massachusetts, USA'},'summary':'Data team','detailsPageUrl':'https://www.dice.com/job-detail/one','companyPageUrl':'https://www.dice.com/company/one','postedDate':'2026-01-01T00:00:00Z','modifiedDate':'2099-01-01T00:00:00Z','workplaceTypes':['Hybrid']}], 'metadata':{'totalPages':1}}
    monkeypatch.setattr(d,'DiceClient',Fake); monkeypatch.setattr(d,'QUERIES',['Director Data']); monkeypatch.setattr(d.time,'sleep',lambda n:None)
    rows=collect_dice()
    assert rows[0]['company']=='Actual employer'
    assert rows[0]['posted_at'].year==2026
    assert rows[0]['evidence']['description_is_summary']
    assert classify(rows[0])['match_status']=='match'
