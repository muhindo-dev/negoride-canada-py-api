"""app_settings — feature flags and every configurable number (spec §2.11).

Every key has a code default in DEFAULTS, so the platform works on an empty
table; admins override values in the dashboard (Settings page), which writes a
row. Reads are cached per process for a few seconds.

    from backend.services import settings_service as S
    if S.flag('pay_before_trip'): ...
    S.get_int('cancel.fee_cents')
"""
import json
import threading
import time

from backend.models import db
from backend.models.platform import AppSetting

# key: (default, type, category, description, public)
# `public` settings are returned to the mobile app by GET /api/app/config.
DEFAULTS = {
    # ── Feature flags ────────────────────────────────────────────────────────
    'ff.trip_state_machine': (True, 'bool', 'flags', 'Strict trip lifecycle (§4)', True),
    'ff.pay_before_trip': (True, 'bool', 'flags', 'Driver cannot head to pickup until payment is authorized (§6)', True),
    'ff.ride_pin': (True, 'bool', 'flags', 'Customer 4-digit PIN required to start a ride (§8.4)', True),
    'ff.arrival_geofence': (True, 'bool', 'flags', "Enforce the 'I've arrived' geofence (§4)", True),
    'ff.notifications_v4': (True, 'bool', 'flags', 'Multi-channel notification engine (§5)', True),
    'ff.sms_fallback': (True, 'bool', 'flags', 'SMS escalation for critical pushes not opened in time', False),
    'ff.cancellation_fees': (True, 'bool', 'flags', 'Apply cancellation / no-show fees (§7)', True),
    'ff.receipts_email': (True, 'bool', 'flags', 'Email thank-you + receipt at completion (§13)', False),
    'ff.combined_receipt_email': (True, 'bool', 'flags', 'One combined thank-you + receipt email [CONFIRM WITH CLIENT]', False),
    'ff.sos': (True, 'bool', 'flags', 'SOS / Safety toolkit (§8)', True),
    'ff.live_share': (True, 'bool', 'flags', 'Share live trip links (§9)', True),
    'ff.audio_recording': (True, 'bool', 'flags', 'Optional in-trip audio recording (§10)', True),
    'ff.route_deviation': (True, 'bool', 'flags', 'Route deviation / long-stop "Are you OK?" checks', True),
    'ff.twilio_verify': (True, 'bool', 'flags', 'Phone verification through Twilio Verify (§11)', True),
    'ff.phone_required_signup': (False, 'bool', 'flags', 'Require a verified phone before an account is active', True),
    'ff.passwordless_login': (True, 'bool', 'flags', 'Log in with phone + OTP', True),
    'ff.step_up_new_device': (False, 'bool', 'flags', 'OTP step-up when logging in from an unseen device', True),
    'ff.legal_consent_required': (True, 'bool', 'flags', 'Three explicit consent ticks required at sign-up (§12)', True),
    'ff.legal_scroll_to_accept': (False, 'bool', 'flags', 'Agree button activates only after scrolling to the end', True),
    'ff.driver_onboarding_v2': (True, 'bool', 'flags', '7-step driver onboarding wizard (§14)', True),
    'ff.background_check': (True, 'bool', 'flags', 'Certn background check step', True),
    'ff.bgc_pay_later': (False, 'bool', 'flags', '"Pay later from earnings" for the background check fee', True),
    'ff.bgc_platform_pays_recheck': (False, 'bool', 'flags', 'Platform pays annual re-screening', False),
    'ff.live_eta': (True, 'bool', 'flags', 'Server-computed live ETA (§16)', True),
    'ff.ratings_v2': (True, 'bool', 'flags', 'Two-way ratings with tags and tips (§17)', True),
    'ff.rideshare_self_booking': (True, 'bool', 'flags', 'Customers book rideshare seats directly (§18)', True),
    'ff.rideshare_seat_negotiation': (True, 'bool', 'flags', 'Negotiate price per seat within driver bounds', True),
    'ff.pick_a_driver': (True, 'bool', 'flags', 'Customer can choose a specific nearby driver', True),
    'ff.favourite_first': (True, 'bool', 'flags', 'Request my favourite driver first', True),
    'ff.auto_suspend_low_rating': (True, 'bool', 'flags', 'Automatic warning / suspension on low rating', False),
    'ff.strike_suspension': (True, 'bool', 'flags', 'Automatic warning / suspension on reliability strikes', False),
    'ff.referrals': (False, 'bool', 'flags', 'Driver referral bonus', True),
    'ff.home_v4': (True, 'bool', 'flags', 'Map-first v4 Home screens (§21.2) — off restores the legacy Home', True),
    'ff.driver_no_show_credit': (True, 'bool', 'flags', '$5 apology credit on driver no-show', False),

    # ── Pricing / commission ─────────────────────────────────────────────────
    'pricing.commission_pct': (10, 'int', 'pricing', 'Platform commission % of fare', True),
    'pricing.booking_fee_cents': (0, 'int', 'pricing', 'Booking/service fee added to each car-hire ride', True),
    'pricing.tax_inclusive': (True, 'bool', 'pricing', 'Fares are GST/HST-inclusive [CONFIRM WITH ACCOUNTANT]', True),
    'pricing.min_fare_cents': (500, 'int', 'pricing', 'Lowest allowed offer', True),

    # ── Trip lifecycle ───────────────────────────────────────────────────────
    'ride.arrival_geofence_m': (150, 'int', 'ride', "Max distance from pickup for 'I've arrived'", True),
    'ride.arriving_eta_s': (120, 'int', 'ride', 'Auto DRIVER_ARRIVING when ETA ≤ this', False),
    'ride.arriving_distance_m': (500, 'int', 'ride', 'Auto DRIVER_ARRIVING when distance ≤ this', False),
    'ride.complete_geofence_m': (1000, 'int', 'ride', "Max distance from drop-off for 'Complete' (0 = off)", False),
    'ride.payment_timeout_s': (300, 'int', 'ride', 'AWAITING_PAYMENT → EXPIRED after', True),
    'ride.negotiation_timeout_s': (1800, 'int', 'ride', 'REQUESTED/NEGOTIATING → EXPIRED after', False),
    'ride.driver_no_show_grace_s': (900, 'int', 'ride', 'DRIVER_NO_SHOW when not arrived by ETA + this', False),
    'ride.auto_close_h': (72, 'int', 'ride', 'COMPLETED → CLOSED after (hours)', False),
    'ride.wait_window_s': (300, 'int', 'ride', 'Customer wait window after DRIVER_ARRIVED', True),
    'ride.wait_warning_before_s': (120, 'int', 'ride', 'Send wait warning this long before the window ends', False),
    'rideshare.boarding_before_min': (30, 'int', 'ride', 'Rideshare trip → BOARDING this many minutes before departure', True),
    'rideshare.charge_now_after_days': (6, 'int', 'ride', 'Charge immediately (no hold) when departure is further out', False),
    'rideshare.request_timeout_min': (30, 'int', 'ride', 'Request-to-book auto-decline after', True),
    'rideshare.departure_reminder_min': (60, 'int', 'ride', 'Departure reminder lead time', False),
    'carhire.favourite_first_s': (45, 'int', 'ride', 'Favourite driver exclusivity before broadcast', True),
    'carhire.broadcast_radius_km': (15, 'int', 'ride', 'Radius for broadcasting new requests', False),

    # ── Cancellation & refunds (§7) [CONFIRM WITH CLIENT] ───────────────────
    'cancel.free_window_s': (120, 'int', 'cancellation', 'Free cancellation window after confirmation', True),
    'cancel.fee_cents': (500, 'int', 'cancellation', 'Cancellation fee while driver en route', True),
    'cancel.fee_pct_cap': (10, 'int', 'cancellation', 'Fee capped at this % of fare (whichever is lower)', True),
    'cancel.after_arrival_fee_cents': (500, 'int', 'cancellation', 'Base fee after driver arrived', True),
    'wait.free_s': (120, 'int', 'cancellation', 'Free waiting time after arrival', True),
    'wait.rate_cents_per_min': (35, 'int', 'cancellation', 'Waiting time rate after the free period', True),
    'noshow.customer_fee_cents': (700, 'int', 'cancellation', 'Customer no-show fee', True),
    'noshow.driver_credit_cents': (500, 'int', 'cancellation', 'Apology ride credit on driver no-show', True),
    'rideshare.refund_full_h': (24, 'int', 'cancellation', '100 % refund if cancelled more than N h before', True),
    'rideshare.refund_half_h': (2, 'int', 'cancellation', '50 % refund if cancelled more than N h before', True),
    'rideshare.refund_half_pct': (50, 'int', 'cancellation', 'Partial refund percentage', True),
    'strikes.window_days': (7, 'int', 'cancellation', 'Reliability strike window', False),
    'strikes.warn_after': (3, 'int', 'cancellation', 'Warning when strikes exceed', False),
    'strikes.suspend_after': (5, 'int', 'cancellation', 'Temporary suspension when strikes exceed', False),
    'strikes.suspend_days': (3, 'int', 'cancellation', 'Length of an automatic strike suspension', False),

    # ── Ratings (§17, §15) ───────────────────────────────────────────────────
    'rating.window': (100, 'int', 'ratings', 'Rolling window of rated trips', False),
    'rating.prior_mean': (4.8, 'float', 'ratings', 'Bayesian prior mean for new drivers', False),
    'rating.prior_weight': (5, 'int', 'ratings', 'Bayesian prior weight', False),
    'rating.rate_within_h': (72, 'int', 'ratings', 'Ratings accepted up to N h after completion', True),
    'rating.warn_below': (4.3, 'float', 'ratings', 'Driver warning below this (over last N rides)', False),
    'rating.suspend_below': (4.0, 'float', 'ratings', 'Auto-suspension pending review below this', False),
    'rating.min_rides_for_rules': (50, 'int', 'ratings', 'Rides considered by the rating rules', False),
    'rating.reminder_after_h': (2, 'int', 'ratings', 'Rating reminder sent after', False),

    # ── Safety (§8–§10) ──────────────────────────────────────────────────────
    'safety.oncall_phones': ('', 'string', 'safety', 'Comma-separated E.164 on-call phones for SOS escalation', False),
    'safety.sos_ack_timeout_s': (60, 'int', 'safety', 'Escalate SOS if not acknowledged within', False),
    'safety.max_trusted_contacts': (5, 'int', 'safety', 'Trusted contacts per user', True),
    'safety.route_deviation_m': (500, 'int', 'safety', 'Off-route distance that triggers a check', False),
    'safety.long_stop_s': (300, 'int', 'safety', 'Unexpected stop duration that triggers a check', False),
    'safety.check_response_s': (60, 'int', 'safety', 'No answer to "Are you OK?" alerts the admin after', True),
    'safety.support_phone': ('', 'string', 'safety', 'NegoRide support phone', True),
    'safety.support_email': ('support@negoride.ca', 'string', 'safety', 'NegoRide support email', True),
    'tracking.share_expiry_after_end_min': (30, 'int', 'safety', 'Share link expires N minutes after trip end', False),
    'tracking.retention_days': (90, 'int', 'safety', 'Breadcrumb retention (unless incident/dispute)', False),
    'tracking.active_interval_s': (4, 'int', 'safety', 'Driver location interval during a ride', True),
    'tracking.online_interval_s': (10, 'int', 'safety', 'Driver location interval while online', True),
    'recording.retention_days': (7, 'int', 'safety', 'Auto-delete recordings after (unless held)', True),
    'recording.hold_after_case_days': (90, 'int', 'safety', 'Keep held recordings after the case closes', False),
    'recording.chunk_seconds': (60, 'int', 'safety', 'Audio chunk length', True),
    'recording.max_chunk_bytes': (5000000, 'int', 'safety', 'Max bytes per uploaded audio chunk', True),
    'safety.sos_location_interval_s': (3, 'int', 'safety', 'App location cadence while an SOS is open', True),
    'safety.check_throttle_s': (600, 'int', 'safety', 'At most one "Are you OK?" check per ride per N s', False),
    'safety.long_stop_radius_m': (60, 'int', 'safety', 'Movement radius that still counts as stopped', False),
    'safety.incident_share_hours': (24, 'int', 'safety', 'Max lifetime of an SOS live-location link', False),
    'tracking.share_max_hours': (12, 'int', 'safety', 'Max lifetime of a trip share link while the trip runs', False),
    'tracking.public_rate_limit_per_min': (60, 'int', 'safety', 'Public tracking requests per IP per minute', False),
    # safety audit gaps (v4_0101)
    'tracking.public_rate_limit_per_token_per_min': (120, 'int', 'safety', 'Public tracking requests per share link per minute (all viewers)', False),
    'tracking.batch_flush_s': (3, 'int', 'safety', 'Breadcrumb buffer flush interval (bulk insert)', False),
    'tracking.max_point_age_s': (600, 'int', 'safety', 'Older (offline catch-up) points are stored but not used for live updates', False),
    'safety.pin_max_attempts': (5, 'int', 'safety', 'Wrong ride-PIN attempts before the ride PIN locks', False),
    'safety.pin_lock_window_s': (600, 'int', 'safety', 'Sliding window / lock duration for wrong ride-PIN attempts', False),

    # ── Identity (§11) ───────────────────────────────────────────────────────
    'otp.resend_after_s': (30, 'int', 'identity', 'Resend cooldown', True),
    'otp.max_sends_per_phone_h': (5, 'int', 'identity', 'Sends per phone per hour', False),
    'otp.max_sends_per_ip_h': (10, 'int', 'identity', 'Sends per IP per hour', False),
    'otp.max_check_attempts': (5, 'int', 'identity', 'Code attempts per verification', False),
    'otp.voice_after_failed_sms': (2, 'int', 'identity', 'Offer a voice call after N SMS', True),
    'otp.allowed_countries': ('CA,US', 'string', 'identity', 'Allowed phone country codes', True),
    'otp.block_voip_drivers': (True, 'bool', 'identity', 'Block VoIP numbers for drivers', False),
    'otp.code_ttl_s': (600, 'int', 'identity', 'OTP code lifetime (Twilio Verify default 10 min)', True),
    'otp.token_ttl_s': (900, 'int', 'identity', 'verification_token lifetime after a correct code', False),
    'otp.whatsapp_enabled': (False, 'bool', 'identity', 'Offer the WhatsApp OTP channel', True),
    'otp.lookup_at_signup': (True, 'bool', 'identity', 'Twilio Lookup line-type check at sign-up (when Twilio is configured)', False),
    'otp.block_voip_signup': (False, 'bool', 'identity', 'Block VoIP numbers at customer sign-up (drivers: otp.block_voip_drivers)', False),
    'ff.sensitive_action_reverify': (True, 'bool', 'flags', 'v4 clients must re-verify the phone before payout-account changes and account deletion', True),
    'legal.consent_min_app_version': ('4.0.0', 'string', 'identity', 'Clients at/above this X-App-Version must send the three consent ticks', False),
    'otp.allowed_nanp_regions': ('', 'string', 'identity', 'Extra NANP (+1) regions allowed besides CA/US, e.g. "876,809" area codes or "JM,DO" (Caribbean numbers are refused by default — fraud / SMS pumping)', False),
    'legal.enforce_reacceptance': (True, 'bool', 'identity', 'Block API calls (403 legal_pending) until a policy version marked "requires re-acceptance" is accepted (v4 clients)', False),
    'legal.marketing_consent_version': ('2026-09', 'string', 'identity', 'Version tag of the CASL marketing consent wording stored as proof', True),
    'legal.marketing_consent_text': ('Yes, send me NegoRide news, offers and promotions by email and SMS. I can unsubscribe at any time.', 'string', 'identity', 'CASL marketing consent wording (EN) shown by the apps and stored as proof with every grant', True),
    'legal.marketing_consent_text_fr': ('Oui, envoyez-moi les nouvelles, offres et promotions de NegoRide par courriel et SMS. Je peux me désabonner en tout temps.', 'string', 'identity', 'CASL marketing consent wording (FR)', True),

    # ── Onboarding (§14) [CONFIRM WITH CLIENT] ───────────────────────────────
    'onboarding.bgc_fee_cents': (3999, 'int', 'onboarding', 'Background check fee (CAD cents)', True),
    'onboarding.certn_package': ('rideshare_ca_basic', 'string', 'onboarding', 'Certn package key', False),
    'onboarding.min_driver_age': (21, 'int', 'onboarding', 'Minimum driver age', True),
    'onboarding.min_vehicle_year': (2012, 'int', 'onboarding', 'Oldest allowed vehicle model year', True),
    'onboarding.recheck_months': (12, 'int', 'onboarding', 'Annual re-screening interval', False),
    'onboarding.referral_bonus_cents': (5000, 'int', 'onboarding', 'Referral bonus', True),
    'onboarding.orientation_pass_score': (4, 'int', 'onboarding', 'Orientation quiz pass mark (of 5)', True),
    'onboarding.certn_check_types': ('IDENTITY_VERIFICATION_1,CRIMINAL_RECORD_REPORT_1,MOTOR_VEHICLE_RECORD_1', 'string', 'onboarding',
                                     'Certn Centric check_types_with_arguments keys ordered when no package id is set [CONFIRM WITH CLIENT]', False),
    'onboarding.allowed_licence_classes': ('1,2,3,4,5,G', 'string', 'onboarding', 'Full (non-learner) licence classes accepted', True),
    'onboarding.allowed_provinces': ('AB,BC,MB,NB,NL,NS,NT,NU,ON,PE,QC,SK,YT', 'string', 'onboarding', 'Provinces/territories served', True),
    'onboarding.required_documents': ('licence_front,licence_back,registration,insurance,vehicle_front,vehicle_back,vehicle_left,vehicle_right,vehicle_interior,selfie',
                                      'string', 'onboarding', 'Documents required before submitting', True),
    'onboarding.expiry_reminder_days': ('30,14,3', 'string', 'onboarding', 'Document expiry reminder thresholds (days)', False),
    'onboarding.recheck_reminder_days': (30, 'int', 'onboarding', 'Notify drivers this many days before the annual re-check is due', False),
    'onboarding.bgc_start_delay_min': (30, 'int', 'onboarding', 'Minutes between the fee payment and ordering the Certn check (cancel + refund window)', True),
    'onboarding.rideshare_endorsement_provinces': ('ON,BC,AB,QC', 'string', 'onboarding', 'Provinces where the insurance upload must attest a rideshare endorsement', True),
    'onboarding.face_match_threshold': (90, 'int', 'onboarding', 'Face-match similarity (0-100) at/above which the selfie is flagged "match" for the reviewer (never auto-approves)', False),
    'onboarding.certn_dispute_contact': ('Certn Support — https://certn.co/contact', 'string', 'onboarding',
                                         'Where drivers dispute background-check results [REVIEW WITH COUNSEL]', True),
    'support.sla_urgent_h': (1, 'int', 'support', 'First-response SLA for urgent tickets (hours)', False),
    'support.sla_high_h': (4, 'int', 'support', 'First-response SLA for high-priority tickets (hours)', False),
    'support.sla_normal_h': (24, 'int', 'support', 'First-response SLA for normal tickets (hours)', False),
    'support.sla_low_h': (72, 'int', 'support', 'First-response SLA for low-priority tickets (hours)', False),

    # ── ETA (§16) ────────────────────────────────────────────────────────────
    'eta.min_refresh_s': (30, 'int', 'eta', 'Minimum seconds between Google Routes calls per ride', False),
    'eta.deviation_m': (300, 'int', 'eta', 'Refresh ETA at once when the driver moves this much further from the target', False),
    'eta.avg_speed_kmh': (32, 'int', 'eta', 'Average speed for the no-Google ETA fallback', False),
    'eta.road_factor': (1.3, 'float', 'eta', 'Straight-line → road distance factor (fallback)', False),

    # ── Experience (§18, §21.2, §21.3) — owned by the experience module ────
    'carhire.broadcast_max_drivers': (10, 'int', 'ride', 'Nearest N online drivers a broadcast request is offered to', False),
    'carhire.broadcast_timeout_s': (180, 'int', 'ride', 'Unanswered broadcast requests expire after', True),
    'carhire.nearby_radius_km': (10, 'int', 'ride', "'Choose a driver' list radius", True),
    'rideshare.search_radius_km': (25, 'int', 'ride', 'Rideshare search radius around origin / destination', True),
    'pricing.fair_base_cents': (425, 'int', 'pricing', 'Typical-fare estimate: Toronto benchmark starting fare (CAD cents); adjust for your market', False),
    'pricing.fair_per_km_cents': (175, 'int', 'pricing', 'Typical-fare estimate: distance rate per km (CAD cents); Toronto benchmark', False),
    'pricing.fair_per_min_cents': (15, 'int', 'pricing', 'Typical-fare estimate: travel-time contribution per minute (CAD cents)', False),
    'pricing.fair_spread_pct': (13, 'int', 'pricing', 'Fair-price hint: ± spread around the typical fare', False),
    'pricing.fair_car_pct': (100, 'int', 'pricing', 'Typical-fare estimate multiplier for standard car hire (%)', False),
    'pricing.fair_courier_pct': (115, 'int', 'pricing', 'Typical-fare estimate multiplier for courier service (%)', False),
    'pricing.fair_movers_pct': (175, 'int', 'pricing', 'Typical-fare estimate multiplier for moving service (%)', False),
    'pricing.fair_airport_pct': (110, 'int', 'pricing', 'Typical-fare estimate multiplier for airport service (%)', False),
    'pricing.fair_special_car_pct': (130, 'int', 'pricing', 'Typical-fare estimate multiplier for special / premium cars (%)', False),
    'rating.trend_drop': (0.3, 'float', 'ratings', 'Admin trend alert when a 7-day average falls by more than this', False),
    'analytics.max_events_per_min': (120, 'int', 'app', 'Client analytics events accepted per user/IP per minute', False),

    # ── Company / receipts (§13) [CONFIRM WITH CLIENT] ──────────────────────
    'company.legal_name': ('NegoRide Canada Inc.', 'string', 'company', 'Legal name on receipts', True),
    'company.address': ('Toronto, ON, Canada', 'string', 'company', 'Address on receipts', True),
    'company.gst_number': ('', 'string', 'company', 'GST/HST registration number', False),
    'company.qst_number': ('', 'string', 'company', 'QST registration number', False),
    'company.website': ('https://negoride.ca', 'string', 'company', 'Public website', True),
    'tax.default_province': ('ON', 'string', 'company', 'Province used for sales tax when the pickup province is unknown', False),
    'ff.driver_statements': (True, 'bool', 'flags', 'Weekly driver earnings statement email + PDF (§13.3)', False),

    # ── Trip / payments / notifications audit gaps (v4_0402) ───────────────
    'ff.live_activities': (True, 'bool', 'flags', 'Server-driven iOS Live Activity updates through OneSignal (§5.1)', True),
    'safety.settle_hold_h': (24, 'int', 'cancellation', 'Safety-ended rides: keep the payment hold this many hours for an admin decision, then release it', False),
    'carhire.counter_offer_ttl_s': (90, 'int', 'ride', 'A driver counter-offer on a broadcast request stays valid for (seconds)', True),
    'tip.within_h': (72, 'int', 'ratings', 'Riders can add a tip up to N hours after the ride ended', True),
    'tip.max_cents': (50000, 'int', 'ratings', 'Largest tip accepted', True),
    'receipts.sweep_after_s': (120, 'int', 'company', 'Receipt sweeper issues missing receipts for rides captured more than N s ago', False),
    'services.enabled': (['car_hire', 'rideshare', 'courier', 'movers', 'airport', 'special_car'], 'json', 'app',
                         'Service types offered (apps, onboarding). JSON list of car_hire, rideshare, courier, movers, airport, special_car', True),

    # ── App ──────────────────────────────────────────────────────────────────
    'search.region_codes': ('ca', 'string', 'app', 'Address autocomplete regions (comma-separated ISO codes, e.g. ca,us)', True),
    'app.min_supported_version': ('3.0.0', 'string', 'app', 'Older builds are asked to update', True),
    'app.latest_version': ('4.0.0', 'string', 'app', 'Latest store version', True),
    'app.legacy_clients_allowed': (True, 'bool', 'app', 'Allow pre-v4 builds (no X-App-Version header). Off = every client gets the v4 rules (consent ticks, phone-required sign-up, sensitive-action OTP, re-acceptance gate)', True),
}

_cache = {}
_cache_at = 0.0
_CACHE_TTL = 5.0
_lock = threading.Lock()


def _coerce(raw, typ):
    if raw is None:
        return None
    if typ == 'bool':
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
    if typ == 'int':
        return int(float(raw))
    if typ == 'float':
        return float(raw)
    if typ == 'json':
        return raw if not isinstance(raw, str) else json.loads(raw)
    return str(raw)


def _normalize_key(key):
    if key in DEFAULTS:
        return key
    if ('ff.' + key) in DEFAULTS:
        return 'ff.' + key
    return key


def _load():
    global _cache, _cache_at
    now = time.monotonic()
    if now - _cache_at < _CACHE_TTL and _cache:
        return _cache
    with _lock:
        try:
            rows = AppSetting.query.all()
            _cache = {r.key: r for r in rows}
            _cache = {k: (r.value, r.value_type) for k, r in _cache.items()}
        except Exception:
            db.session.rollback()
            _cache = _cache or {}
        _cache_at = now
    return _cache


def invalidate():
    global _cache_at
    _cache_at = 0.0


# Env vars that seed a setting's default (an admin override in app_settings still wins).
ENV_DEFAULTS = {
    'onboarding.bgc_fee_cents': 'BACKGROUND_CHECK_FEE_CENTS',
}


def _env_default(key, spec):
    import os
    env = ENV_DEFAULTS.get(key)
    raw = os.getenv(env, '').strip() if env else ''
    if raw:
        try:
            return _coerce(raw, spec[1])
        except (TypeError, ValueError):
            pass
    return spec[0]


def get(key, default=None):
    key = _normalize_key(key)
    spec = DEFAULTS.get(key)
    rows = _load()
    if key in rows:
        raw, typ = rows[key]
        try:
            return _coerce(raw, spec[1] if spec else typ)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if spec:
        return _env_default(key, spec)
    return default


def get_int(key, default=0):
    v = get(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_float(key, default=0.0):
    v = get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def flag(name):
    return bool(get(name if name.startswith('ff.') else 'ff.' + name, False))


def set_value(key, value, actor_id=None):
    """Upsert a setting. Returns (before, after)."""
    key = _normalize_key(key)
    spec = DEFAULTS.get(key)
    typ = spec[1] if spec else ('bool' if isinstance(value, bool) else 'string')
    coerced = _coerce(value, typ)  # validates
    pricing_limits = {
        'pricing.fair_base_cents': (0, 10000),
        'pricing.fair_per_km_cents': (0, 5000),
        'pricing.fair_per_min_cents': (0, 1000),
        'pricing.fair_spread_pct': (0, 50),
        'pricing.fair_car_pct': (50, 300),
        'pricing.fair_courier_pct': (50, 300),
        'pricing.fair_movers_pct': (50, 300),
        'pricing.fair_airport_pct': (50, 300),
        'pricing.fair_special_car_pct': (50, 300),
    }
    if key in pricing_limits:
        low, high = pricing_limits[key]
        if not low <= coerced <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
    before = get(key)
    row = AppSetting.query.filter_by(key=key).first()
    stored = json.dumps(coerced) if typ == 'json' else (
        ('true' if coerced else 'false') if typ == 'bool' else str(coerced))
    if not row:
        row = AppSetting(key=key, value_type=typ,
                         category=spec[2] if spec else 'custom',
                         description=spec[3] if spec else None,
                         is_public=bool(spec[4]) if spec else False)
        db.session.add(row)
    row.value = stored
    row.updated_by = actor_id
    db.session.flush()
    invalidate()
    return before, coerced


def all_settings(public_only=False):
    rows = _load()
    out = []
    keys = set(DEFAULTS) | set(rows)
    for key in sorted(keys):
        spec = DEFAULTS.get(key)
        public = bool(spec[4]) if spec else False
        if public_only and not public:
            continue
        out.append({
            'key': key,
            'value': get(key),
            'default': spec[0] if spec else None,
            'type': spec[1] if spec else rows[key][1],
            'category': spec[2] if spec else 'custom',
            'description': spec[3] if spec else None,
            'is_public': public,
            'overridden': key in rows,
        })
    return out


ALL_SERVICES = ('car_hire', 'rideshare', 'courier', 'movers', 'airport', 'special_car')


def enabled_services():
    """Service types currently offered (setting `services.enabled`), in
    canonical order, unknown values dropped. Use this instead of hard-coded
    lists (apps via /api/app/config → `services`, driver onboarding)."""
    val = get('services.enabled')
    if isinstance(val, str):
        val = [v.strip() for v in val.split(',')]
    wanted = {str(v).strip().lower() for v in (val or [])}
    out = [s for s in ALL_SERVICES if s in wanted]
    return out or list(ALL_SERVICES)


def public_config():
    return {s['key']: s['value'] for s in all_settings(public_only=True)}
