"""Deterministic ATS collection; no model or credentials are exposed to content."""
import re
import time
from dataclasses import dataclass
from ai_core.tools.web_search import fetch_json
from src.guardrails.content import plain_text, safe_link
from src.pipelines.classification import posting_date, title_match


@dataclass(frozen=True)
class CollectionResult:
    jobs: list
    complete_board: bool


def collect_snapshot(source, *, collector=None):
    """Only fully paginated employer boards can establish absence.

    Search results and public feeds are windows, even if every requested page
    succeeded or the window returned no matching jobs.
    """
    jobs = (collector or collect)(source)
    complete = source['provider'] in {'ashby', 'greenhouse', 'lever'}
    return CollectionResult(jobs=jobs, complete_board=complete)


def collect(source):
    provider,board=source['provider'],source['board']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',board): raise ValueError('Invalid board identifier')
    if provider in ('jobicy','remotive'):
        from ai_core.tools.public_feeds import collect_public
        return collect_public(provider)
    if provider=='dice':
        from ai_core.tools.dice import collect_dice
        return collect_dice()
    rows=[]
    if provider=='ashby':
        payload=fetch_json(f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true')
        for j in payload['jobs']:
            if not j.get('isListed',True): continue
            addr=(j.get('address') or {}).get('postalAddress') or {}
            locations=[(j.get('location',''),addr.get('addressCountry',''))]
            locations += [(x.get('location',''),(x.get('address') or {}).get('addressCountry','')) for x in j.get('secondaryLocations',[])]
            chosen=next((x for x in locations if x[1].upper() in ('USA','US','UNITED STATES')),locations[0])
            rows.append(dict(source_job_id=j.get('id') or j['jobUrl'],title=j['title'],location=chosen[0],country=chosen[1],
                work_mode={'OnSite':'On-site','Hybrid':'Hybrid','Remote':'Remote'}.get(j.get('workplaceType'),'Unknown'),
                description=j.get('descriptionPlain') or plain_text(j.get('descriptionHtml','')),url=j['jobUrl'],
                posted_at=posting_date(j.get('publishedAt')),evidence={'posting_date_field':'publishedAt','posting_date_semantics':'last_published','locations':locations}))
    elif provider=='greenhouse':
        payload=fetch_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true')
        for j in payload['jobs']:
            if j.get('internal_job_id') is None: continue
            posted=None
            if title_match(j['title'])[1]!='exclude':
                time.sleep(.25)
                detail=fetch_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{j["id"]}')
                posted=posting_date(detail.get('first_published'))
            rows.append(dict(source_job_id=str(j['id']),title=j['title'],location=j.get('location',{}).get('name',''),country='',
                work_mode='Unknown',description=plain_text(j.get('content','')),url=j['absolute_url'],posted_at=posted,
                evidence={'posting_date_field':'first_published','updated_at_is_not_posted_at':True}))
    elif provider=='lever':
        for offset in range(0,20000,100):
            page=fetch_json(f'https://api.lever.co/v0/postings/{board}?mode=json&skip={offset}&limit=100')
            if not isinstance(page,list): raise ValueError('Unexpected source response')
            for j in page:
                rows.append(dict(source_job_id=j['id'],title=j['text'],location=j.get('categories',{}).get('location',''),country='',
                    work_mode={'remote':'Remote','hybrid':'Hybrid','on-site':'On-site'}.get(j.get('workplaceType'),'Unknown'),
                    description=j.get('descriptionPlain',''),url=j['hostedUrl'],posted_at=None,
                    evidence={'posting_date_field':None}))
            if len(page)<100: break
            time.sleep(.5)
        else: raise ValueError('Pagination limit exceeded; run incomplete')
    else: raise ValueError('Unsupported provider')
    for job in rows:
        if not safe_link(job['url']): raise ValueError('Unsafe posting URL')
        job['company']=source['company']
    return rows
