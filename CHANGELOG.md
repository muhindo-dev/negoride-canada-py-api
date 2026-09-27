# Changelog

## 4.0.0 — NegoRide Canada v4 (backend, admin, app 4.0.0+18, website)

Implements `NEGORIDE_CANADA_V4_UPGRADE_SPEC.md` (client items 1–18). Every feature is behind an `ff.*` flag.

### Riders
- Clear Uber-style trip steps with a live progress bar: driver on the way (live car + minutes), arriving, arrived
  (wait timer + Ride PIN + vehicle check), on trip, arrived, rate & tip, receipt.
- Pay before the trip: the fare is held on the card at confirmation and charged only when the trip ends.
- Fair, visible cancellation policy with the exact fee shown before cancelling; automatic refunds.
- Thank-you email with a perfect PDF receipt (tax by province, credit notes for refunds).
- Safety toolkit: red SOS button connected to the NegoRide safety team, 911 (hold to call), help contacts by
  province incl. 988, share live trip, trusted contacts, optional audio recording, "Are you OK?" route checks.
- Instant address search, fair-price hint, choose your driver, favourite drivers, rideshare seat booking
  (instant or request-to-book, seat price negotiation), two-way ratings with tags and tips.
- Notification inbox, notification preferences and quiet hours, English/French.
- Phone verification with Twilio Verify (SMS autofill, voice fallback), log in with phone.
- Terms, Privacy and Community Guidelines accepted with three explicit ticks; policy updates re-accepted in-app.

### Drivers
- One big contextual button: Head to pickup → I've arrived → Enter PIN & start → Complete trip.
- 7-step onboarding wizard with Certn background check (paid in-app), document expiry reminders.
- Demand heatmap, today's earnings, weekly earnings statements, reliability strikes explained.

### Operations (admin)
- Command Center, live operations map, Safety Center with SOS alarm, unified rides with timeline and refunds,
  user activation/suspension (instant session revocation), onboarding queue, finance & reconciliation,
  disputes/support, ratings explorer, notification log & broadcasts, legal editor, settings & feature flags,
  analytics, admin roles, audit log. API docs at `/api/docs`.

### Platform
- Trip state machine + `trip_events` timeline; Socket.IO realtime (`/rt`); RQ + Redis jobs and scheduler;
  webhook inbox with retries; idempotency keys; audit log; integer-cents money; UTC everywhere.
- Additive migrations `v4_*` only; v3.0.x apps keep working against the new backend.

### Security fixes found during the upgrade
- Scheduled bookings: any user could cancel/price/accept any booking — now party-restricted.
- Rideshare: any user could mark any seat booking Reserved/Completed or change its price; anyone could publish trips.
- Legacy admin status toggle / delete now revoke sessions and are audited; only super admins can grant admin rights.
- Rideshare seat race condition (overbooking under REPEATABLE READ) fixed with locking reads.
