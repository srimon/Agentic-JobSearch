"""Owner-only application digest. SMTP credentials use an optional owner-only secret file or hidden prompt."""
import argparse
import fcntl
import getpass
import hashlib
import html
from urllib.parse import urlsplit
import json
import os
from pathlib import Path
import smtplib
import ssl
import subprocess
import sys
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

ADDRESS = 'sean.chopparapu@gmail.com'
ROOT = Path(__file__).resolve().parents[1]
EXPORT = r'''
import json
from src.db.store import connection
from src.applications.private import private_connection,decrypt
from src.applications.dismissals import dismissal_for
from src.applications.archives import archive_for
from src.applications.learning import current,explain
with connection() as c:
 u=c.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject='admin' AND active").fetchone()
 if not u: raise RuntimeError('Active owner missing')
with private_connection(u['id']) as c:
 model=current(c,u['id'])
 rows=c.execute('SELECT job_id,payload FROM jobsearch.private_applications WHERE user_id=%s ORDER BY job_id',(u['id'],)).fetchall()
 out=[]
 for row in rows:
  p=decrypt(u['id'],'application:'+str(row['job_id']),row['payload'])
  job=c.execute('SELECT id,url,title,level,work_mode,source_id FROM jobsearch.jobs WHERE id=%s',(row['job_id'],)).fetchone()
  if job and archive_for(c,u['id'],job): continue
  dismissed=dismissal_for(c,u['id'],job) if job else None
  ranking=explain(job,model) if job else {'adjustment':0,'reasons':[]}
  p['learning_adjustment']=ranking['adjustment'];p['learning_reasons']=ranking['reasons']
  p['job_id']=str(row['job_id'])
  p['dismissal_reason']=dismissed['reason'] if dismissed else None
  out.append({k:p.get(k) for k in ('job_id','company','title','status','submitted','attempt_finished_at','next_action','url','dismissal_reason','confirmation_source','learning_adjustment','learning_reasons')})
 for row in c.execute("SELECT j.id::text AS job_id,j.company,j.title,j.url FROM jobsearch.saved_jobs s JOIN jobsearch.jobs j ON j.id=s.job_id WHERE s.user_id=%s AND s.stage IN ('applied','interviewing','offer','closed') AND NOT EXISTS(SELECT 1 FROM jobsearch.private_applications a WHERE a.user_id=s.user_id AND a.job_id=s.job_id)",(u['id'],)).fetchall():
  if archive_for(c,u['id'],row): continue
  out.append({**dict(row),'status':'submitted','submitted':True,'confirmation_source':'user_reported','next_action':'Application stage tracked by you. Do not submit again.'})
 out.sort(key=lambda row:-(row.get('learning_adjustment') or 0))
 print(json.dumps(out))
'''



def report_transport():
    value = os.environ.get('JOBSEARCH_REPORT_TRANSPORT', 'compose')
    if value not in ('compose', 'direct'):
        raise RuntimeError('Unsupported report transport')
    return value

def state_directory():
    return Path(os.environ.get('JOBSEARCH_REPORT_STATE_DIR', str(ROOT / 'data' / 'processed')))

def report_origin():
    value = os.environ.get('JOBSEARCH_REPORT_ORIGIN', 'http://localhost:3105').rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password
        or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)
        or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'))):
        raise RuntimeError('Report origin must be HTTPS, or loopback HTTP')
    return value

def export_rows():
    if report_transport() == 'direct':
        try:
            from src.applications.reporting import export_rows as direct_export
            return direct_export()
        except Exception:
            raise RuntimeError('Could not read the owner application report; no email sent.') from None
    result = subprocess.run(['docker','compose','-p','jobsearch','-f',str(ROOT/'compose.yaml'),'exec','-T','api','python','-c',EXPORT],capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('Could not read the owner application report; no email sent.')
    return json.loads(result.stdout)


def application_url(value):
    if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return value

def html_report(body):
    lines = []
    for line in body.splitlines():
        if line.startswith('Manage status: ' + report_origin() + '/?view=emailed&job='):
            url = line.removeprefix('Manage status: ')
            try:
                uuid.UUID(url.rsplit('=',1)[1])
                lines.append('<p><a href="'+html.escape(url,quote=True)+'">Update status in Jobsearch</a></p>')
                continue
            except ValueError:
                pass
        if line.startswith('Application link: '):
            url = application_url(line.removeprefix('Application link: '))
            if url:
                lines.append('<p><a href="' + html.escape(url, quote=True) + '">Open job / application page</a></p>')
                continue
        lines.append('<p>' + html.escape(line) + '</p>')
    return '<!doctype html><html><body>' + ''.join(lines) + '</body></html>'

def render(rows):
    lines = ['Jobsearch application report', '',
             'Applied entries distinguish employer confirmation from completion reported by you. Unknown outcomes must not be retried.', '']
    for row in rows:
        status = 'Applied (confirmed)' if row.get('submitted') and row.get('status') == 'submitted' else str(row.get('status') or 'not_submitted')
        if row.get('submitted') and row.get('confirmation_source') == 'user_reported':
            status = 'Successfully applied (confirmed by you)'
        # Only a fixed allowlist is exported: never resumes, demographic answers, or receipt bodies.
        company = ' '.join(str(row.get('company') or '').split())[:200]
        title = ' '.join(str(row.get('title') or '').split())[:300]
        if row.get('dismissal_reason'):
            status = 'Dismissed — ' + str(row['dismissal_reason']).replace('_',' ') + ' (application history: ' + status + ')'
        reason = ' '.join(str(row.get('next_action') or 'No additional reason recorded.').split())[:600]
        if row.get('dismissal_reason'):
            reason = 'Restore this job in Jobsearch before application preparation. ' + reason
        lines.append(f'{company} | {title} | {status} | {reason}')
        if row.get('learning_reasons'):
            lines.append('Ranking feedback: '+str(row.get('learning_adjustment',0))+' — '+' '.join(row['learning_reasons']))
        url = application_url(row.get('url'))
        if url:
            lines.append('Application link: ' + url)
        if row.get('job_id'):
            job_id = str(uuid.UUID(str(row['job_id'])))
            lines.append('Manage status: ' + report_origin() + '/?view=emailed&job=' + job_id)
        if row.get('status') in ('submission_unknown', 'submitting'):
            lines.append('Verify the previous attempt before submitting again; duplicate retry is blocked.')
    if not rows:
        lines.append('No application records yet.')
    return '\n'.join(lines) + '\n'

def record(stream, digest, status):
    stream.write(json.dumps({'report_hash':digest,'status':status,'time':datetime.now(timezone.utc).isoformat()})+'\n')
    stream.flush()
    os.fsync(stream.fileno())

def deliver(body, password, journal):
    digest = hashlib.sha256((ADDRESS+'\n'+body).encode()).hexdigest()
    journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(journal, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+', encoding='utf-8') as log:
        fcntl.flock(log, fcntl.LOCK_EX)
        prior = [json.loads(line) for line in log if line.strip()]
        if any(x['report_hash']==digest and x['status'] in ('sending','smtp_accepted','delivery_unknown') for x in prior):
            raise RuntimeError('This report was sent or needs reconciliation; duplicate delivery blocked.')
        message = EmailMessage()
        message['From'] = ADDRESS
        message['To'] = ADDRESS
        message['Subject'] = 'Jobsearch application report'
        message['Message-ID'] = f'<jobsearch-{digest}@gmail.com>'
        message.set_content(body)
        message.add_alternative(html_report(body), subtype='html')
        # No plaintext fallback and no SMTP debug logging.
        with smtplib.SMTP('smtp.gmail.com',587,timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(ADDRESS,password)
            record(log,digest,'sending')
            try:
                refused = smtp.send_message(message)
                if refused:
                    record(log,digest,'rejected')
                    raise RuntimeError('Recipient rejected by SMTP server.')
            except RuntimeError:
                raise
            except Exception:
                record(log,digest,'delivery_unknown')
                raise RuntimeError('Delivery uncertain; reconcile before retrying.') from None
            record(log,digest,'smtp_accepted')
    return 'Gmail accepted the report for delivery. Inbox delivery is not independently verified.'


def validate_password(value):
    value = value.strip().replace(' ', '')
    if len(value) != 16 or not value.isascii() or not value.isalpha():
        raise RuntimeError('Expected a 16-letter Google app password.')
    return value

def secret_directory():
    directory = Path(os.environ.get('JOBSEARCH_REPORT_SECRET_DIR', str(ROOT / '.secrets')))
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('Secret directory must be owned by the current user with permissions 0700 and must not be a symlink.')
    return directory

def save_password(value):
    value = validate_password(value)
    directory = secret_directory()
    fd, temporary = tempfile.mkstemp(prefix='.gmail-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(value + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'gmail_app_password')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def load_password():
    path = secret_directory() / 'gmail_app_password'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'r', encoding='ascii') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError('Gmail secret must be a regular owner-only file with permissions 0600.')
        return validate_password(stream.read(128))


def scheduled_body(body, now=None):
    now = now or datetime.now(timezone.utc)
    window = now.astimezone(timezone.utc).replace(hour=(now.astimezone(timezone.utc).hour // 3) * 3, minute=0, second=0, microsecond=0)
    lines = ['Scheduled report window: ' + window.isoformat(), '']
    path = state_directory() / 'scheduled-run-summary.json'
    if path.exists():
        if now.timestamp() - path.stat().st_mtime > 10800:
            lines.append('Run summary is stale; current collection/source-check results are not verified.')
        else:
            if path.stat().st_size > 100000:
                raise RuntimeError('Scheduled summary exceeds size limit.')
            summary = json.loads(path.read_text())
            allowed = {'jobs', 'sources', 'applications', 'failures'}
            if not isinstance(summary, dict) or set(summary) - allowed:
                raise RuntimeError('Scheduled summary has unsupported fields.')
            for key in ('jobs', 'sources', 'applications', 'failures'):
                entries = summary.get(key, [])
                if not isinstance(entries, list) or len(entries) > 100 or any(not isinstance(x, str) or len(x) > 1000 for x in entries):
                    raise RuntimeError('Scheduled summary has invalid entries.')
                lines.append(key.capitalize() + ':')
                lines.extend(' - ' + ' '.join(x.split()) for x in entries)
                if not entries:
                    lines.append(' - No entries recorded.')
    else:
        lines.append('No run summary recorded; discovery and source checks are not verified for this window.')
    return '\n'.join(lines) + '\n\n' + body


TRACK_REPORT = r"""
import sys,json,uuid,re
from src.db.store import connection
from src.applications.private import private_connection
from src.applications.email_history import record_report
data=json.load(sys.stdin)
assert re.fullmatch('[0-9a-f]{64}',data['report_hash'])
ids=[str(uuid.UUID(x)) for x in data['job_ids']]
with connection() as c:
 u=c.execute("SELECT id FROM jobsearch.users WHERE issuer='local' AND subject='admin' AND active").fetchone()
assert u
with private_connection(u['id']) as c:
 record_report(c,u['id'],data['report_hash'],ids,accepted=data['accepted'])
"""

def track_report(body, rows, accepted=False):
    data = {'report_hash':hashlib.sha256((ADDRESS+'\n'+body).encode()).hexdigest(),
            'job_ids':[str(uuid.UUID(str(row['job_id']))) for row in rows if row.get('job_id')], 'accepted':accepted}
    if report_transport() == 'direct':
        try:
            from src.applications.reporting import record_report_data
            record_report_data(data)
            return
        except Exception:
            raise RuntimeError('Email history update failed. Check delivery journal before retrying; email may already have been accepted.' if accepted else 'Could not prepare email history; no email sent.') from None
    result = subprocess.run(['docker','compose','-p','jobsearch','-f',str(ROOT/'compose.yaml'),'exec','-T','api','python','-c',TRACK_REPORT],input=json.dumps(data),capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('Email history update failed. Check delivery journal before retrying; email may already have been accepted.' if accepted else 'Could not prepare email history; no email sent.')

def send_tracked(body, rows, password, journal):
    from src.applications.delivery_state import exclusive,require_known_deliveries
    with exclusive(journal.parent,'report-dispatch.lock'):
        require_known_deliveries(journal)
        return _send_tracked(body,rows,password,journal)

def _send_tracked(body, rows, password, journal):
    track_report(body, rows)
    try:
        message = deliver(body,password,journal)
    except Exception:
        # Reconcile a prior accepted identical report or a failure after SMTP acceptance.
        # No email is resent during recovery; unresolved sends remain blocked.
        digest = hashlib.sha256((ADDRESS+'\n'+body).encode()).hexdigest()
        events = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()] if journal.exists() else []
        matching = [event for event in events if event['report_hash']==digest]
        if not matching or matching[-1]['status']!='smtp_accepted':
            raise
        message = 'Report was already accepted by Gmail; emailed-job history synchronized without resending.'
    track_report(body, rows, accepted=True)
    return message

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preview','send','configure'])
    parser.add_argument('--scheduled', action='store_true', help='Include current run summary and three-hour window for delivery deduplication.')
    args = parser.parse_args()
    if args.scheduled and (state_directory()/'daily-owner.json').exists():
        raise RuntimeError('Scheduled reporting is owned by the daily workflow; direct scheduled sends are disabled.')
    if args.action == 'configure':
        if not sys.stdin.isatty():
            raise RuntimeError('Run configure in your interactive WSL terminal.')
        value = getpass.getpass('Google app password (hidden; saved in .secrets): ')
        if value != getpass.getpass('Confirm app password (hidden): '):
            raise RuntimeError('Passwords do not match; existing secret unchanged.')
        save_password(value)
        print('Gmail app password saved with owner-only permissions. No email sent.')
        return
    rows = export_rows()
    body = render(rows)
    if args.scheduled:
        body = scheduled_body(body)
    if args.action == 'preview':
        print(body)
        return
    password = load_password()
    if password is None:
        if not sys.stdin.isatty():
            raise RuntimeError('First run ./scripts/email-report.sh configure in your WSL terminal.')
        password = validate_password(getpass.getpass('Google app password (hidden, not saved): '))
    try:
        print(send_tracked(body,rows,password,state_directory()/'email-delivery.jsonl'))
    finally:
        password = None

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,RuntimeError) else 'Email operation failed ('+type(exc).__name__+'); credentials were not logged.',file=sys.stderr)
        sys.exit(1)
