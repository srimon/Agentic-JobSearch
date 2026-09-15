"""Which Library paths a signed-in visitor may reach through the Library gateway.

The Reader is for every signed-in account; everything else the Library serves (monitoring, operations, logs, RAG,
VectorDB, architecture, agent information, the explanatory tool, the Qdrant proxy, teaching, data quality and every
path this list does not know) is for administrators. The gateway sends the visitor's raw request URI in
X-Original-URI; it is normalised here before matching and a malformed or traversing URI is refused outright.

The allow-list is exactly what the Reader page (infra/mbk/web/app/reader/page.tsx, its shell and panels) fetches:
  GET  /  (redirects to /reader)           GET  /reader
  GET  /_next/*  (scripts, styles, fonts)  GET  /favicon.ico, /icon.svg
  GET  /api/config  (hub links)            GET  /__hub/session  (header name and roles)
  GET  /api?op=books  (the book list)      GET  /api/system/book  (cover and dates)
  GET  /api/system/character  (character panel)
  POST /api?op=ask  (the question; the answer, its citations and cast list come back in this one response)
The Reader makes no streaming or Qdrant proxy calls.
"""
import re
from urllib.parse import parse_qsl, unquote

READER = 'reader'
QUESTION = 'question'
ADMINISTRATOR = 'administrator'
INVALID = 'invalid'

READ_METHODS = frozenset({'GET', 'HEAD'})
READER_PATHS = frozenset({'/', '/reader', '/favicon.ico', '/icon.svg', '/api/config', '/__hub/session',
                          '/api/system/book', '/api/system/character'})
READER_PREFIXES = ('/_next/',)
# The console's single API route takes its operation in the query string: /api?op=...
READER_API_READS = frozenset({'books'})
QUESTION_OP = 'ask'
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


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


def classify(method, uri):
    """READER, QUESTION (a Reader question, counted against the daily limit), ADMINISTRATOR or INVALID.
    No URI at all (a caller that does not send one) is an unknown path, so administrator."""
    if uri is None or uri == '':
        return ADMINISTRATOR
    normalized = normalize(uri)
    if normalized is None:
        return INVALID
    path, query = normalized
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
