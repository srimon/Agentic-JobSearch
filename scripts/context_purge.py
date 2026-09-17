"""Blank the raw network address in the sign-up record once it is older than the retention window:
python -m scripts.context_purge [--months N] [--dry-run].

The owner keeps the address as sent for twelve months (abuse investigation, analytics) and no
longer: this pass sets ip to NULL in jobsearch.account_context, consent_events and signup_attempts
where the row is older than settings.context_address_retention_months, and keeps everything else
(country, city, device, choices). Runs daily as the CronJob jbs-production/account-context-purge in
the api image (the hub's scripts/jobsearch_account_options.py), as the application role. Prints one
JSON line of counts; never a row. Exit 1 when the pass fails.
"""
import argparse
import json
import logging
import sys
from src.settings import settings
from src.db.store import connection

log = logging.getLogger('jobsearch.context_purge')
# table -> the column that dates the row
TABLES = {'account_context': 'recorded_at', 'consent_events': 'recorded_at', 'signup_attempts': 'created_at'}


def purge(conn, months, dry_run=False):
    """Rows per table whose address was (or would be) blanked."""
    counts = {}
    for table, dated in TABLES.items():
        if dry_run:
            counts[table] = conn.execute("SELECT count(*) n FROM jobsearch.{} WHERE ip IS NOT NULL AND {} < now()-(%s * interval '1 month')".format(table, dated),
                                         (months,)).fetchone()['n']
        else:
            counts[table] = conn.execute("UPDATE jobsearch.{} SET ip=NULL WHERE ip IS NOT NULL AND {} < now()-(%s * interval '1 month')".format(table, dated),
                                         (months,)).rowcount
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--months', type=int, default=None, help='retention window; default settings.context_address_retention_months')
    parser.add_argument('--dry-run', action='store_true', help='count what would be blanked and change nothing')
    args = parser.parse_args(argv)
    months = args.months if args.months is not None else settings().context_address_retention_months
    if months < 1:
        parser.error('--months must be at least 1')
    try:
        with connection() as conn:
            counts = purge(conn, months, args.dry_run)
    except Exception as error:
        log.error('context_purge_failed error_class=%s', type(error).__name__)
        return 1
    print(json.dumps({'event': 'context_purge.dry_run' if args.dry_run else 'context_purge.done', 'months': months, 'blanked': counts}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
