import uuid
from unittest.mock import Mock, MagicMock
import pytest
from ai_core.tools.analytics_slack import deliver, configuration, NoRedirect, PROXY

ENV = {'JOBSEARCH_SLACK_ENABLED': 'true', 'JOBSEARCH_SLACK_POLICY': 'all',
       'JOBSEARCH_SLACK_WEBHOOK': 'https://hooks.slack.com/services/TEST/TEST/TEST'}


def fixtures():
    db = Mock(autocommit=True)
    db.execute.return_value.fetchone.return_value = {'event_id': str(uuid.uuid4())}
    response = Mock(status=200); response.read.return_value = b'ok'
    client = MagicMock(); client.open.return_value.__enter__.return_value = response
    return db, client


def test_accepts_only_after_durable_claim():
    db, client = fixtures()
    client.open.side_effect = lambda *a, **kw: (assert_claim(db), client.open.return_value)[1]
    assert deliver(db, uuid.uuid4(), 'success', 12, env=ENV, opener=client) == 'accepted'
    assert db.execute.call_args.args[1][0] == 'accepted'
    assert 'production' in client.open.call_args.args[0].data.decode()


def assert_claim(db):
    assert 'ON CONFLICT(event_id) DO NOTHING' in db.execute.call_args.args[0]


def test_duplicate_does_not_send():
    db, client = fixtures(); db.execute.return_value.fetchone.return_value = None
    assert deliver(db, uuid.uuid4(), 'success', env=ENV, opener=client) == 'already_recorded'
    client.open.assert_not_called()


@pytest.mark.parametrize('status,body', [(302, b'ok'), (200, b'not_ok'), (500, b'ok')])
def test_ambiguous_response_is_never_accepted(status, body):
    db, client = fixtures(); r = client.open.return_value.__enter__.return_value
    r.status = status; r.read.return_value = body
    assert deliver(db, uuid.uuid4(), 'failure', error_class='RuntimeError', env=ENV, opener=client) == 'unknown'
    assert client.open.call_count == 1


def test_timeout_is_unknown_without_leaking_exception(capsys):
    db, client = fixtures(); client.open.side_effect = TimeoutError('SECRET_WEBHOOK')
    assert deliver(db, uuid.uuid4(), 'failure', env=ENV, opener=client) == 'unknown'
    assert 'SECRET_WEBHOOK' not in capsys.readouterr().out
    assert db.execute.call_args.args[1][0] == 'unknown'


@pytest.mark.parametrize('env,expected', [({**ENV, 'JOBSEARCH_SLACK_ENABLED':'false'}, 'disabled'),
                                       ({**ENV, 'JOBSEARCH_SLACK_POLICY':'failures'}, 'filtered')])
def test_policy_prevents_journal_and_network(env, expected):
    db, client = fixtures()
    assert deliver(db, uuid.uuid4(), 'success', env=env, opener=client) == expected
    db.execute.assert_not_called(); client.open.assert_not_called()


def test_rejects_transaction_and_untrusted_error_text():
    db, client = fixtures(); db.autocommit = False
    with pytest.raises(ValueError): deliver(db, uuid.uuid4(), 'success', env=ENV, opener=client)
    db.autocommit = True
    with pytest.raises(ValueError): deliver(db, uuid.uuid4(), 'failure', error_class='https://secret', env=ENV, opener=client)
    client.open.assert_not_called()


@pytest.mark.parametrize('url', ['http://hooks.slack.com/services/A/B/C', 'https://evil.com/services/A/B/C',
                               'https://hooks.slack.com.evil.com/services/A/B/C', 'https://hooks.slack.com/services/A/B/C?token=x'])
def test_exact_webhook_only(url):
    with pytest.raises(ValueError): configuration({**ENV, 'JOBSEARCH_SLACK_WEBHOOK':url})


def test_redirects_denied():
    assert NoRedirect().redirect_request(None, None, None, None, None, None) is None
    assert PROXY == 'http://jobsearch-slack-egress.hub-system.svc.cluster.local:3128'
