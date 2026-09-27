"""Platform housekeeping jobs."""
from datetime import datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.platform import IdempotencyKey, WebhookEvent

MAX_WEBHOOK_ATTEMPTS = 5


def tick():
    retried = retry_failed_webhooks()
    purge_idempotency_keys()
    return retried


def retry_failed_webhooks():
    """Re-process webhook events that failed or were never picked up."""
    stale = datetime.utcnow() - timedelta(minutes=2)
    rows = (WebhookEvent.query
            .filter(WebhookEvent.attempts < MAX_WEBHOOK_ATTEMPTS)
            .filter((WebhookEvent.status == 'failed') |
                    ((WebhookEvent.status == 'received') & (WebhookEvent.received_at <= stale)))
            .limit(50).all())
    paths = {'stripe': 'backend.routes.webhooks.process_stripe_event',
             'certn': 'backend.services.onboarding_service.process_certn_event'}
    n = 0
    for r in rows:
        path = paths.get(r.provider)
        if not path:
            continue
        try:
            jobs.run_job(path, (r.id,))
            n += 1
        except Exception:
            pass
    return n


def purge_idempotency_keys(days=7):
    IdempotencyKey.query.filter(IdempotencyKey.created_at < datetime.utcnow() - timedelta(days=days)) \
        .delete(synchronize_session=False)
    db.session.commit()
