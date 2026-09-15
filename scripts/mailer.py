"""Deliver queued account mail: JBS/bin/python -m scripts.mailer [--once]. Run a single replica; it polls every
10 seconds, commits each row on its own, touches JOBSEARCH_MAILER_HEARTBEAT after every successful pass (the
worker/scheduler probe pattern) and exits promptly on SIGTERM. --once drains the queue one time (jobs, tests)."""
import argparse
import logging
import os
import signal
import threading
from pathlib import Path
from src.settings import settings
from src.db.store import connection
from src.mail import deliver_pending

log = logging.getLogger('jobsearch.mailer')


def heartbeat_path():
    return Path(os.environ.get('JOBSEARCH_MAILER_HEARTBEAT', '/tmp/jobsearch-mailer-heartbeat'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Deliver what is queued now and exit')
    parser.add_argument('--interval', type=float, default=10.0, help='Seconds between polls')
    args = parser.parse_args(argv)
    stop = threading.Event()
    try:
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    except ValueError:
        pass  # signals can only be registered from the main thread (tests)
    transport = settings().mail_transport
    while not stop.is_set():
        try:
            with connection() as conn:
                deliver_pending(conn, transport)
            heartbeat_path().touch()
        except Exception as error:
            log.error('mailer_pass_failed error_class=%s', type(error).__name__)
            if args.once:
                return 1
        if args.once:
            break
        stop.wait(max(args.interval, 0.1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
