"""The shared text store (the owner's 18 September batch, section 5).

Every Bagala surface marks its static copy with ``data-text="<page>.<slug>"``, reads the stored overrides once on
load and replaces the text of the elements it holds a key for. Job Search owns accounts, so it owns the store:

* ``GET /api/hub/page-text`` - public, no session, ``Cache-Control: no-store``, ``{key: value}``. The public edge
  and the product gateways forward ``/__hub/page-text`` here as they already forward ``/__hub/session``.
* ``PUT /api/hub/page-text`` - administrators only, a small batch of ``{key: value}``. The same-origin rule is the
  one every write in this API gets (the Origin check in src/api/main.py); the role is the one every other
  administrator route uses.

What a value may be: plain text, at most 2000 characters, no control characters (the rule the enquiry route
already applies) and nothing HTML-shaped, because a surface writes it with ``textContent`` and a value that looks
like markup would only ever be shown as its own characters. An empty value removes the override, which is how
"Reset this page to the original" works. Every write records the administrator and the second, in the row and in
jobsearch.audit_events, where the Admin console's activity view reads it.
"""
import re
import time

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.db.store import connection, audit

# "<page>.<slug>", the shape the surfaces agreed on: lower case, digits and hyphens inside a dotted path.
KEY = re.compile(r'^[a-z0-9]+(\.[a-z0-9-]+)+$')
MAX_VALUE = 2000
MAX_KEY = 120
# One screen's worth of copy at a time; a surface only ever sends the keys it changed.
MAX_KEYS = 200
# The control characters the enquiry route refuses too: everything in C0 except tab, newline and carriage return.
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# Anything that opens a tag, a comment or a processing instruction. The value is text; it is never parsed as HTML.
MARKUP = re.compile(r'<[a-zA-Z/!?]')


def clean(key, value):
    """The stored form of one submitted value, or None when the key is to be removed.

    Raises HTTPException(422) with the offending key, never with the value, so nothing submitted is echoed back.
    """
    if not isinstance(key, str) or len(key) > MAX_KEY or not KEY.match(key):
        raise HTTPException(422, 'Not a text key: ' + str(key)[:MAX_KEY])
    if not isinstance(value, str):
        raise HTTPException(422, 'Text must be a string: ' + key)
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_VALUE:
        raise HTTPException(422, 'Text must be at most 2000 characters: ' + key)
    if CONTROL.search(text):
        raise HTTPException(422, 'Text may not hold control characters: ' + key)
    if MARKUP.search(text):
        raise HTTPException(422, 'Text may not hold markup: ' + key)
    return text


def create_router(administrator):
    router = APIRouter()

    @router.get('/api/hub/page-text')
    def page_text():
        """Every stored override, for anyone: the surfaces read this before they paint their static copy."""
        with connection() as conn:
            rows = conn.execute('SELECT key,value FROM jobsearch.page_text ORDER BY key').fetchall()
        return JSONResponse({row['key']: row['value'] for row in rows}, headers={'Cache-Control': 'no-store'})

    @router.put('/api/hub/page-text')
    def save_page_text(body: dict = Body(...), user=Depends(administrator)):
        if not isinstance(body, dict) or not body:
            raise HTTPException(422, 'Send a batch of text keys and their values.')
        if len(body) > MAX_KEYS:
            raise HTTPException(422, 'Send at most 200 keys at a time.')
        # Everything is checked before anything is written, so a batch with one bad value changes nothing.
        cleaned = {key: clean(key, value) for key, value in body.items()}
        now = int(time.time())
        actor = str(user['id'])
        with connection() as conn:
            for key, value in cleaned.items():
                if value is None:
                    conn.execute('DELETE FROM jobsearch.page_text WHERE key=%s', (key,))
                else:
                    conn.execute("""INSERT INTO jobsearch.page_text(key,value,updated_by,updated_at_utc)
                        VALUES(%s,%s,%s,%s) ON CONFLICT(key) DO UPDATE
                        SET value=excluded.value,updated_by=excluded.updated_by,updated_at_utc=excluded.updated_at_utc""",
                                 (key, value, actor, now))
            # The audit trail carries the keys and whether each was set or cleared, never the words themselves.
            audit(conn, actor, 'page_text.update', ','.join(sorted(cleaned))[:200], details={
                'set': sorted(key for key, value in cleaned.items() if value is not None),
                'cleared': sorted(key for key, value in cleaned.items() if value is None),
                'updated_at_utc': now})
        return {'ok': True, 'updated': len(cleaned), 'updated_at_utc': now}

    return router
