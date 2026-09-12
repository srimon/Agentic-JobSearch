"""Run with JBS/bin/python -m scripts.accounts ACTION USERNAME. Passwords use getpass."""
import argparse
import getpass
from src.auth.passwords import password_hash, username
from src.db.store import connection, audit

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create','reset','disable','enable','revoke'])
    parser.add_argument('username')
    parser.add_argument('--name', default='')
    parser.add_argument('--roles', nargs='+', choices=['viewer','member','operator','administrator'], default=['member'])
    args = parser.parse_args()
    name = username(args.username)
    encoded = None
    if args.action in ('create','reset'):
        password = getpass.getpass('Password (15-128 characters): ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
        encoded = password_hash(password)
    with connection() as conn:
        if args.action == 'create':
            row = conn.execute("INSERT INTO jobsearch.users(issuer,subject,display_name,roles,password_hash) VALUES('local',%s,%s,%s,%s) RETURNING id", (name,args.name or name,args.roles,encoded)).fetchone()
        else:
            row = conn.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject=%s FOR UPDATE", (name,)).fetchone()
            if not row: parser.error('Account not found')
            if args.action == 'reset':
                conn.execute('UPDATE jobsearch.users SET password_hash=%s WHERE id=%s', (encoded,row['id']))
            elif args.action in ('disable','enable'):
                conn.execute('UPDATE jobsearch.users SET active=%s WHERE id=%s', (args.action=='enable',row['id']))
            conn.execute('DELETE FROM jobsearch.sessions WHERE user_id=%s', (row['id'],))
        audit(conn,'local-console','account.'+args.action,str(row['id']))
    print('Account operation completed.')

if __name__ == '__main__': main()
