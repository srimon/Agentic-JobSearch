"""Official no-key Himalayas search API; bounded window, never a complete board.

API docs: https://himalayas.app/docs/remote-jobs-api
Keep attribution and the Himalayas posting URL; never redistribute to other boards.
"""
import time
from datetime import datetime,timezone
from urllib.parse import urlencode,urlsplit
from ai_core.tools.web_search import fetch_json,FetchError
from src.guardrails.content import plain_text
from src.pipelines.classification import posting_date

def epoch(value):
    if type(value) not in (int,float) or not 0<value<253402300800:return None
    return datetime.fromtimestamp(value,timezone.utc)

def collect_himalayas():
    rows=[];seen=set();now=datetime.now(timezone.utc)
    for page in range(1,6):
        query=urlencode({'country':'US','seniority':'Director,Executive','sort':'recent','page':page})
        payload=fetch_json('https://himalayas.app/jobs/api/search?'+query,max_bytes=4_000_000)
        jobs=payload.get('jobs') if isinstance(payload,dict) else None
        if not isinstance(jobs,list) or len(jobs)>20:raise FetchError('Invalid Himalayas page')
        for item in jobs:
            url=item.get('guid','');parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.hostname!='himalayas.app' or parsed.username or parsed.password or parsed.port not in (None,443) or not parsed.path.startswith('/companies/') or '/jobs/' not in parsed.path:
                raise FetchError('Invalid Himalayas attribution URL')
            if url in seen:continue
            seen.add(url)
            expires=epoch(item.get('expiryDate'))
            if expires and expires<=now:continue
            locations=item.get('locationRestrictions',[])
            if not isinstance(locations,list) or any(not isinstance(x,str) for x in locations):raise FetchError('Invalid Himalayas location')
            published=epoch(item.get('pubDate'))
            date=posting_date(published.isoformat()) if published else None
            country='US' if any(x.lower() in ('us','usa','united states','united states of america') for x in locations) else ''
            title=item.get('title');company=item.get('companyName')
            if not isinstance(title,str) or not isinstance(company,str):raise FetchError('Invalid Himalayas identity')
            rows.append({'source_job_id':url,'company':plain_text(company),'title':plain_text(title),'location':plain_text(', '.join(locations)),'country':country,'work_mode':'Remote','description':plain_text(item.get('description') or item.get('excerpt') or ''),'url':url,'posted_at':date,'evidence':{'provider':'himalayas','attribution':'Himalayas','source_url':url,'posting_date_field':'pubDate','expiry_date':expires.isoformat() if expires else None,'bounded_feed':True,'result_cap':100}})
        if len(jobs)<20:break
        if page<5:time.sleep(.5)
    return rows
