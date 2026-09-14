"""PostgreSQL collection leases. This queue never sends applications or email."""
import threading
import uuid
from contextlib import contextmanager
from src.db.store import connection, audit
from src.settings import settings

class LeaseLost(Exception):
    pass


def require_lease(conn, run):
    """Lock ownership through the entire result transaction, including commit."""
    row = conn.execute("""SELECT id FROM jobsearch.runs
        WHERE id=%s AND status='running' AND lease_token=%s
        AND lease_expires_at>clock_timestamp()
        AND started_at>clock_timestamp()-(%s * interval '1 second') FOR UPDATE""",
        (run['id'], run['lease_token'], settings().worker_max_run_seconds)).fetchone()
    if not row:
        raise LeaseLost()


def renew(run):
    with connection() as conn:
        conn.execute("SET LOCAL statement_timeout='5s'")
        return bool(conn.execute("""UPDATE jobsearch.runs
            SET lease_expires_at=clock_timestamp()+(%s * interval '1 second'),
                heartbeat_at=clock_timestamp()
            WHERE id=%s AND status='running' AND lease_token=%s
              AND lease_expires_at>clock_timestamp()
              AND started_at>clock_timestamp()-(%s * interval '1 second')
            RETURNING id""", (settings().worker_lease_seconds, run['id'],
                run['lease_token'], settings().worker_max_run_seconds)).fetchone())


@contextmanager
def heartbeat(run):
    stop = threading.Event()
    lost = threading.Event()
    def loop():
        while not stop.wait(settings().worker_heartbeat_seconds):
            try:
                if renew(run):
                    continue
            except Exception:
                pass
            lost.set()
            return
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stop.set()
        thread.join(timeout=11)


@contextmanager
def claim(worker_id):
    """Claim one task, retaining a conservative per-provider session lock.

    Provider serialization is deliberately stricter than per-source exclusion.
    A hung process can delay its provider until its connection closes; leases
    fence results but cannot cancel a remote HTTP request already in flight.
    """
    config = settings()
    # Do not keep a transaction open while collecting from external websites.
    with connection() as gate:
        gate.autocommit = True
        provider = None
        try:
            with connection() as conn:
                conn.execute("SET LOCAL lock_timeout='5s'")
                conn.execute("""UPDATE jobsearch.runs SET status='failed',
                    finished_at=clock_timestamp(),error='Lease retries exhausted',
                    lease_token=NULL,lease_expires_at=NULL
                    WHERE status='running' AND lease_expires_at<=clock_timestamp()
                      AND attempts >= %s""", (config.worker_max_attempts,))
                candidates = conn.execute("""SELECT r.*,s.company,s.provider,s.board,s.enabled
                    FROM jobsearch.runs r JOIN jobsearch.sources s ON s.id=r.source_id
                    WHERE r.status='queued' OR
                      (r.status='running' AND r.lease_expires_at<=clock_timestamp()
                       AND r.attempts<%s AND r.started_at<=clock_timestamp()-
                         (CASE s.provider WHEN 'remotive' THEN 21600
                          WHEN 'jobicy' THEN 3600 WHEN 'himalayas' THEN 21600 ELSE 0 END * interval '1 second'))
                    ORDER BY r.created_at LIMIT 100""",
                    (config.worker_max_attempts,)).fetchall()
                run = None
                for candidate in candidates:
                    key = 'jobsearch:provider:' + candidate['provider']
                    if not gate.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) acquired', (key,)).fetchone()['acquired']:
                        continue
                    provider = key
                    candidate = conn.execute("""SELECT r.*,s.company,s.provider,s.board,s.enabled
                        FROM jobsearch.runs r JOIN jobsearch.sources s ON s.id=r.source_id
                        WHERE r.id=%s AND (r.status='queued' OR
                          (r.status='running' AND r.lease_expires_at<=clock_timestamp()
                           AND r.attempts<%s AND r.started_at<=clock_timestamp()-
                             (CASE s.provider WHEN 'remotive' THEN 21600
                              WHEN 'jobicy' THEN 3600 WHEN 'himalayas' THEN 21600 ELSE 0 END * interval '1 second')))
                        FOR UPDATE OF r SKIP LOCKED""",(candidate['id'],config.worker_max_attempts)).fetchone()
                    if candidate is None:
                        gate.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(provider,))
                        provider = None
                        continue
                    if not candidate['enabled']:
                        conn.execute("""UPDATE jobsearch.runs SET status='failed',
                            finished_at=clock_timestamp(),error='Source disabled',
                            lease_token=NULL,lease_expires_at=NULL WHERE id=%s""", (candidate['id'],))
                        gate.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(provider,))
                        provider = None
                        continue
                    token = uuid.uuid4()
                    attempt = conn.execute("""UPDATE jobsearch.runs SET status='running',
                        started_at=clock_timestamp(),finished_at=NULL,error=NULL,
                        worker_id=%s,lease_token=%s,attempts=attempts+1,
                        heartbeat_at=clock_timestamp(),
                        lease_expires_at=clock_timestamp()+(%s * interval '1 second')
                        WHERE id=%s RETURNING attempts""",
                        (worker_id,token,config.worker_lease_seconds,candidate['id'])).fetchone()
                    run = {**candidate, 'lease_token': token, 'attempts': attempt['attempts']}
                    audit(conn,'collector','tool.fetch.start',run['source_id'],
                          details={'run_id':str(run['id']),'attempt':run['attempts']})
                    break
            yield run
        finally:
            if provider:
                gate.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (provider,))


def fail(run, kind):
    with connection() as conn:
        require_lease(conn, run)
        conn.execute("""UPDATE jobsearch.runs SET status='failed',
            finished_at=clock_timestamp(),error=%s,lease_token=NULL,lease_expires_at=NULL
            WHERE id=%s""", (kind,run['id']))
        conn.execute('UPDATE jobsearch.sources SET last_error=%s WHERE id=%s', (kind,run['source_id']))
        audit(conn,'collector','tool.fetch.failed',run['source_id'],'error',
              {'run_id':str(run['id']),'error_class':kind})
