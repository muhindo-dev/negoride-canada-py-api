"""Periodic onboarding jobs (registered in backend/jobs/scheduler.py:PERIODIC).

  poll_background_checks   every 6 h — start paid checks whose Certn order failed,
                           poll initiated/pending cases (webhook fallback), send
                           annual re-check reminders and expire lapsed checks
  document_expiry_check    daily — reminders 30/14/3 days before licence /
                           insurance / registration expiry (idempotent through
                           driver_documents.reminders_sent); on expiry the document
                           is marked expired, the driver is set offline and
                           can_go_online() refuses until a valid one is uploaded
"""
from backend.services import onboarding_service as O


def poll_background_checks():
    res = O.poll_pending()
    res.update({'recheck_' + k: v for k, v in O.recheck_scan().items()})
    return res


def document_expiry_check():
    return O.expiry_scan()
