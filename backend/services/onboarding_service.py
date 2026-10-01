"""Driver onboarding wizard + Certn background checks (spec §14).

Checklist ("Become a NegoRide driver — 7 steps"), each with a status
not_started | in_progress | under_review | done | action_needed:

  1 account_created     sign-up + the three legal consents
  2 phone_verified      A server-confirmed OTP verification for the account phone
  3 email_verified      existing email verification
  4 profile_completed   pre-qualification quiz (before paying anything) + legal/eligibility
                        info + Driver Agreement & Safety Policy e-signature
  5 documents_submitted licence (front/back), registration, insurance, 4 vehicle sides +
                        interior, selfie — stored privately (private_storage), expiry dates
  6 background_check    consent e-signature → fee (Stripe, or "pay later from earnings")
                        → Certn case (invite link opened in the app WebView) → result
  7 payout_ready        existing Stripe Connect payout account
  Final: review (admin) → orientation (5 cards + 5-question quiz) → can go online

Admin approval sets user_type='Driver' and the legacy is_<svc>/is_<svc>_approved
flags, so AdminUser.is_approved_driver() and every v3 code path keep working.
"""
import logging
import re
import secrets
import string
import uuid
from datetime import date, datetime, timedelta

from backend import jobs
from backend.models import db
from backend.models.identity import BackgroundCheck, DriverApplication, DriverDocument
from backend.models.user import AdminUser
from backend.services import legal_service as L
from backend.services import settings_service as S
from backend.services.audit import audit

log = logging.getLogger('negoride.onboarding')

DOC_TYPES = ('licence_front', 'licence_back', 'registration', 'insurance', 'vehicle_front', 'vehicle_back',
             'vehicle_left', 'vehicle_right', 'vehicle_interior', 'selfie')
EXPIRY_REQUIRED = ('licence_front', 'insurance')
EXPIRY_MONITORED = ('licence_front', 'insurance', 'registration')
DOC_TITLES = {
    'licence_front': ("Driver's licence — front", 'Permis de conduire — recto'),
    'licence_back': ("Driver's licence — back", 'Permis de conduire — verso'),
    'registration': ('Vehicle registration', 'Certificat d’immatriculation'),
    'insurance': ('Insurance (with rideshare endorsement where required)', 'Assurance (avec avenant covoiturage si requis)'),
    'vehicle_front': ('Vehicle — front', 'Véhicule — avant'), 'vehicle_back': ('Vehicle — back', 'Véhicule — arrière'),
    'vehicle_left': ('Vehicle — left side', 'Véhicule — côté gauche'),
    'vehicle_right': ('Vehicle — right side', 'Véhicule — côté droit'),
    'vehicle_interior': ('Vehicle — interior', 'Véhicule — intérieur'), 'selfie': ('Selfie', 'Égoportrait'),
}
DOC_LABEL_FOR_NOTICE = {'licence_front': "driver's licence", 'insurance': 'insurance',
                        'registration': 'vehicle registration'}
ALLOWED_MIME = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png', 'image/heic': 'heic',
                'image/heif': 'heif', 'image/webp': 'webp', 'application/pdf': 'pdf'}
MAX_DOC_BYTES = 10 * 1024 * 1024
SERVICE_TYPES = S.ALL_SERVICES   # every type the platform knows (admin approvals)


def offered_service_types():
    """Types drivers may apply for now (setting services.enabled)."""
    return list(S.enabled_services())
# service type → legacy capability column suffix (is_<x> / is_<x>_approved)
LEGACY_FLAG = {'car_hire': 'car', 'rideshare': 'car', 'airport': 'car', 'special_car': 'car',
               'courier': 'delivery', 'movers': 'delivery'}
POSTAL_RE = re.compile(r'^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d$', re.I)
ACTIVE_BGC = ('awaiting_payment', 'paid', 'initiated', 'pending', 'clear', 'consider')
STEP_TITLES = {
    'account_created': ('Create account', 'Créer un compte'),
    'phone_verified': ('Verify phone', 'Vérifier le téléphone'),
    'email_verified': ('Verify email', 'Vérifier le courriel'),
    'profile_completed': ('Personal & eligibility info', 'Renseignements personnels et admissibilité'),
    'documents_submitted': ('Documents', 'Documents'),
    'background_check': ('Background check', 'Vérification des antécédents'),
    'payout_ready': ('Payout setup', 'Configuration des versements'),
    'review': ('Application review', 'Examen de la candidature'),
    'orientation': ('Safety orientation', 'Formation sur la sécurité'),
}
STEP_ORDER = ('account_created', 'phone_verified', 'email_verified', 'profile_completed', 'documents_submitted',
              'background_check', 'payout_ready', 'review', 'orientation')

ORIENTATION = {
    'cards': [
        {'title': {'en': 'Always check the Ride PIN', 'fr': 'Vérifiez toujours le NIP de course'},
         'body': {'en': 'Start a trip only after the rider gives you their 4-digit PIN. It proves you picked up the right person.',
                  'fr': 'Ne démarrez la course qu’après avoir reçu le NIP à 4 chiffres du passager. C’est la preuve que vous avez la bonne personne.'}},
        {'title': {'en': 'Respect is non-negotiable', 'fr': 'Le respect n’est pas négociable'},
         'body': {'en': 'Zero tolerance for discrimination or harassment. Service animals must always be accepted.',
                  'fr': 'Tolérance zéro pour la discrimination ou le harcèlement. Les animaux d’assistance doivent toujours être acceptés.'}},
        {'title': {'en': 'Sober, rested, buckled', 'fr': 'Sobre, reposé, attaché'},
         'body': {'en': 'Never drive after drugs, cannabis or alcohol. Take breaks. Everyone wears a seat belt.',
                  'fr': 'Ne conduisez jamais après avoir consommé drogue, cannabis ou alcool. Prenez des pauses. Tout le monde boucle sa ceinture.'}},
        {'title': {'en': 'Negotiate fairly', 'fr': 'Négociez équitablement'},
         'body': {'en': 'The agreed price is final. No off-app cash deals and no changing the price after agreement.',
                  'fr': 'Le prix convenu est final. Aucune entente en argent hors de l’application, aucun changement après l’accord.'}},
        {'title': {'en': 'SOS and 911', 'fr': 'SOS et 911'},
         'body': {'en': 'In danger, call 911 first. The SOS button alerts the NegoRide safety team with your live location.',
                  'fr': 'En cas de danger, appelez d’abord le 911. Le bouton SOS alerte l’équipe sécurité de NegoRide avec votre position.'}},
    ],
    'questions': [
        {'q': {'en': 'At pickup, what must you do before starting a booked trip?',
               'fr': 'Au lieu de prise en charge, que devez-vous faire avant de démarrer une course réservée?'},
         'options': {'en': ['Check the rider’s name and start the trip; the PIN is optional',
                            'Enter the 4-digit Ride PIN in the app and wait for it to confirm',
                            'Ask the rider to confirm the destination instead of using a PIN'],
                     'fr': ['Vérifier le nom du passager et démarrer; le NIP est facultatif',
                            'Saisir le NIP de course à 4 chiffres dans l’application et attendre sa confirmation',
                            'Demander au passager de confirmer la destination au lieu d’utiliser un NIP']},
         'explanation': {'en': 'The app-confirmed Ride PIN confirms you picked up the correct rider. Do not start the trip before it is accepted.',
                         'fr': 'Le NIP de course confirmé par l’application vérifie que vous avez le bon passager. Ne démarrez pas avant sa validation.'},
         'answer': 1},
        {'q': {'en': 'A passenger is travelling with a guide dog or other service animal. What should you do?',
               'fr': 'Un passager voyage avec un chien-guide ou un autre animal d’assistance. Que devez-vous faire?'},
         'options': {'en': ['Accept the passenger and animal without an extra fee; contact support if a genuine safety issue needs help',
                            'Decline because the animal was not listed when the ride was booked',
                            'Accept only after the passenger agrees to pay a cleaning surcharge'],
                     'fr': ['Accepter le passager et l’animal sans frais supplémentaires; joindre le soutien en cas de véritable problème de sécurité',
                            'Refuser parce que l’animal n’était pas indiqué lors de la réservation',
                            'Accepter seulement si le passager paie un supplément de nettoyage']},
         'explanation': {'en': 'Service animals are accepted without an added fee. Ask support for help with a specific safety or accessibility concern; do not impose a surcharge.',
                         'fr': 'Les animaux d’assistance sont acceptés sans frais supplémentaires. En cas de problème précis de sécurité ou d’accessibilité, demandez de l’aide au soutien; n’ajoutez pas de supplément.'},
         'answer': 0},
        {'q': {'en': 'The rider asks to change the agreed fare to a direct cash payment outside the app. What should you do?',
               'fr': 'Le passager vous demande de remplacer le tarif convenu par un paiement comptant hors application. Que devez-vous faire?'},
         'options': {'en': ['Keep the booking and agreed fare in the app; contact support if the trip details have changed',
                            'Accept the cash and mark the ride complete in the app as well',
                            'Collect the app fare, then negotiate any extra amount at drop-off'],
                     'fr': ['Garder la réservation et le tarif convenu dans l’application; joindre le soutien si les détails du trajet ont changé',
                            'Accepter l’argent comptant et marquer aussi la course comme terminée dans l’application',
                            'Percevoir le tarif de l’application, puis négocier un supplément à l’arrivée']},
         'explanation': {'en': 'Do not move payment off-app or change the agreed fare. If the destination or other trip details change, use the app’s supported flow or contact support.',
                         'fr': 'Ne faites pas le paiement hors application et ne modifiez pas le tarif convenu. Si la destination ou les détails changent, utilisez l’option prévue dans l’application ou contactez le soutien.'},
         'answer': 0},
        {'q': {'en': 'A passenger’s behaviour makes you fear someone may be harmed. What is the safest response?',
               'fr': 'Le comportement d’un passager vous fait craindre que quelqu’un soit blessé. Quelle est la réponse la plus sûre?'},
         'options': {'en': ['Continue to the destination and report it after the trip',
                            'If safe, stop in a safe public place, call 911, then alert NegoRide using in-app SOS',
                            'End the trip in a quiet location and wait to see whether the situation improves'],
                     'fr': ['Continuer jusqu’à destination et signaler la situation après la course',
                            'Si possible sans danger, s’arrêter dans un lieu public sûr, appeler le 911, puis prévenir NegoRide avec le bouton SOS',
                            'Terminer la course dans un endroit isolé et attendre de voir si la situation s’améliore']},
         'explanation': {'en': 'For immediate danger, prioritize a safe location and emergency services (911). Use in-app SOS to notify NegoRide when it is safe to do so.',
                         'fr': 'En cas de danger immédiat, privilégiez un lieu sûr et les services d’urgence (911). Utilisez le bouton SOS pour prévenir NegoRide dès que vous pouvez le faire sans danger.'},
         'answer': 1},
        {'q': {'en': 'Before accepting or driving a NegoRide trip, which condition must be true?',
               'fr': 'Avant d’accepter ou d’effectuer une course NegoRide, quelle condition doit être respectée?'},
         'options': {'en': ['You are rested, fit to drive and not impaired by alcohol, cannabis, medication or other drugs',
                            'You have had no alcohol, but cannabis is allowed whenever it is legal locally',
                            'You may drive after drinking if you feel alert and the trip is short'],
                     'fr': ['Vous êtes reposé, apte à conduire et sans effet de l’alcool, du cannabis, de médicaments ou d’autres drogues',
                            'Vous n’avez pas bu d’alcool, mais le cannabis est permis dès qu’il est légal dans la région',
                            'Vous pouvez conduire après avoir bu si vous vous sentez alerte et que le trajet est court']},
         'explanation': {'en': 'Drive only when rested and unimpaired. Local legality does not make impaired driving safe or acceptable; do not drive if medication affects you.',
                         'fr': 'Conduisez seulement si vous êtes reposé et sans facultés affaiblies. La légalité locale ne rend pas sécuritaire la conduite avec facultés affaiblies; ne conduisez pas si un médicament vous affecte.'},
         'answer': 0},
    ],
}


class OnboardingError(Exception):
    def __init__(self, message, code='onboarding_error', status=400, data=None):
        super().__init__(message)
        self.message, self.code, self.status, self.data = message, code, status, data or {}


def _now():
    return datetime.utcnow()


def _iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%dT%H:%M:%SZ')
    return v.isoformat()


def _csv(key):
    return [x.strip() for x in (S.get(key) or '').split(',') if x.strip()]


def parse_date(v):
    if v in (None, ''):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v).strip()[:10]
    for f in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def age_on(dob, today=None):
    today = today or _now().date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


# ── application ─────────────────────────────────────────────────────────────

def _referral_code():
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(10):
        code = 'NR' + ''.join(secrets.choice(alphabet) for _ in range(6))
        if not DriverApplication.query.filter_by(referral_code=code).first():
            return code
    return 'NR' + uuid.uuid4().hex[:8].upper()


def get_application(user, create=True):
    app = DriverApplication.query.filter_by(user_id=user.id).first()
    if app or not create:
        return app
    app = DriverApplication(user_id=user.id, status='in_progress', current_step='account_created', steps={},
                            referral_code=_referral_code(), created_at=_now(),
                            legal_first_name=user.first_name or None, legal_last_name=user.last_name or None)
    db.session.add(app)
    db.session.flush()
    audit('onboarding.started', user, 'driver_application', app.id, actor_type='user')
    return app


def latest_documents(app):
    """{type: latest non-superseded DriverDocument}."""
    out = {}
    for d in (DriverDocument.query.filter(DriverDocument.application_id == app.id,
                                          DriverDocument.status != 'superseded')
              .order_by(DriverDocument.id)):
        out[d.type] = d
    return out


def latest_bgc(user_id):
    return BackgroundCheck.query.filter_by(user_id=user_id).order_by(BackgroundCheck.id.desc()).first()


def _payout_status(user):
    from backend.models.payout_account import PayoutAccount
    acc = PayoutAccount.query.filter_by(user_id=user.id).first()
    return acc.status if acc else None


def agreements_signed(user):
    for t in L.DRIVER_REQUIRED:
        d = L.current(t, 'en')
        if d and not L.has_accepted_version(user.id, t, d.version):
            return False
    return True


PROFILE_FIELDS = ('legal_first_name', 'legal_last_name', 'date_of_birth', 'address_line', 'city', 'province',
                  'postal_code', 'service_types', 'licence_class', 'licence_number', 'licence_expires_at',
                  'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_color', 'vehicle_plate')


def profile_missing(app):
    return [f for f in PROFILE_FIELDS if not getattr(app, f)]


def compute_steps(user, app, lang='en'):
    lang = 'fr' if (lang or '').startswith('fr') else 'en'
    docs = latest_documents(app)
    required_docs = [t for t in _csv('onboarding.required_documents') if t in DOC_TYPES]
    bgc = latest_bgc(user.id)
    prequal = app.prequal or {}
    steps = []

    def add(key, status, detail=None):
        steps.append({'key': key, 'number': STEP_ORDER.index(key) + 1 if STEP_ORDER.index(key) < 7 else None,
                      'title': STEP_TITLES[key][1 if lang == 'fr' else 0], 'status': status, 'detail': detail or {}})

    pending_legal = [p for p in L.pending_for(user, lang) if p['type'] in L.SIGNUP_REQUIRED]
    add('account_created', 'action_needed' if pending_legal else 'done',
        {'legal_pending': [p['type'] for p in pending_legal]})
    ph_ok, ph_issue = driver_phone_ok(user)
    add('phone_verified', 'done' if ph_ok else ('action_needed' if user.phone_verified_at else 'not_started'),
        {'phone_masked': _mask(user.phone_e164) if user.phone_verified_at else None, 'purpose': 'driver_onboarding',
         'line_type': user.phone_line_type, 'issue': ph_issue})
    add('email_verified', 'done' if user.email_verified_at else ('action_needed' if not user.email else 'not_started'),
        {'email': user.email})

    missing = profile_missing(app)
    signed = agreements_signed(user)
    if prequal.get('passed') is False:
        st = 'action_needed'
    elif not missing and signed and prequal.get('passed'):
        st = 'done'
    elif prequal or len(missing) < len(PROFILE_FIELDS) or signed:
        st = 'in_progress'
    else:
        st = 'not_started'
    add('profile_completed', st, {'prequal': prequal or None, 'missing_fields': missing, 'agreements_signed': signed})

    uploaded = [t for t in required_docs if t in docs]
    rejected = [t for t, d in docs.items() if d.status in ('rejected', 'expired')]
    approved = [t for t in required_docs if t in docs and docs[t].status == 'approved']
    if rejected:
        st = 'action_needed'
    elif len(approved) == len(required_docs) and required_docs:
        st = 'done'
    elif len(uploaded) == len(required_docs) and required_docs:
        st = 'under_review'
    elif uploaded:
        st = 'in_progress'
    else:
        st = 'not_started'
    add('documents_submitted', st, {'required': required_docs, 'uploaded': uploaded, 'approved': approved,
                                    'rejected': rejected,
                                    'missing': [t for t in required_docs if t not in docs]})

    if not S.flag('background_check'):
        st, bdetail = 'done', {'disabled': True}
    elif not bgc or bgc.status == 'cancelled':
        st, bdetail = 'not_started', {}
    else:
        st = {'awaiting_payment': 'in_progress', 'paid': 'under_review', 'initiated': 'action_needed',
              'pending': 'under_review', 'clear': 'done', 'consider': 'under_review', 'failed': 'action_needed',
              'expired': 'action_needed'}.get(bgc.status, 'in_progress')
        bdetail = bgc_public(bgc)
    add('background_check', st, bdetail)

    pst = _payout_status(user)
    add('payout_ready', 'done' if pst == 'active' else ('in_progress' if pst in ('restricted', 'pending') else 'not_started'),
        {'payout_account_status': pst, 'required_to_submit': False})

    rs = {'in_progress': 'not_started', 'submitted': 'under_review', 'under_review': 'under_review',
          'needs_changes': 'action_needed', 'approved': 'done', 'rejected': 'action_needed'}.get(app.status, 'not_started')
    add('review', rs, {'application_status': app.status, 'rejection_reason': app.rejection_reason if app.status in ('rejected', 'needs_changes') else None})
    add('orientation', 'done' if app.orientation_completed_at else 'not_started',
        {'available': True, 'score': app.orientation_score, 'pass_score': S.get_int('onboarding.orientation_pass_score')})
    return steps


def driver_phone_ok(user):
    """A server-confirmed phone verification is sufficient for onboarding.

    Carrier line-type lookup is informational only; it must not make a verified
    account repeat OTP verification or block driver onboarding.
    """
    if not user.phone_verified_at or not (user.phone_e164 or user.phone_number):
        return False, 'not_verified'
    return True, None


def _mask(e164):
    from backend.utils.phone import mask
    return mask(e164) if e164 else None


def _record_progress(app, steps):
    """Remember when each step was first done (funnel analytics) and the current step."""
    state = dict(app.steps or {})
    changed = False
    for s in steps:
        if s['status'] == 'done' and not (state.get(s['key']) or {}).get('done_at'):
            state[s['key']] = {'done_at': _iso(_now())}
            changed = True
    current = next((s['key'] for s in steps if s['status'] != 'done'), 'orientation')
    if changed:
        app.steps = state
    if app.current_step != current:
        app.current_step = current


def overview(user, lang='en'):
    app = get_application(user)
    steps = compute_steps(user, app, lang)
    _record_progress(app, steps)
    main = [s for s in steps if s['key'] not in ('orientation',)]
    done = sum(1 for s in main if s['status'] == 'done')
    missing_submit = submit_blockers(user, app, steps)
    return {
        'application': application_public(app),
        'steps': steps,
        'current_step': app.current_step,
        'progress_pct': int(round(100.0 * done / len(main))) if main else 0,
        'can_submit': app.status in ('in_progress', 'needs_changes') and not missing_submit,
        'submit_blockers': missing_submit,
        'documents': [document_public(d) for d in latest_documents(app).values()],
        'background_check': bgc_public(latest_bgc(user.id)),
        'renewal_due': renewal_due(latest_bgc(user.id)),
        'insurance_endorsement_required': endorsement_required(app, user),
        'requirements': requirements(),
        'can_go_online': _can_go_online(user),
    }


def renewal_due(b):
    """Annual re-check can be started (and paid) now: the latest check is clear and
    expires within onboarding.recheck_reminder_days, or it already expired."""
    if not b:
        return False
    if b.status == 'expired':
        return True
    return bool(b.status == 'clear' and b.expires_at and
                b.expires_at < _now() + timedelta(days=S.get_int('onboarding.recheck_reminder_days')))


def endorsement_provinces():
    return [p.upper() for p in _csv('onboarding.rideshare_endorsement_provinces')]


def endorsement_required(app, user=None):
    prov = ((app.province if app else None) or (user.province if user else None) or '').upper()
    return bool(prov and prov in endorsement_provinces())


def _can_go_online(user):
    from backend.services import account_service
    ok, reason = account_service.can_go_online(user)
    return {'ok': ok and user.is_approved_driver(), 'reason': reason if not ok else (
        None if user.is_approved_driver() else 'Your driver application is not approved yet.')}


def requirements():
    return {
        'min_driver_age': S.get_int('onboarding.min_driver_age'),
        'min_vehicle_year': S.get_int('onboarding.min_vehicle_year'),
        'allowed_licence_classes': _csv('onboarding.allowed_licence_classes'),
        'allowed_provinces': _csv('onboarding.allowed_provinces'),
        'required_documents': [{'type': t, 'title': DOC_TITLES[t][0], 'title_fr': DOC_TITLES[t][1],
                                'expiry_required': t in EXPIRY_REQUIRED}
                               for t in _csv('onboarding.required_documents') if t in DOC_TYPES],
        'service_types': offered_service_types(),
        'bgc_fee_cents': S.get_int('onboarding.bgc_fee_cents'),
        'bgc_pay_later_available': S.flag('bgc_pay_later'),
        'bgc_refund_note': 'The fee is non-refundable once your check is submitted to Certn; '
                           'it is refunded if you cancel before submission.',
        'bgc_start_delay_min': S.get_int('onboarding.bgc_start_delay_min'),
        'rideshare_endorsement_provinces': endorsement_provinces(),
        'orientation_pass_score': S.get_int('onboarding.orientation_pass_score'),
    }


def application_public(app):
    d = app.to_dict()
    d.pop('notes', None)
    return d


def document_public(d, admin=False):
    out = d.to_dict()
    out['title'] = DOC_TITLES.get(d.type, (d.type,))[0]
    if not admin:
        out.pop('reviewed_by', None)
        out.pop('sha256', None)
    return out


def bgc_public(b, admin=False):
    if not b:
        return None
    d = b.to_dict()
    if not admin:
        for k in ('adjudicated_by', 'adjudication_note', 'raw_status', 'provider_score', 'last_polled_at'):
            d.pop(k, None)
    d['timeline'] = _bgc_timeline(b)
    d['typical_turnaround'] = 'Certn usually completes checks in 1–3 business days.'
    return d


def _bgc_timeline(b):
    items = [('consent_signed', b.created_at), ('fee_paid', b.fee_paid_at), ('check_started', b.initiated_at),
             ('completed', b.completed_at), ('adjudicated', b.adjudicated_at)]
    return [{'event': k, 'at': _iso(v)} for k, v in items if v]


# ── step 4: prequal, profile, agreements ────────────────────────────────────

def _editable(app):
    if app.status in ('submitted', 'under_review', 'approved', 'rejected'):
        raise OnboardingError('Your application is under review and cannot be changed right now.',
                              'application_locked', 409)


def prequal(user, data):
    app = get_application(user)
    reasons = []
    dob = parse_date(data.get('date_of_birth'))
    min_age = S.get_int('onboarding.min_driver_age')
    if not dob:
        reasons.append({'field': 'date_of_birth', 'message': 'Enter your date of birth.'})
    elif age_on(dob) < min_age:
        reasons.append({'field': 'date_of_birth', 'message': f'Drivers must be at least {min_age} years old.'})
    lic = str(data.get('licence_class') or '').strip().upper()
    if lic not in [c.upper() for c in _csv('onboarding.allowed_licence_classes')]:
        reasons.append({'field': 'licence_class', 'message': 'A full (non-learner, non-probationary) driver’s licence is required '
                                                            f'(accepted classes: {", ".join(_csv("onboarding.allowed_licence_classes"))}).'})
    try:
        year = int(data.get('vehicle_year'))
    except (TypeError, ValueError):
        year = None
    min_year = S.get_int('onboarding.min_vehicle_year')
    if not year or year < min_year or year > _now().year + 1:
        reasons.append({'field': 'vehicle_year', 'message': f'Your vehicle must be a {min_year} model or newer.'})
    prov = str(data.get('province') or '').strip().upper()
    if prov not in _csv('onboarding.allowed_provinces'):
        reasons.append({'field': 'province', 'message': 'NegoRide is not available in that province yet.'})
    if data.get('has_valid_insurance') is False or str(data.get('has_valid_insurance')).lower() == 'false':
        reasons.append({'field': 'has_valid_insurance', 'message': 'Valid vehicle insurance is required.'})
    passed = not reasons
    app.prequal = {'passed': passed, 'reasons': reasons, 'at': _iso(_now()),
                   'answers': {'date_of_birth': _iso(dob), 'licence_class': lic, 'vehicle_year': year, 'province': prov}}
    if passed:
        app.date_of_birth = app.date_of_birth or dob
        app.licence_class = app.licence_class or lic
        app.vehicle_year = app.vehicle_year or year
        app.province = app.province or prov
    audit('onboarding.prequal', user, 'driver_application', app.id, after={'passed': passed, 'reasons': reasons},
          actor_type='user')
    return app.prequal


def save_profile(user, data):
    app = get_application(user)
    _editable(app)
    errors = {}
    str_fields = {'legal_first_name': 100, 'legal_last_name': 100, 'address_line': 255, 'city': 100,
                  'licence_number': 60, 'vehicle_make': 60, 'vehicle_model': 60, 'vehicle_color': 40, 'vehicle_plate': 20}
    for f, n in str_fields.items():
        if f in data and data[f] is not None:
            setattr(app, f, str(data[f]).strip()[:n] or None)
    if 'date_of_birth' in data:
        dob = parse_date(data.get('date_of_birth'))
        if not dob:
            errors['date_of_birth'] = 'Use the format YYYY-MM-DD.'
        elif age_on(dob) < S.get_int('onboarding.min_driver_age'):
            errors['date_of_birth'] = f'Drivers must be at least {S.get_int("onboarding.min_driver_age")} years old.'
        else:
            app.date_of_birth = dob
    if 'province' in data:
        p = str(data.get('province') or '').upper()
        if p not in _csv('onboarding.allowed_provinces'):
            errors['province'] = 'Choose a province or territory we serve.'
        else:
            app.province = p
    if 'postal_code' in data:
        pc = str(data.get('postal_code') or '').strip().upper()
        if not POSTAL_RE.match(pc):
            errors['postal_code'] = 'Enter a valid Canadian postal code (e.g. M5V 2T6).'
        else:
            app.postal_code = pc[:3] + ' ' + pc[-3:]
    if 'service_types' in data:
        st = data.get('service_types') or []
        if isinstance(st, str):
            st = [s.strip() for s in st.split(',') if s.strip()]
        offered = offered_service_types()
        bad = [s for s in st if s not in offered]
        if bad or not st:
            errors['service_types'] = f'Choose at least one of: {", ".join(offered)}.'
        else:
            app.service_types = list(dict.fromkeys(st))
    if 'licence_class' in data:
        lic = str(data.get('licence_class') or '').strip().upper()
        if lic not in [c.upper() for c in _csv('onboarding.allowed_licence_classes')]:
            errors['licence_class'] = 'A full (non-learner) licence class is required.'
        else:
            app.licence_class = lic
    if 'licence_expires_at' in data:
        exp = parse_date(data.get('licence_expires_at'))
        if not exp or exp <= _now().date():
            errors['licence_expires_at'] = 'Your licence must not be expired.'
        else:
            app.licence_expires_at = exp
    if 'vehicle_year' in data:
        try:
            y = int(data.get('vehicle_year'))
            if y < S.get_int('onboarding.min_vehicle_year') or y > _now().year + 1:
                raise ValueError
            app.vehicle_year = y
        except (TypeError, ValueError):
            errors['vehicle_year'] = f'Your vehicle must be a {S.get_int("onboarding.min_vehicle_year")} model or newer.'
    if 'vehicle_seats' in data and data.get('vehicle_seats') not in (None, ''):
        try:
            app.vehicle_seats = max(1, min(14, int(data.get('vehicle_seats'))))
        except (TypeError, ValueError):
            errors['vehicle_seats'] = 'Enter the number of passenger seats.'
    if errors:
        raise OnboardingError('Please fix the highlighted fields.', 'validation_failed', 422, {'fields': errors})
    if app.legal_first_name and app.legal_last_name:
        user.legal_name = f'{app.legal_first_name} {app.legal_last_name}'[:200]
    if app.province:
        user.province = app.province
    if app.status == 'needs_changes':
        pass  # stays until re-submitted
    return app


def sign_agreements(user, signature_name, app_version=None, ip=None, ua=None):
    if not (signature_name or '').strip():
        raise OnboardingError('Type your full legal name to sign.', 'signature_required')
    app = get_application(user)
    try:
        docs = L.resolve(types=list(L.DRIVER_REQUIRED))
    except L.LegalError as e:
        raise OnboardingError(e.message, e.code, e.status)
    rows = L.accept(user, docs, method='esignature', app_version=app_version, signature_name=signature_name,
                    ip=ip, user_agent=ua)
    audit('onboarding.agreements_signed', user, 'driver_application', app.id,
          after={'documents': [f'{d.type}@{d.version}' for d in docs]}, actor_type='user')
    return rows


# ── step 5: documents ───────────────────────────────────────────────────────

def upload_document(user, doc_type, file_storage, expires_at=None, attestation_rideshare_endorsement=None):
    app = get_application(user)
    if app.status in ('submitted', 'under_review') and doc_type not in EXPIRY_MONITORED:
        raise OnboardingError('Your application is under review.', 'application_locked', 409)
    if doc_type not in DOC_TYPES:
        raise OnboardingError(f'Unknown document type. Use one of: {", ".join(DOC_TYPES)}.', 'invalid_type')
    if not file_storage or not getattr(file_storage, 'filename', None):
        raise OnboardingError('Attach the photo or PDF.', 'file_required')
    mime = (file_storage.mimetype or '').lower()
    if mime not in ALLOWED_MIME:
        name = (file_storage.filename or '').lower()
        guess = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.pdf': 'application/pdf',
                 '.heic': 'image/heic', '.webp': 'image/webp'}
        mime = next((v for k, v in guess.items() if name.endswith(k)), mime)
    if mime not in ALLOWED_MIME:
        raise OnboardingError('Upload a JPG, PNG, HEIC or PDF file.', 'invalid_file_type')
    data = file_storage.read()
    if not data:
        raise OnboardingError('The file is empty.', 'file_empty')
    if len(data) > MAX_DOC_BYTES:
        raise OnboardingError('Files must be 10 MB or smaller.', 'file_too_large')
    exp = parse_date(expires_at) if expires_at else None
    if doc_type in EXPIRY_REQUIRED and not exp:
        raise OnboardingError('Enter the expiry date shown on the document.', 'expiry_required')
    if exp and exp <= _now().date():
        raise OnboardingError('This document has already expired.', 'document_expired')
    meta = None
    if doc_type == 'insurance':
        attested = str(attestation_rideshare_endorsement).strip().lower() in ('1', 'true', 'yes', 'on')
        prov = (app.province or user.province or '').upper() or None
        if endorsement_required(app, user) and not attested:
            raise OnboardingError(f'In {prov}, your insurance must include a rideshare (ride-hailing) endorsement. '
                                  'Confirm that your policy includes it.', 'endorsement_attestation_required', 422,
                                  {'province': prov, 'field': 'attestation_rideshare_endorsement'})
        meta = {'attestation_rideshare_endorsement': attested, 'province': prov,
                'endorsement_required': endorsement_required(app, user), 'attested_at': _iso(_now()) if attested else None}

    from backend.services import private_storage as PS
    key = f'driver-docs/{user.id}/{app.id}/{doc_type}-{uuid.uuid4().hex}.{ALLOWED_MIME[mime]}'
    PS.put(key, data, mime)
    for old in DriverDocument.query.filter(DriverDocument.application_id == app.id, DriverDocument.type == doc_type,
                                           DriverDocument.status != 'superseded').all():
        old.status = 'superseded'
    doc = DriverDocument(application_id=app.id, user_id=user.id, type=doc_type, file_path=key, mime_type=mime,
                         sha256=PS.sha256_hex(data), expires_at=exp, status='pending', reminders_sent=[],
                         meta=meta, created_at=_now())
    if doc_type == 'selfie':
        doc.face_match_status = 'pending'
    db.session.add(doc)
    if doc_type == 'licence_front' and exp:
        app.licence_expires_at = exp
    db.session.flush()
    audit('onboarding.document_uploaded', user, 'driver_document', doc.id,
          after={'type': doc_type, 'expires_at': _iso(exp), 'sha256': doc.sha256, 'meta': meta}, actor_type='user')
    if doc_type in ('selfie', 'licence_front'):
        docs = latest_documents(app)
        if 'selfie' in docs and 'licence_front' in docs:
            if doc_type == 'licence_front':
                docs['selfie'].face_match_status = 'pending'
            jobs.enqueue_after_commit('backend.services.face_match.run_for_application', app.id)
    if app.status == 'approved':
        from backend.services import realtime
        realtime.to_admins('onboarding.document_uploaded', {'application_id': app.id, 'document_id': doc.id,
                                                             'type': doc_type, 'user_id': user.id})
    return doc


# ── step 6: background check ────────────────────────────────────────────────

def bgc_consent(user, signature_name, app_version=None, ip=None, ua=None):
    if not S.flag('background_check'):
        raise OnboardingError('Background checks are not required right now.', 'feature_disabled', 409)
    app = get_application(user)
    if not (app.prequal or {}).get('passed'):
        raise OnboardingError('Complete the quick eligibility check first — so you never pay for a check you can’t use.',
                              'prequal_required', 409)
    if not (signature_name or '').strip():
        raise OnboardingError('Type your full legal name to sign.', 'signature_required')
    existing = latest_bgc(user.id)
    if existing and existing.status in ACTIVE_BGC and not (
            existing.status == 'clear' and existing.expires_at and existing.expires_at < _now() + timedelta(
                days=S.get_int('onboarding.recheck_reminder_days'))):
        return existing
    try:
        docs = L.resolve(types=[L.BGC_CONSENT])
    except L.LegalError as e:
        raise OnboardingError(e.message, e.code, e.status)
    # a fresh acceptance per check (the unique key is per document, so re-checks reuse the row)
    from backend.models.identity import LegalAcceptance
    had = {r.document_id for r in LegalAcceptance.query.filter(
        LegalAcceptance.user_id == user.id, LegalAcceptance.document_id.in_([d.id for d in docs]))}
    rows = L.accept(user, docs, method='esignature', app_version=app_version, signature_name=signature_name,
                    ip=ip, user_agent=ua)
    platform_pays = bool(existing and existing.status in ('clear', 'expired') and S.flag('bgc_platform_pays_recheck'))
    b = BackgroundCheck(user_id=user.id, application_id=app.id, provider='certn',
                        package=S.get('onboarding.certn_package'),
                        status='awaiting_payment', fee_cents=0 if platform_pays else S.get_int('onboarding.bgc_fee_cents'),
                        paid_by='platform' if platform_pays else 'driver', consent_acceptance_id=rows[0].id,
                        created_at=_now())
    db.session.add(b)
    db.session.flush()
    # Evidence for THIS check (a re-check signs again even when the consent document
    # version is unchanged and the legal_acceptances row is re-used).
    b.consent_evidence = {
        'background_check_id': b.id, 'signature_name': signature_name.strip()[:200], 'signed_at': _iso(_now()),
        'ip': ip, 'user_agent': (ua or '')[:500] or None, 'app_version': app_version,
        'document_id': docs[0].id, 'document_type': docs[0].type, 'document_version': docs[0].version,
        'document_language': docs[0].language, 'acceptance_id': rows[0].id,
        'acceptance_reused': rows[0].document_id in had,
        'is_recheck': bool(existing and existing.status in ('clear', 'expired'))}
    audit('onboarding.bgc_consent', user, 'background_check', b.id,
          after={'signature_name': signature_name, 'acceptance_id': rows[0].id}, meta=b.consent_evidence,
          actor_type='user')
    if platform_pays:
        b.status, b.fee_paid_at = 'paid', _now()
        schedule_initiation(b)
    return b


def schedule_initiation(b):
    """Order the Certn case after onboarding.bgc_start_delay_min (the window in which the
    driver can still cancel for a full refund). The 6-hourly poll is the safety net."""
    delay_min = max(0, S.get_int('onboarding.bgc_start_delay_min'))
    b.start_after = _now() + timedelta(minutes=delay_min)
    jobs.enqueue_after_commit(initiate_background_check, b.id, delay_s=delay_min * 60)


def bgc_pay(user, pay_later=False):
    b = latest_bgc(user.id)
    if not b or b.status != 'awaiting_payment':
        raise OnboardingError('Sign the background check consent first.', 'consent_required', 409)
    app = get_application(user)
    if pay_later:
        if not S.flag('bgc_pay_later'):
            raise OnboardingError('Paying from earnings is not available.', 'feature_disabled', 409)
        b.paid_by, b.deduction_status, b.status, b.fee_paid_at = 'earnings', 'pending', 'paid', _now()
        app.pay_later_from_earnings = True
        audit('onboarding.bgc_pay_later', user, 'background_check', b.id, after={'fee_cents': b.fee_cents},
              actor_type='user')
        schedule_initiation(b)
        return b, None
    from backend.models.money import RidePayment
    from backend.services.payments import payment_service as PS
    rp = (RidePayment.query.filter_by(ride_type='background_check', ride_id=b.id, purpose='background_check')
          .order_by(RidePayment.id.desc()).first())
    if rp and rp.capture_status == 'pending' and rp.checkout_url:
        return b, rp
    try:
        rp = PS.start_extra_payment('background_check', 'background_check', b.id, user, b.fee_cents,
                                    description='NegoRide driver background check (Certn)')
    except PS.PaymentError as e:
        raise OnboardingError(e.message, e.code, e.status)
    return b, rp


def bgc_sync(user):
    """App returned from Checkout: poll the payment (webhook fallback)."""
    b = latest_bgc(user.id)
    if b and b.status == 'awaiting_payment':
        from backend.models.money import RidePayment
        from backend.services.payments import payment_service as PS
        rp = (RidePayment.query.filter_by(ride_type='background_check', ride_id=b.id, purpose='background_check')
              .order_by(RidePayment.id.desc()).first())
        if rp:
            PS.sync_from_provider(rp)
            db.session.rollback()
            b = latest_bgc(user.id)
    return b


def on_background_check_fee_paid(rp):
    """Called by payment_service when the background-check Checkout is paid."""
    b = db.session.get(BackgroundCheck, int(rp.ride_id))
    if not b:
        log.error('background-check payment %s for unknown check %s', rp.id, rp.ride_id)
        return
    if b.status != 'awaiting_payment':
        return
    b.status, b.fee_payment_id, b.fee_paid_at, b.paid_by = 'paid', rp.id, _now(), 'driver'
    audit('onboarding.bgc_paid', None, 'background_check', b.id, after={'ride_payment_id': rp.id,
                                                                         'amount_cents': rp.amount_captured_cents})
    schedule_initiation(b)
    jobs.enqueue_after_commit('backend.services.onboarding_service.send_bgc_receipt', b.id)
    db.session.commit()


def initiate_background_check(bgc_id):
    """Job: order the Certn case (invite flow) once the fee is secured."""
    from backend.services import certn_client as CC
    from backend.services.notify import notify
    b = BackgroundCheck.query.filter_by(id=bgc_id).with_for_update().first()
    if not b or b.status != 'paid' or b.provider_application_id:
        db.session.rollback()
        return None
    if b.start_after and b.start_after > _now() + timedelta(seconds=5):
        db.session.rollback()
        return None   # still inside the cancel window — the delayed job / poll starts it
    user = db.session.get(AdminUser, b.user_id)
    app = db.session.get(DriverApplication, b.application_id) if b.application_id else None
    claims = {}
    if app and app.legal_first_name:
        claims['name'] = {'given_name': app.legal_first_name, 'family_name': app.legal_last_name or ''}
    try:
        package = S.get('onboarding.certn_package') or ''
        res = CC.get_client().order_case(user.email or f'driver-{user.id}@negoride.invalid',
                                         _csv('onboarding.certn_check_types'),
                                         input_claims=claims or None,
                                         package=package if _looks_like_uuid(package) else None)
    except CC.CertnError as e:
        b.raw_status = f'order_failed: {e}'[:60]
        db.session.commit()
        log.error('Certn order failed for bgc %s: %s', b.id, e)
        return None
    b.provider_application_id = res['id']
    b.invite_url = res.get('invite_link')
    b.status, b.raw_status, b.initiated_at = 'initiated', 'APPLICANT_INVITED', _now()
    audit('onboarding.bgc_initiated', None, 'background_check', b.id, after={'provider_case_id': res['id']})
    notify('onboarding.step_required', [b.user_id], {'step': 'Complete your background check with Certn'})
    db.session.commit()
    return b.provider_application_id


def _looks_like_uuid(s):
    return bool(re.fullmatch(r'[0-9a-fA-F-]{32,36}', s or ''))


def apply_case(b, case, source='webhook'):
    """Apply a CertnCentric case snapshot. Admin adjudications are never overwritten."""
    from backend.services import certn_client as CC
    new_status, result = CC.map_case(case)
    b.raw_status = (case.get('overall_status') or case.get('case_status') or b.raw_status or '')[:60]
    b.provider_score = (case.get('overall_score') or b.provider_score or None)
    b.last_polled_at = _now() if source == 'poll' else b.last_polled_at
    if b.adjudicated_by or b.status in ('clear', 'failed', 'expired') or new_status == b.status:
        return b.status   # admin decisions and final outcomes are never overwritten
    before = b.status
    b.status = new_status
    if result:
        b.result = result
    audit('onboarding.bgc_status', None, 'background_check', b.id, before={'status': before},
          after={'status': new_status, 'raw_status': b.raw_status, 'score': b.provider_score}, meta={'source': source})
    _after_bgc_outcome(b, before)
    return new_status


def _after_bgc_outcome(b, before, admin=None, note=None):
    from backend.services import realtime
    from backend.services.notify import notify
    app = db.session.get(DriverApplication, b.application_id) if b.application_id else None
    if b.status in ('clear', 'consider', 'failed') and not b.completed_at:
        b.completed_at = _now()
    if b.status == 'clear':
        b.expires_at = _now() + timedelta(days=30 * S.get_int('onboarding.recheck_months'))
        b.recheck_reminded_at = None
        notify('background_check.completed', [b.user_id],
               {'summary': 'Good news — your background check is clear.'})
        if app and app.status == 'submitted':
            app.status = 'under_review'
        _notify_admins_bgc(b, 'clear', 'onboarding.bgc_clear')
    elif b.status == 'consider':
        notify('background_check.completed', [b.user_id],
               {'summary': 'Your background check is complete and is being reviewed by our team. '
                           'We will update you within 2 business days.'})
        _notify_admins_bgc(b, 'consider', 'onboarding.bgc_review')
    elif b.status == 'failed':
        contact = S.get('onboarding.certn_dispute_contact')
        reason = ('We’re sorry — based on your background check we can’t approve your application at this time. '
                  f'You have the right to a copy of your report and to dispute inaccurate information with Certn '
                  f'({contact}) or with us at {S.get("safety.support_email")}.')
        user = db.session.get(AdminUser, b.user_id)
        if app and app.status not in ('approved',):
            app.status, app.rejection_reason = 'rejected', reason
            app.reviewed_at, app.reviewed_by = _now(), getattr(admin, 'id', None)
            if user:
                _clear_applied_flags(user, app)
        elif user and (user.is_approved_driver() or (app and app.status == 'approved')):
            # an approved driver whose (re-)check failed is paused pending review (§15)
            from backend.services import account_service
            if user.effective_account_status() == 'active' and not user.pending_account_status:
                res = account_service.set_status(user, 'pending_review', admin, 'failed_background_check',
                                                 'Background check result did not meet requirements'
                                                 + (f' — {note}' if note else ''), notify_user=False,
                                                 commit=False, source='rule:background_check')
                if res.get('applied'):
                    jobs.enqueue_after_commit('backend.services.account_service.after_commit_effects', user.id,
                                              'pending_review')
        notify('onboarding.rejected', [b.user_id], {'reason': reason})
        _notify_admins_bgc(b, 'failed', 'onboarding.bgc_failed')
    elif b.status == 'expired':
        notify('onboarding.step_required', [b.user_id],
               {'step': 'Your background check invitation expired — contact support to restart it'})
    queue_progress_refresh(b.user_id)


def _notify_admins_bgc(b, result, realtime_event):
    """Ops console: a check needs adjudication (consider) or completed (clear / failed)."""
    from backend.services.notify import notify_admins
    u = db.session.get(AdminUser, b.user_id)
    name = ((u.legal_name or u.name) if u else None) or None
    notify_admins('admin.background_check_review',
                  {'user_id': b.user_id, 'name': name, 'result': result, 'check_id': b.id,
                   'background_check_id': b.id, 'application_id': b.application_id},
                  roles=('ops', 'safety_reviewer'), dedupe_key=f'bgc-{b.id}-{result}', realtime_event=realtime_event)


def adjudicate(b, admin, decision, note):
    if decision not in ('clear', 'failed'):
        raise OnboardingError('Decision must be clear or failed.', 'invalid_decision')
    if not (note or '').strip():
        raise OnboardingError('A reason is required.', 'reason_required')
    if b.status not in ('consider', 'pending', 'initiated', 'clear', 'failed'):
        raise OnboardingError('This check has no result to adjudicate yet.', 'not_ready', 409)
    before = b.status
    b.status, b.result = decision, 'clear' if decision == 'clear' else 'reject'
    b.adjudicated_by, b.adjudicated_at, b.adjudication_note = admin.id, _now(), note.strip()
    audit('onboarding.bgc_adjudicated', admin, 'background_check', b.id, before={'status': before},
          after={'status': decision}, meta={'note': note})
    _after_bgc_outcome(b, before, admin, note)
    return b


def process_certn_event(webhook_event_id):
    """Job (and webhook retry target): route one stored Certn event."""
    import json
    from backend.models.platform import WebhookEvent
    from backend.services import certn_client as CC
    row = db.session.get(WebhookEvent, webhook_event_id)
    if not row or row.status == 'processed':
        return
    row.attempts = (row.attempts or 0) + 1
    db.session.commit()
    try:
        ev = json.loads(row.payload or '{}')
        case_id = ev.get('object_id')
        b = BackgroundCheck.query.filter_by(provider='certn', provider_application_id=case_id).first() if case_id else None
        if b:
            try:
                case = CC.get_client().get_case(case_id)
            except CC.CertnError:
                case = {'overall_status': ev.get('case_status')}
            apply_case(b, case, source='webhook')
        row = db.session.get(WebhookEvent, webhook_event_id)
        row.status, row.processed_at, row.error = ('processed' if b else 'ignored'), _now(), None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        row = db.session.get(WebhookEvent, webhook_event_id)
        row.status, row.error = 'failed', str(exc)[:2000]
        db.session.commit()
        raise


def refresh_from_provider(b):
    from backend.services import certn_client as CC
    if not b.provider_application_id:
        return b.status
    st = apply_case(b, CC.get_client().get_case(b.provider_application_id), source='poll')
    b.last_polled_at = _now()
    return st


def report_link(b):
    from backend.services import certn_client as CC
    if not b.provider_application_id:
        raise OnboardingError('This check has not been started yet.', 'not_started', 409)
    return CC.get_client().report_url(b.provider_application_id)


# ── submit / orientation / referral ─────────────────────────────────────────

def submit_blockers(user, app, steps=None):
    steps = steps or compute_steps(user, app)
    by = {s['key']: s for s in steps}
    out = []
    if by['account_created']['status'] != 'done':
        out.append({'step': 'account_created', 'message': 'Accept the Terms, Privacy Policy and Community Guidelines.'})
    ph_ok, ph_issue = driver_phone_ok(user)
    if not ph_ok:
        out.append({'step': 'phone_verified', 'issue': ph_issue, 'purpose': 'driver_onboarding',
                    'message': 'Verify your phone number to continue.'})
    if user.email and not user.email_verified_at:
        out.append({'step': 'email_verified', 'message': 'Verify your email address.'})
    if not (app.prequal or {}).get('passed'):
        out.append({'step': 'profile_completed', 'message': 'Pass the quick eligibility check.'})
    missing = profile_missing(app)
    if missing:
        out.append({'step': 'profile_completed', 'message': 'Complete your personal and vehicle details.',
                    'fields': missing})
    if not by['profile_completed']['detail'].get('agreements_signed'):
        out.append({'step': 'profile_completed', 'message': 'Sign the Driver Agreement and Safety Policy.'})
    d = by['documents_submitted']['detail']
    if d.get('missing') or d.get('rejected'):
        out.append({'step': 'documents_submitted', 'message': 'Upload every required document.',
                    'missing': d.get('missing'), 'rejected': d.get('rejected')})
    if S.flag('background_check'):
        b = latest_bgc(user.id)
        if not b or b.status not in ('paid', 'initiated', 'pending', 'clear', 'consider'):
            out.append({'step': 'background_check', 'message': 'Start your background check.'})
    return out


def submit(user):
    app = get_application(user)
    if app.status not in ('in_progress', 'needs_changes'):
        raise OnboardingError('Your application was already submitted.', 'already_submitted', 409)
    blockers = submit_blockers(user, app)
    if blockers:
        raise OnboardingError('A few steps are still missing.', 'incomplete', 422, {'blockers': blockers})
    b = latest_bgc(user.id)
    app.status = 'under_review' if (not S.flag('background_check') or (b and b.status == 'clear')) else 'submitted'
    app.submitted_at = _now()
    if user.user_type not in ('Admin', 'Super Admin', 'Driver'):
        user.user_type = 'Pending Driver'
    for st in app.service_types or []:
        col = LEGACY_FLAG.get(st)
        if col:
            setattr(user, f'is_{col}', 'Yes')
    audit('onboarding.submitted', user, 'driver_application', app.id, after={'status': app.status}, actor_type='user')
    from backend.services import realtime
    realtime.to_admins('onboarding.submitted', {'application_id': app.id, 'user_id': user.id})
    return app


def orientation_content(lang='en'):
    lang = 'fr' if (lang or '').startswith('fr') else 'en'
    return {'cards': [{'title': c['title'][lang], 'body': c['body'][lang]} for c in ORIENTATION['cards']],
            'questions': [{'index': i, 'question': q['q'][lang], 'options': q['options'][lang]}
                          for i, q in enumerate(ORIENTATION['questions'])],
            'pass_score': S.get_int('onboarding.orientation_pass_score')}


def complete_orientation(user, answers, lang='en'):
    app = get_application(user)
    if not isinstance(answers, list) or len(answers) != len(ORIENTATION['questions']):
        raise OnboardingError('Answer all 5 questions.', 'answers_required')
    score = 0
    wrong = []
    for i, q in enumerate(ORIENTATION['questions']):
        try:
            ok = int(answers[i]) == q['answer']
        except (TypeError, ValueError):
            ok = False
        score += 1 if ok else 0
        if not ok:
            wrong.append(i)
    passed = score >= S.get_int('onboarding.orientation_pass_score')
    app.orientation_score = score
    if passed:
        app.orientation_completed_at = app.orientation_completed_at or _now()
    audit('onboarding.orientation', user, 'driver_application', app.id, after={'score': score, 'passed': passed},
          actor_type='user')
    lang = 'fr' if (lang or '').startswith('fr') else 'en'
    review = [{'index': i, 'question': ORIENTATION['questions'][i]['q'][lang],
               'correct_answer': ORIENTATION['questions'][i]['options'][lang][ORIENTATION['questions'][i]['answer']],
               'explanation': ORIENTATION['questions'][i]['explanation'][lang]} for i in wrong]
    return {'score': score, 'passed': passed, 'wrong_questions': wrong, 'review': review,
            'pass_score': S.get_int('onboarding.orientation_pass_score')}


def apply_referral(user, code):
    app = get_application(user)
    code = (code or '').strip().upper()
    if app.referred_by:
        raise OnboardingError('A referral code was already applied.', 'referral_exists', 409)
    if app.status not in ('in_progress', 'needs_changes'):
        raise OnboardingError('Referral codes must be added before you submit.', 'application_locked', 409)
    ref = DriverApplication.query.filter_by(referral_code=code).first()
    if not ref or ref.user_id == user.id:
        raise OnboardingError('That referral code is not valid.', 'invalid_referral')
    app.referred_by = ref.user_id
    return app


# ── admin decisions ─────────────────────────────────────────────────────────

def review_document(doc, admin, decision, note=None):
    if decision not in ('approve', 'approved', 'reject', 'rejected'):
        raise OnboardingError('Decision must be approve or reject.', 'invalid_decision')
    approve = decision.startswith('approve')
    if not approve and not (note or '').strip():
        raise OnboardingError('Tell the driver what to fix (reviewer note).', 'note_required')
    before = doc.status
    doc.status = 'approved' if approve else 'rejected'
    doc.reviewer_note = (note or '').strip()[:500] or None
    doc.reviewed_by, doc.reviewed_at = admin.id, _now()
    audit('onboarding.document_reviewed', admin, 'driver_document', doc.id, before={'status': before},
          after={'status': doc.status, 'note': doc.reviewer_note})
    if not approve:
        from backend.services.notify import notify
        notify('onboarding.needs_changes', [doc.user_id],
               {'reason': f'Please re-upload your {DOC_TITLES.get(doc.type, (doc.type,))[0].lower()}: {doc.reviewer_note}'})
    queue_progress_refresh(doc.user_id)
    return doc


def decide(app, admin, decision, reason=None, service_types=None, override_background_check=False):
    from backend.services.notify import notify
    user = db.session.get(AdminUser, app.user_id)
    before = {'status': app.status}
    if decision == 'approve':
        b = latest_bgc(user.id)
        if S.flag('background_check') and (not b or b.status != 'clear'):
            if not override_background_check:
                raise OnboardingError('The background check is not clear yet.', 'background_check_not_clear', 409)
            if not (reason or '').strip():
                raise OnboardingError('A reason is required to approve without a clear background check.',
                                      'reason_required')
        docs = latest_documents(app)
        rejected = [t for t, d in docs.items() if d.status in ('rejected', 'expired')]
        if rejected:
            raise OnboardingError('Some documents are rejected or expired.', 'documents_rejected', 409,
                                  {'documents': rejected})
        for d in docs.values():
            if d.status == 'pending':
                review_document(d, admin, 'approve', 'Approved with the application')
        types = service_types or app.service_types or ['car_hire']
        types = [t for t in types if t in SERVICE_TYPES] or ['car_hire']
        app.service_types = types
        app.status, app.reviewed_by, app.reviewed_at, app.rejection_reason = 'approved', admin.id, _now(), None
        if user.user_type not in ('Admin', 'Super Admin'):
            user.user_type = 'Driver'
        for t in types:
            col = LEGACY_FLAG.get(t)
            if col:
                setattr(user, f'is_{col}', 'Yes')
                setattr(user, f'is_{col}_approved', 'Yes')
        if app.licence_number:
            user.driving_license_number = app.licence_number
        if app.licence_expires_at:
            user.driving_license_validity = app.licence_expires_at.isoformat()
        vehicle = ' '.join(str(x) for x in (app.vehicle_year, app.vehicle_make, app.vehicle_model) if x)
        if vehicle:
            user.automobile = vehicle[:55]
        if app.vehicle_seats:
            user.max_passengers = app.vehicle_seats
        if app.legal_first_name:
            user.legal_name = f'{app.legal_first_name} {app.legal_last_name or ""}'.strip()
        notify('onboarding.approved', [user.id], {})
        _referral_bonus(app)
    elif decision in ('reject', 'needs_changes'):
        if not (reason or '').strip():
            raise OnboardingError('A reason is required.', 'reason_required')
        app.status = 'rejected' if decision == 'reject' else 'needs_changes'
        app.rejection_reason, app.reviewed_by, app.reviewed_at = reason.strip(), admin.id, _now()
        if decision == 'reject':
            _clear_applied_flags(user, app)
            if user.user_type == 'Pending Driver':
                user.user_type = 'Customer'
        notify('onboarding.rejected' if decision == 'reject' else 'onboarding.needs_changes', [user.id],
               {'reason': reason.strip()})
    else:
        raise OnboardingError('Decision must be approve, reject or needs_changes.', 'invalid_decision')
    audit(f'onboarding.application_{decision}', admin, 'driver_application', app.id, before=before,
          after={'status': app.status, 'service_types': app.service_types},
          meta={'reason': reason, 'override_background_check': bool(override_background_check)})
    queue_progress_refresh(user.id)
    return app


def _clear_applied_flags(user, app):
    """Undo the is_<svc>='Yes' "applied" flags set at submit (never touches approved services)."""
    cols = {LEGACY_FLAG[t] for t in (app.service_types or []) if t in LEGACY_FLAG}
    for col in cols:
        if getattr(user, f'is_{col}_approved', None) != 'Yes' and getattr(user, f'is_{col}', None) == 'Yes':
            setattr(user, f'is_{col}', 'No')


def queue_progress_refresh(user_id):
    """Funnel analytics: re-compute + record step progress after a change made outside the
    wizard (webhook, admin review, phone/email verification) — not only when the overview opens."""
    jobs.enqueue_after_commit('backend.services.onboarding_service.refresh_progress', user_id)


def refresh_progress(user_id):
    """Job: record step progress for an existing application (no-op without one)."""
    user = db.session.get(AdminUser, user_id)
    app = DriverApplication.query.filter_by(user_id=user_id).first() if user else None
    if not app:
        return False
    _record_progress(app, compute_steps(user, app))
    db.session.commit()
    return True


def _referral_bonus(app):
    if not app.referred_by or not S.flag('referrals'):
        return
    cents = S.get_int('onboarding.referral_bonus_cents')
    if cents <= 0:
        return
    from backend.services import wallet_service as W
    try:
        W.credit(app.referred_by, W.cents_to_dollars(cents), 'referral_bonus', f'referral-{app.id}',
                 f'Referral bonus — driver #{app.user_id} approved')
    except Exception:
        log.exception('referral bonus failed for application %s', app.id)


def settle_bgc_deductions(driver_id, commit=True):
    """Pay-later: recover the fronted fee from the wallet — partially when the balance
    is short (deducted_cents tracks what was taken). Returns the checks fully settled."""
    from decimal import Decimal
    from backend.services import wallet_service as W
    n = 0
    for b in (BackgroundCheck.query.filter_by(user_id=driver_id, deduction_status='pending')
              .order_by(BackgroundCheck.id).with_for_update().all()):
        remaining = int(b.fee_cents or 0) - int(b.deducted_cents or 0)
        if remaining <= 0:
            b.deduction_status, b.deduction_settled_at = ('settled' if b.fee_cents else 'waived'), _now()
            n += 1
            continue
        balance_cents = int((W.balance_of(driver_id) * 100).to_integral_value())
        take = min(remaining, balance_cents)
        if take <= 0:
            continue
        try:
            W.debit(driver_id, W.cents_to_dollars(take), 'background_check_fee',
                    f'bgc-fee-{b.id}-{int(b.deducted_cents or 0)}',
                    f'Background check fee (paid from earnings) #{b.id}'
                    + ('' if take == remaining else f' — partial {Decimal(take) / 100:.2f}'))
        except ValueError:
            continue
        b.deducted_cents = int(b.deducted_cents or 0) + take
        after = {'amount_cents': take, 'deducted_cents': b.deducted_cents, 'fee_cents': b.fee_cents}
        if b.deducted_cents >= int(b.fee_cents or 0):
            b.deduction_status, b.deduction_settled_at = 'settled', _now()
            n += 1
        audit('onboarding.bgc_deduction_settled' if b.deduction_status == 'settled' else 'onboarding.bgc_deduction_partial',
              None, 'background_check', b.id, after=after)
    if commit:
        db.session.commit()
    return n


def outstanding_deduction_cents(driver_id):
    """For payouts (finance): fronted fees not yet recovered (fee − already deducted)."""
    from sqlalchemy import func
    return int(db.session.query(func.coalesce(func.sum(BackgroundCheck.fee_cents - BackgroundCheck.deducted_cents), 0))
               .filter(BackgroundCheck.user_id == driver_id, BackgroundCheck.deduction_status == 'pending').scalar() or 0)


# ── legacy /api/become-driver ───────────────────────────────────────────────

def from_legacy_become_driver(user, data):
    """Mirror the v3 form into a submitted application (admin queue)."""
    app = get_application(user)
    if data.get('first_name'):
        app.legal_first_name = app.legal_first_name or str(data['first_name'])[:100]
    if data.get('last_name'):
        app.legal_last_name = app.legal_last_name or str(data['last_name'])[:100]
    dob = parse_date(data.get('date_of_birth'))
    if dob:
        app.date_of_birth = app.date_of_birth or dob
    if data.get('driving_license_number'):
        app.licence_number = str(data['driving_license_number'])[:60]
    exp = parse_date(data.get('driving_license_validity'))
    if exp:
        app.licence_expires_at = exp
    if data.get('automobile'):
        app.vehicle_make = app.vehicle_make or str(data['automobile'])[:60]
    types = []
    for col, st in (('is_car', 'car_hire'), ('is_delivery', 'courier')):
        if str(data.get(col) or '').lower() in ('yes', 'true', '1'):
            types.append(st)
    if types:
        app.service_types = types
    if app.status in ('in_progress', 'needs_changes'):
        app.status, app.submitted_at = 'submitted', _now()
        notes = (app.notes or '')
        if 'legacy' not in notes:
            app.notes = (notes + '\nSubmitted through the v3 /api/become-driver form.').strip()
    return app


# ── periodic jobs (see onboarding_jobs) ─────────────────────────────────────

def expiry_scan(today=None):
    from backend.services.notify import notify
    today = today or _now().date()
    thresholds = sorted({int(x) for x in _csv('onboarding.expiry_reminder_days') if x.isdigit()})
    horizon = today + timedelta(days=max(thresholds or [30]))
    rows = (DriverDocument.query.filter(DriverDocument.type.in_(EXPIRY_MONITORED),
                                        DriverDocument.status.in_(('approved', 'pending')),
                                        DriverDocument.expires_at.isnot(None),
                                        DriverDocument.expires_at <= horizon).limit(2000).all())
    reminded = expired = 0
    for d in rows:
        label = DOC_LABEL_FOR_NOTICE.get(d.type, d.type)
        days_left = (d.expires_at - today).days
        if days_left < 0:
            d.status = 'expired'
            u = db.session.get(AdminUser, d.user_id)
            if u and u.ready_for_trip == 'Yes':
                u.ready_for_trip = 'No'
            audit('onboarding.document_expired', None, 'driver_document', d.id, after={'type': d.type})
            notify('document.expired', [d.user_id], {'document': label})
            expired += 1
            continue
        due = [t for t in thresholds if days_left <= t]
        if not due:
            continue
        t = min(due)
        sent = list(d.reminders_sent or [])
        if t in sent:
            continue
        sent = sorted(set(sent) | {x for x in thresholds if x >= t})
        d.reminders_sent = sent
        notify('document.expiring', [d.user_id], {'document': label, 'days': days_left})
        reminded += 1
    db.session.commit()
    return {'reminded': reminded, 'expired': expired}


def poll_pending(now=None):
    from backend.services import certn_client as CC
    now = now or _now()
    stale = now - timedelta(hours=5)
    started = polled = 0
    for b in (BackgroundCheck.query.filter_by(status='paid').filter(BackgroundCheck.provider_application_id.is_(None))
              .filter((BackgroundCheck.start_after.is_(None)) | (BackgroundCheck.start_after <= now)).limit(100)):
        if initiate_background_check(b.id):
            started += 1
    rows = (BackgroundCheck.query.filter(BackgroundCheck.status.in_(('initiated', 'pending')),
                                         BackgroundCheck.provider_application_id.isnot(None))
            .filter((BackgroundCheck.last_polled_at.is_(None)) | (BackgroundCheck.last_polled_at <= stale))
            .limit(200).all())
    for b in rows:
        try:
            refresh_from_provider(b)
            polled += 1
            db.session.commit()
        except CC.CertnError as e:
            db.session.rollback()
            log.warning('Certn poll failed for bgc %s: %s', b.id, e)
    return {'started': started, 'polled': polled}


def recheck_scan(now=None):
    from backend.services.notify import notify
    now = now or _now()
    lead = timedelta(days=S.get_int('onboarding.recheck_reminder_days'))
    reminded = expired = 0
    for b in BackgroundCheck.query.filter(BackgroundCheck.status == 'clear', BackgroundCheck.expires_at.isnot(None),
                                          BackgroundCheck.expires_at <= now + lead).limit(500):
        if b.expires_at <= now:
            b.status = 'expired'
            audit('onboarding.bgc_expired', None, 'background_check', b.id)
            notify('onboarding.step_required', [b.user_id],
                   {'step': 'Your annual background check is due — renew it to keep driving'})
            expired += 1
        elif not b.recheck_reminded_at:
            b.recheck_reminded_at = now
            days = max(1, (b.expires_at - now).days)
            notify('onboarding.step_required', [b.user_id],
                   {'step': f'Your annual background check is due in {days} days — renew it in the app'})
            reminded += 1
    db.session.commit()
    return {'reminded': reminded, 'expired': expired}


def funnel():
    """Admin analytics: how many applicants reached / are stuck at each step."""
    from sqlalchemy import func
    total = DriverApplication.query.count()
    at_step = dict(db.session.query(DriverApplication.current_step, func.count(DriverApplication.id))
                   .group_by(DriverApplication.current_step).all())
    by_status = dict(db.session.query(DriverApplication.status, func.count(DriverApplication.id))
                     .group_by(DriverApplication.status).all())
    reached = {k: 0 for k in STEP_ORDER}
    for (steps,) in db.session.query(DriverApplication.steps).all():
        if isinstance(steps, str):
            import json
            try:
                steps = json.loads(steps)
            except ValueError:
                steps = {}
        for k in (steps or {}):
            if k in reached:
                reached[k] += 1
    out, prev = [], total
    for k in STEP_ORDER:
        n = reached[k]
        out.append({'step': k, 'title': STEP_TITLES[k][0], 'completed': n, 'currently_at': int(at_step.get(k, 0)),
                    'drop_off_pct': round(100.0 * (prev - n) / prev, 1) if prev else 0.0})
        prev = n if n else prev
    return {'total_applications': total, 'by_status': {k: int(v) for k, v in by_status.items()}, 'steps': out}


# ── background check: cancel + refund before submission, fee receipt ──────

CANCELLABLE_BGC = ('awaiting_payment', 'paid')


def cancel_background_check(user, reason=None):
    """Driver cancels a check that has NOT been submitted to Certn yet (spec §14.2 #2:
    refundable if cancelled before submission). Card fees are refunded in full,
    pay-later deductions are waived (anything already recovered goes back to the
    wallet). Returns (check, refunded_cents)."""
    b = (BackgroundCheck.query.filter_by(user_id=user.id).order_by(BackgroundCheck.id.desc())
         .with_for_update().first())
    if not b or b.status not in CANCELLABLE_BGC:
        raise OnboardingError('There is no background check to cancel.', 'nothing_to_cancel', 409)
    if b.provider_application_id or b.status not in CANCELLABLE_BGC:
        raise OnboardingError('Your check was already submitted to Certn, so the fee can no longer be refunded.',
                              'already_submitted', 409)
    refunded = 0
    before = b.status
    if b.status == 'paid' and b.paid_by == 'driver' and b.fee_payment_id:
        refunded = _refund_bgc_fee(b, user, reason)
    elif b.paid_by == 'earnings':
        if int(b.deducted_cents or 0) > 0:
            from backend.services import wallet_service as W
            W.credit(user.id, W.cents_to_dollars(b.deducted_cents), 'refund',
                     f'bgc-fee-refund-{b.id}', f'Background check #{b.id} cancelled — fee returned',
                     add_to_earnings=False)
            refunded = int(b.deducted_cents)
        b.deduction_status = 'waived'
    b.status, b.cancelled_at = 'cancelled', _now()
    audit('onboarding.bgc_cancelled', user, 'background_check', b.id, before={'status': before},
          after={'status': 'cancelled', 'refunded_cents': refunded, 'paid_by': b.paid_by},
          meta={'reason': (reason or '')[:500] or None}, actor_type='user')
    queue_progress_refresh(user.id)
    return b, refunded


def _refund_bgc_fee(b, actor, reason=None):
    from backend.models.money import RidePayment
    from backend.services.payments import payment_service as PS
    from backend.services.payments.gateway import GatewayError, get_gateway
    rp = RidePayment.query.filter_by(id=b.fee_payment_id).with_for_update().first()
    if not rp:
        return 0
    amount = int(rp.amount_captured_cents or 0) - int(rp.amount_refunded_cents or 0)
    if amount <= 0:
        return 0
    key = f'bgc-{b.id}-cancel-refund'
    try:
        res = get_gateway().refund(rp.intent_id, amount, idempotency_key=key, reason='requested_by_customer')
    except GatewayError as e:
        raise OnboardingError(f'The refund could not be processed right now: {e}', 'refund_failed', 502)
    PS._refund_row(rp, amount, 'refund', 'bgc_cancel_before_submission',
                   (reason or 'Background check cancelled before submission to Certn'), key,
                   provider_id=res.get('id'), actor=actor, actor_type='user')
    rp.amount_refunded_cents = int(rp.amount_refunded_cents or 0) + amount
    b.refunded_cents, b.refunded_at = amount, _now()
    return amount


def send_bgc_receipt(bgc_id):
    """Job: email the NegoRide receipt for a background-check fee paid by card. Idempotent."""
    from backend.models.money import RidePayment
    from backend.services.notify import email_provider, templates
    from backend.utils.money import fmt
    b = BackgroundCheck.query.filter_by(id=bgc_id).with_for_update().first()
    if not b or b.receipt_emailed_at or b.paid_by != 'driver' or not b.fee_payment_id:
        db.session.rollback()
        return None
    user = db.session.get(AdminUser, b.user_id)
    rp = db.session.get(RidePayment, b.fee_payment_id)
    if not user or not user.email or not rp:
        db.session.rollback()
        return None
    fr = (user.preferred_language or '').startswith('fr')
    amount = int(rp.amount_captured_cents or b.fee_cents or 0)
    paid_at = b.fee_paid_at or _now()
    method = ' '.join(x for x in ((rp.payment_method_brand or '').title(),
                                  f'•••• {rp.payment_method_last4}' if rp.payment_method_last4 else '') if x) or 'Card'
    ctx = {
        'lang': 'fr' if fr else 'en',
        'title': 'Reçu — vérification des antécédents' if fr else 'Receipt — background check',
        'preheader': (f'Nous avons reçu votre paiement de {fmt(amount)}.' if fr
                      else f'We received your payment of {fmt(amount)}.'),
        'first_name': (user.first_name or (user.name or '').split(' ')[0] or '').strip(),
        'receipt_number': f'BGC-{paid_at:%Y}-{b.id:06d}',
        'paid_at': paid_at.strftime('%Y-%m-%d %H:%M UTC'),
        'amount': fmt(amount), 'method': method,
        'description': ('Vérification des antécédents du chauffeur NegoRide (Certn)' if fr
                        else 'NegoRide driver background check (Certn)'),
        'refund_note': ('Remboursable si vous annulez avant l’envoi de la vérification à Certn '
                        f'(environ {S.get_int("onboarding.bgc_start_delay_min")} min après le paiement); '
                        'non remboursable ensuite.') if fr else
                       ('Refundable if you cancel before the check is submitted to Certn (about '
                        f'{S.get_int("onboarding.bgc_start_delay_min")} minutes after payment); non-refundable afterwards.'),
        'fr': fr,
    }
    html, text = templates.render('bgc_receipt', ctx)
    try:
        email_provider.send(user.email, ctx['title'] + ' · NegoRide', html, text=text, tag='bgc-receipt')
    except Exception as exc:
        db.session.rollback()
        log.warning('bgc receipt email failed for %s: %s', bgc_id, exc)
        return None
    b.receipt_emailed_at = _now()
    audit('onboarding.bgc_receipt_emailed', None, 'background_check', b.id,
          after={'receipt_number': ctx['receipt_number'], 'amount_cents': amount})
    db.session.commit()
    return ctx['receipt_number']
