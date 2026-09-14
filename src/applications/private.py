"""User-bound encrypted storage. Collector role has neither grants nor the key."""
import json
import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.db.store import connection

@lru_cache
def cipher():
    key=Path(os.environ.get('JOBSEARCH_INTAKE_KEY_FILE','/run/secrets/intake_key')).read_bytes()
    if len(key)!=32: raise ValueError('Invalid intake key')
    return AESGCM(key)

def encrypt(user_id,kind,value):
    nonce=os.urandom(12)
    return nonce+cipher().encrypt(nonce,json.dumps(value).encode(),f'{user_id}:{kind}:v1'.encode())

def decrypt(user_id,kind,value):
    raw=bytes(value)
    return json.loads(cipher().decrypt(raw[:12],raw[12:],f'{user_id}:{kind}:v1'.encode()))

def application_summaries(conn, user_id, job_ids):
    """Read only the displayed page, under the caller's owner transaction."""
    if not job_ids:
        return {}
    if len(job_ids) > 25:
        raise ValueError('Application summary page exceeds 25 jobs')
    records = conn.execute(
        'SELECT job_id,payload FROM jobsearch.private_applications WHERE user_id=%s AND job_id=ANY(%s::uuid[])',
        (user_id, list(job_ids)),
    ).fetchall()
    result = {}
    for record in records:
        job_id = str(record['job_id'])
        report = decrypt(user_id, 'application:' + job_id, record['payload'])
        result[job_id] = {'application_status': report.get('status'), 'next_action': report.get('next_action')}
    return result

@contextmanager
def private_connection(user_id):
    with connection() as c:
        c.execute("SELECT set_config('jobsearch.user_id',%s,true)",(str(user_id),))
        yield c
