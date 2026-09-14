"""Restricted ATS fetcher. Arbitrary URL browsing is intentionally unsupported."""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
from urllib.parse import urlsplit

HOSTS = {'api.ashbyhq.com', 'boards-api.greenhouse.io', 'api.lever.co', 'jobicy.com', 'remotive.com', 'himalayas.app'}


class FetchError(Exception):
    pass


def public_addresses(host):
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise FetchError('Destination is not public')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=25, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        proxy = os.environ.get('JOBSEARCH_FETCH_PROXY', '')
        if proxy:
            parsed = urlsplit(proxy)
            if (parsed.scheme != 'http' or parsed.hostname != 'discovery-egress.hub-system.svc.cluster.local'
                    or parsed.port != 3128 or parsed.username or parsed.password
                    or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
                raise FetchError('Unapproved discovery proxy')
            tunnel = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=self.timeout)
            tunnel.set_tunnel(self.host, 443)
            tunnel.connect()
            sock, tunnel.sock = tunnel.sock, None
        else:
            sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def fetch_json(url, max_bytes=20_000_000):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise FetchError('Destination denied')
    address = public_addresses(parsed.hostname)[0]
    for attempt in range(3):
        conn = PinnedHTTPS(parsed.hostname, address)
        try:
            conn.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''), headers={
                'Accept':'application/json', 'User-Agent':'Jobsearch/0.1 (public job monitoring)', 'Accept-Encoding':'identity'})
            response = conn.getresponse()
            if response.status in (429,500,502,503,504) and attempt < 2:
                retry = response.getheader('Retry-After','')
                # Long or date-based Retry-After is deferred to a later run, never ignored.
                if retry and (not retry.isdigit() or int(retry) > 30):
                    raise FetchError('Source requested deferred retry')
                time.sleep(max(2 ** attempt, int(retry or 0)))
                continue
            if response.status != 200:
                raise FetchError(f'Source HTTP {response.status}')
            if 'json' not in response.getheader('Content-Type','').lower():
                raise FetchError('Unexpected response type')
            raw = response.read(max_bytes+1)
            if len(raw) > max_bytes:
                raise FetchError('Response exceeded limit')
            return json.loads(raw)
        except (OSError, http.client.HTTPException) as error:
            if attempt == 2:
                raise FetchError('Source connection failed: ' + type(error).__name__) from None
            time.sleep(2 ** attempt)
        finally:
            conn.close()
    raise FetchError('Retries exhausted')
