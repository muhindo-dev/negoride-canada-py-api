"""Notification catalogue (spec §5.3).

Each event declares its preference group, channels, criticality, deep-link
route, Android channel and bilingual (EN/FR) copy. Copy is rendered with Jinja2
against the context passed to `notify()`; missing variables render empty.

Groups in MANDATORY_GROUPS (safety, transactional) cannot be muted (§5.5).
"""

MANDATORY_GROUPS = ('safety', 'ride', 'payment', 'account', 'legal')
MUTABLE_GROUPS = ('negotiation', 'rideshare', 'ratings', 'onboarding', 'payouts', 'marketing')
ALL_GROUPS = MANDATORY_GROUPS + MUTABLE_GROUPS

# Android channels created by the app (flutter_local_notifications, §5.4).
ANDROID_CHANNELS = ('ride_critical', 'ride_updates', 'negotiation', 'payments', 'marketing')


def E(group, channels, title_en, body_en, title_fr, body_fr, route=None, critical=False,
      sms_fallback=False, android='ride_updates', email_template=None, sound=None):
    return {
        'group': group, 'channels': tuple(channels), 'critical': critical, 'sms_fallback': sms_fallback,
        'route': route, 'android_channel': android, 'email_template': email_template, 'sound': sound,
        'title': {'en': title_en, 'fr': title_fr}, 'body': {'en': body_en, 'fr': body_fr},
    }


CATALOGUE = {
    # ── negotiation ──────────────────────────────────────────────────────────
    'negotiation.new_request': E(
        'negotiation', ('push', 'socket', 'inbox'),
        'New ride request', 'New ride request{% if distance_km %} {{ distance_km }} km away{% endif %} — offer {{ price }}',
        'Nouvelle demande de course', 'Nouvelle demande{% if distance_km %} à {{ distance_km }} km{% endif %} — offre {{ price }}',
        route='negotiation', android='negotiation', sound='new_request'),
    'negotiation.counter_offer': E(
        'negotiation', ('push', 'socket', 'inbox'),
        'New offer', '{{ from_name }} countered: {{ price }}',
        'Nouvelle offre', '{{ from_name }} propose : {{ price }}',
        route='negotiation', android='negotiation'),
    'negotiation.agreed': E(
        'ride', ('push', 'socket', 'inbox'),
        'Price agreed', 'Price agreed: {{ price }}.{% if is_customer %} Complete payment to confirm.{% endif %}',
        'Prix convenu', 'Prix convenu : {{ price }}.{% if is_customer %} Payez pour confirmer.{% endif %}',
        route='ride', android='ride_updates'),
    # ── payment ──────────────────────────────────────────────────────────────
    'payment.authorized': E(
        'payment', ('push', 'socket', 'inbox'),
        'Ride confirmed', '{% if is_customer %}Ride confirmed. {{ driver_first }} is getting ready to head to you.'
                          '{% else %}Payment secured — you can head to {{ customer_first }} now.{% endif %}',
        'Course confirmée', '{% if is_customer %}Course confirmée. {{ driver_first }} se prépare à venir vous chercher.'
                            '{% else %}Paiement sécurisé — vous pouvez aller chercher {{ customer_first }}.{% endif %}',
        route='ride', android='payments'),
    'payment.failed': E(
        'payment', ('push', 'socket', 'inbox'),
        'Payment failed', 'Payment failed — update your card to keep this ride.',
        'Paiement refusé', 'Paiement refusé — mettez à jour votre carte pour garder cette course.',
        route='ride', android='payments'),
    'refund.issued': E(
        'payment', ('push', 'inbox', 'email'),
        'Refund issued', 'Refund of {{ amount }} on its way{% if released %} — your hold was released{% else %} (5–10 business days){% endif %}.',
        'Remboursement émis', 'Remboursement de {{ amount }} en route{% if released %} — la préautorisation est levée{% else %} (5 à 10 jours ouvrables){% endif %}.',
        route='receipt', android='payments', email_template='refund_issued'),
    # Sent by services/receipts.py itself (PDF attached); logged here so the
    # admin notification log shows it. Do not call notify() with these keys.
    'ride.receipt': E(
        'payment', ('inbox', 'email'),
        'Your receipt {{ number }}', 'Thanks for riding with NegoRide. Total charged {{ total }}.',
        'Votre reçu {{ number }}', 'Merci d’avoir roulé avec NegoRide. Total facturé {{ total }}.',
        route='receipt', android='payments'),
    'refund.credit_note': E(
        'payment', ('inbox', 'email'),
        'Credit note {{ number }}', 'We refunded {{ amount }} for ride #{{ ride_id }}.',
        'Note de crédit {{ number }}', 'Nous avons remboursé {{ amount }} pour la course no {{ ride_id }}.',
        route='receipt', android='payments'),
    'driver.statement': E(
        'payouts', ('inbox', 'email'),
        'Your weekly statement', 'Week of {{ period }}: net earnings {{ net }}.',
        'Votre relevé hebdomadaire', 'Semaine du {{ period }} : gains nets {{ net }}.',
        route='wallet', android='payments'),
    'payout.sent': E(
        'payouts', ('push', 'inbox'),
        'Payout sent', '{{ amount }} is on its way to your bank.',
        'Virement envoyé', '{{ amount }} est en route vers votre banque.',
        route='wallet', android='payments'),
    # ── ride lifecycle ───────────────────────────────────────────────────────
    'ride.driver_en_route': E(
        'ride', ('push', 'socket', 'inbox'),
        '{{ driver_first }} is on the way', '{{ driver_first }} is on the way{% if eta_min %} · {{ eta_min }} min{% endif %}{% if vehicle %} · {{ vehicle }}{% endif %}',
        '{{ driver_first }} est en route', '{{ driver_first }} est en route{% if eta_min %} · {{ eta_min }} min{% endif %}{% if vehicle %} · {{ vehicle }}{% endif %}',
        route='ride', android='ride_updates'),
    'ride.driver_arriving': E(
        'ride', ('push', 'socket'),
        'Your driver is almost there', 'Your driver is {{ eta_min or 1 }} min away — get ready.',
        'Votre chauffeur arrive', 'Votre chauffeur est à {{ eta_min or 1 }} min — préparez-vous.',
        route='ride', critical=True, android='ride_critical'),
    'ride.driver_arrived': E(
        'ride', ('push', 'socket', 'inbox'),
        'Your driver has arrived', 'Your driver has arrived.{% if pin %} PIN: {{ pin }}.{% endif %}{% if wait_until %} Waiting until {{ wait_until }}.{% endif %}{% if vehicle %} {{ vehicle }}{% endif %}',
        'Votre chauffeur est arrivé', 'Votre chauffeur est arrivé.{% if pin %} NIP : {{ pin }}.{% endif %}{% if wait_until %} Attente jusqu’à {{ wait_until }}.{% endif %}{% if vehicle %} {{ vehicle }}{% endif %}',
        route='ride', critical=True, sms_fallback=True, android='ride_critical', sound='driver_arrived'),
    'ride.wait_warning': E(
        'ride', ('push', 'socket'),
        'Your driver is waiting', '{{ minutes_left or 2 }} minutes left before a no-show fee applies.',
        'Votre chauffeur attend', 'Il reste {{ minutes_left or 2 }} minutes avant des frais d’absence.',
        route='ride', critical=True, android='ride_critical'),
    'ride.started': E(
        'ride', ('push', 'socket', 'inbox'),
        'Trip started', 'Trip started — you can share your live location with a trusted contact.',
        'Trajet commencé', 'Trajet commencé — partagez votre position en direct avec un proche.',
        route='ride', android='ride_updates'),
    'ride.completed': E(
        'ride', ('push', 'socket', 'inbox'),
        "You've arrived", "{% if is_customer %}You've arrived. Rate your trip with {{ driver_first }}.{% else %}Trip complete. {{ earning }} added to your earnings.{% endif %}",
        'Vous êtes arrivé', "{% if is_customer %}Vous êtes arrivé. Évaluez votre trajet avec {{ driver_first }}.{% else %}Trajet terminé. {{ earning }} ajoutés à vos gains.{% endif %}",
        route='rate', android='ride_updates'),
    'ride.cancelled': E(
        'ride', ('push', 'socket', 'inbox', 'sms'),
        'Ride cancelled', 'Your ride was cancelled by the {{ cancelled_by }}.{% if refund_text %} {{ refund_text }}{% endif %}',
        'Course annulée', 'Votre course a été annulée par le {{ cancelled_by_fr }}.{% if refund_text %} {{ refund_text }}{% endif %}',
        route='ride', critical=True, android='ride_critical'),
    'ride.customer_no_show': E(
        'ride', ('push', 'socket', 'inbox'),
        'Marked as no-show', 'Your driver waited the full window. A no-show fee of {{ fee }} applies.',
        'Absence constatée', 'Votre chauffeur a attendu toute la période. Des frais de {{ fee }} s’appliquent.',
        route='ride', android='ride_updates'),
    'ride.driver_no_show': E(
        'ride', ('push', 'socket', 'inbox', 'sms'),
        "Sorry — your driver didn't show", "You won't be charged{% if credit %} and we added a {{ credit }} ride credit{% endif %}. Request again?",
        'Désolé — chauffeur absent', "Vous ne serez pas facturé{% if credit %} et nous avons ajouté un crédit de {{ credit }}{% endif %}. Redemander ?",
        route='home', critical=True, android='ride_critical'),
    'ride.expired': E(
        'ride', ('push', 'socket', 'inbox'),
        'Ride request expired', '{{ reason or "The request expired before it was confirmed." }} Nothing was charged.',
        'Demande expirée', 'La demande a expiré avant confirmation. Aucun frais.',
        route='home', android='ride_updates'),
    'ride.eta_updated': E(
        'ride', ('socket',), '', '', '', '', route='ride'),
    'rating.reminder': E(
        'ratings', ('push', 'inbox'),
        'How was your trip?', 'How was your trip with {{ other_first }}?',
        'Comment était votre trajet ?', 'Comment s’est passé votre trajet avec {{ other_first }} ?',
        route='rate', android='ride_updates'),
    # ── rideshare ────────────────────────────────────────────────────────────
    'rideshare.booking_requested': E(
        'rideshare', ('push', 'socket', 'inbox'),
        'New seat request', '{{ customer_first }} wants {{ seats }} seat(s) on {{ route }}. Approve within {{ minutes }} min.',
        'Nouvelle demande de place', '{{ customer_first }} veut {{ seats }} place(s) pour {{ route }}. Répondez sous {{ minutes }} min.',
        route='rideshare_trip', android='ride_updates'),
    'rideshare.booking_approved': E(
        'rideshare', ('push', 'socket', 'inbox'),
        'Seat request approved', 'Your seat on {{ route }} was approved — pay to confirm.',
        'Demande acceptée', 'Votre place pour {{ route }} est acceptée — payez pour confirmer.',
        route='rideshare_booking', android='ride_updates'),
    'rideshare.booking_declined': E(
        'rideshare', ('push', 'socket', 'inbox'),
        'Seat request declined', 'Your request for {{ route }} was not accepted. Nothing was charged.',
        'Demande refusée', 'Votre demande pour {{ route }} n’a pas été acceptée. Aucun frais.',
        route='search', android='ride_updates'),
    'rideshare.booking_confirmed': E(
        'rideshare', ('push', 'socket', 'inbox', 'email'),
        'Seat booked', 'Seat booked: {{ route }}, {{ departure }}',
        'Place réservée', 'Place réservée : {{ route }}, {{ departure }}',
        route='rideshare_booking', android='ride_updates', email_template='generic'),
    'rideshare.departure_reminder': E(
        'rideshare', ('push', 'sms', 'inbox'),
        'Departure soon', 'Your ride leaves in {{ minutes }} min from {{ pickup }}.',
        'Départ bientôt', 'Votre trajet part dans {{ minutes }} min de {{ pickup }}.',
        route='rideshare_booking', android='ride_updates'),
    'rideshare.boarding': E(
        'rideshare', ('push', 'socket', 'inbox'),
        'Boarding has started', 'Boarding for {{ route }} has started. Show your PIN to the driver.',
        'Embarquement', 'L’embarquement pour {{ route }} a commencé. Montrez votre NIP au chauffeur.',
        route='rideshare_booking', android='ride_updates'),
    # ── safety ───────────────────────────────────────────────────────────────
    'safety.sos_triggered': E(
        'safety', ('socket', 'push', 'sms', 'email', 'inbox'),
        'EMERGENCY: SOS triggered', 'EMERGENCY: {{ name }} triggered SOS. Live location: {{ link }}',
        'URGENCE : SOS déclenché', 'URGENCE : {{ name }} a déclenché un SOS. Position en direct : {{ link }}',
        route='safety_incident', critical=True, android='ride_critical', sound='driver_arrived',
        email_template='generic'),
    'safety.route_deviation': E(
        'safety', ('push', 'socket', 'inbox'),
        'Are you OK?', 'Your trip changed route. Are you OK?',
        'Tout va bien ?', 'Votre trajet a changé d’itinéraire. Tout va bien ?',
        route='safety_check', critical=True, android='ride_critical'),
    'safety.long_stop': E(
        'safety', ('push', 'socket', 'inbox'),
        'Are you OK?', 'Your car has been stopped for a while. Are you OK?',
        'Tout va bien ?', 'Votre voiture est arrêtée depuis un moment. Tout va bien ?',
        route='safety_check', critical=True, android='ride_critical'),
    'safety.sos_escalated': E(
        'safety', ('socket', 'push', 'sms', 'inbox'),
        'SOS NOT ACKNOWLEDGED', 'SOS #{{ incident_id }} from {{ name }} has not been acknowledged. Open the Safety Center now.',
        'SOS NON PRIS EN CHARGE', 'Le SOS n° {{ incident_id }} de {{ name }} n’a pas été pris en charge. Ouvrez le centre de sécurité.',
        route='safety_incident', critical=True, android='ride_critical', sound='driver_arrived'),
    'safety.check_unanswered': E(
        'safety', ('socket', 'push', 'inbox'),
        'Safety check unanswered', '{{ name }} did not answer an "Are you OK?" check ({{ kind }}). Incident #{{ incident_id }}.',
        'Vérification sans réponse', '{{ name }} n’a pas répondu à « Tout va bien ? » ({{ kind }}). Incident n° {{ incident_id }}.',
        route='safety_incident', critical=True, android='ride_critical'),
    'safety.trip_shared': E(
        'safety', ('sms',),
        '', '{{ name }} is sharing a NegoRide trip with you: {{ link }}',
        '', '{{ name }} partage un trajet NegoRide avec vous : {{ link }}'),
    # ── onboarding / account ─────────────────────────────────────────────────
    'onboarding.step_required': E(
        'onboarding', ('push', 'email', 'inbox'),
        'Next step', 'Next: {{ step }}',
        'Prochaine étape', 'Prochaine étape : {{ step }}',
        route='driver_onboarding', email_template='generic'),
    'onboarding.approved': E(
        'account', ('push', 'email', 'inbox'),
        "You're approved to drive", 'Welcome to NegoRide! Complete the safety orientation and go online.',
        'Vous êtes approuvé', 'Bienvenue chez NegoRide ! Terminez l’orientation sécurité et passez en ligne.',
        route='driver_onboarding', email_template='generic'),
    'onboarding.needs_changes': E(
        'account', ('push', 'email', 'inbox'),
        'Action needed on your application', '{{ reason }}',
        'Action requise', '{{ reason }}',
        route='driver_onboarding', email_template='generic'),
    'onboarding.rejected': E(
        'account', ('push', 'email', 'inbox'),
        'Update on your driver application', '{{ reason }}',
        'Mise à jour de votre candidature', '{{ reason }}',
        route='driver_onboarding', email_template='generic'),
    'background_check.completed': E(
        'account', ('push', 'email', 'inbox'),
        'Your background check is complete', '{{ summary }}',
        'Vérification des antécédents terminée', '{{ summary }}',
        route='driver_onboarding', email_template='generic'),
    'document.expiring': E(
        'account', ('push', 'email', 'inbox'),
        'Document expiring soon', 'Your {{ document }} expires in {{ days }} days. Upload a new one to keep driving.',
        'Document bientôt expiré', 'Votre {{ document }} expire dans {{ days }} jours. Téléversez-en un nouveau.',
        route='driver_onboarding', email_template='generic'),
    'document.expired': E(
        'account', ('push', 'email', 'sms', 'inbox'),
        'Document expired', 'Your {{ document }} has expired. You cannot go online until you upload a valid one.',
        'Document expiré', 'Votre {{ document }} est expiré. Vous ne pouvez pas passer en ligne.',
        route='driver_onboarding', email_template='generic'),
    'account.deactivated': E(
        'account', ('push', 'email', 'sms', 'inbox'),
        'Your account status changed', 'Your account is {{ status }}.{% if until %} Until {{ until }}.{% endif %} {{ reason }}',
        'Statut du compte modifié', 'Votre compte est {{ status_fr }}.{% if until %} Jusqu’au {{ until }}.{% endif %} {{ reason }}',
        route='account_status', email_template='generic'),
    'account.reactivated': E(
        'account', ('push', 'email', 'sms', 'inbox'),
        'Your account is active again', 'Welcome back — your NegoRide account has been reactivated.',
        'Votre compte est réactivé', 'Bon retour — votre compte NegoRide est réactivé.',
        route='home', email_template='generic'),
    'account.warning': E(
        'account', ('push', 'email', 'inbox'),
        'Important notice about your account', '{{ message }}',
        'Avis important concernant votre compte', '{{ message }}',
        route='account_status', email_template='generic'),
    'account.phone_changed': E(
        'account', ('sms',),
        '', 'Your NegoRide phone number was changed. If this wasn\'t you, contact support immediately.',
        '', 'Votre numéro NegoRide a été modifié. Si ce n’est pas vous, contactez le soutien.'),
    'legal.policy_updated': E(
        'legal', ('push', 'email', 'inbox'),
        'We updated our {{ document }}', 'We updated our {{ document }}. Please review.',
        'Mise à jour : {{ document }}', 'Nous avons mis à jour nos {{ document }}. Veuillez les consulter.',
        route='legal', email_template='generic'),
    'support.reply': E(
        'account', ('push', 'inbox'),
        'Support replied', '{{ subject }}',
        'Réponse du soutien', '{{ subject }}',
        route='support_ticket'),
    'broadcast': E(
        'marketing', ('push', 'inbox'),
        '{{ title }}', '{{ body }}', '{{ title }}', '{{ body }}',
        route='{{ route }}', android='marketing'),
}


def get(event_key):
    spec = CATALOGUE.get(event_key)
    if spec is None:
        raise KeyError(f'Unknown notification event {event_key}')
    return spec
