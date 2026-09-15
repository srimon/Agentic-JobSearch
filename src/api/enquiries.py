"""Anonymous enquiries from the "Email Admin" dialog in every Bagala footer. Gateways and the public edge forward
same-origin POST /__hub/enquiries here. The sender's email address and message are stored and mailed to the
admin recipient, but never logged or written to audit events."""
import hashlib
import logging
import re
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from src.settings import settings
from src.db.store import connection, audit
from src.auth.local import throttled
from src.auth.passwords import email_address
from src.mail import queue_mail

ACCEPTED = {'detail': 'Thank you. Your message has been sent.'}
RETRY_LATER = HTTPException(429, 'Too many messages. Try again later.', headers={'Retry-After': '900'})
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
log = logging.getLogger('jobsearch.api')


class Enquiry(BaseModel):
    # Loose limits here so the honeypot is answered before field rules; the real rules are checked in the handler.
    name: str = Field(default='', max_length=1000)
    email: str = Field(default='', max_length=1000)
    message: str = Field(default='', max_length=10000)
    company_website: str = Field(default='', max_length=1000)
    page: str | None = Field(default=None, max_length=1000)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def forwarded_client(request):
    """First X-Forwarded-For hop as seen by the app, or '' when the request was not forwarded."""
    return request.headers.get('x-forwarded-for', '').split(',')[0].strip()[:100]


def recipient(cfg):
    return (cfg.enquiry_recipient or '').strip() or (cfg.report_recipient or '').strip()


def create_router():
    router = APIRouter()

    @router.post('/api/enquiries', status_code=202)
    def enquiry(body: Enquiry, request: Request):
        if body.company_website.strip():
            return ACCEPTED
        name = ' '.join(body.name.split())
        if not 1 <= len(name) <= 120 or CONTROL.search(name):
            raise HTTPException(422, 'Enter your name (up to 120 characters).')
        try:
            email = email_address(body.email)
        except ValueError:
            raise HTTPException(422, 'Enter a valid email address.')
        message = body.message.strip()
        if not 10 <= len(message) <= 2000:
            raise HTTPException(422, 'Enter a message of 10 to 2000 characters.')
        page = ' '.join((body.page or '').split()) or None
        if page and len(page) > 200:
            raise HTTPException(422, 'Page must be at most 200 characters.')
        client = forwarded_client(request)
        client_hash = sha('client:' + (client or (request.client.host if request.client else '')))
        # The global budget bounds floods; a forwarded client address gets its own budget, and every sender address
        # has one too, so an unforwarded request (where all callers share the gateway's address) is still limited.
        buckets = [('enquiry', 30)]
        if client:
            buckets.append(('enquiry:client:' + client_hash, 3))
        buckets.append(('enquiry:email:' + sha(email.lower()), 3))
        cfg = settings()
        to = recipient(cfg)
        with connection() as conn:
            throttle = throttled(conn, buckets)
            if throttle:
                audit(conn, 'anonymous', 'enquiry.create', 'enquiry', 'throttled')
            else:
                row = conn.execute('INSERT INTO jobsearch.enquiries(name,email,message,page,client_hash) VALUES(%s,%s,%s,%s,%s) RETURNING id',
                                   (name, email, message, page, client_hash)).fetchone()
                if to:
                    text = ('New enquiry from ' + name + '\n\nName: ' + name + '\nEmail: ' + email + '\nPage: ' + (page or 'Not given') +
                            '\n\nMessage:\n' + message + '\n')
                    queue_mail(conn, 'enquiry', to, 'New enquiry from ' + name, text)
                else:
                    log.warning('enquiry_stored_without_recipient enquiry_id=%s', row['id'])
                audit(conn, 'anonymous', 'enquiry.create', 'enquiry:' + str(row['id']), 'allowed', details={'mail': 'queued' if to else 'none'})
        if throttle:
            raise RETRY_LATER
        return ACCEPTED

    return router
