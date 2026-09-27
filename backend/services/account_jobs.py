"""Hourly account housekeeping (scheduler: backend.services.account_jobs.tick).

  • temporary suspensions whose `suspended_until` passed → active (+ notification)
  • deferred status changes whose ride is over but whose hook was missed → applied
  • pay-later background-check deductions → settled when the wallet allows
"""
import logging
from datetime import datetime

from backend.models import db
from backend.models.identity import BackgroundCheck
from backend.models.user import AdminUser
from backend.services import account_service as A

log = logging.getLogger('negoride.account_jobs')


def end_expired_suspensions(now=None):
    now = now or datetime.utcnow()
    rows = (AdminUser.query.filter(AdminUser.account_status == 'suspended', AdminUser.suspended_until.isnot(None),
                                   AdminUser.suspended_until <= now).limit(500).all())
    n = 0
    for u in rows:
        try:
            A.set_status(u, 'active', None, 'suspension_ended', 'Temporary suspension ended',
                         notify_user=True, source='job:suspension_ended')
            n += 1
        except Exception:
            db.session.rollback()
            log.exception('could not end suspension for user %s', u.id)
    return n


def apply_deferred():
    n = 0
    for u in AdminUser.query.filter(AdminUser.pending_account_status.isnot(None)).limit(500).all():
        try:
            if A.apply_pending(u):
                n += 1
        except Exception:
            db.session.rollback()
            log.exception('could not apply deferred status for user %s', u.id)
    return n


def settle_deductions():
    from backend.services import onboarding_service
    ids = {r[0] for r in db.session.query(BackgroundCheck.user_id)
           .filter(BackgroundCheck.deduction_status == 'pending').limit(500).all()}
    n = 0
    for uid in ids:
        try:
            n += onboarding_service.settle_bgc_deductions(uid)
        except Exception:
            db.session.rollback()
            log.exception('deduction settle failed for %s', uid)
    return n


def tick():
    return {'suspensions_ended': end_expired_suspensions(), 'deferred_applied': apply_deferred(),
            'deductions_settled': settle_deductions()}
