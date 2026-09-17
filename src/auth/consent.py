"""Consent for use of account data beyond running the service (the hub's
docs/plans/account-creation-options.md): analytics profiling, sharing with partners and
advertising, each a choice of its own, changeable at any time under Account.

The notice below is what the person is shown, word for word, on the sign-up form, on the phone
page of the phone-scan check and under Account; the front end renders these same strings from
GET /api/session and GET /api/auth/consent. A change to the wording is a new VERSION, and every
recorded choice keeps the version and digest of the notice it answered.

Who must opt in is decided by the visitor's location (src/auth/context.py regime): EU/EEA and UK
visitors and Californians start with every purpose off; everyone else starts with them on and is
told so, and can turn them off. A withdrawal is a new event and a changed current row, so an
export keyed to user_consent stops using the data from that moment.
"""
import hashlib
import json
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from psycopg.types.json import Jsonb
from src.db.store import connection, audit
from src.auth.context import visitor, regime

# 2026-09-17b: the owner's decision of that evening added news as a fourth purpose; the first version had three.
VERSION = '2026-09-17b'
PURPOSES = ('analytics', 'partners', 'advertising', 'news')
NOTICE = {
    'intro': 'Beyond running the service, may we use details about you and how you use Bagala for the following? '
             'You can change each choice at any time under Account.',
    'analytics': 'Analytics profiling: combine your sign-up details, location and usage into profiles that help us understand who uses Bagala.',
    'partners': 'Partners: share those profiles with selected partners.',
    'advertising': 'Advertising: use them to choose advertising for you.',
    'news': 'News: send you occasional news about Bagala products by email.',
    'opt_in': 'These are off unless you turn them on.',
    'opt_out': 'These are on unless you turn them off.',
}


def notice_hash():
    return hashlib.sha256(json.dumps(NOTICE, sort_keys=True).encode()).hexdigest()


class Choice(BaseModel):
    analytics: bool = False
    partners: bool = False
    advertising: bool = False
    news: bool = False


def defaults(request):
    """What the sign-up form and the phone page show this visitor: the regime their location
    puts them under, whether they must opt in, and the notice."""
    seen = visitor(request)
    name = regime(seen['country'], seen['region_code'])
    opt_in = name != 'other'
    return {'regime': name, 'opt_in_required': opt_in, 'version': VERSION, 'notice': NOTICE,
            'default': {purpose: not opt_in for purpose in PURPOSES}}


def as_choice(value):
    value = value or {}
    return {purpose: bool(value.get(purpose)) for purpose in PURPOSES}


def record(conn, user_id, choice, source, regime_name, ip=None, country=None):
    """Store a choice as the current state and as an event; returns the current row."""
    choice = as_choice(choice)
    flags = [choice[purpose] for purpose in PURPOSES]
    conn.execute("""INSERT INTO jobsearch.consent_events(user_id,source,notice_version,notice_hash,regime,analytics,partners,advertising,news,ip,country)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                 (user_id, source, VERSION, notice_hash(), regime_name, *flags, ip, country))
    return conn.execute("""INSERT INTO jobsearch.user_consent(user_id,analytics,partners,advertising,news,notice_version,regime,updated_at)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT(user_id) DO UPDATE SET analytics=EXCLUDED.analytics,partners=EXCLUDED.partners,
                             advertising=EXCLUDED.advertising,news=EXCLUDED.news,notice_version=EXCLUDED.notice_version,regime=EXCLUDED.regime,updated_at=now()
                           RETURNING *""",
                        (user_id, *flags, VERSION, regime_name)).fetchone()


def current(conn, user_id):
    row = conn.execute('SELECT * FROM jobsearch.user_consent WHERE user_id=%s', (user_id,)).fetchone()
    if row:
        return {'choices': as_choice(row), 'version': row['notice_version'], 'regime': row['regime'], 'updated_at': row['updated_at'], 'recorded': True}
    return {'choices': as_choice({}), 'version': None, 'regime': None, 'updated_at': None, 'recorded': False}


def exportable(conn, purpose):
    """The accounts whose data may be used for `purpose` right now: the one query any
    monetization export must start from. Nothing else about an account is selected here."""
    if purpose not in PURPOSES:
        raise ValueError('unknown purpose')
    rows = conn.execute('SELECT user_id FROM jobsearch.user_consent WHERE ' + purpose + ' ORDER BY user_id').fetchall()
    return [row['user_id'] for row in rows]


def create_router(current_user):
    router = APIRouter(prefix='/api/auth/consent')

    @router.get('')
    def read(request: Request, user=Depends(current_user)):
        with connection() as conn:
            state = current(conn, user['id'])
        return {**state, 'notice': NOTICE, 'current_version': VERSION, 'opt_in_required': defaults(request)['opt_in_required']}

    @router.put('')
    def change(body: Choice, request: Request, user=Depends(current_user)):
        seen = visitor(request)
        wanted = body.model_dump()
        with connection() as conn:
            before = current(conn, user['id'])['choices']
            # The regime a change is recorded under is the one the visitor is under now; the
            # first choice's regime stays on its own event.
            row = record(conn, user['id'], wanted, 'account', regime(seen['country'], seen['region_code']), seen['ip'], seen['country'])
            changed = sorted(purpose for purpose in PURPOSES if before[purpose] != wanted[purpose])
            audit(conn, str(user['id']), 'account.consent', 'local', details={'changed': changed, 'version': VERSION})
        return {'ok': True, 'choices': as_choice(row), 'version': row['notice_version'], 'updated_at': row['updated_at']}

    return router
