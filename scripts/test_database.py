"""Initialize only the explicitly selected disposable integration-test database.

Usage: JOBSEARCH_AUTH_TEST=1 JOBSEARCH_DATABASE_URL=<test DSN> python scripts/test_database.py
Never use application credentials pointing at the application database.
"""
import os
from pathlib import Path
import psycopg


def main():
    if os.environ.get('JOBSEARCH_AUTH_TEST') != '1':
        raise SystemExit('Set JOBSEARCH_AUTH_TEST=1 for the disposable test database only')
    dsn=os.environ.get('JOBSEARCH_DATABASE_URL','')
    if not dsn:
        raise SystemExit('Disposable test database URL is required')
    root=Path(__file__).resolve().parents[1]
    with psycopg.connect(dsn) as c:
        if c.execute('SELECT current_database()').fetchone()[0]!='jobsearch_auth_test':
            raise SystemExit('Refusing to reset any database except jobsearch_auth_test')
        c.execute("""DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobsearch_app') THEN
                CREATE ROLE jobsearch_app NOLOGIN;
            END IF;
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='jobsearch_worker') THEN
                CREATE ROLE jobsearch_worker NOLOGIN;
            END IF;
        END $$""")
        c.execute('DROP SCHEMA IF EXISTS jobsearch CASCADE')
        for migration in sorted((root/'src/db').glob('*.sql')):
            c.execute(migration.read_text())
        c.execute('GRANT USAGE ON SCHEMA jobsearch TO jobsearch_app,jobsearch_worker')
        c.execute('GRANT SELECT,INSERT,UPDATE ON jobsearch.sources,jobsearch.runs,jobsearch.jobs,jobsearch.observations TO jobsearch_worker')
        c.execute('GRANT INSERT ON jobsearch.audit_events TO jobsearch_worker')
        c.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA jobsearch TO jobsearch_worker')
    print('Disposable jobsearch_auth_test schema initialized')


if __name__=='__main__':
    main()
