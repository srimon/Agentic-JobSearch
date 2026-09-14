"""Persistent single-writer delivery guards shared by manual and scheduled reports."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager

@contextmanager
def exclusive(directory, name):
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(directory/name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another report workflow is active; no duplicate dispatch.') from None
        yield
    finally:os.close(fd)

def read_json(path, default=None):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    except FileNotFoundError:return default
    with os.fdopen(fd) as stream:return json.load(stream)

def atomic_json(path,value):
    fd,name=tempfile.mkstemp(prefix='.workflow-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);json.dump(value,stream,sort_keys=True)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)

def journal_states(path):
    if not path.exists():return {}
    result={}
    with path.open() as stream:
        for line in stream:
            if not line.strip():continue
            event=json.loads(line)
            if event['status'] not in ('sending','smtp_accepted','delivery_unknown','rejected'):
                raise RuntimeError('Unknown delivery journal state; reconciliation required.')
            result[event['report_hash']]=event['status']
    return result

def require_known_deliveries(path):
    if any(state in ('sending','delivery_unknown') for state in journal_states(path).values()):
        raise RuntimeError('A previous email outcome is uncertain; reconcile before sending another report.')
