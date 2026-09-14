"""Delivery recovery tests use a fake SMTP transport and temporary persistent state."""
import hashlib,json
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.applications import daily
from src.applications.daily_state import initialize
from src.applications.delivery_state import exclusive,atomic_json,read_json
from scripts import email_report as email

@pytest.fixture
def runner(tmp_path,monkeypatch):
    monkeypatch.setattr(daily,'settings',lambda:SimpleNamespace(schedule_timezone='America/Los_Angeles',schedule_hour=8))
    monkeypatch.setattr(daily,'now_utc',lambda:datetime(2026,9,15,15,1,tzinfo=timezone.utc))
    monkeypatch.setattr(daily,'owner_id',lambda:1)
    monkeypatch.setattr(daily,'publish',Mock())
    counts=dict(completed=2,failed=1,queued=0,running=0,enabled=3,missing=0,active=0)
    monkeypatch.setattr(daily,'collection',Mock(return_value=counts))
    monkeypatch.setattr(daily,'prepare',Mock(return_value=({'reviewed':0,'capped':0},[])))
    monkeypatch.setattr(daily,'export_rows',lambda:[])
    # No blocker queries are needed for this empty fixture, but keep the owner transaction boundary.
    from contextlib import nullcontext
    monkeypatch.setattr(daily,'private_connection',lambda uid:nullcontext(None))
    monkeypatch.setattr(email,'load_password',lambda:'abcdefghijklmnop')
    monkeypatch.setattr(email,'track_report',Mock())
    monkeypatch.setattr(daily,'record_report_data',Mock())
    monkeypatch.setenv('JOBSEARCH_REPORT_STATE_DIR',str(tmp_path))
    smtp=Mock();smtp.__enter__=Mock(return_value=smtp);smtp.__exit__=Mock(return_value=False)
    smtp.send_message.return_value={}
    monkeypatch.setattr(email.smtplib,'SMTP',Mock(return_value=smtp))
    (tmp_path/'email-delivery.jsonl').write_text('')
    initialize(tmp_path,{'owner':'kubernetes','version':1,'not_before':'2026-09-15T15:00:00+00:00'},{})
    return tmp_path,smtp

def test_success_then_same_day_changed_body_no_resend(runner,monkeypatch):
    path,smtp=runner
    assert daily.run(path)['delivery']=='smtp_accepted'
    monkeypatch.setattr(email,'render',lambda rows:'different content')
    assert daily.run(path)['phase']=='completed'
    assert smtp.send_message.call_count==1 and daily.prepare.call_count==1
    assert 'report_hash' not in daily.public_record(read_json(path/'daily-workflow.json')['2026-09-15'])

def test_timeout_has_no_email(runner):
    path,smtp=runner
    daily.collection.return_value.update(active=1,running=1,completed=1)
    with pytest.raises(RuntimeError):daily.run(path,wait_seconds=0)
    assert not smtp.send_message.called
    assert read_json(path/'daily-workflow.json')['2026-09-15']['phase']=='failed'

@pytest.mark.parametrize('hour,minute',[(14,59),(16,1)])
def test_outside_window(runner,monkeypatch,hour,minute):
    path,smtp=runner
    monkeypatch.setattr(daily,'now_utc',lambda:datetime(2026,9,15,hour,minute,tzinfo=timezone.utc))
    assert daily.run(path)['phase']=='outside_start_window'
    assert not smtp.send_message.called and not daily.prepare.called

def test_missing_state_and_uncertain_journal_fail_closed(runner):
    path,smtp=runner
    (path/'email-delivery.jsonl').write_text(json.dumps({'report_hash':'a'*64,'status':'delivery_unknown'})+'\n')
    with pytest.raises(RuntimeError):daily.run(path)
    assert not smtp.send_message.called
    (path/'daily-workflow.json').unlink()
    with pytest.raises(RuntimeError):daily.run(path)
    assert not smtp.send_message.called

def test_crash_after_smtp_acceptance_recovers_history_without_resend(runner,monkeypatch):
    path,smtp=runner
    def fail_history(*args,**kwargs):
        if kwargs.get('accepted'):raise RuntimeError('history unavailable')
    email.track_report.side_effect=fail_history
    with pytest.raises(RuntimeError):daily.run(path)
    assert read_json(path/'daily-workflow.json')['2026-09-15']['phase']=='blocked'
    assert daily.run(path)['phase']=='completed'
    assert smtp.send_message.call_count==1 and daily.record_report_data.call_count==1

def test_unknown_smtp_blocks_daily_and_manual_new_body(runner):
    path,smtp=runner;smtp.send_message.side_effect=OSError('lost response')
    with pytest.raises(RuntimeError):daily.run(path)
    with pytest.raises(RuntimeError):daily.run(path)
    with pytest.raises(RuntimeError):email.send_tracked('a different body',[],'fake',path/'email-delivery.jsonl')
    assert smtp.send_message.call_count==1

def test_concurrent_report_guard(runner):
    path,smtp=runner
    with exclusive(path,'report-dispatch.lock'):
        with pytest.raises(RuntimeError):email.send_tracked('manual',[],'fake',path/'email-delivery.jsonl')
    assert not smtp.send_message.called

def test_workflow_lock_prevents_second_preparer(runner):
    path,smtp=runner
    with exclusive(path,'daily-workflow.lock'):
        with pytest.raises(RuntimeError):daily.run(path)
    assert not daily.prepare.called and not smtp.send_message.called

def test_state_recovery_copy_preserves_no_resend(runner,tmp_path_factory):
    import shutil
    path,smtp=runner;daily.run(path)
    restored=tmp_path_factory.mktemp('restored')
    for name in ('daily-owner.json','daily-workflow.json','email-delivery.jsonl'):
        shutil.copy2(path/name,restored/name)
    assert daily.run(restored)['phase']=='completed'
    assert smtp.send_message.call_count==1

def test_initialization_is_idempotent_and_never_replaces_state(runner):
    path,smtp=runner;config=read_json(path/'daily-owner.json')
    daily.run(path)
    assert initialize(path,config,{})=='already_initialized'
    assert read_json(path/'daily-workflow.json')['2026-09-15']['phase']=='completed'
    with pytest.raises(RuntimeError):initialize(path,{**config,'not_before':'2026-09-16T15:00:00+00:00'},{})

def test_check_does_not_prepare_or_send(runner):
    path,smtp=runner
    assert daily.run(path,check=True)['ownership']=='kubernetes'
    assert not daily.prepare.called and not smtp.send_message.called

def test_dst_uses_local_eight(monkeypatch):
    monkeypatch.setattr(daily,'settings',lambda:SimpleNamespace(schedule_timezone='America/Los_Angeles',schedule_hour=8))
    assert daily.next_run(datetime(2026,11,1,7,tzinfo=timezone.utc))=='2026-11-01T16:00:00+00:00'
