# Notification engine (spec §5)

Code: `backend/services/notify/` — `notify(event_key, user_ids, context)` (queued after commit) →
`dispatcher.notify_now` (job) → inbox row (`notifications`) + one `notification_deliveries` row per channel →
`channels.py` (OneSignal push, Twilio SMS, email provider, Socket.IO). Every notification lands in the inbox.

* **Preferences**: `GET|PUT /api/notification-preferences`. Groups negotiation, rideshare, ratings, onboarding, payouts, marketing can be muted per channel
  and respect quiet hours; safety, ride, payment, account, legal are always delivered.
* **Retries**: failed sends retry with backoff 20 s / 90 s (3 attempts), then `failed` with the provider error.
* **Escalation**: critical events with SMS fallback send an SMS if the push is not opened within 60 s
  (the app acks via socket `notification:ack` or `POST /api/notifications/{id}/opened`). Users who replied STOP are never texted.
* **Languages**: EN/FR copy per event, chosen from `users.preferred_language`.
* **Push**: OneSignal `include_aliases.external_id = user id`, `existing_android_channel_id` (ride_critical, ride_updates,
  negotiation, payments, marketing), `ios_interruption_level=time_sensitive` for critical, custom sounds `driver_arrived.wav`, `new_request.wav`,
  `data = {notification_id, event, route, ride_type, ride_id, deep_link}`.
* **Realtime**: Socket.IO namespace `/rt`, JWT in `auth.token`; rooms `user:{id}`, `ride:{type}:{id}`, `admin:ops`, `admin:sos`.
  Events: `notification`, `ride.stage_changed`, `ride.driver_location`, `ride.eta_updated`, `negotiation.updated`,
  `carhire.request_*`, `recording.status`, `safety.check`, admin: `driver.location`, `safety.sos`, `safety.sos_updated`, `alert`.
  The same ride event can arrive through the user room and the ride room — clients dedupe on `event_id`.
* **Admin**: `GET /api/admin/notifications` (delivery log per channel), `/stats`, `POST /broadcast` (segmented, dry-run).

## Catalogue

| Event | Group | Channels | Critical | Deep-link route | English copy |
|---|---|---|---|---|---|
| `negotiation.new_request` | negotiation | push, socket, inbox |  | negotiation | New ride request{% if distance_km %} {{ distance_km }} km away{% endif %} — offer {{ price }} |
| `negotiation.counter_offer` | negotiation | push, socket, inbox |  | negotiation | {{ from_name }} countered: {{ price }} |
| `negotiation.agreed` | ride (mandatory) | push, socket, inbox |  | ride | Price agreed: {{ price }}.{% if is_customer %} Complete payment to confirm.{% endif %} |
| `payment.authorized` | payment (mandatory) | push, socket, inbox |  | ride | {% if is_customer %}Ride confirmed. {{ driver_first }} is getting ready to head to you.{% else %}Payment secur |
| `payment.failed` | payment (mandatory) | push, socket, inbox |  | ride | Payment failed — update your card to keep this ride. |
| `refund.issued` | payment (mandatory) | push, inbox, email |  | receipt | Refund of {{ amount }} on its way{% if released %} — your hold was released{% else %} (5–10 business days){% e |
| `ride.receipt` | payment (mandatory) | inbox, email |  | receipt | Thanks for riding with NegoRide. Total charged {{ total }}. |
| `refund.credit_note` | payment (mandatory) | inbox, email |  | receipt | We refunded {{ amount }} for ride #{{ ride_id }}. |
| `driver.statement` | payouts | inbox, email |  | wallet | Week of {{ period }}: net earnings {{ net }}. |
| `payout.sent` | payouts | push, inbox |  | wallet | {{ amount }} is on its way to your bank. |
| `ride.driver_en_route` | ride (mandatory) | push, socket, inbox |  | ride | {{ driver_first }} is on the way{% if eta_min %} · {{ eta_min }} min{% endif %}{% if vehicle %} · {{ vehicle } |
| `ride.driver_arriving` | ride (mandatory) | push, socket | yes | ride | Your driver is {{ eta_min or 1 }} min away — get ready. |
| `ride.driver_arrived` | ride (mandatory) | push, socket, inbox | yes + SMS fallback | ride | Your driver has arrived.{% if pin %} PIN: {{ pin }}.{% endif %}{% if wait_until %} Waiting until {{ wait_until |
| `ride.wait_warning` | ride (mandatory) | push, socket | yes | ride | {{ minutes_left or 2 }} minutes left before a no-show fee applies. |
| `ride.started` | ride (mandatory) | push, socket, inbox |  | ride | Trip started — you can share your live location with a trusted contact. |
| `ride.completed` | ride (mandatory) | push, socket, inbox |  | rate | {% if is_customer %}You've arrived. Rate your trip with {{ driver_first }}.{% else %}Trip complete. {{ earning |
| `ride.cancelled` | ride (mandatory) | push, socket, inbox, sms | yes | ride | Your ride was cancelled by the {{ cancelled_by }}.{% if refund_text %} {{ refund_text }}{% endif %} |
| `ride.customer_no_show` | ride (mandatory) | push, socket, inbox |  | ride | Your driver waited the full window. A no-show fee of {{ fee }} applies. |
| `ride.driver_no_show` | ride (mandatory) | push, socket, inbox, sms | yes | home | You won't be charged{% if credit %} and we added a {{ credit }} ride credit{% endif %}. Request again? |
| `ride.expired` | ride (mandatory) | push, socket, inbox |  | home | {{ reason or "The request expired before it was confirmed." }} Nothing was charged. |
| `ride.eta_updated` | ride (mandatory) | socket |  | ride |  |
| `rating.reminder` | ratings | push, inbox |  | rate | How was your trip with {{ other_first }}? |
| `rideshare.booking_requested` | rideshare | push, socket, inbox |  | rideshare_trip | {{ customer_first }} wants {{ seats }} seat(s) on {{ route }}. Approve within {{ minutes }} min. |
| `rideshare.booking_approved` | rideshare | push, socket, inbox |  | rideshare_booking | Your seat on {{ route }} was approved — pay to confirm. |
| `rideshare.booking_declined` | rideshare | push, socket, inbox |  | search | Your request for {{ route }} was not accepted. Nothing was charged. |
| `rideshare.booking_confirmed` | rideshare | push, socket, inbox, email |  | rideshare_booking | Seat booked: {{ route }}, {{ departure }} |
| `rideshare.departure_reminder` | rideshare | push, sms, inbox |  | rideshare_booking | Your ride leaves in {{ minutes }} min from {{ pickup }}. |
| `rideshare.boarding` | rideshare | push, socket, inbox |  | rideshare_booking | Boarding for {{ route }} has started. Show your PIN to the driver. |
| `safety.sos_triggered` | safety (mandatory) | socket, push, sms, email, inbox | yes | safety_incident | EMERGENCY: {{ name }} triggered SOS. Live location: {{ link }} |
| `safety.route_deviation` | safety (mandatory) | push, socket, inbox | yes | safety_check | Your trip changed route. Are you OK? |
| `safety.long_stop` | safety (mandatory) | push, socket, inbox | yes | safety_check | Your car has been stopped for a while. Are you OK? |
| `safety.sos_escalated` | safety (mandatory) | socket, push, sms, inbox | yes | safety_incident | SOS #{{ incident_id }} from {{ name }} has not been acknowledged. Open the Safety Center now. |
| `safety.check_unanswered` | safety (mandatory) | socket, push, inbox | yes | safety_incident | {{ name }} did not answer an "Are you OK?" check ({{ kind }}). Incident #{{ incident_id }}. |
| `safety.trip_shared` | safety (mandatory) | sms |  |  | {{ name }} is sharing a NegoRide trip with you: {{ link }} |
| `onboarding.step_required` | onboarding | push, email, inbox |  | driver_onboarding | Next: {{ step }} |
| `onboarding.approved` | account (mandatory) | push, email, inbox |  | driver_onboarding | Welcome to NegoRide! Complete the safety orientation and go online. |
| `onboarding.needs_changes` | account (mandatory) | push, email, inbox |  | driver_onboarding | {{ reason }} |
| `onboarding.rejected` | account (mandatory) | push, email, inbox |  | driver_onboarding | {{ reason }} |
| `background_check.completed` | account (mandatory) | push, email, inbox |  | driver_onboarding | {{ summary }} |
| `document.expiring` | account (mandatory) | push, email, inbox |  | driver_onboarding | Your {{ document }} expires in {{ days }} days. Upload a new one to keep driving. |
| `document.expired` | account (mandatory) | push, email, sms, inbox |  | driver_onboarding | Your {{ document }} has expired. You cannot go online until you upload a valid one. |
| `account.deactivated` | account (mandatory) | push, email, sms, inbox |  | account_status | Your account is {{ status }}.{% if until %} Until {{ until }}.{% endif %} {{ reason }} |
| `account.reactivated` | account (mandatory) | push, email, sms, inbox |  | home | Welcome back — your NegoRide account has been reactivated. |
| `account.warning` | account (mandatory) | push, email, inbox |  | account_status | {{ message }} |
| `account.phone_changed` | account (mandatory) | sms |  |  | Your NegoRide phone number was changed. If this wasn't you, contact support immediately. |
| `legal.policy_updated` | legal (mandatory) | push, email, inbox |  | legal | We updated our {{ document }}. Please review. |
| `support.reply` | account (mandatory) | push, inbox |  | support_ticket | {{ subject }} |
| `broadcast` | marketing | push, inbox |  | {{ route }} | {{ body }} |
