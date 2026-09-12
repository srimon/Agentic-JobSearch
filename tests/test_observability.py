import json,logging
from src.observability import event

def test_sensitive_fields_not_logged(caplog):
    with caplog.at_level(logging.INFO,logger='jobsearch.telemetry'):
        event('http.completed',route='/api/auth/login',status=401,password='secret-value',cookie='session-value',body='private body',authorization='bearer token')
    row=json.loads(caplog.records[-1].message)
    assert row['status']==401
    assert not {'password','cookie','body','authorization'} & row.keys()
    assert 'secret-value' not in caplog.text and 'session-value' not in caplog.text
