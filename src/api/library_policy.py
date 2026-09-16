"""Which Library paths a signed-in visitor may reach through the Library gateway.

The reading page, its Logs and its Explanatory Tool are for every signed-in account; everything else the Library
serves (monitoring, operations, RAG, VectorDB, architecture, agent information, the run log and plan behind the
administrators' explanatory tool, the Qdrant proxy, teaching, data quality and every path this list does not know)
is for administrators. The gateway sends the visitor's raw request URI in X-Original-URI; it is normalised here
before matching and a malformed or traversing URI is refused outright.

The allow-list is exactly what those three pages (infra/mbk/web/app/reader/*, their shell and panels) fetch:
  GET  /  (redirects to /reader)           GET  /reader
  GET  /reader/logs, /reader/explain  (the member views, drawn from the answer already in the browser)
  GET  /_next/*  (scripts, styles, fonts)  GET  /favicon.ico, /icon.svg
  GET  /api/config  (hub links)            GET  /__hub/session  (header name and roles)
  GET  /api?op=books  (the book list)      GET  /api/system/book  (cover and dates)
  GET  /api/system/character  (character panel)
  POST /api?op=ask  (the question; the answer, its citations and cast list come back in this one response)
Logs and the Explanatory Tool add no call of their own: both read the answer the reading page already holds, which
is why /api/system/recent_runs (everyone's last questions), /api/system/explain (any run id) and
/api/system/explain/review stay administrator-only, as does Phoenix under /api/monitoring/. The Reader makes no
streaming or Qdrant proxy calls.

The Library answers on two addresses from one build (16 Sep 2026): the root shape (https://library.bagala.ai/ and
http://localhost:3001/) and its short path on the shared host (https://bagala.ai/library/). The gateway sends the
address the visitor used, so a request on the short path arrives here as /library/reader, /library/_next/...,
/library/api/?op=ask. After normalising, one leading /library is taken off and the rest is judged exactly as the
root shape is judged: the same pages and calls for every signed-in account, and nothing more. The console asks for
its API route as /library/api/ on the short path (Cloudflare's human check leaves paths containing "/api/" alone);
a trailing slash is dropped by normalising, so that is /api like any other spelling of it.
"""
import re
from urllib.parse import parse_qsl, unquote

READER = 'reader'
QUESTION = 'question'
ADMINISTRATOR = 'administrator'
INVALID = 'invalid'

READ_METHODS = frozenset({'GET', 'HEAD'})
READER_PATHS = frozenset({'/', '/reader', '/reader/logs', '/reader/explain', '/favicon.ico', '/icon.svg',
                          '/api/config', '/__hub/session', '/api/system/book', '/api/system/character'})
READER_PREFIXES = ('/_next/',)
# The console's single API route takes its operation in the query string: /api?op=...
READER_API_READS = frozenset({'books'})
QUESTION_OP = 'ask'
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
# The short path the Library is served under on the shared host (apps/library/infra/mbk/web/next.config.ts).
PREFIX = '/library'


def normalize(uri):
    """(path, query) for a request URI, or None when it is malformed or tries to leave its directory.
    The query is kept apart; the path is percent-decoded once, its repeated slashes collapsed and a trailing slash
    dropped. A path still holding '%' after decoding (double encoding), a backslash, a control character or a
    '.'/'..' segment is refused."""
    if not isinstance(uri, str) or not uri.startswith('/') or len(uri) > 8192:
        return None
    raw_path, _, query = uri.split('#', 1)[0].partition('?')
    path = unquote(raw_path)
    if '%' in path or '\\' in path or CONTROL.search(path):
        return None
    path = re.sub('/{2,}', '/', path)
    if any(segment in ('.', '..') for segment in path.split('/')):
        return None
    if len(path) > 1:
        path = path.rstrip('/') or '/'
    return path, query


def without_prefix(path):
    """A normalised path as the root shape names it: /library is /, /library/reader is /reader.
    Exactly one prefix comes off, so /library/library/reader is /library/reader (an unknown path, administrator),
    and a name that merely starts with it (/libraryx) is not under it and stays as it is."""
    if path == PREFIX:
        return '/'
    if path.startswith(PREFIX + '/'):
        return path[len(PREFIX):]
    return path


def classify(method, uri):
    """READER, QUESTION (a Reader question, counted against the daily limit), ADMINISTRATOR or INVALID.
    No URI at all (a caller that does not send one) is an unknown path, so administrator."""
    if uri is None or uri == '':
        return ADMINISTRATOR
    normalized = normalize(uri)
    if normalized is None:
        return INVALID
    path, query = normalized
    path = without_prefix(path)
    method = (method or 'GET').upper()
    if path == '/api':
        ops = [value for key, value in parse_qsl(query, keep_blank_values=True) if key == 'op']
        if len(ops) != 1:
            return ADMINISTRATOR
        op = ops[0].strip()
        if method == 'POST' and op == QUESTION_OP:
            return QUESTION
        if method in READ_METHODS and op in READER_API_READS:
            return READER
        return ADMINISTRATOR
    if method in READ_METHODS and (path in READER_PATHS or path.startswith(READER_PREFIXES)):
        return READER
    return ADMINISTRATOR
