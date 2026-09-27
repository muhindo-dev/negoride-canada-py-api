"""Swappable transactional email provider (spec §13.1).

EMAIL_PROVIDER = smtp (default, uses MAIL_* settings) | postmark | console | memory
Every message is multipart (HTML + plain text) and may carry attachments
(receipt PDFs).  `memory` keeps messages in OUTBOX for tests.
"""
import base64
import logging
import os
import smtplib
import ssl
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

import requests

log = logging.getLogger('negoride.email')
OUTBOX = []


class EmailError(Exception):
    pass


def provider_name():
    return (os.getenv('EMAIL_PROVIDER') or 'smtp').strip().lower()


def _from_header():
    from flask import current_app
    explicit = os.getenv('EMAIL_FROM', '').strip()
    if explicit:
        return explicit
    name = current_app.config.get('MAIL_FROM_NAME', 'NegoRide Canada')
    addr = current_app.config.get('MAIL_FROM_ADDRESS') or current_app.config.get('MAIL_USERNAME') or 'no-reply@negoride.ca'
    return formataddr((name, addr))


def send(to, subject, html, text=None, attachments=None, reply_to=None, tag=None):
    """Send one email. Returns a provider message id. Raises EmailError."""
    attachments = attachments or []
    text = text or _html_to_text(html)
    reply_to = reply_to or os.getenv('EMAIL_REPLY_TO', '').strip() or None
    p = provider_name()
    if p == 'memory':
        mid = f'mem-{uuid.uuid4().hex[:12]}'
        OUTBOX.append({'id': mid, 'to': to, 'subject': subject, 'html': html, 'text': text,
                       'attachments': [(a[0], len(a[1]), a[2]) for a in attachments], 'tag': tag})
        return mid
    if p == 'console':
        log.warning('[email:console] to=%s subject=%s attachments=%s', to, subject, [a[0] for a in attachments])
        return f'console-{uuid.uuid4().hex[:12]}'
    if p == 'postmark':
        return _postmark(to, subject, html, text, attachments, reply_to, tag)
    return _smtp(to, subject, html, text, attachments, reply_to)


def _postmark(to, subject, html, text, attachments, reply_to, tag):
    token = os.getenv('POSTMARK_SERVER_TOKEN', '')
    if not token:
        raise EmailError('POSTMARK_SERVER_TOKEN not configured')
    body = {
        'From': _from_header(), 'To': to, 'Subject': subject, 'HtmlBody': html, 'TextBody': text,
        'MessageStream': os.getenv('POSTMARK_STREAM', 'outbound'), 'TrackOpens': True,
    }
    if reply_to:
        body['ReplyTo'] = reply_to
    if tag:
        body['Tag'] = tag
    if attachments:
        body['Attachments'] = [{'Name': n, 'Content': base64.b64encode(b).decode(), 'ContentType': m}
                               for n, b, m in attachments]
    r = requests.post('https://api.postmarkapp.com/email', json=body, timeout=15,
                      headers={'X-Postmark-Server-Token': token, 'Accept': 'application/json'})
    data = r.json() if r.content else {}
    if r.status_code != 200 or data.get('ErrorCode'):
        raise EmailError(f"Postmark error {data.get('ErrorCode')}: {data.get('Message')}")
    return data.get('MessageID')


def _smtp(to, subject, html, text, attachments, reply_to):
    from flask import current_app
    cfg = current_app.config
    username, password = cfg.get('MAIL_USERNAME', ''), cfg.get('MAIL_PASSWORD', '')
    if not username or not password:
        log.warning('[email] SMTP not configured — message to %s logged only', to)
        return f'unsent-{uuid.uuid4().hex[:12]}'
    outer = MIMEMultipart('mixed')
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(text, 'plain', 'utf-8'))
    alt.attach(MIMEText(html, 'html', 'utf-8'))
    outer.attach(alt)
    for name, blob, mime in attachments:
        part = MIMEApplication(blob, _subtype=mime.split('/')[-1])
        part.add_header('Content-Disposition', 'attachment', filename=name)
        outer.attach(part)
    from_addr = cfg.get('MAIL_FROM_ADDRESS') or username
    outer['Subject'] = subject
    outer['From'] = _from_header()
    outer['To'] = to
    mid = make_msgid(domain=from_addr.split('@')[-1] if '@' in from_addr else None)
    outer['Message-ID'] = mid
    if reply_to:
        outer['Reply-To'] = reply_to
    try:
        ctx = ssl.create_default_context()
        if cfg.get('MAIL_USE_SSL'):
            with smtplib.SMTP_SSL(cfg.get('MAIL_SERVER'), cfg.get('MAIL_PORT'), context=ctx, timeout=20) as s:
                s.login(username, password)
                s.sendmail(from_addr, [to], outer.as_string())
        else:
            with smtplib.SMTP(cfg.get('MAIL_SERVER'), cfg.get('MAIL_PORT'), timeout=20) as s:
                if cfg.get('MAIL_USE_TLS', True):
                    s.starttls(context=ctx)
                s.login(username, password)
                s.sendmail(from_addr, [to], outer.as_string())
    except Exception as exc:
        raise EmailError(str(exc))
    return mid


def _html_to_text(html):
    import re
    import html as h
    t = re.sub(r'(?is)<(script|style).*?</\1>', '', html or '')
    t = re.sub(r'(?i)<br\s*/?>|</p>|</tr>|</h\d>|</div>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = h.unescape(t)
    return re.sub(r'\n\s*\n+', '\n\n', t).strip()
