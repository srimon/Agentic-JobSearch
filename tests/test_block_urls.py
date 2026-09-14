import pytest
from ai_core.agents.researcher import greenhouse_posting_url,collect
from src.guardrails.content import safe_link

def test_block_feed_http_is_upgraded_without_changing_identity():
    job={'id':5317296008,'absolute_url':'http://block.xyz/careers/jobs/5317296008?gh_jid=5317296008'}
    assert greenhouse_posting_url('block',job)=='https://block.xyz/careers/jobs/5317296008?gh_jid=5317296008'
    assert not safe_link(job['absolute_url'])

@pytest.mark.parametrize('url',[
    'http://block.xyz.evil.example/careers/jobs/123',
    'http://user@block.xyz/careers/jobs/123',
    'http://block.xyz:80/careers/jobs/123',
    'http://block.xyz/careers/jobs/456',
    'http://block.xyz/careers/jobs/123?gh_jid=456',
    'http://block.xyz/careers/jobs/123?redirect=https://evil.example',
    'http://block.xyz/careers/jobs/123#other',
    'javascript:alert(1)',
])
def test_only_exact_verified_block_shape_can_be_upgraded(url):
    assert greenhouse_posting_url('block',{'id':123,'absolute_url':url})==url
    assert not safe_link(url)

def test_other_boards_and_existing_https_are_unchanged():
    for board,url in [('other','http://block.xyz/careers/jobs/123'),('block','https://block.xyz/careers/jobs/123')]:
        assert greenhouse_posting_url(board,{'id':123,'absolute_url':url})==url

def test_whole_board_still_fails_on_an_unapproved_link(monkeypatch):
    import ai_core.agents.researcher as researcher
    jobs=[{'id':123,'internal_job_id':1,'title':'Accountant','absolute_url':'http://block.xyz/careers/jobs/123'},
          {'id':456,'internal_job_id':2,'title':'Accountant','absolute_url':'http://unapproved.example/job'}]
    monkeypatch.setattr(researcher,'fetch_json',lambda *args,**kwargs:{'jobs':jobs})
    with pytest.raises(ValueError,match='Unsafe posting URL'):
        collect({'provider':'greenhouse','board':'block','company':'Block'})
