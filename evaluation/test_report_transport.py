import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('portable_sender', Path(__file__).resolve().parents[1] / 'scripts/email_report.py')
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)


def test_direct_transport_never_invokes_docker(monkeypatch):
    monkeypatch.setenv('JOBSEARCH_REPORT_TRANSPORT', 'direct')
    with patch('src.applications.reporting.export_rows', return_value=[]) as export, patch('src.applications.reporting.record_report_data') as track, patch.object(sender.subprocess, 'run', side_effect=AssertionError('Docker must not run')):
        assert sender.export_rows() == []
        sender.track_report('body', [], accepted=True)
        export.assert_called_once()
        assert track.call_args.args[0]['accepted'] is True


def test_direct_failure_suppresses_private_details(monkeypatch):
    monkeypatch.setenv('JOBSEARCH_REPORT_TRANSPORT', 'direct')
    with patch('src.applications.reporting.export_rows', side_effect=RuntimeError('PRIVATE RECORD')):
        with pytest.raises(RuntimeError) as error:
            sender.export_rows()
    assert 'PRIVATE RECORD' not in str(error.value)


def test_transport_fails_closed(monkeypatch):
    monkeypatch.setenv('JOBSEARCH_REPORT_TRANSPORT', 'invalid')
    with pytest.raises(RuntimeError): sender.export_rows()


def test_origin_and_mounted_state(monkeypatch, tmp_path):
    monkeypatch.setenv('JOBSEARCH_REPORT_ORIGIN', 'https://hub.example.invalid')
    monkeypatch.setenv('JOBSEARCH_REPORT_STATE_DIR', str(tmp_path))
    body = sender.render([{'job_id': '46ad0a49-bafc-55f3-ad51-d21cb03bec01'}])
    assert 'https://hub.example.invalid/?view=emailed&job=' in body
    assert 'Update status in Jobsearch' in sender.html_report(body)
    assert sender.state_directory() == tmp_path
    for bad in ('http://public.example.invalid', 'https://user:secret@example.invalid', 'https://example.invalid/path'):
        monkeypatch.setenv('JOBSEARCH_REPORT_ORIGIN', bad)
        with pytest.raises(RuntimeError): sender.report_origin()


def test_direct_role_guard(monkeypatch):
    from src.applications import reporting
    from types import SimpleNamespace
    monkeypatch.setattr(reporting, 'settings', lambda: SimpleNamespace(database_url='postgresql://jobsearch_owner@localhost/jobsearch'))
    with pytest.raises(RuntimeError): reporting.export_rows()
