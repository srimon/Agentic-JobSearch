import json,logging
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from src import observability as obs

def test_only_allowlisted_events_are_exported(monkeypatch):
    exporter=InMemoryLogRecordExporter()
    import opentelemetry.exporter.otlp.proto.http._log_exporter as export
    monkeypatch.setattr(export,'OTLPLogExporter',lambda **_:exporter)
    oldlevel=obs.logger.level
    obs.logger.setLevel(logging.INFO)
    provider,handler=obs.setup_log_export(Resource.create({'service.name':'synthetic'}))
    try:
        obs.event('collection.completed',source_id=7,fetched=3,password='secret',resume='private')
        logging.getLogger('unrelated').warning('private unrelated content')
        provider.force_flush()
        logs=exporter.get_finished_logs()
        assert len(logs)==1
        body=json.loads(logs[0].log_record.body)
        assert body['source_id']==7 and body['fetched']==3
        assert 'password' not in body and 'resume' not in body
    finally:
        obs.logger.removeHandler(handler)
        obs.logger.setLevel(oldlevel)
        provider.shutdown()
