"""Standalone durable source scheduler; never executes collection tasks."""
import argparse
import signal
import threading
from pathlib import Path
from ai_core.agents.supervisor import enqueue
from src.db.store import connection
from src.settings import settings
from src.observability import setup, event


def schedule():
    with connection() as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(74190316) acquired').fetchone()['acquired']:
            return 0
        rows=conn.execute("""SELECT s.id FROM jobsearch.sources s WHERE s.enabled
            AND NOT EXISTS(SELECT 1 FROM jobsearch.runs r WHERE r.source_id=s.id
              AND r.created_at>now()-(%s * interval '1 hour')) ORDER BY s.id""",
            (settings().schedule_hours,)).fetchall()
        return sum(bool(enqueue(conn,row['id'],'scheduler')) for row in rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    setup('jobsearch-scheduler')
    while not stop.is_set():
        try:
            schedule()
            Path('/tmp/jobsearch-scheduler-heartbeat').touch()
        except Exception as error:
            event('scheduler.failed',error_class=type(error).__name__)
            if args.once:
                return 1
        if args.once:
            break
        stop.wait(30)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
