"""Run with JBS/bin/python -m scripts.accounts ACTION USERNAME [EMAIL]. Passwords use getpass.
Actions: create, reset, disable, enable, revoke, roles USERNAME --roles ..., verify USERNAME, email USERNAME EMAIL."""
import argparse
import getpass
import psycopg.errors
from src.auth.passwords import password_hash, username, email_address
from src.db.store import connection, audit
from src.settings import ROLES

REVOKING = ('reset', 'disable', 'enable', 'revoke')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create','reset','disable','enable','revoke','roles','verify','email'])
    parser.add_argument('username')
    parser.add_argument('email', nargs='?', default='', help='New address for the email action')
    parser.add_argument('--name', default='')
    parser.add_argument('--roles', nargs='+', choices=list(ROLES), default=None)
    args = parser.parse_args()
    name = username(args.username)
    encoded = None
    if args.action in ('create','reset'):
        password = getpass.getpass('Password (15-128 characters): ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
        encoded = password_hash(password)
    if args.action == 'roles' and not args.roles:
        parser.error('roles requires --roles')
    if args.action == 'email':
        try:
            address = email_address(args.email)
        except ValueError as error:
            parser.error(str(error))
    with connection() as conn:
        if args.action == 'create':
            row = conn.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local',%s,%s,%s,%s) RETURNING id", (name,args.name or name,args.roles or ['member'],encoded)).fetchone()
        else:
            row = conn.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject=%s FOR UPDATE", (name,)).fetchone()
            if not row: parser.error('Account not found')
            if args.action == 'reset':
                conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s', (encoded,row['id']))
            elif args.action in ('disable','enable'):
                conn.execute('UPDATE jobsearch.users SET active=%s WHERE id=%s', (args.action=='enable',row['id']))
            elif args.action == 'roles':
                conn.execute('UPDATE jobsearch.users SET roles=%s WHERE id=%s', (args.roles,row['id']))
            elif args.action == 'verify':
                conn.execute('UPDATE jobsearch.users SET email_verified_at=coalesce(email_verified_at,now()) WHERE id=%s', (row['id'],))
            elif args.action == 'email':
                # The address starts unverified: the user confirms it through the queued mail, or run verify.
                from src.auth.signup import send_verification
                try:
                    with conn.transaction():
                        conn.execute('UPDATE jobsearch.users SET email=%s,email_verified_at=NULL WHERE id=%s', (address,row['id']))
                except psycopg.errors.UniqueViolation:
                    parser.error('Another account already uses that email address')
                send_verification(conn, row['id'], address)
            if args.action in REVOKING:
                conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s', (row['id'],))
        audit(conn,'local-console','account.'+args.action,str(row['id']))
    print('Account operation completed.')

if __name__ == '__main__': main()
