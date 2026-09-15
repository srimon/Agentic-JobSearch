"""Owner recovery: turn off two-step sign-in for one local account (lost authenticator and recovery codes).

Usage: JBS/bin/python scripts/mfa_reset.py --username NAME [--apply]   (or python -m scripts.mfa_reset)
Dry run by default. Uses JOBSEARCH_DATABASE_URL. Prints only the username and the outcome; the account keeps its
password and sessions, and the person can set up two-step sign-in again from the Account page."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.auth.passwords import username  # noqa: E402
from src.db.store import connection, audit  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--username', required=True)
    parser.add_argument('--apply', action='store_true', help='Make the change; without it nothing is written')
    args = parser.parse_args(argv)
    try:
        name = username(args.username)
    except ValueError as error:
        parser.error(str(error))
    with connection() as conn:
        user = conn.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject=%s FOR UPDATE", (name,)).fetchone()
        if not user:
            print(name + ': account not found')
            return 1
        mfa = conn.execute('SELECT enabled_at FROM jobsearch.user_mfa WHERE user_id=%s', (user['id'],)).fetchone()
        state = 'on' if mfa and mfa['enabled_at'] else ('pending setup' if mfa else 'off')
        if not args.apply:
            print(name + ': two-step sign-in is ' + state + ('; run again with --apply to turn it off' if mfa else '; nothing to do'))
            return 0
        if not mfa:
            print(name + ': two-step sign-in is off; nothing changed')
            return 0
        from src.auth.mfa import clear_mfa
        clear_mfa(conn, user['id'])
        audit(conn, 'local-console', 'account.mfa.reset', str(user['id']))
    print(name + ': two-step sign-in turned off')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
