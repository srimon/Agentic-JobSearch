"""Fixed, read-only monitoring queries. Never proxy arbitrary URLs or raw spans."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Literal
import requests
from fastapi import APIRouter, Depends

BASE={'grafana':'http://grafana:3000','prometheus':'http://prometheus:9090','phoenix':'http://phoenix:6006'}


def get_json(tool,path,params=None):
    with requests.Session() as session:
        session.trust_env=False
        if tool=="grafana":session.headers["Authorization"]="Bearer "+Path("/run/secrets/grafana_viewer_token").read_text().strip()
        with session.get(BASE[tool]+path,params=params,timeout=(2,5),allow_redirects=False,stream=True) as response:
            if response.status_code!=200:raise RuntimeError('Monitoring upstream unavailable')
            raw=bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw)>2_000_000:raise RuntimeError('Monitoring response too large')
            return json.loads(raw)


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):return None


def label(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:/ -]{1,100}',value) else 'Unavailable'


def timestamp(value):
    if not isinstance(value,str):return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat()
    except ValueError:return None


def prometheus():
    targets=get_json('prometheus','/api/v1/targets')['data']['activeTargets']
    names=['jobsearch_queue_ready','jobsearch_queue_running','jobsearch_queue_oldest_seconds','jobsearch_current_matches']
    result=get_json('prometheus','/api/v1/query',{'query':'{__name__=~"'+'|'.join(names)+'"}'})
    if result.get('status')!='success':raise RuntimeError('Metric query failed')
    metrics={name:None for name in names}
    for item in result['data']['result']:
        key=item.get('metric',{}).get('__name__')
        if key in metrics:metrics[key]=number(item['value'][1])
    end=int(time.time())
    history=get_json('prometheus','/api/v1/query_range',{'query':'jobsearch_queue_ready','start':end-3600,'end':end,'step':60})
    if history.get('status')!='success':raise RuntimeError('History query failed')
    series=history['data']['result']
    samples=[{'at':number(v[0]),'value':number(v[1])} for v in (series[0]['values'] if series else [])][-61:]
    return {'metrics':metrics,'samples':samples,'targets':[
        {'name':label(t.get('labels',{}).get('job')),'health':t.get('health') if t.get('health') in ('up','down','unknown') else 'unknown',
         'last_scrape':timestamp(t.get('lastScrape')),'duration_seconds':number(t.get('lastScrapeDuration'))}
        for t in targets if str(t.get('labels',{}).get('job','')).startswith('jobsearch-')]}


def phoenix():
    projects=get_json('phoenix','/v1/projects',{'limit':100}).get('data',[])
    if not any(p.get('name')=='jobsearch' for p in projects):
        return {'project':'jobsearch','traces':[],'message':'No Jobsearch traces have arrived yet.'}
    payload=get_json('phoenix','/v1/projects/jobsearch/traces',{'limit':25,'sort':'start_time','order':'desc','include_spans':'true'})
    traces=[]
    for trace in payload.get('data',[]):
        trace_id=trace.get('trace_id','')
        if not re.fullmatch('[a-fA-F0-9]{32}',trace_id):continue
        spans=trace.get('spans') or []
        root=next((span for span in spans if span.get('parent_id') is None),{})
        statuses={span.get('status_code') for span in spans}
        status='ERROR' if 'ERROR' in statuses else ('OK' if statuses=={'OK'} else 'UNSET')
        start=timestamp(trace.get('start_time'));end=timestamp(trace.get('end_time'))
        latency=(datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()*1000 if start and end else None
        traces.append({'trace_id':trace_id,'name':label(root.get('name')),
            'start_time':timestamp(trace.get('start_time')),'latency_ms':number(latency),
            'span_count':len(spans),'status':status if status in ('OK','ERROR','UNSET') else 'UNSET'})
    return {'project':'jobsearch','traces':traces,'message':'Latest 25 traces. Collection traces are operational evidence; no LLM evaluation score is inferred.'}



def grafana():
    dashboard=get_json('grafana','/api/dashboards/uid/jobsearch-operations')['dashboard']
    allowed={1:'jobsearch_current_matches',2:'jobsearch_enabled_sources',3:'jobsearch_queue_depth',4:'up{job=~"jobsearch-.*"}',5:'histogram_quantile(0.95, sum by (le) (rate(jobsearch_http_duration_seconds_bucket[5m])))',6:'sum by (outcome) (jobsearch_collection_runs_total)',7:'sum by (decision) (jobsearch_decisions_total)',8:'time()-jobsearch_source_last_success_seconds',9:'ALERTS{alertstate="firing"}'}
    end=int(time.time())
    def panel(item):
        ident=item['id'];history=item.get('type')=='timeseries'
        params={'query':allowed[ident]}
        if history:params.update(start=end-3600,end=end,step=60)
        payload={'id':ident,'title':label(item.get('title')),'series':[],'available':False}
        try:
            result=get_json('grafana','/api/datasources/proxy/uid/jobsearch-prometheus/api/v1/'+('query_range' if history else 'query'),params)
            if result.get('status')!='success':raise RuntimeError('Query failed')
            for row in result['data']['result'][:25]:
                tags=row.get('metric',{})
                name=' / '.join(label(tags[k]) for k in ('job','outcome','decision','source_id','alertname') if k in tags) or 'Value'
                samples=[{'at':number(v[0]),'value':number(v[1])} for v in row.get('values',[row['value']] if 'value' in row else [])][-61:]
                payload['series'].append({'name':name,'samples':samples})
            payload['available']=True
        except Exception:pass
        return payload
    items=[p for p in dashboard.get('panels',[]) if p.get('id') in allowed]
    with ThreadPoolExecutor(max_workers=4) as pool:panels=list(pool.map(panel,items))
    return {'title':label(dashboard.get('title')),'panels':panels,'message':'Live Grafana dashboard metrics, refreshed every 30 seconds. Charts cover the past hour. Raw log bodies are excluded from this view.'}

def create_router(operator):
    router=APIRouter(prefix='/api/observability')
    @router.get('/{tool}')
    def read(tool:Literal['prometheus','phoenix','grafana'],user=Depends(operator)):
        checked=datetime.now(timezone.utc).isoformat()
        try:
            payload={'prometheus':prometheus,'phoenix':phoenix,'grafana':grafana}[tool]()
            return {'tool':tool,'available':True,'checked_at':checked,**payload}
        except Exception:
            return {'tool':tool,'available':False,'checked_at':checked,'message':'Live monitoring is unavailable. Retry or check service health.'}
    return router
