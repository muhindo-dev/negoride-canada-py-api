"""Account activation / deactivation and automatic account rules (spec §15, §7.3, §14).

    set_status(user, status, actor, reason_code, reason_text, until=None, notify_user=True)
    can_go_online(user) -> (ok, reason)          used by /api/go-on-off and /api/update-location
    evaluate_strikes(driver_id)                  called by trip_effects after each reliability strike
    evaluate_rating_rules(driver_id)             called by the ratings module after each new rating
    apply_pending(user)                          deferred change once the active ride is over

Effects of a non-active status (take effect immediately):
  * legacy integer `status` = 0 (1 only for active) — v3 builds keep working
  * token_version += 1 → every existing JWT is rejected (utils/auth.py)
  * the user's /rt sockets get `account.status_changed` and are disconnected
  * drivers are set offline (ready_for_trip = 'No')
  * new requests are refused (jwt_required_with_user answers 403 outside
    INACTIVE_ALLOWED_PREFIXES)
A user who is on an active ride (CONFIRMED → IN_PROGRESS, seat CONFIRMED →
RIDING) is NOT cut off mid-trip: the change is stored in
`pending_account_status` / `pending_status_meta` and applied by an
@trip_effects.after_hook when the ride reaches a stage outside that set.
"""
import logging
from datetime import datetime, timedelta

from backend.models import db
from backend.models.identity import BackgroundCheck, DriverDocument
from backend.models.user import AdminUser
from backend.services import settings_service as S
from backend.services import trip_effects
from backend.services.audit import audit

log = logging.getLogger('negoride.account')

STATUSES = ('active', 'suspended', 'deactivated', 'banned', 'pending_review')
ACTIONS = {'activate': 'active', 'reactivate': 'active', 'suspend': 'suspended', 'deactivate': 'deactivated',
           'ban': 'banned', 'pending_review': 'pending_review'}
STATUS_FR = {'active': 'actif', 'suspended': 'suspendu', 'deactivated': 'désactivé', 'banned': 'banni',
             'pending_review': 'en cours d’examen'}
# reason_code: (category, EN label, FR label)
REASONS = {
    'safety_concern': ('safety', 'Safety concern', 'Préoccupation de sécurité'),
    'harassment': ('conduct', 'Harassment or abusive behaviour', 'Harcèlement ou comportement abusif'),
    'discrimination': ('conduct', 'Discrimination', 'Discrimination'),
    'policy_violation': ('conduct', 'Community Guidelines violation', 'Non-respect des lignes directrices'),
    'fraud': ('fraud', 'Suspected fraud', 'Fraude soupçonnée'),
    'payment_issue': ('payments', 'Payment issue', 'Problème de paiement'),
    'fake_documents': ('documents', 'Invalid or falsified documents', 'Documents invalides ou falsifiés'),
    'expired_documents': ('documents', 'Expired documents', 'Documents expirés'),
    'failed_background_check': ('background_check', 'Background check result', 'Résultat de la vérification des antécédents'),
    'low_rating': ('quality', 'Low rating', 'Note faible'),
    'reliability_strikes': ('reliability', 'Repeated cancellations or no-shows', 'Annulations ou absences répétées'),
    'under_investigation': ('safety', 'Under investigation', 'Enquête en cours'),
    'user_request': ('account', 'At your request', 'À votre demande'),
    'appeal_granted': ('account', 'Appeal granted', 'Appel accueilli'),
    'suspension_ended': ('account', 'Suspension ended', 'Fin de la suspension'),
    'reinstated': ('account', 'Account reinstated', 'Compte rétabli'),
    'other': ('other', 'Other', 'Autre'),
}
# Stages during which a status change is deferred (the ride is under way / money secured).
DEFER_STAGES = frozenset(('CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'IN_PROGRESS',
                          'BOARDING', 'CHECKED_IN', 'RIDING'))
EXPIRING_DOC_TYPES = ('licence_front', 'licence_back', 'insurance', 'registration')
DOC_LABELS = {
    'licence_front': ("driver's licence", 'permis de conduire'), 'licence_back': ("driver's licence", 'permis de conduire'),
    'insurance': ('insurance', 'assurance'), 'registration': ('vehicle registration', 'certificat d’immatriculation'),
}


class AccountError(Exception):
    def __init__(self, message, code='account_error', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def reason_label(code, lang='en'):
    r = REASONS.get(code or '', None)
    if not r:
        return None
    return r[2] if lang == 'fr' else r[1]


def reason_category(code):
    r = REASONS.get(code or '')
    return r[0] if r else ('other' if code else None)


def _iso(v):
    return v.strftime('%Y-%m-%dT%H:%M:%SZ') if v else None


def active_ride(user):
    """(ride_type, ride) if the user is on a ride that must not be cut, else (None, None)."""
    from backend.services import ride_actions
    try:
        rt, ride = ride_actions.find_active_for(user)
    except Exception:
        log.exception('find_active_for failed')
        return None, None
    if ride is not None and getattr(ride, 'trip_stage', None) in DEFER_STAGES:
        return rt, ride
    return None, None


def message_context(user, status, reason_code=None, reason_text=None, until=None):
    lang = (user.preferred_language or 'en')[:2]
    return {'status': status.replace('_', ' '), 'status_fr': STATUS_FR.get(status, status),
            'until': until.strftime('%Y-%m-%d %H:%M UTC') if until else '',
            'reason': reason_label(reason_code, lang) or '', 'reason_code': reason_code or '',
            'reason_category': reason_category(reason_code) or '', 'can_appeal': status != 'active'}


def preview_message(user, status, reason_code=None, until=None):
    """Rendered notification copy (EN + FR) an admin sees before confirming."""
    from backend.services.notify import catalogue as C
    from backend.services.notify.dispatcher import render
    key = 'account.reactivated' if status == 'active' else 'account.deactivated'
    spec = C.get(key)
    ctx = message_context(user, status, reason_code, None, until)
    ctx_fr = dict(ctx, reason=reason_label(reason_code, 'fr') or '')
    return {'event_key': key, 'channels': list(spec['channels']),
            'en': {'title': render(spec['title']['en'], ctx), 'body': render(spec['body']['en'], ctx)},
            'fr': {'title': render(spec['title']['fr'], ctx_fr), 'body': render(spec['body']['fr'], ctx_fr)}}


def set_status(user, status, actor=None, reason_code=None, reason_text=None, until=None, notify_user=True,
               defer_if_active_ride=True, commit=True, source='admin'):
    """Change the account status. Returns {'applied': bool, 'deferred': bool, 'account_status': …}."""
    status = ACTIONS.get(status, status)
    if status not in STATUSES:
        raise AccountError('Unknown account status.', 'invalid_status')
    if status == 'suspended' and until is not None and until <= datetime.utcnow():
        raise AccountError('The suspension end must be in the future.', 'invalid_until')
    if status != 'suspended':
        until = None

    if status != 'active' and defer_if_active_ride:
        rt, ride = active_ride(user)
        if ride is not None:
            user.pending_account_status = status
            user.pending_status_meta = {
                'reason_code': reason_code, 'reason_text': reason_text, 'until': _iso(until),
                'actor_id': getattr(actor, 'id', None), 'notify_user': bool(notify_user), 'source': source,
                'ride_type': rt, 'ride_id': ride.id, 'requested_at': _iso(datetime.utcnow())}
            audit('account.status_deferred', actor, 'user', user.id,
                  before={'account_status': user.effective_account_status()},
                  after={'pending_account_status': status, 'until': _iso(until)},
                  meta={'reason_code': reason_code, 'reason_text': reason_text, 'ride_type': rt, 'ride_id': ride.id,
                        'source': source})
            if commit:
                db.session.commit()
            return {'applied': False, 'deferred': True, 'account_status': user.effective_account_status(),
                    'pending_account_status': status, 'active_ride': {'ride_type': rt, 'ride_id': ride.id}}

    _apply(user, status, actor, reason_code, reason_text, until, source)
    if notify_user:
        _notify(user, status, reason_code, until)
    if commit:
        db.session.commit()
        after_commit_effects(user.id, status)
    return {'applied': True, 'deferred': False, 'account_status': user.effective_account_status(),
            'suspended_until': _iso(user.suspended_until)}


def _apply(user, status, actor, reason_code, reason_text, until, source):
    before = {'account_status': user.effective_account_status(), 'status': user.status,
              'suspended_until': _iso(user.suspended_until), 'status_reason_code': user.status_reason_code}
    now = datetime.utcnow()
    user.account_status = status
    user.status = 1 if status == 'active' else 0
    user.status_reason = (reason_text or '')[:500] or None
    user.status_reason_code = (reason_code or '')[:40] or None
    user.status_changed_by = getattr(actor, 'id', None)
    user.status_changed_at = now
    user.suspended_until = until if status == 'suspended' else None
    user.pending_account_status = None
    user.pending_status_meta = None
    if status != 'active':
        user.token_version = int(user.token_version or 0) + 1   # revoke every JWT now
        if user.ready_for_trip == 'Yes':
            user.ready_for_trip = 'No'
    audit('account.status_changed', actor, 'user', user.id, before=before,
          after={'account_status': status, 'status': user.status, 'suspended_until': _iso(user.suspended_until),
                 'status_reason_code': user.status_reason_code},
          meta={'reason_text': reason_text, 'source': source})


def _notify(user, status, reason_code, until):
    from backend.services.notify import notify
    if status == 'active':
        notify('account.reactivated', [user.id], {})
    else:
        notify('account.deactivated', [user.id], {
            **message_context(user, status, reason_code, None, until),
            'per_user': {str(user.id): {'reason': reason_label(reason_code, (user.preferred_language or 'en')[:2]) or ''}}})


def after_commit_effects(user_id, status):
    """Tell connected clients and drop their sockets (best effort, in-process).
    Revoked tokens also make any reconnect fail at the /rt handshake."""
    from backend.services import realtime
    realtime.to_user(user_id, 'account.status_changed', {'account_status': status})
    if status == 'active':
        return
    try:
        from backend.app import socketio
        from backend.sockets import realtime_events as RE
        for sid, uid in list(RE._sid_user.items()):
            if uid == user_id:
                try:
                    socketio.server.disconnect(sid, namespace=realtime.NAMESPACE)
                except Exception:
                    pass
                RE._sid_user.pop(sid, None)
    except Exception:
        log.debug('socket disconnect skipped', exc_info=True)


def apply_pending(user, commit=True):
    """Apply a deferred status change when the user's active ride is over."""
    if not user.pending_account_status:
        return False
    rt, ride = active_ride(user)
    if ride is not None:
        return False
    meta = user.pending_status_meta or {}
    until = None
    if meta.get('until'):
        until = datetime.strptime(meta['until'], '%Y-%m-%dT%H:%M:%SZ')
        if until <= datetime.utcnow():
            user.pending_account_status = None
            user.pending_status_meta = None
            audit('account.status_deferred_lapsed', None, 'user', user.id, meta=meta)
            if commit:
                db.session.commit()
            return False
    status = user.pending_account_status
    actor = db.session.get(AdminUser, meta['actor_id']) if meta.get('actor_id') else None
    _apply(user, status, actor, meta.get('reason_code'), meta.get('reason_text'), until,
           (meta.get('source') or 'admin') + ':deferred')
    if meta.get('notify_user', True):
        _notify(user, status, meta.get('reason_code'), until)
    if commit:
        db.session.commit()
        after_commit_effects(user.id, status)
    return True


@trip_effects.after_hook
def _on_ride_event(event, ride):
    """Deferred status changes + pay-later background-check deductions."""
    if event.to_stage in DEFER_STAGES:
        return
    from backend.services import rides as R
    try:
        party_ids = R.all_party_ids(event.ride_type, ride)
    except Exception:
        party_ids = []
    for uid in party_ids:
        u = db.session.get(AdminUser, uid)
        if u and u.pending_account_status:
            apply_pending(u)
    if event.to_stage in ('COMPLETED', 'DROPPED_OFF', 'CLOSED'):
        drv = R.driver_id(event.ride_type, ride)
        if drv:
            try:
                from backend.services import onboarding_service
                onboarding_service.settle_bgc_deductions(drv)
            except Exception:
                log.exception('bgc deduction settle failed for driver %s', drv)


# ── go-online gate ──────────────────────────────────────────────────────────

def can_go_online(user):
    """(ok, reason) — the reason is shown to the driver as-is."""
    st = user.effective_account_status()
    if st != 'active':
        return False, f'Your account is {st.replace("_", " ")}. You cannot go online.'
    if user.pending_account_status:
        return False, 'Your account is under review after this trip. You cannot go online right now.'
    today = datetime.utcnow().date()
    docs = (DriverDocument.query.filter(DriverDocument.user_id == user.id,
                                        DriverDocument.type.in_(EXPIRING_DOC_TYPES),
                                        DriverDocument.status.in_(('approved', 'pending', 'expired'))).all())
    for d in docs:
        if d.status == 'expired' or (d.expires_at and d.expires_at < today):
            label = DOC_LABELS.get(d.type, (d.type,))[0]
            return False, f'Your {label} has expired. Upload a valid one to go online.'
    from backend.models.identity import DriverApplication
    app = DriverApplication.query.filter_by(user_id=user.id).first()
    if app and app.status == 'approved' and not app.orientation_completed_at:
        return False, 'Complete the short safety orientation in the app before going online.'
    bgc = BackgroundCheck.query.filter_by(user_id=user.id).order_by(BackgroundCheck.id.desc()).first()
    if bgc:
        if bgc.status == 'failed':
            return False, 'Your background check did not meet our requirements. Contact support for details.'
        if bgc.status == 'expired' or (bgc.status == 'clear' and bgc.expires_at and bgc.expires_at < datetime.utcnow()):
            return False, 'Your annual background check is due. Renew it in the app to go online.'
    return True, None


# ── automatic rules ─────────────────────────────────────────────────────────

def _recent_audit(user_id, action, days):
    from backend.models.platform import AuditLog
    since = datetime.utcnow() - timedelta(days=days)
    u = db.session.get(AdminUser, user_id)
    if u and u.created_at and u.created_at > since:
        since = u.created_at   # ignore rows of an earlier account that had the same id
    return AuditLog.query.filter(AuditLog.action == action, AuditLog.entity_type == 'user',
                                 AuditLog.entity_id == str(user_id), AuditLog.created_at >= since).first()


def evaluate_strikes(driver_id):
    """Spec §7.3: > strikes.warn_after strikes in strikes.window_days → warning;
    > strikes.suspend_after → temporary suspension of strikes.suspend_days."""
    if not S.flag('strike_suspension'):
        return None
    from backend.models.money import DriverStrike
    user = db.session.get(AdminUser, driver_id)
    if not user:
        return None
    days = S.get_int('strikes.window_days')
    n = DriverStrike.query.filter(DriverStrike.driver_id == driver_id,
                                  DriverStrike.created_at >= datetime.utcnow() - timedelta(days=days)).count()
    if n > S.get_int('strikes.suspend_after'):
        if user.effective_account_status() != 'active' or user.pending_account_status:
            return 'already_restricted'
        set_status(user, 'suspended', None, 'reliability_strikes',
                   f'{n} cancellations/no-shows in {days} days',
                   until=datetime.utcnow() + timedelta(days=S.get_int('strikes.suspend_days')), source='rule:strikes')
        return 'suspended'
    if n > S.get_int('strikes.warn_after'):
        if _recent_audit(driver_id, 'account.strike_warning', days):
            return 'already_warned'
        from backend.services.notify import notify
        audit('account.strike_warning', None, 'user', driver_id, meta={'strikes': n, 'window_days': days})
        notify('account.warning', [driver_id], {
            'message': f'You have {n} cancellations or no-shows in the last {days} days. More than '
                       f'{S.get_int("strikes.suspend_after")} leads to a temporary suspension.'})
        db.session.commit()
        return 'warned'
    return None


def evaluate_rating_rules(driver_id):
    """Spec §15: average over the last rating.min_rides_for_rules rated rides
    < rating.suspend_below → suspended pending review; < rating.warn_below → warning."""
    if not S.flag('auto_suspend_low_rating'):
        return None
    try:
        from backend.models.experience import RideRating
    except ImportError:
        return None
    user = db.session.get(AdminUser, driver_id)
    if not user:
        return None
    n = S.get_int('rating.min_rides_for_rules')
    rows = (RideRating.query.filter(RideRating.ratee_id == driver_id, RideRating.role == 'customer',
                                    RideRating.hidden_by_admin.is_(False))
            .order_by(RideRating.id.desc()).limit(n).all())
    if len(rows) < n or n <= 0:
        return None
    avg = sum(r.stars for r in rows) / float(len(rows))
    if avg < S.get_float('rating.suspend_below'):
        if user.effective_account_status() != 'active' or user.pending_account_status:
            return 'already_restricted'
        set_status(user, 'pending_review', None, 'low_rating',
                   f'Average rating {avg:.2f} over the last {n} rated rides', source='rule:rating')
        return 'pending_review'
    if avg < S.get_float('rating.warn_below'):
        if _recent_audit(driver_id, 'account.rating_warning', 30):
            return 'already_warned'
        from backend.services.notify import notify
        audit('account.rating_warning', None, 'user', driver_id, meta={'average': round(avg, 3), 'rides': n})
        notify('account.warning', [driver_id], {
            'message': f'Your average rating over your last {n} trips is {avg:.2f}. Drivers below '
                       f'{S.get_float("rating.suspend_below"):.1f} are paused for review.'})
        db.session.commit()
        return 'warned'
    return None


# ── status for the user, appeals ────────────────────────────────────────────

def status_payload(user):
    st = user.effective_account_status()
    lang = (user.preferred_language or 'en')[:2]
    ok, why = can_go_online(user) if user.is_approved_driver() else (None, None)
    return {
        'account_status': st,
        'is_active': st == 'active',
        'reason_code': user.status_reason_code if st != 'active' else None,
        'reason_category': reason_category(user.status_reason_code) if st != 'active' else None,
        'reason_label': reason_label(user.status_reason_code, lang) if st != 'active' else None,
        'suspended_until': _iso(user.suspended_until) if st == 'suspended' else None,
        'changed_at': _iso(user.status_changed_at),
        'pending_account_status': user.pending_account_status,
        'can_appeal': st in ('suspended', 'deactivated', 'banned', 'pending_review'),
        'can_go_online': ok,
        'go_online_block_reason': why,
        'support_email': S.get('safety.support_email'),
    }


def sms_phone_changed(old_e164, lang='en'):
    """Job: SMS the OLD number after a phone change (spec §11.2 #3)."""
    from backend.services import twilio_client
    from backend.services.notify import catalogue as C
    body = C.get('account.phone_changed')['body']['fr' if (lang or '')[:2] == 'fr' else 'en']
    try:
        twilio_client.send_sms(old_e164, 'NegoRide: ' + body)
    except twilio_client.TwilioError as e:
        log.info('phone-changed SMS to old number not sent: %s', e)


def ensure_jobs_loaded():
    """Imported by routes/account.py so the after-hook is registered at app start."""
    return True
