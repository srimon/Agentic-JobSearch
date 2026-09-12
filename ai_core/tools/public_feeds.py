from ai_core.tools.web_search import fetch_json,FetchError
from src.guardrails.content import plain_text,safe_link
from src.pipelines.classification import posting_date

def collect_public(provider):
    if provider=='jobicy':
        payload=fetch_json('https://jobicy.com/api/v2/remote-jobs?count=200&geo=usa')
    elif provider=='remotive':
        payload=fetch_json('https://remotive.com/api/remote-jobs')
    else: raise ValueError('Unsupported public feed')
    if not isinstance(payload.get('jobs'),list): raise FetchError('Invalid public feed')
    rows=[]
    for j in payload['jobs']:
        if provider=='jobicy':
            title,company,location=j['jobTitle'],j['companyName'],j.get('jobGeo','')
            desc,date=j.get('jobDescription') or j.get('jobExcerpt',''),j.get('pubDate')
            field='pubDate'
        else:
            title,company,location=j['title'],j['company_name'],j.get('candidate_required_location','')
            desc,date=j.get('description',''),j.get('publication_date')
            field='publication_date'
        if not safe_link(j['url']): raise FetchError('Unsafe public feed link')
        rows.append(dict(source_job_id=str(j['id']),company=plain_text(company),title=plain_text(title),location=plain_text(location),country='',work_mode='Remote',description=plain_text(desc),url=j['url'],posted_at=posting_date(date),evidence={'provider':provider,'posting_date_field':field,'source_date':date,'source_delay_hours':24 if provider=='remotive' else None,'bounded_feed':provider=='jobicy'}))
    return rows
