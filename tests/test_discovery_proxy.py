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
