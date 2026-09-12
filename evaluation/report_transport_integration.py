"""Run only inside the disconnected disposable report-test database/container."""
import os
import io
import json
from contextlib import redirect_stdout
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from src.db.store import connection
from src.applications.private import private_connection, encrypt
from src.applications.reporting import export_rows
from src.settings import settings
from scripts import email_report as sender

assert settings().database_url == 'postgresql://jobsearch_app@127.0.0.1/jobsearch_report_test'
with tempfile.TemporaryDirectory() as directory:
    key = Path(directory) / 'key'
    key.write_bytes(os.urandom(32))
    os.environ['JOBSEARCH_INTAKE_KEY_FILE'] = str(key)
    os.environ['JOBSEARCH_REPORT_TRANSPORT'] = 'direct'
    with connection() as c:
        uid = c.execute("INSERT INTO jobsearch.users(issuer,subject,roles) VALUES('local','admin',ARRAY['administrator']) RETURNING id").fetchone()['id']
        source = c.execute("INSERT INTO jobsearch.sources(company,provider,board,enabled) VALUES('Synthetic','greenhouse','synthetic',false) RETURNING id").fetchone()['id']
    active, archived, saved = (uuid.uuid4() for _ in range(3))
    with private_connection(uid) as c:
        for identifier in (active, archived, saved):
            c.execute("INSERT INTO jobsearch.jobs(id,source_id,source_job_id,company,title,location,work_mode,country_status,level,match_status,reason,description,url,content_hash) VALUES(%s,%s,%s,'Synthetic','Director Data','US','Remote','us_based','Director','match','Synthetic','Synthetic fixture',%s,'synthetic')",
                      (identifier,source,str(identifier),'https://example.invalid/'+str(identifier)))
        for identifier in (active, archived):
            payload = {'company':'Synthetic','title':'Director Data','status':'needs_information','resume':'PRIVATE','demographics':'PRIVATE','receipt':'PRIVATE','url':'https://example.invalid/job'}
            c.execute('INSERT INTO jobsearch.private_applications(user_id,job_id,payload) VALUES(%s,%s,%s)',(uid,identifier,encrypt(uid,'application:'+str(identifier),payload)))
        c.execute("INSERT INTO jobsearch.job_archives(user_id,identity,job_id,final_status) VALUES(%s,jobsearch.posting_identity(%s),%s,'applied')",(uid,'https://example.invalid/'+str(archived),archived))
        c.execute("INSERT INTO jobsearch.saved_jobs(user_id,job_id,stage) VALUES(%s,%s,'applied')",(uid,saved))
    rows = export_rows()
    compatibility = io.StringIO()
    with redirect_stdout(compatibility):
        exec(sender.EXPORT, {})
    assert json.loads(compatibility.getvalue()) == rows
    assert {row['job_id'] for row in rows} == {str(active),str(saved)}
    assert all(not {'receipt','resume','demographics'} & row.keys() for row in rows)
    body = sender.render(rows)
    journal = Path(directory) / 'delivery.jsonl'
    with patch.object(sender.subprocess, 'run', side_effect=AssertionError('Compose invoked')), patch.object(sender.smtplib, 'SMTP') as factory:
        smtp = factory.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        sender.send_tracked(body,rows,'synthetic-only',journal)
        assert smtp.send_message.call_count == 1
        assert 'without resending' in sender.send_tracked(body,rows,'synthetic-only',journal)
        assert smtp.send_message.call_count == 1
        with private_connection(uid) as c:
            history = c.execute('SELECT job_id,emailed_at FROM jobsearch.emailed_jobs WHERE user_id=%s',(uid,)).fetchall()
        assert {str(row['job_id']) for row in history} == {str(active),str(saved)}
        assert all(row['emailed_at'] for row in history)
        smtp.send_message.side_effect = TimeoutError()
        unknown_body = body + '\nsynthetic second report\n'
        for _ in range(2):
            try:
                sender.send_tracked(unknown_body,rows,'synthetic-only',journal)
            except (RuntimeError, TimeoutError):
                pass
            else:
                raise AssertionError('uncertain report was retried')
        assert smtp.send_message.call_count == 2
print('PASS: direct database export, archive suppression, private-field filtering, accepted-history reconciliation and uncertain-send blocking; SMTP mocked; Docker unavailable to sender.')
