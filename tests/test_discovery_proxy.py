from unittest.mock import Mock,patch
import pytest
from ai_core.tools.web_search import PinnedHTTPS,FetchError

def test_proxy_keeps_destination_tls_identity(monkeypatch):
 monkeypatch.setenv('JOBSEARCH_FETCH_PROXY','http://discovery-egress.hub-system.svc.cluster.local:3128')
 connection=PinnedHTTPS('api.ashbyhq.com','1.1.1.1')
 context=Mock();connection._context=context
 with patch('ai_core.tools.web_search.http.client.HTTPConnection') as factory:
  raw=Mock();factory.return_value.sock=raw
  connection.connect()
  factory.return_value.set_tunnel.assert_called_once_with('api.ashbyhq.com',443)
  context.wrap_socket.assert_called_once_with(raw,server_hostname='api.ashbyhq.com')

def test_unapproved_proxy_fails_before_connection(monkeypatch):
 monkeypatch.setenv('JOBSEARCH_FETCH_PROXY','http://example.com:3128')
 with patch('ai_core.tools.web_search.socket.create_connection') as connect:
  with pytest.raises(FetchError):PinnedHTTPS('api.ashbyhq.com','1.1.1.1').connect()
  connect.assert_not_called()


def test_public_get_retries_transient_connection_failure():
 from ai_core.tools.web_search import fetch_json
 with patch('ai_core.tools.web_search.public_addresses',return_value=['1.1.1.1']), patch('ai_core.tools.web_search.PinnedHTTPS') as factory, patch('ai_core.tools.web_search.time.sleep') as sleep:
  first,second=Mock(),Mock();first.request.side_effect=ConnectionRefusedError()
  response=second.getresponse.return_value;response.status=200;response.getheader.return_value='application/json';response.read.return_value=b'{"jobs":[]}'
  factory.side_effect=[first,second]
  assert fetch_json('https://jobicy.com/api/v2/remote-jobs')=={'jobs':[]}
  assert factory.call_count==2
  sleep.assert_called_once_with(1)
  first.close.assert_called_once();second.close.assert_called_once()
