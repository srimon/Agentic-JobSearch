"""Dice's public MCP search, fixed destination and fixed read-only tool."""
import json,time
from ai_core.tools.web_search import public_addresses,PinnedHTTPS,FetchError
from src.guardrails.content import plain_text,safe_link
from src.pipelines.classification import posting_date
HOST='mcp.dice.com'
QUERIES=['Director Data','Senior Director Data','Director Analytics','Director Business Intelligence','VP Data','SVP Data','VP Analytics','Chief Technology Officer','Chief Information Officer','Chief Data Officer','Chief Digital Officer','Director AI','Senior Director AI','VP AI','SVP AI','Chief AI Officer','Director Machine Learning','VP Artificial Intelligence']

def decode(raw):
    text=raw.decode('utf-8')
    if text.lstrip().startswith('{'): return json.loads(text)
    for line in text.splitlines():
        if line.startswith('data:'):
            value=json.loads(line[5:].strip())
            if 'result' in value or 'error' in value: return value
    raise FetchError('Invalid MCP response')

class DiceClient:
    def __init__(self):
        self.headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json','User-Agent':'Jobsearch/0.1'}
        self.seq=0
        response=self.call('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'Jobsearch','version':'0.1'}})
        version=response['result']['protocolVersion']
        if version!='2025-03-26': raise FetchError('Unsupported MCP version')
        self.headers['MCP-Protocol-Version']=version
        self.call('notifications/initialized',None,notify=True)

    def call(self,method,params,notify=False):
        self.seq+=1
        payload={'jsonrpc':'2.0','method':method}
        if not notify: payload['id']=self.seq
        if params is not None: payload['params']=params
        conn=PinnedHTTPS(HOST,public_addresses(HOST)[0])
        try:
            conn.request('POST','/mcp',body=json.dumps(payload),headers=self.headers)
            response=conn.getresponse()
            if response.status not in (200,202,204): raise FetchError('Dice HTTP '+str(response.status))
            session=response.getheader('mcp-session-id')
            if session: self.headers['Mcp-Session-Id']=session
            raw=response.read(8_000_001)
            if len(raw)>8_000_000: raise FetchError('Dice response too large')
            if notify: return {}
            result=decode(raw)
            if 'error' in result: raise FetchError('Dice MCP error')
            return result
        finally: conn.close()

    def search(self,keyword,page):
        result=self.call('tools/call',{'name':'search_jobs','arguments':{'keyword':keyword,'location':'United States','jobs_per_page':100,'page_number':page,'sort':'datePosted'}})['result']
        if result.get('isError'): raise FetchError('Dice search failed')
        value=result.get('structuredContent')
        if value is None:
            value=json.loads(next(x['text'] for x in result['content'] if x['type']=='text'))
        if not isinstance(value.get('data'),list): raise FetchError('Invalid Dice results')
        return value

def collect_dice():
    client=DiceClient(); rows=[]
    for keyword in QUERIES:
        for page in (1,2):
            payload=client.search(keyword,page)
            metadata=payload.get('metadata') or {}
            total_pages=metadata.get('totalPages') or 1
            for j in payload['data']:
                link=j.get('detailsPageUrl') or ''
                if not safe_link(link): raise FetchError('Unsafe Dice job link')
                company_link=j.get('companyPageUrl') or ''
                if company_link and not safe_link(company_link): company_link=''
                modes=j.get('workplaceTypes') or []
                mode={'On-Site':'On-site','Remote':'Remote','Hybrid':'Hybrid'}.get(modes[0],'Unknown') if len(modes)==1 else 'Unknown'
                rows.append(dict(source_job_id=j.get('guid') or j['id'],company=j.get('companyName') or 'Employer not specified',title=j.get('title') or '',
                 location=(j.get('jobLocation') or {}).get('displayName') or '',country='',work_mode=mode,
                 description=plain_text(j.get('summary') or ''),url=link,posted_at=posting_date(j.get('postedDate')),
                 evidence={'provider':'dice','posting_date_field':'postedDate','company_url':company_link,'description_is_summary':True,'search_keyword':keyword,'search_capped':total_pages>2,'retrieval':'public_mcp_search'}))
            if page>=total_pages: break
            time.sleep(1)
        time.sleep(1)
    return rows
