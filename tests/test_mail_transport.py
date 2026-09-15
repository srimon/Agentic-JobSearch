"""The Resend transport's request shape; no network and no database."""
from types import SimpleNamespace
import src.mail as mail


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"id": "provider-1"}'


def test_resend_request_names_its_client_and_keeps_idempotency(tmp_path, monkeypatch):
    key = tmp_path / 'api.key'
    key.write_text('re_test_value' + chr(10), encoding='utf-8')
    seen = {}

    def fake_urlopen(request, timeout):
        seen['headers'] = {k.lower(): v for k, v in request.header_items()}
        seen['timeout'] = timeout
        return _Response()

    monkeypatch.setattr(mail.urllib.request, 'urlopen', fake_urlopen)
    row = {'id': 7, 'to_address': 'person@example.com', 'subject': 's', 'text_body': 't', 'html_body': None}
    cfg = SimpleNamespace(resend_api_key_file=str(key), mail_from='Bagala <no-reply@bagala.ai>')
    assert mail.send_resend(row, cfg) == 'provider-1'
    headers = seen['headers']
    assert headers['user-agent'] == mail.USER_AGENT and not headers['user-agent'].startswith('Python-urllib')
    assert headers['authorization'] == 'Bearer re_test_value'
    assert headers['idempotency-key'] == 'jobsearch-outbound-mail/7'
