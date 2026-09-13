"""Explicit telemetry: no request bodies, headers, SQL, or scraped content."""
import json,logging,os,time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import contextmanager
from prometheus_client import Counter,Histogram,Gauge,start_http_server,REGISTRY
from prometheus_client.core import GaugeMetricFamily
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
HTTP=Counter('jobsearch_http_requests','HTTP requests',['route','status'])
LATENCY=Histogram('jobsearch_http_duration_seconds','HTTP time',['route'])
RUNS=Counter('jobsearch_collection_runs','Collection outcomes',['provider','outcome'])
DURATION=Histogram('jobsearch_collection_duration_seconds','Collection time',['provider'])
DECISIONS=Counter('jobsearch_decisions','Classification decisions',['decision'])
HEARTBEAT=Gauge('jobsearch_worker_heartbeat_seconds','Last worker progress timestamp')
SCHEDULER_HEARTBEAT=Gauge('jobsearch_scheduler_heartbeat_seconds','Last successful scheduling pass')
_initialized=False
ALLOWED={'route','status','duration_seconds','run_id','source_id','provider','outcome','error_class','fetched','accepted','review','excluded'}
logger=logging.getLogger('jobsearch.telemetry')

def event(name,**fields):
    ctx=trace.get_current_span().get_span_context()
    record={'event':name,'at':time.time(),'service':os.getenv('OTEL_SERVICE_NAME','jobsearch'),'trace_id':format(ctx.trace_id,'032x') if ctx.is_valid else None}
    record.update({k:v for k,v in fields.items() if k in ALLOWED and isinstance(v,(str,int,float,bool))})
    logger.info(json.dumps(record))

class DatabaseMetrics:
    def collect(self):
        from src.db.store import connection
        ok=GaugeMetricFamily('jobsearch_database_metrics_up','Database metrics availability')
        try:
            with connection() as c:
                rows=c.execute("SELECT id,extract(epoch from last_success_at) AS last_success FROM jobsearch.sources WHERE enabled").fetchall()
                queued=c.execute("SELECT count(*) n FROM jobsearch.runs WHERE status IN ('queued','running')").fetchone()['n']
                queue=c.execute("SELECT count(*) FILTER (WHERE status='queued') ready, count(*) FILTER (WHERE status='running') running, coalesce(extract(epoch FROM now()-min(created_at) FILTER (WHERE status='queued')),0) oldest FROM jobsearch.runs").fetchone()
                matches=c.execute("SELECT count(*) n FROM jobsearch.jobs WHERE match_status='match' AND availability='observed_open'").fetchone()['n']
                run_counts=c.execute('SELECT status,count(*) n FROM jobsearch.runs GROUP BY status').fetchall()
                candidate_counts=c.execute("SELECT match_status,count(*) n FROM jobsearch.jobs WHERE availability='observed_open' GROUP BY match_status").fetchall()
            fresh=GaugeMetricFamily('jobsearch_source_last_success_seconds','Latest successful collection',labels=['source_id'])
            for row in rows: fresh.add_metric([str(row['id'])],float(row['last_success'] or 0))
            yield fresh
            history=GaugeMetricFamily('jobsearch_discovery_runs','Persisted discovery runs by status',labels=['status'])
            counts={r['status']:r['n'] for r in run_counts}
            for status in ('queued','running','completed','failed'): history.add_metric([status],counts.get(status,0))
            yield history
            candidates=GaugeMetricFamily('jobsearch_discovery_candidates','Currently observed listings by classification',labels=['status'])
            counts={r['match_status']:r['n'] for r in candidate_counts}
            for status in ('match','review'): candidates.add_metric([status],counts.get(status,0))
            yield candidates
            for name,value in [('jobsearch_queue_depth',queued),('jobsearch_current_matches',matches),('jobsearch_enabled_sources',len(rows)),('jobsearch_queue_ready',queue['ready']),('jobsearch_queue_running',queue['running']),('jobsearch_queue_oldest_seconds',float(queue['oldest']))]:
                metric=GaugeMetricFamily(name,name); metric.add_metric([],value); yield metric
            ok.add_metric([],1)
        except Exception:
            ok.add_metric([],0)
        yield ok

def setup(service):
    global _initialized
    if _initialized or os.getenv('JOBSEARCH_TELEMETRY')!='true': return
    _initialized=True
    os.environ['OTEL_SERVICE_NAME']=service
    resource=Resource.create({'service.name':service,'deployment.environment.name':os.getenv('JOBSEARCH_ENVIRONMENT','local')})
    provider=TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT','http://otel:4318/v1/traces'),timeout=3)))
    trace.set_tracer_provider(provider)
    folder=Path('/app/telemetry'); folder.mkdir(exist_ok=True)
    handler=RotatingFileHandler(folder/(service+'.jsonl'),maxBytes=5*1024*1024,backupCount=3)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.setLevel(logging.INFO); logger.addHandler(handler); logger.addHandler(logging.StreamHandler()); logger.propagate=False
    if os.getenv('JOBSEARCH_OTLP_LOGS')=='true':
        setup_log_export(resource)
    if service=='jobsearch-api': REGISTRY.register(DatabaseMetrics())
    start_http_server(9108)
    event('service.started')

@contextmanager
def collection_span(run):
    started=time.monotonic()
    with trace.get_tracer('jobsearch').start_as_current_span('source.collect',record_exception=False,set_status_on_exception=False) as span:
        span.set_attribute('source.id',run['source_id']); span.set_attribute('source.provider',run['provider']); span.set_attribute('run.id',str(run['id']))
        event('collection.started',run_id=str(run['id']),source_id=run['source_id'],provider=run['provider'])
        try: yield span
        finally: DURATION.labels(run['provider']).observe(time.monotonic()-started)


def setup_log_export(resource):
    """Export only the dedicated allowlisted event logger, never root logs."""
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    provider=LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(
        endpoint=os.getenv('OTEL_EXPORTER_OTLP_LOGS_ENDPOINT','http://otel:4318/v1/logs'),timeout=3),
        max_queue_size=512,max_export_batch_size=64))
    handler=LoggingHandler(level=logging.INFO,logger_provider=provider)
    logger.addHandler(handler)
    return provider,handler
