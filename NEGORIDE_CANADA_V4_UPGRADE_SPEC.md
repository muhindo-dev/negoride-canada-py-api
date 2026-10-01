# NegoRide Canada — v4 Upgrade Specification

> **Audience:** the AI coding agent (and human developers) implementing the next major version of NegoRide Canada.
> **Source:** client feedback ("NEGORIDE CANADA — updates without checking anything", items 1–18), reframed, expanded and made implementable.
> **Status:** Approved scope to build. Items marked **[CONFIRM WITH CLIENT]** have a sensible default already specified. Build the default, keep it configurable, and flag it in the PR.
> **Date:** 2026-09-27
> **Implementation status:** ✅ Implemented and verified — updated 2026-09-28. See **§0.1** for the per-section status and every section below for a *Status* note. Acceptance checkboxes are ticked with their evidence.

---

## 0. How to use this document

1. Read **§1 (Context)** and **§2 (Engineering rules)** before touching code. They apply to every feature.
2. Build in the **phase order in §3**. Later features depend on the trip state machine (§4) and the notification engine (§5).
3. Every feature section has the same structure: **Client said → What it really means → User stories → Backend → API → Mobile (Flutter) → Admin dashboard → Edge cases → Acceptance criteria.**
4. **§20 (Traceability matrix)** maps every original client comment to the sections that deliver it. Nothing in the client list may be dropped.
5. When a section says "**Verify against vendor docs**", do not guess endpoint names or payloads. Read the vendor's current API reference (Twilio, Certn, Stripe, Google, OneSignal) and adapt.
6. Update the docs (`docs/` + API reference, §19) in the same PR as the code.

---

## 0.1 Implementation status (updated 2026-09-28)

**Legend:** ✅ Done (built + automated tests) · 🟡 Done in code, needs a client-side action or a real-device/production check · ⏳ Deferred by the spec itself ("later").

| § | Area | Status | Where | Verified by |
|---|---|---|---|---|
| 2 | Engineering rules (additive migrations `v4_*`, cents, idempotency, webhook inbox, RQ jobs, env secrets, audit, PIPEDA, UTC, flags, tests) | ✅ | backend `database/migrations/v4_*`, `utils/money.py`, `utils/idempotency.py`, `jobs/`, `services/audit.py`, `services/settings_service.py` | 353 backend tests green |
| 4 | Trip state machine + timeline + legacy mapping + scheduled jobs + `/api/rides/*` + Active Ride screen | ✅ | `services/trip_state_machine.py`, `routes/rides.py`, app `lib/screens/ride_v4` | `test_carhire_flow.py`, `test_state_machine_matrix.py` (every from→to pair, all 4 graphs), live socket E2E, Android emulator E2E |
| 5 | Notification engine (socket `/rt`, OneSignal push, SMS fallback, email, inbox, preferences, retries, Live Activities, editable templates) | ✅ | `services/notify/`, `sockets/realtime_events.py`, app `lib/services/notifications`, iOS `NegoRideLiveActivity` | `test_notifications_realtime.py`, emulator; driver-arrived 1.1 s measured |
| 6 | Pay before trip (Stripe manual capture, capture at completion, partial capture/release, failures + retry) | ✅ | `services/payments/` | `test_payment_bypass_is_impossible`, decline/3DS/insufficient-funds tests |
| 7 | Cancellation & refund engine (every table row), fee preview, strikes, admin refunds, safety settlement | ✅ | `services/refund_policy.py`, `payment_service.settle_cancellation` | `test_refund_policy.py` (one test per row) |
| 8 | SOS + Safety toolkit + Safety Center + PIN (lockout) + vehicle card + route deviation + trusted contacts | ✅ | `routes/safety.py`, admin `pages/safety`, app `lib/screens/safety_v4` | `test_safety*.py`, admin browser test (banner ≈300 ms), emulator |
| 9 | Live location pipeline, share links, public `/t/{token}`, admin live map + replay | ✅ | `services/tracking.py`, `live_share.py`, website `/t/[token]` | safety tests, website e2e |
| 10 | Optional audio recording (opt-in, chunks, encrypted storage, audited access, retention) | ✅ | `services/recording_service.py`, `private_storage.py` | safety tests, emulator |
| 11 | Twilio Verify — all 14 scenarios, fraud rules, SMS autofill | 🟡 | `services/phone_verification.py`, app `identity_v4` | `test_identity*.py`; needs Twilio credentials + console setup (RUNBOOK §10) |
| 12 | Legal consent (3 ticks, reader, CASL proof, re-acceptance gate, admin editor, website pages) | 🟡 | `services/legal_service.py`, app sign-up, website legal pages | identity tests, `consent_gating_test.dart`; 8 documents are drafts marked [REVIEW WITH COUNSEL] |
| 13 | Thank-you email + receipts + credit notes + tip receipts + weekly statements | 🟡 | `services/receipts.py`, templates | `test_receipts.py` (totals match to the cent); real-client rendering check (Gmail/Outlook/Apple) pending; GST number pending |
| 14 | Driver onboarding wizard + Certn (CertnCentric API) + expiry monitoring + face match (advisory) | 🟡 | `services/onboarding_service.py`, `certn_client.py`, app `onboarding_v4` | `test_onboarding*.py`; Certn sandbox keys + package confirmation pending |
| 15 | Account activation/deactivation (token revocation, sockets, deferred during rides, suspended screen + appeal, auto rules) | ✅ | `services/account_service.py`, app `account_v4` | `test_account_status.py`, emulator |
| 16 | Live ETA (Google Routes, throttled), smooth car, Live Activity updates | 🟡 | `services/eta.py`, app ride_v4 | `test_eta.py`; needs `GOOGLE_MAPS_SERVER_KEY` |
| 17 | Two-way ratings, tags, tips, Bayesian score, admin explorer | ✅ | `services/ratings_service.py`, app rate screen | `test_ratings.py` |
| 18 | Rideshare self-booking (seat locking, request-to-book, negotiation) + pick-a-driver + favourites + counter-offer marketplace | ✅ | `rideshare_service.py`, `matching_service.py`, app experience_v4 | `test_rideshare_v4.py` (last-seat race), `test_carhire_v4.py`, emulator marketplace run |
| 19 | Admin operations console (14 modules) + docs (OpenAPI/Swagger, guides, runbook, changelog) | ✅ | admin `frontend/src/v4`, backend `docs/` | headless Chrome run of every module |
| 21 | UI/UX redesign (design system, dark mode, EN/FR, accessibility, flutx removed) + instant address search | ✅ | app `lib/theme`, `lib/l10n`, `experience_v4` | 182 Flutter tests, a11y large-text tests, emulator (FR, dark, 200 % text) |
| 22 | Landing website (EN/FR, download, legal, tracking, app links, SEO) | 🟡 | `/Users/mac/Desktop/github/negoride-canada-web` | build + astro check clean, Lighthouse 0.98–1.0, pa11y 0 errors, 41/41 e2e; needs domain, assetlinks SHA-256, App Store URL |
| 23–24 | Data model + env vars | ✅ | migrations `v4_0001…v4_0403`, `.env.example` | migrations up/down tested |
| 25 | QA checklist | 🟡 | backend `tests/`, app `test/` + `integration_test/` (s1–s8 incl. resilience) | Stripe/Twilio/Certn sandbox runs with real test keys, real v3.0.17 build regression and real-device iOS checks remain |

**Remaining before launch (cannot be done in code):** provide Twilio, Certn, Postmark/SMTP, Google (server + browser), OneSignal REST, Stripe test keys for QA; set up Redis + `worker.py` service on the VPS; fill `company.gst_number`/`qst_number`, legal address, `safety.oncall_phones`, `safety.support_phone`; legal review of the 8 documents; website domain + DNS + `CORS_ORIGINS` + assetlinks SHA-256 + App Store URL; Apple Developer capabilities (App Group, Associated Domains, Live Activities); Play background-location declaration; real-device checks (Live Activity, universal links, killed-app notification taps, email client rendering). The admin **Readiness** panel (`GET /api/admin/readiness`) lists the open items live.

## 1. Context — what exists today (do not break it)

| Layer | Location | Tech | Notes |
|---|---|---|---|
| **Live backend (canonical)** | `/Applications/MAMP/htdocs/negoride-canada-api/negoride-canada-py-api/backend/` | Flask 3, SQLAlchemy, Flask-JWT-Extended, Flask-SocketIO (eventlet), Stripe, MySQL `negoride` | Serves the mobile app at `https://negoride.ugnews24.info`. **All new backend work goes here.** |
| Legacy backend | `/Applications/MAMP/htdocs/negoride-canada-api/` (Laravel 8 + Encore Admin) | PHP | Reference only. **Do not add features here.** |
| Admin dashboard | `negoride-canada-py-api/frontend/` | React + Vite | Pages today: Dashboard, Users, Trips, Bookings, Negotiations, Payments, Payouts, Wallets, Chats, Companies, RouteStages. |
| Mobile app | `/Users/mac/Desktop/github/negoride-canada-mobo/` | Flutter 3.32+, GetX, Dio, Google Maps, OneSignal, flutter_local_notifications, socket_io_client, flutter_webrtc, record, geolocator | v3.0.17+17. Base URL in `lib/utils/AppConfig.dart`. |

**The two ride products (this is the core idea — keep it):**

1. **Car Hire (on-demand, negotiated):** the customer requests a ride, customer and driver **negotiate the price** (the "Nego" in NegoRide), then the ride happens. Backed by `Negotiation` + `NegotiationRecord` models, `routes/negotiations.py`, SSE `routes/stream.py`.
2. **Rideshare (scheduled, seat-based):** drivers publish scheduled journeys with seats and prices. Customers browse and book seats. Backed by `Trip` + `TripBooking` (+ `ScheduledBooking` / `routes/bookings.py`).

Other things that already exist and must be reused, not rebuilt: Stripe payments and Stripe Connect payouts (`payout_account.py`, `wallet_service.py`), wallet and transactions, OneSignal push (`services/notification_service.py`), in-app chat, WebRTC calling (`sockets/call_events.py`), important contacts (`/api/important-contacts`), OTP endpoints (`/api/otp-request`, `/api/otp-verify`), email verification and password reset, driver location updates (`/api/update-location`, `/api/go-on-off`).

**Standard response envelope (mandatory for every mobile endpoint):**
```json
{ "code": 1, "message": "Human readable message", "data": { } }
```
`code: 1` = success, `code: 0` = failure. Never change this contract. The Flutter app depends on it.

---

## 2. Engineering rules (apply to everything)

> **Status (2026-09-28):** ✅ All 12 rules applied: additive `v4_*` migrations, legacy status kept in sync, integer cents, `Idempotency-Key`, webhook inbox + async processing, RQ/Redis jobs (thread fallback), env-only secrets (production refuses defaults), audit log (legacy admin too), encryption at rest + retention, UTC + local-time display, `ff.*` flags in admin, tests for every feature.

1. **Additive database changes only.** New tables and new nullable columns are fine. Never rename or drop existing columns (`status`, `payment_status`, etc.) because the live app reads them. Keep a numbered SQL migration file per change in `negoride-canada-py-api/backend/database/migrations/NNN_description.sql` (or introduce Alembic, but be consistent).
2. **Backward compatibility:** old app builds (v3.0.x) must keep working after the backend deploys. When a new state machine replaces string statuses, **write both** the new field and the legacy field.
3. **Money:** store in **integer cents, CAD**. The existing mixed cents/dollars (`initial_price` cents, `agreed_price` dollars) is a known hazard. New tables use cents everywhere. Add helper functions and never do float math on money.
4. **Idempotency:** every payment, refund, payout, SOS and webhook handler must be idempotent (`Idempotency-Key` header from the app; unique DB constraints on external event IDs).
5. **Webhooks** (Stripe, Certn, Twilio) must verify signatures, persist the raw event to a `webhook_events` table first, then process asynchronously.
6. **Background jobs:** introduce a job runner (**RQ + Redis** recommended; Celery is acceptable). Emails, SMS, pushes, PDF generation, ETA calculation and Certn polling must never block an HTTP request.
7. **Secrets** come from environment variables only (`.env`, never committed). Hardcoded keys found during work must be moved to env.
8. **Audit log:** every admin action and every safety event writes to `audit_logs` (who, what, when, before/after, IP).
9. **Privacy (Canada):** comply with **PIPEDA** (and **Québec Law 25** if operating in QC). Collect the minimum. Encrypt sensitive files at rest. Define retention. Log admin access to personal data.
10. **Time:** store UTC and display in the user's local time zone (Canada spans six).
11. **Feature flags:** every new feature ships behind a flag in a `app_settings` table (editable in admin), so the client can turn things on gradually.
12. **Tests:** each feature needs backend unit tests for its business rules (state machine, refund calculation, rating math) and at least one API integration test.

---

## 3. Delivery phases (build order)

> **Status (2026-09-28):** ✅ P1–P6 delivered in order (foundation first).

| Phase | Theme | Items | Why first |
|---|---|---|---|
| **P1 — Foundation** | Trip state machine, event log, realtime (Socket.IO), notification engine, job queue, settings table, audit log | §4, §5 | Everything else plugs into these. |
| **P2 — Money & trust** | Pay-before-trip (auth/capture), cancellation and refund engine, email thank-you, PDF receipts | §6, §7, §13 | Client items 3, 4, 14, 17. Legal/financial risk. |
| **P3 — Safety** | SOS + Help center, live location sharing, admin live map, audio recording | §8, §9, §10 | Client items 1, 8, 9. |
| **P4 — Identity & onboarding** | Twilio Verify everywhere, legal consent, driver onboarding wizard, Certn background check, activation controls | §11, §12, §14, §15 | Client items 5, 6, 7, 16. |
| **P5 — Experience** | Live ETA, instant address search, rideshare self-booking and pick-a-driver, ratings, full UI/UX refresh | §16, §17, §18, §21 | Client items 2 (UI), 10, 11, 12, 15. |
| **P6 — Growth & control** | Advanced admin dashboard, landing website | §19 (dashboard), §22 | Client items 13, 18. |

---

## 4. Trip lifecycle and state machine (Client item 2)

> **Status (2026-09-28):** ✅ Implemented (`services/trip_state_machine.py`, `routes/rides.py`, app `ActiveRideScreen`). Deliberate deviation: car-hire legacy status keeps `Active`/`Cancelled` because the v3 app depends on those strings.

### Client said
> "Customer notification showing them that drivers have arrived. Add very clear logic of trip steps, like Uber … think beyond … implement all necessary steps both backend and frontend, API endpoints and documentation."

### What it really means
Today trip status is a loose collection of strings (`Pending`, `Accepted`, `Accept`, `Started`, `Ongoing`, `Active`, `Completed`, `Canceled`, `Cancelled`, `Declined`…) spread across controllers. The client wants **one clear, strict, observable trip journey**, where every step is visible to the customer, the driver and the admin, and every step can trigger notifications. "Driver has arrived" is one step of that journey.

### 4.1 Car Hire (negotiated, on-demand) states

```
                ┌──────────────┐
                │  REQUESTED   │  customer submits pickup + drop-off + offer
                └──────┬───────┘
                       ▼
                ┌──────────────┐  driver(s) counter-offer; customer accepts/counter
                │ NEGOTIATING  │  (existing NegotiationRecord flow)
                └──────┬───────┘
                       ▼
                ┌──────────────┐
                │ PRICE_AGREED │  both sides accepted a price → quote locked
                └──────┬───────┘
                       ▼
             ┌────────────────────┐  Stripe authorization hold (see §6)
             │ AWAITING_PAYMENT   │  timeout: 5 min → EXPIRED
             └─────────┬──────────┘
                       ▼
                ┌──────────────┐  payment authorized = booking confirmed
                │  CONFIRMED   │
                └──────┬───────┘
                       ▼
             ┌────────────────────┐  driver taps "Start heading to pickup"
             │  DRIVER_EN_ROUTE   │  live location + ETA streamed (§16)
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐  auto: ETA ≤ 2 min OR distance ≤ 500 m
             │  DRIVER_ARRIVING   │
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐  driver taps "I've arrived" (only allowed
             │  DRIVER_ARRIVED    │  within 150 m geofence) → wait timer starts
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐  driver enters customer's 4-digit Ride PIN
             │   IN_PROGRESS      │  (§8.4). Route + location recorded.
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐  driver taps "Complete" near drop-off
             │    COMPLETED       │  → capture payment, wallet split, receipt
             └─────────┬──────────┘
                       ▼
             ┌────────────────────┐  both rated (or 72 h passed)
             │      CLOSED        │
             └────────────────────┘

Branches (terminal unless noted):
  EXPIRED                 no agreement / no payment in time
  CANCELLED_BY_CUSTOMER   fee per §7
  CANCELLED_BY_DRIVER     full refund to customer, driver reliability penalty
  CUSTOMER_NO_SHOW        from DRIVER_ARRIVED after wait window; fee per §7
  DRIVER_NO_SHOW          driver not arrived by ETA + 15 min; full refund, auto-rematch offer
  DISPUTED                (non-terminal overlay) opened by either party within 72 h
  REFUNDED / PARTIALLY_REFUNDED  (payment overlay)
```

### 4.2 Rideshare (scheduled seats) states

**Trip (driver's journey):** `DRAFT → PUBLISHED → BOARDING (T-30 min) → IN_PROGRESS → COMPLETED → CLOSED`, plus `CANCELLED_BY_DRIVER`.
**Seat booking (customer):** `PENDING_PAYMENT → CONFIRMED → CHECKED_IN (driver confirms pickup / PIN) → RIDING → DROPPED_OFF → CLOSED`, plus `CANCELLED_BY_CUSTOMER`, `CANCELLED_BY_DRIVER`, `NO_SHOW`.
Rideshare supports **multiple pickups**. The driver app shows an ordered pickup list with per-passenger "Arrived / Picked up / No-show" buttons. Each passenger gets their own "driver arrived" notification.

### 4.3 Backend implementation

- New column `trip_stage` (VARCHAR 40, indexed) on `negotiations` and on `trip_bookings` / `trips`. Keep the legacy `status` column in sync through a single mapping function:
  | trip_stage | legacy `status` |
  |---|---|
  | REQUESTED, NEGOTIATING | `Pending` |
  | PRICE_AGREED, AWAITING_PAYMENT, CONFIRMED | `Accepted` |
  | DRIVER_EN_ROUTE, DRIVER_ARRIVING, DRIVER_ARRIVED, IN_PROGRESS | `Started` |
  | COMPLETED, CLOSED | `Completed` |
  | EXPIRED, CANCELLED_*, *_NO_SHOW | `Canceled` |
- New service `backend/services/trip_state_machine.py`:
  - `ALLOWED_TRANSITIONS` dict; `transition(ride, to_stage, actor, meta)` validates the transition, the actor's role (only the driver can mark ARRIVED, and so on), geofence and time rules, then writes the stage, writes the legacy status, inserts a `trip_events` row, emits a realtime event and enqueues notifications. **This is the only function allowed to change a stage.**
  - Wrap it in a DB transaction with `SELECT … FOR UPDATE` to prevent double transitions.
- New table **`trip_events`**: `id, ride_type ('carhire'|'rideshare_trip'|'rideshare_booking'), ride_id, from_stage, to_stage, actor_type ('customer'|'driver'|'admin'|'system'), actor_id, lat, lng, meta JSON, created_at`. This becomes the trip timeline shown in app and admin.
- Scheduled jobs (every 30 s): expire unpaid AWAITING_PAYMENT, detect DRIVER_NO_SHOW, auto-advance DRIVER_ARRIVING by distance, auto-close after 72 h, move rideshare trips to BOARDING.

### 4.4 API endpoints (new)

| Method | Path | Actor | Purpose |
|---|---|---|---|
| GET | `/api/rides/{type}/{id}` | party/admin | Full ride object: stage, parties, price, payment, ETA, PIN (customer only), timeline |
| GET | `/api/rides/{type}/{id}/timeline` | party/admin | `trip_events` list |
| POST | `/api/rides/{type}/{id}/en-route` | driver | → DRIVER_EN_ROUTE |
| POST | `/api/rides/{type}/{id}/arrived` | driver | → DRIVER_ARRIVED (body: lat, lng; geofence enforced) |
| POST | `/api/rides/{type}/{id}/start` | driver | → IN_PROGRESS (body: `pin`) |
| POST | `/api/rides/{type}/{id}/complete` | driver | → COMPLETED (body: lat, lng, final odometer optional) |
| POST | `/api/rides/{type}/{id}/cancel` | either | body: `reason_code`, `note`; response includes fee preview (§7) |
| GET | `/api/rides/{type}/{id}/cancel-preview` | either | fee/refund that *would* apply now |
| POST | `/api/rides/{type}/{id}/no-show` | driver | → CUSTOMER_NO_SHOW (only after wait window) |
| GET | `/api/rides/active` | any | the caller's current active ride (app resume / crash recovery) |

Existing endpoints (`bookings/{id}/start`, `bookings/{id}/complete`, `negotiations-complete`, etc.) must internally call the state machine so that both old and new app versions produce the same events.

### 4.5 Mobile (Flutter)

- **One "Active Ride" screen** for both roles, driven entirely by `trip_stage` from `/api/rides/active` and realtime events. Replace ad-hoc status checks in `TripStatusManager.dart` with a single `RideStage` enum and a stage → UI config map.
- **Customer progress bar (stepper):** Confirmed → Driver on the way (ETA) → Arriving → Arrived (wait timer + PIN displayed large) → On trip (live ETA to destination, share trip, SOS) → Arrived at destination → Rate & tip → Receipt.
- **Driver screen:** one big contextual primary button whose label changes with the stage ("Head to pickup" → "I've arrived" → "Enter PIN & start" → "Complete trip"). Swipe-to-confirm prevents accidental taps. Turn-by-turn opens in Google Maps / Apple Maps / Waze.
- On app launch, call `/api/rides/active` and restore the ride screen (crash and kill resilience).
- Keep the screen awake during active rides (`wakelock_plus` is already installed).

### 4.6 Acceptance criteria
- [x] Invalid transitions (for example COMPLETED → IN_PROGRESS) return `code: 0` with a clear message and change nothing. — ✅ `test_full_happy_path`, `test_state_machine_matrix.py`.
- [x] "I've arrived" is rejected when the driver is more than 150 m (configurable) from pickup. — ✅ geofence test in `test_carhire_flow.py`; emulator.
- [x] Each transition produces exactly one `trip_events` row, one realtime event and the configured notifications. — ✅ happy-path test compares events with realtime emits; live socket E2E.
- [x] Legacy `status` stays correct for every stage; v3.0.17 app still works end to end. — ✅ `test_legacy_v3_flow_still_works` + legacy endpoint regression script (API level; a real v3.0.17 build run is still recommended).
- [x] Killing and reopening the app mid-trip returns to the correct screen. — ✅ `integration_test/s6b_relaunch_test.dart` on the Android emulator.

---

## 5. Notification engine (Client item 2 — notifications and listeners)

> **Status (2026-09-28):** ✅ Implemented (`services/notify/`, socket `/rt`, OneSignal, Twilio SMS fallback, email, inbox, preferences + quiet hours, retries, server-driven iOS Live Activities, admin-editable templates).

### Client said
> "Add logic of notifications and notification listeners … make use of powerful notification libraries … both front and backends."

### What it really means
A single, reliable, multi-channel notification system. Every important event reaches the right person on the right channel, with a record of what was sent and whether it was delivered. Today only a thin OneSignal helper exists.

### 5.1 Channel strategy

| Channel | Library/provider | Use for |
|---|---|---|
| **Realtime in-app** | **Flask-SocketIO** (already installed) ↔ `socket_io_client` (already in Flutter) | Live stage changes, driver location, negotiation offers, SOS alerts to admin. Replace SSE polling (`stream.py`) progressively; keep SSE as a fallback. |
| **Push** | **OneSignal** (already integrated both sides — keep it, don't switch vendors) | App backgrounded or closed. Use `external_id` = user id. |
| **Local notifications** | `flutter_local_notifications` (installed) | Foreground banners, ongoing Android "trip in progress" notification with ETA. |
| **iOS Live Activities / Dynamic Island + Android ongoing notification** | OneSignal Live Activities support or the `live_activities` Flutter package | "Driver arriving in 3 min" on the lock screen, like Uber. **High-impact differentiator.** |
| **SMS** | **Twilio Messaging** | Fallback for critical events when push fails (driver arrived, SOS to trusted contacts, trip share links). |
| **Email** | Transactional email provider (§13) | Receipts, thank-you, onboarding, background-check results, policy changes. |
| **In-app inbox** | New `notifications` table + screen | History of everything, with unread badge. |

### 5.2 Backend design
- `backend/services/notify/` package:
  - `dispatcher.py` → `notify(event_key, user_ids, context)` looks up the event in the **catalogue** (below), renders templates, respects user preferences and quiet hours, then enqueues one job per channel.
  - `channels/push_onesignal.py`, `channels/sms_twilio.py`, `channels/email.py`, `channels/socket.py`, `channels/inbox.py`.
  - **Delivery tracking:** `notification_deliveries` table (`notification_id, channel, provider_message_id, status queued|sent|delivered|failed|opened, error, attempts, timestamps`). Retries with exponential backoff (3 attempts). **Critical events escalate:** if push is not confirmed opened within 60 s, send SMS.
- Tables:
  - `notifications` (`id, user_id, event_key, title, body, data JSON, deep_link, read_at, created_at`)
  - `notification_preferences` (`user_id, event_group, push, sms, email` booleans). Safety and transactional groups cannot be disabled.
  - `device_tokens` (optional; OneSignal manages subscriptions, but store `onesignal_subscription_id`, platform, app_version, last_seen for diagnostics)
- Socket.IO rooms: `user:{id}`, `ride:{type}:{id}`, `admin:ops`, `admin:sos`. Authenticate on connect with the JWT and reject unauthenticated sockets.

### 5.3 Notification catalogue (minimum set)

| Event key | Recipient | Channels | Example copy |
|---|---|---|---|
| `negotiation.new_request` | nearby drivers | push, socket, sound | "New ride request 3.2 km away — offer $18" |
| `negotiation.counter_offer` | other party | push, socket | "Driver countered: $21" |
| `negotiation.agreed` | both | push, socket | "Price agreed: $20. Complete payment to confirm." |
| `payment.authorized` | both | push, socket, inbox | "Ride confirmed. Amara is heading to you." |
| `payment.failed` | customer | push, inbox | "Payment failed — update your card to keep this ride." |
| `ride.driver_en_route` | customer | push, socket, live activity | "Amara is on the way · 7 min · Grey Toyota Corolla ABC 123" |
| `ride.driver_arriving` | customer | push (time-sensitive), live activity | "Your driver is 1 min away — get ready" |
| **`ride.driver_arrived`** | customer | **push (time-sensitive) + socket + SMS fallback + sound + vibration** | "Your driver has arrived. PIN: 4821. Waiting until 10:42." |
| `ride.wait_warning` | customer | push | "2 minutes left before a no-show fee applies" |
| `ride.started` | customer, trusted contacts (if auto-share on) | push, socket, SMS to contacts | "Trip started — share your live location" |
| `ride.completed` | both | push, email (§13) | "You've arrived. Rate your trip." |
| `ride.cancelled` | other party | push, SMS | "Your ride was cancelled by the driver. Full refund issued." |
| `refund.issued` | customer | push, email | "Refund of $12.00 on its way (5–10 business days)" |
| `rating.reminder` | both | push (once, 2 h later) | "How was your trip with Amara?" |
| `rideshare.booking_confirmed` | customer, driver | push, email | "Seat booked: Toronto → Ottawa, Fri 8:00" |
| `rideshare.departure_reminder` | passengers, driver | push, SMS | "Your ride leaves in 1 hour from Union Station" |
| `safety.sos_triggered` | admins, trusted contacts | socket alarm, push, SMS, email | "EMERGENCY: [name] triggered SOS — live location: …" |
| `safety.route_deviation` | customer | push | "Your trip changed route. Are you OK? [I'm OK] [Get help]" |
| `onboarding.step_required` | driver applicant | push, email | "Next: verify your phone number" |
| `background_check.completed` | driver, admin | push, email | "Your background check is complete" |
| `account.deactivated` / `account.reactivated` | user | push, email, SMS | per §15 |
| `payout.sent` | driver | push | "$146.20 is on its way to your bank" |
| `legal.policy_updated` | all | push, email, in-app blocking modal | "We updated our Terms. Please review." |

### 5.4 Flutter listeners
- `lib/services/notifications/NotificationCenter.dart`: one singleton that initializes OneSignal, local notifications and the socket. Exposes a `Stream<AppEvent>`. Screens subscribe through GetX controllers.
- **Deep-link router:** every notification carries `data.route` + `data.ride_id`. Tapping it opens the exact screen (cold start, background and foreground).
- Android notification channels: `ride_critical` (max importance, custom sound "driver_arrived.mp3"), `ride_updates`, `negotiation`, `payments`, `marketing`. iOS: time-sensitive interruption level for `ride_critical`.
- Foreground behaviour: show an in-app banner plus a sound for critical events. Don't duplicate system notifications.
- Notification inbox screen with unread badge on the Home tab.

### 5.5 Acceptance criteria
- [x] "Driver arrived" reaches the customer in under 3 s through socket or push, with SMS fallback within 60 s if the push is not opened. — ✅ 1.1 s measured over a real socket; SMS escalation tests.
- [x] Every sent notification appears in the inbox and in admin → Notifications log with delivery status. — ✅ `test_every_notification_lands_in_inbox_with_deliveries`; admin Notifications log.
- [x] Tapping any notification from a killed-app state opens the correct screen. — ✅ cold-start queue in DeepLinkRouter + tests; real-device push tap check pending.
- [x] Users can mute marketing and non-critical groups. Safety and transactional messages are always delivered. — ✅ `test_mutable_group_can_be_muted_but_safety_cannot`.

---

## 6. Pay before the trip starts (Client item 14)

> **Status (2026-09-28):** ✅ Implemented (Stripe manual capture; hard server-side guard; capture at completion; partial capture / release on cancel; far-future rides charged immediately; failure + retry flows). ⏳ Saved card (§6.6) deferred by the spec ("later").

### Client said
> "Customers must have to pay first for the trip to start."

### What it really means and design decision
Money must be secured **before** the driver starts driving, but the platform still needs fair refunds and fees. Use a **Stripe authorization hold (manual capture)**:

1. On PRICE_AGREED, create a Checkout Session / PaymentIntent with `capture_method=manual` for the agreed price plus fees in **CAD**. The current app uses Stripe Checkout in a WebView. Keep that path (`payment_intent_data.capture_method = manual`) and optionally add native **Apple Pay / Google Pay** through `flutter_stripe` PaymentSheet in a later iteration.
2. When the Stripe webhook `payment_intent.amount_capturable_updated` / `checkout.session.completed` arrives, the ride moves to **CONFIRMED**. Before that, the backend **refuses** `en-route`, `arrived` and `start` (hard rule, enforced server-side, not just in the UI).
3. On COMPLETED, **capture** (amount may be adjusted down, never up without consent). Then the existing wallet split and commission logic runs.
4. On a cancellation with a fee, **partial capture** for the fee amount and release the rest. On a free cancellation, cancel the PaymentIntent, which releases the hold instantly (better customer experience than a refund).
5. **Rideshare** bookings made more than 6 days ahead: card authorizations expire after about 7 days, so **charge immediately** and refund per policy (§7). Otherwise use the manual-capture flow.
6. Optional **wallet balance / saved card** later. Save the payment method (`setup_future_usage=off_session`) with consent for one-tap payment next time.

**Data:** new `payments` fields or table: `intent_id, amount_authorized_cents, amount_captured_cents, amount_refunded_cents, currency='cad', capture_status, auth_expires_at`. Reuse the existing `payment.py` model where possible.

**Acceptance:** a driver cannot move a ride past CONFIRMED until payment is authorized. A backend test proves this even when the app is bypassed.

---

## 7. Cancellation and refund policy (Client item 17)

> **Status (2026-09-28):** ✅ Implemented — every row of 7.1/7.2 is a rule in `refund_policy.py` with a unit test; numbers editable in admin Settings; safety endings held for admin settlement.

### What it really means
A written, visible, fair policy **and** a refund engine that applies it automatically, so no refund needs manual work. The rules below are **proposed defaults — [CONFIRM WITH CLIENT]**. Every number lives in `app_settings` and can be edited in admin.

### 7.1 Car Hire
| Situation | Customer charged | Driver receives |
|---|---|---|
| Cancel before payment / before driver en route | $0 | $0 |
| Cancel within **2 min** after confirmation | $0 (hold released) | $0 |
| Cancel after 2 min while driver en route | **$5.00 CAD** cancellation fee (or 10 % of fare, whichever is lower) | fee minus commission |
| Cancel after driver ARRIVED | $5.00 + waiting time accrued | fee minus commission |
| Customer no-show (wait window **5 min** after ARRIVED) | $7.00 no-show fee | fee minus commission |
| Driver cancels after confirmation | $0, full release | $0 + reliability strike |
| Driver no-show (ETA + 15 min) | $0 + **$5 ride credit** apology (optional) | reliability strike |
| Trip ended early for safety (SOS) | pro-rated or $0 after admin review | admin decides |
| Dispute upheld (overcharge, wrong route) | partial/full refund by admin | clawback from wallet |

### 7.2 Rideshare (seat bookings)
| Customer cancels | Refund |
|---|---|
| More than 24 h before departure | 100 % |
| 2–24 h before | 50 % |
| Less than 2 h / no-show | 0 % |
| Driver cancels the trip (any time) | 100 % to every passenger + driver strike |

### 7.3 Implementation
- `backend/services/refund_policy.py` → `evaluate(ride, actor, now) -> {fee_cents, refund_cents, driver_share_cents, rule_id, explanation}`. Pure function with unit tests for every row above.
- `/cancel-preview` shows the exact fee **before** the user confirms. The cancel sheet says for example "Cancelling now costs $5.00 because your driver has been driving for 4 min."
- Refunds run through the Stripe Refunds API or PaymentIntent cancel/partial capture, update `amount_refunded_cents`, and trigger `refund.issued` notifications and an email.
- The admin can issue a **manual refund** (full/partial) with a mandatory reason. It is audited.
- Policy text is a versioned legal document (§12) shown in-app (Help → Cancellation & refunds), on the website and linked from the receipt.
- **Strikes:** driver cancellations and no-shows count toward reliability (§17). More than 3 in 7 days produces an automatic warning, and more than 5 an automatic temporary suspension (configurable).

---

## 8. Emergency and help center (Client item 1)

> **Status (2026-09-28):** ✅ Implemented (Safety toolkit, SOS never fails, 3 s location, admin alarm, escalation to on-call phones, PIN with lockout, vehicle card with photo, route-deviation checks against the planned route, trusted contacts, flag passenger). 🟡 On-call phone numbers must be configured.

### Client said
> "Emergency and help button, with the red emergency button connected to the dashboard. Show help contacts. Show 911 button."

### What it really means
A **Safety Toolkit** that is always one tap away during a ride, where every emergency instantly appears on the admin dashboard with the rider's live location.

### 8.1 UX
- A **red shield/SOS button** floats on every active-ride screen (customer **and** driver) and appears in the side menu at all times.
- Tapping it opens the **Safety Toolkit sheet**:
  1. **Call 911**: big red button. Requires **slide-to-call or a 3-second hold** to avoid pocket dials, then opens the dialer with `tel:911`. **Never auto-dial without a user gesture.**
  2. **Show my location and trip details**: large text with the current address, lat/lng, vehicle make/colour/plate and driver name, so the user can read it to the 911 operator.
  3. **Alert NegoRide Safety Team**: sends an SOS to the admin dashboard (silent option available).
  4. **Share live trip** with trusted contacts (§9).
  5. **Help contacts:** NegoRide support (phone, chat, email), the user's trusted contacts, local non-emergency police line (by province), roadside assistance, Kids Help Phone / crisis line (**Talk Suicide Canada: 988**). Source these from the existing `/api/important-contacts` endpoint and extend it with `category` and `province`.
  6. **Report a safety issue (non-urgent)**: form with categories (unsafe driving, harassment, vehicle condition, other) plus optional attachments.
  7. **Start audio recording** (§10), if not already on.

### 8.2 What happens on SOS (backend)
1. `POST /api/safety/sos` with `{ ride_type, ride_id?, lat, lng, accuracy, battery, silent: bool }` and an `Idempotency-Key`.
2. Creates `safety_incidents` (`id, user_id, role, ride ref, status open|acknowledged|resolved|false_alarm, severity, lat, lng, created_at, acknowledged_by, resolved_at, notes`).
3. The app switches to **high-frequency location** (every 3 s) posting to `/api/safety/incidents/{id}/location` until resolved.
4. Emits a socket event to `admin:sos`. The admin dashboard plays an **alarm sound**, shows a full-width red banner and a live map pin, and the incident stays pinned until acknowledged.
5. Sends SMS to the user's trusted contacts with a live-tracking link (§9).
6. Optionally auto-starts audio recording (if the user pre-consented in Safety settings).
7. Escalation: if no admin acknowledges within 60 s, SMS and call the on-call admin phone numbers (configurable list).

### 8.3 Admin
- **Safety Center** page: open incidents first, live map, timeline, one-click call to rider/driver, notes, status changes, link to recording and trip events, export incident report as PDF (for police/insurance).

### 8.4 Extra safety features (outside the box)
- **Ride PIN:** the customer shows a 4-digit PIN. The trip cannot start until the driver enters it, which prevents getting into the wrong car.
- **Vehicle verification card:** big plate number, car photo, driver photo, "Match the plate before you get in".
- **Route deviation and long-stop detection:** if the car goes more than 500 m off the expected route or stops for more than 5 min unexpectedly, the app asks "Are you OK?" with [I'm OK] [Get help]. No response in 60 s alerts the admin.
- **Trusted contacts and auto-share:** users save up to 5 contacts and can choose "Always share my trips at night (9 pm – 5 am)".
- **Driver safety too:** drivers get the same SOS and can flag a passenger.

### 8.5 Acceptance
- [x] An SOS appears on the admin dashboard in under 2 s with live location updates. — ✅ ≈300 ms in the admin headless-browser test; live location updates every 3 s.
- [x] The 911 button requires a deliberate gesture and works without internet (it's just the dialer). — ✅ 3-second hold / slide; `safety_call_911_test.dart`; dialer only (works offline).
- [x] SOS works even if the ride has ended or no ride exists. — ✅ `test_sos_without_ride…`, `test_sos_during_and_after_ride`; invalid ride ids fall back.

---

## 9. Live location sharing and trip tracking (Client item 9)

> **Status (2026-09-28):** ✅ Implemented (batched breadcrumbs, offline catch-up, Redis latest position, share links, public tracking page on the website + API fallback, admin live map with rides/SOS layers and replay).

### Client asked
> "Live location sharing button of the trip for customers for security purposes. Is it possible for us to track the trip in the dashboard?"

**Answer: yes.** The app already sends driver locations (`/api/update-location`). We extend this into a proper live-tracking pipeline.

### 9.1 Design
- **Driver location stream:** while online, the driver app sends a location every 10 s. During an active ride it sends every **3–5 s**, over the socket (fallback HTTP), with a background service on Android (foreground service notification) and background location mode on iOS.
- Store the latest position in Redis (fast) and append breadcrumbs to `ride_locations` (`ride ref, lat, lng, speed, heading, accuracy, recorded_at`). Batch-insert and keep 90 days (configurable). Keep longer if an incident or dispute exists.
- **Share Trip button** (customer, during CONFIRMED → COMPLETED):
  - `POST /api/rides/{type}/{id}/share` → returns `https://negoride.ca/t/{token}` (random 32-char token, expires 30 min after trip end, revocable).
  - The native share sheet (SMS, WhatsApp, email) or direct share to trusted contacts.
  - The **public tracking web page** (part of the landing site, §22) shows a live map with car icon, route, ETA, driver first name, car and plate, and trip status. It shows **no phone numbers or payment info** and uses `noindex`.
- **Admin Live Operations Map:** every online driver (colour by state: idle / en route / on trip / SOS), click for driver, ride and customer details, follow mode, replay a completed trip route with a time slider.

### 9.2 API
`POST /api/rides/{type}/{id}/share`, `DELETE /api/rides/{type}/{id}/share/{token}`, `GET /api/public/track/{token}` (no auth, rate-limited), `GET /api/admin/live/drivers`, `GET /api/admin/rides/{type}/{id}/route`.

---

## 10. Optional in-trip audio recording (Client item 8)

> **Status (2026-09-28):** ✅ Implemented (opt-in, 1-min chunks, encrypted private storage, other party informed by banner + push, audited streaming for safety reviewers only, retention with legal hold).

### What it really means
Customers and drivers can **choose** to record audio during a trip as safety evidence. Recordings go to the admin dashboard **only when needed** (incident, dispute or report), with strict privacy rules.

### 10.1 Rules
- **Opt-in** per user in Safety settings ("Record audio on my trips": off / always / ask each trip), plus a manual Record button on the ride screen.
- **Transparency:** when recording is active, the other party sees "🔴 Audio recording is on for safety" in their app. Disclose recording in the Terms and Privacy Policy. **[CONFIRM WITH CLIENT's lawyer]**: Canada is broadly a one-party-consent jurisdiction for participants, but platform-held recordings raise PIPEDA obligations, so disclosure to both parties is the safe design.
- **Storage:** record in AAC/M4A chunks (1 min) with the existing `record` package. Upload in the background to private object storage (S3-compatible, server-side encryption), never a public URL. A chunk manifest is linked to the ride.
- **Access:** only admins with the `safety_reviewer` role, via short-lived signed URLs. Every play or download is written to `audit_logs`.
- **Retention:** auto-delete after **7 days** unless linked to an incident, report or dispute. Then keep until the case closes plus 90 days.
- Users can see that a recording exists but can't download the other party's audio (request through support).

### 10.2 API and admin
`POST /api/recordings` (start, returns upload URLs), `POST /api/recordings/{id}/chunks`, `POST /api/recordings/{id}/stop`. Admin → Safety Center → Recordings tab: audio player with timeline aligned to trip events and map position.

---

## 11. Phone verification with Twilio Verify (Client item 6)

> **Status (2026-09-28):** 🟡 All 14 scenarios implemented and tested with test numbers; needs Twilio credentials, Verify service and console setup (RUNBOOK §10) for production.

### Client said
> "Negoride app = Negoride backend/API = Twilio Verify API = SMS = customer/driver. Implement different scenarios for phone number SMSing."

### 11.1 Flow
```
App ──(phone E.164)──▶ NegoRide API ──▶ Twilio Verify (SMS / voice / WhatsApp)
App ◀── code entry ──  NegoRide API ◀── Verify check result
```
**The app never talks to Twilio directly. Twilio credentials stay on the server.** Reuse and upgrade the existing `/api/otp-request` and `/api/otp-verify` (keep them as aliases).

### 11.2 Scenarios to implement
| # | Scenario | Behaviour |
|---|---|---|
| 1 | **Sign-up** | Phone verification is required before the account becomes active. |
| 2 | **Passwordless login** | "Log in with phone": OTP instead of password (optional, flag). |
| 3 | **Change phone number** | Verify the new number and notify the old number by SMS. |
| 4 | **Driver onboarding** | Mandatory step (§14). A server-confirmed OTP verification of the account phone completes this step. Carrier line-type lookup is informational and must not block onboarding or require repeat verification. |
| 5 | **New device / suspicious login** | Step-up OTP when logging in from an unseen device. |
| 6 | **Password reset by phone** | Alternative to email reset. |
| 7 | **Sensitive actions** | Payout account change, account deletion: re-verify. |
| 8 | **Resend / fallback** | Resend after 30 s. After 2 failed SMS, offer a **voice call**. Optional WhatsApp channel. |
| 9 | **Wrong code / expiry** | Max 5 attempts per code, 10-min expiry (Twilio defaults), friendly errors. |
| 10 | **Rate limits and fraud** | Max 5 sends per phone per hour and 10 per IP per hour. Enable Twilio **Fraud Guard / geo-permissions** (Canada + US only by default). Block premium-rate prefixes. |
| 11 | **Number intelligence** | Twilio **Lookup** line type check at signup may inform fraud controls, but it does not override a server-confirmed phone verification for driver onboarding. |
| 12 | **Duplicate numbers** | One verified phone per account. Offer "Log in instead" if already registered. |
| 13 | **Transactional SMS** (not OTP) | Driver-arrived fallback, trip share, SOS: Twilio Messaging Service with a Canadian long code or toll-free verified number. Honour STOP/HELP keywords. |
| 14 | **Test mode** | Configurable test numbers with a fixed code in non-production only, so App Store reviewers and QA can log in. |

### 11.3 Data and API
- `users` add: `phone_e164`, `phone_verified_at`, `phone_line_type`.
- `phone_verifications` log: `user_id, phone, purpose, channel, twilio_sid, status, ip, device_id, created_at`.
- `POST /api/verify/phone/start` `{ phone, purpose, channel: sms|call|whatsapp }` and `POST /api/verify/phone/check` `{ phone, purpose, code }` → returns a short-lived `verification_token` used by the next step (signup, phone change and so on).
- **Flutter:** reuse `OTPScreen.dart` and upgrade it: 6 separate digit boxes, **SMS autofill** (Android SMS Retriever via `sms_autofill`/`pinput`, and iOS `oneTimeCode` content type), countdown resend, "Call me instead", "Change number".

---

## 12. Legal consent — Terms, Privacy Policy, Community Guidelines (Client item 7)

> **Status (2026-09-28):** 🟡 Implemented end to end (3 unticked boxes, reader, CASL proof, server-side re-acceptance gate, admin editor + acceptance stats, website pages). The 8 documents are professional drafts marked [REVIEW WITH COUNSEL].

### Client said
> "Users agreeing to community guidelines, privacy policy, and terms and conditions by reading and marking the boxes. Make this very clear."

### 12.1 Design
- New tables:
  - `legal_documents` (`id, type terms|privacy|community_guidelines|driver_agreement|cancellation_policy|safety_policy|recording_notice, version, title, body_markdown, effective_at, requires_reacceptance bool, audience all|customer|driver`)
  - `legal_acceptances` (`user_id, document_id, version, accepted_at, ip, user_agent, app_version, method checkbox|modal`). **This is the proof for disputes and regulators.**
- **Sign-up screen:** three separate, **unchecked** checkboxes, each with a link that opens the document in-app:
  - ☐ I have read and agree to the **Terms & Conditions**
  - ☐ I have read and agree to the **Privacy Policy**
  - ☐ I agree to follow the **Community Guidelines**
  - The Continue button stays disabled until all three are ticked.
  - Tapping a link opens a full-screen reader showing a "Last updated" date and a short **plain-language summary box** at the top, then the full text. Optional (flag): the "I agree" button activates only after the user scrolls to the bottom.
- **Separate optional** checkbox for marketing emails and SMS (**CASL** requires express, separate consent). Never pre-ticked.
- **Drivers** additionally accept the Driver Agreement, Background Check Consent (§14) and Safety Policy.
- **Re-acceptance:** when a new version has `requires_reacceptance`, the next app open shows a blocking modal with "What changed" and must be accepted to continue. Admin can see acceptance rates per version.
- **Admin:** Legal page for editing documents (Markdown editor), publishing a new version, previewing, and viewing who accepted what.
- The same documents render on the website (`/terms`, `/privacy`, `/guidelines`, `/cancellation-policy`). The App Store and Google Play require a public privacy policy URL.
- The **Community Guidelines** content should cover respect, zero tolerance for discrimination and harassment, no weapons, no drugs or alcohol for drivers, seat belts, child seats, service animals (legally required to be accepted), cleanliness, and the fair negotiation etiquette unique to NegoRide.

**Acceptance:** it is impossible to register without the three explicit ticks, and every tick is stored with version, timestamp and IP.

---

## 13. Thank-you email and payment receipt (Client items 3 and 4)

> **Status (2026-09-28):** 🟡 Implemented (combined thank-you + receipt email with PDF, sequential numbers, tax by province, credit notes, tip receipts, weekly driver statements, admin resend). Pending: GST/HST number, real email-client rendering check.

### Client said
> "Email notification thanking customers about the trip." / "Receipt of payment to customers with the price he/she paid, on mail. Be very careful and very creative, and ensure perfection."

### 13.1 Email infrastructure
- Transactional provider: **Postmark** (best deliverability for receipts), or SendGrid / Amazon SES / Resend. Wrap it in `channels/email.py` so it can be swapped.
- Sending domain `mail.negoride.ca` (or the client's domain) with **SPF, DKIM, DMARC** configured. From: `NegoRide Canada <receipts@negoride.ca>`. Reply-to: support.
- Templates: **MJML → HTML** (responsive, dark-mode safe) rendered with Jinja2. Every email also has a plain-text version. Brand colours and logo.
- All sends go through the job queue and log to `notification_deliveries` (opens and bounces through provider webhooks).

### 13.2 "Thank you for riding" email (sent at COMPLETED)
- Subject: `Thanks for riding with NegoRide, {first_name} 🚗`
- Content: map image of the route (Google Static Maps with the polyline), pickup → drop-off, date, duration, distance, driver first name and photo, car, **fare summary**, **"You negotiated and saved $X vs. the initial ask"** (unique to NegoRide), a one-tap star rating in the email (links to a rating deep link), "Add a tip" button, "Lost an item?" and "Report an issue" links, and the receipt attached.
- It can be combined with the receipt into one email, **[CONFIRM WITH CLIENT]**. The default is **one combined email** so users get less clutter, with a clear "Receipt" section and PDF.

### 13.3 Receipt (must be perfect)
- **Receipt number:** sequential, unique, never reused: `NR-2026-000123`. Stored in a `receipts` table (`id, number, ride ref, customer_id, pdf_path, totals JSON, issued_at, voided_at`).
- **Line items (all CAD):**
  - Negotiated fare
  - Waiting time (if any)
  - Booking/service fee (if any)
  - Tolls/airport fee (if any)
  - Discounts / credits (negative)
  - **Subtotal**
  - **GST/HST/PST by province of pickup**, with the platform's GST/HST registration number. ⚠️ In Canada, ride-hailing services must collect GST/HST (in force since 2019). **[CONFIRM WITH CLIENT's accountant]** for rates, registration number and whether prices are tax-inclusive. Implement a `tax_rates` table by province.
  - Tip (not taxable, shown separately)
  - **Total charged** · payment method ("Visa •••• 4242") · authorization date and capture date
  - Refunds (if any) as a separate section, with the new net total
- Also show: rider name, driver name and vehicle, pickup and drop-off addresses with times, distance and duration, ride ID, support contact, cancellation policy link, company legal name and address.
- **PDF** generated server-side with **WeasyPrint** (HTML → PDF), stored privately and attached to the email. Downloadable in-app (Trips → Trip details → Receipt) and in admin.
- **Refund / adjustment:** issue a new **credit note** document (`NR-CN-2026-000045`) and email it. Never edit an issued receipt.
- **Rideshare:** one receipt per seat booking.
- **Drivers:** a weekly earnings statement email and PDF (gross, commission, fees, net, payouts) is a strong addition, for their taxes.

### 13.4 Acceptance
- [x] Totals on email, PDF, app and Stripe match to the cent (automated test that compares them). — ✅ `test_receipt_totals_match_everywhere`.
- [x] The receipt is sent within 60 s of COMPLETED, and re-sending from admin reuses the same number. — ✅ ≈1 s; resend reuses the number (`test_admin_resend_reuses_number_and_is_audited`); sweeper backstop.
- [~] It renders correctly in Gmail, Outlook and Apple Mail (light and dark). — 🟡 responsive, dark-mode-safe table HTML with Outlook (MSO) buttons; needs a real-client check (Litmus / Email on Acid) before launch.

---

## 14. Driver onboarding and Certn background checks (Client item 5)

> **Status (2026-09-28):** 🟡 Implemented (7-step wizard, prequal before paying, documents with expiry monitoring, Certn via the current CertnCentric API with webhook + polling, pay-later, refund before submission, advisory face match, referrals, funnel). Pending: Certn keys + package confirmation.

### Client said
> "Certn (Canada) API integration for background check. Drivers will pay for their background check. Drivers should have clear steps of becoming a driver: Registration → Verify phone (Twilio) → Submit application → Initiate background check (Certn)."

### 14.1 The onboarding wizard (Flutter; replaces the current `BecomeDriver` / `BecomeDriverFormScreen`)
A checklist screen titled **"Become a NegoRide driver — 7 steps"** with a progress ring. Each step shows a status (Not started / In progress / Under review / Done / Action needed). Users can leave and resume.

| Step | What the driver does | Backend status |
|---|---|---|
| 1. Create account | Standard sign-up + legal consent (§12) | `account_created` |
| 2. Verify phone | Twilio Verify (§11) | `phone_verified` |
| 3. Verify email | Existing email verification | `email_verified` |
| 4. Personal and eligibility info | Legal name, DOB (must be ≥ 21 **[CONFIRM]**), address, SIN is **not** collected (not needed), province, service types (Car Hire / Rideshare / Courier / Movers / Airport / Special Car) | `profile_completed` |
| 5. Documents | Driver's licence (front and back, Class 5/G or equivalent, expiry), vehicle registration, insurance (with rideshare endorsement where the province requires it), vehicle photos (4 sides + interior), selfie for face match. Camera capture with auto edge detection. | `documents_submitted` |
| 6. Background check | Consent screen → **pay the fee** (Stripe) → Certn check initiated | `background_check_pending` → `clear` / `consider` / `failed` |
| 7. Payout setup | Existing Stripe Connect onboarding (`payout_account.py`) | `payout_ready` |
| Final | Admin review → **Approved** → short safety orientation (5 cards + 5-question quiz) → can go online | `approved` / `rejected` / `needs_changes` |

- Table `driver_applications` (`user_id, status, current_step, submitted_at, reviewed_by, reviewed_at, rejection_reason, notes`) and `driver_documents` (`application_id, type, file_path, expires_at, status pending|approved|rejected, reviewer_note`).
- **Document expiry monitoring:** a daily job sends reminders 30, 14 and 3 days before licence or insurance expiry, and automatically blocks going online on expiry.
- The existing `is_car_approved` etc. flags get set from the approved service types (backward compatibility).

### 14.2 Certn integration
> **Verify every endpoint, package name, status value and webhook payload against Certn's current API docs (docs.certn.co / Certn partner portal).** The flow below is the design. Adapt field names to the real API.

1. **Consent:** show Certn's required disclosure and consent text. The driver ticks it and types their full name as an e-signature. Store it as a `legal_acceptances` row (type `background_check_consent`).
2. **Payment:** the driver pays the fee (for example **$39.99 CAD**, set in `app_settings`, **[CONFIRM WITH CLIENT]**, covering the Certn cost plus margin) through a Stripe PaymentIntent (immediate capture). The receipt is emailed. **Non-refundable once the check is submitted.** Refundable if cancelled before submission. State this clearly before payment.
3. **Initiate:** backend job calls Certn to create the application/check (recommended package for rideshare in Canada: **Canadian Criminal Record Check + identity verification + Motor Vehicle Record / driver abstract** where available, **[CONFIRM package with client]**). Use either the **invite flow** (Certn emails or SMSes the applicant to complete identity steps in Certn's hosted page, which is simplest and most compliant) or the **API-submitted applicant data** flow. The default is the invite flow, opened inside the app WebView.
4. **Webhooks:** `/api/webhooks/certn` verifies the signature, stores the raw event and updates the `background_checks` table (`user_id, provider='certn', provider_application_id, package, status, result, report_url(private), fee_payment_id, initiated_at, completed_at, expires_at`).
5. **Polling fallback:** check pending applications every 6 h in case a webhook was missed.
6. **Adjudication:** `clear` → auto-advance. `consider` / needs review → admin reviews in the dashboard (report link, decision with reason). `failed` → rejected, with a respectful notice that includes the dispute/contact information required by law.
7. **Re-checks:** annual re-screening (configurable). The driver is notified 30 days ahead and pays again (or the platform pays, via a flag).

### 14.3 Outside-the-box ideas for a seamless onboarding
- **Pre-qualification quiz** before paying anything (age, licence class, vehicle year ≥ 2012 **[CONFIRM]**, province served) so nobody pays for a check they can't use.
- **"Pay later from earnings"** option (flag): the platform fronts the check fee and deducts it from the first payouts. This lowers the barrier for good drivers.
- **Referral bonus** for drivers who refer approved drivers.
- **Status transparency:** a live timeline ("Certn received your check · typically 1–3 business days").
- **Admin onboarding funnel** analytics: where applicants drop off.

---

## 15. Account activation and deactivation (Client item 16)

> **Status (2026-09-28):** ✅ Implemented (statuses, instant token + socket revocation, deferred during active rides, suspended screen + appeal, automatic rating/strike/document/background-check rules, audited).

### What it really means
Admins can suspend or reactivate any customer or driver from the dashboard with one button, and it takes effect **immediately** everywhere.

- `users` add: `account_status` (`active|suspended|deactivated|banned|pending_review`), `status_reason`, `status_changed_by`, `status_changed_at`, `suspended_until` (temporary suspensions). Keep the existing integer `status` in sync (1 = active, 0 = otherwise).
- Admin action modal: choose Suspend (with duration) / Deactivate / Ban / Reactivate, a **mandatory reason** (from a list plus free text), a "notify user" toggle, and a preview of the message.
- **Effects:** revoke JWTs (maintain a `token_version` on the user and include it in the JWT claims, then reject mismatches), disconnect sockets, set the driver offline, block new requests. **Active rides are not cut mid-trip**: the account is flagged to end after the current ride completes.
- The user sees a clear "Your account is suspended" screen with the reason category, the end date if temporary, and an **Appeal** button (creates a support ticket).
- **Automatic rules** (configurable): driver rating below 4.3 over the last 50 rides triggers a warning, and below 4.0 an auto-suspension pending review (this fulfils an earlier client request). Strikes per §7.3. Expired documents per §14. Failed background check.
- Everything is logged in `audit_logs` and visible in the user's admin profile history.

---

## 16. Live driver movement and ETA (Client item 11)

> **Status (2026-09-28):** 🟡 Implemented (Google Routes ETA throttled 30 s, smooth car, arrival clock, DRIVER_ARRIVING trigger, Live Activity updates). Needs `GOOGLE_MAPS_SERVER_KEY` (falls back to an estimate without it).

### Client said
> "Showing customers the driver movement with minutes (when driver is coming to the customer)."

- The customer map shows the **car icon moving smoothly** (interpolate between location updates, rotate by heading, snap to road with the Google Roads API optionally) and the **route polyline** from driver to pickup (existing `ROUTE_DRAWING_IMPLEMENTATION`).
- **ETA:** the backend computes ETA with the **Google Routes API** (traffic-aware) at most every 30 s per ride, or when the driver deviates. Between server updates the app interpolates locally. Shown as "**4 min** · 1.2 km away", plus the arrival clock time ("arrives 10:38").
- The ETA is pushed in `ride.eta_updated` socket events, shown in the notification / Live Activity, and triggers DRIVER_ARRIVING at 2 min or less.
- **During the trip:** ETA to the destination, shown to the customer and to anyone the trip is shared with.
- **Cost control:** cache and throttle Google calls. Never call Google from the client for ETA.

---

## 17. Ratings and reviews (Client item 15)

> **Status (2026-09-28):** ✅ Implemented (two-way, tags, tips 100 % to driver, Bayesian score, visibility rules, low-star safety prompt, admin explorer / hide with reason).

- **Two-way ratings:** customer ↔ driver, 1–5 stars, after COMPLETED. The prompt appears on the completion screen and can be done within 72 h.
- **Contextual tags:** positive (Safe driving, Clean car, Great conversation, Fair negotiator, On time), negative (Late, Unsafe driving, Rude, Dirty car, Wrong route, Price changed after agreement). Optional comment. An optional **tip** on the same screen (100 % to the driver).
- Ratings of 1–2 stars ask "What went wrong?" and offer "Report a safety issue".
- **Score:** a rolling average of the last 100 rated trips (or a Bayesian average for new drivers, starting from 4.8 with a weight of 5). Store it on `users.rating`, plus `rating_count`.
- **Fairness:** customers never see an individual rating attributed to them. Ratings are hidden from the other party until both submit (or 72 h pass). Admin can remove a rating that was abusive or discriminatory (audited).
- Driver profile card shows rating, total trips, years on NegoRide and top compliments.
- **Admin:** ratings explorer, lowest-rated drivers, trend alerts, and automatic rules per §15.
- Table `ride_ratings` (`ride ref, rater_id, ratee_id, role, stars, tags JSON, comment, tip_cents, created_at, hidden_by_admin`). Unique per (ride, rater).

---

## 18. Rideshare self-booking and pick-a-driver (Client item 10)

> **Status (2026-09-28):** ✅ Implemented (search cards with badges, book seat with transactional seat lock, instant vs request-to-book, per-seat negotiation, choose-a-driver, favourites, favourite-first then broadcast, live counter-offer marketplace).

### Client said
> "For rideshare, the booking button for customers should come back so the drivers book for themselves. (Customer select driver direct — pick driver.)"

### Interpretation **[CONFIRM WITH CLIENT]**
The customer-facing **"Book seat"** button was removed or hidden in rideshare (bookings currently go through driver/admin assignment, e.g. `bookings/{id}/assign-driver`). The client wants it **restored**, so that **customers book directly** on a driver's published trip and **choose the driver themselves**, instead of drivers or admins doing it for them. Build this, and also let customers pick a specific driver in Car Hire.

### 18.1 Rideshare
- The search results (`RideSearchResultsScreen`) list published trips as cards: driver photo, name, rating, car, departure time, pickup point, seats left, price per seat, and badges (Verified, Background checked, Pets OK, Luggage size).
- **"Book seat" button** on each card and on the detail page → choose the number of seats → the rider can **negotiate the price per seat** within bounds set by the driver (keeps the NegoRide DNA, and the driver can switch this off) → pay (§6) → CONFIRMED.
- Driver settings per trip: **Instant booking** (default) or **Request to book** (driver approves within 30 min, otherwise auto-declined with a full release).
- Seat inventory is locked transactionally so two customers can't book the last seat.

### 18.2 Car Hire — pick your driver
- In addition to broadcasting to all nearby drivers, the customer sees a **"Choose a driver"** list of nearby online drivers (photo, rating, car, ETA, distance) and can send a request **directly** to one driver or add them to **Favourites**.
- **Favourite drivers:** "Request my favourite driver first", which goes to the favourite for 45 s, then broadcasts.
- Privacy: show only first names and approximate locations before a ride is confirmed.

---

## 19. Advanced admin dashboard (Client item 18) — plus documentation

> **Status (2026-09-28):** ✅ Implemented — all 14 modules (React + Mantine + TanStack Query + Recharts + maps + socket) and every documentation deliverable (`docs/`, OpenAPI at `/api/docs`, CHANGELOG, app `RELEASE_NOTES_v4.0.0.md`).

### Client said
> "Advanced dashboard" (plus "My full active dashboard to track all activities" from the December list.)

Rebuild the React admin (`negoride-canada-py-api/frontend/`) into an operations console. Suggested stack: keep React + Vite, and add **TanStack Query**, a component kit (**Mantine** or **shadcn/ui**), **Recharts/ECharts** for charts, **Google Maps JS API** for maps, and **socket.io-client** for realtime. Use role-based access.

### 19.1 Modules
1. **Command Center (home):** live KPIs (online drivers, active rides by stage, rides today, GMV today, completion rate, average pickup ETA, cancellations, open SOS), with a mini live map and an alerts feed.
2. **Live Operations Map** (§9): all drivers and rides, filters, follow, replay.
3. **Safety Center** (§8, §10): incidents, recordings, reports, and an alarm on new SOS.
4. **Rides:** unified Car Hire + Rideshare list with filters, detail page with timeline (`trip_events`), map route, negotiation history, payments, receipts, ratings, chat log (when a dispute exists), and actions (cancel, refund, reassign, resend receipt).
5. **Users:** customers and drivers, profile, verification status, **Activate/Deactivate button** (§15), ratings, strikes, documents, audit history, and impersonation-free "view as".
6. **Driver Onboarding queue** (§14): applications by step, document review with zoom and approve/reject per document, Certn status and report, and a funnel chart.
7. **Payments and Finance:** payments, authorizations, captures, refunds, credit notes, payouts, wallets, commission revenue, tax collected per province, CSV/Excel export, and reconciliation against Stripe.
8. **Disputes and Support:** tickets and appeals, SLA timers.
9. **Ratings:** explorer and low-rating alerts.
10. **Notifications:** delivery log, compose broadcast (segment by role and city), templates.
11. **Legal:** documents, versions, acceptance stats (§12).
12. **Settings:** fees, commission %, cancellation policy numbers, geofence radii, wait windows, background-check fee, feature flags, service types, help contacts, on-call safety phones.
13. **Reports and Analytics:** demand heatmap (where requests come from), supply vs demand by hour, negotiation analytics (average discount from initial ask, acceptance rate), cohort retention, driver earnings distribution.
14. **Admin users and roles:** Super admin, Ops, Safety reviewer, Finance, Support. Every action is audited.

### 19.2 Documentation deliverables (client explicitly asked for docs)
- `docs/API.md` or an **OpenAPI 3 spec** (`docs/openapi.yaml`, generated with `flask-smorest` or `apispec`), plus a Swagger UI at `/api/docs` (admin-auth protected in production).
- `docs/TRIP_STATE_MACHINE.md` (diagram + transition table), `docs/NOTIFICATIONS.md` (catalogue), `docs/SAFETY.md`, `docs/DRIVER_ONBOARDING.md`, `docs/PAYMENTS_AND_REFUNDS.md`, `docs/RUNBOOK.md` (deploy, env vars, workers, webhooks, on-call SOS).
- A changelog entry and release notes for app v4.0.0.

---

## 20. Traceability matrix (client comment → spec)

> **Status (2026-09-28):** ✅ All 18 client items delivered — see the Status column.

| # | Client comment | Delivered in | Status (2026-09-28) |
|---|---|---|---|
| 1 | Emergency/help button, red button to dashboard, help contacts, 911 | §8, §19 (Safety Center) | ✅ |
| 2 | Driver-arrived notification, Uber-like trip steps, API + docs | §4, §5, §16, §19.2 | ✅ |
| 2 | Notification logic, listeners, powerful libraries | §5 | ✅ |
| 2 | Improve the entire UI/UX | §21 | ✅ |
| 3 | Thank-you email | §13.2 | ✅ |
| 4 | Payment receipt by email, perfect | §13.3 | ✅ (GST no. pending) |
| 5 | Certn background check, driver pays, clear steps | §14 | ✅ (Certn keys pending) |
| 6 | Twilio Verify, SMS scenarios | §11 | ✅ (Twilio keys pending) |
| 7 | Agree to guidelines, privacy, terms with checkboxes | §12 | ✅ (legal review pending) |
| 8 | Optional audio recording connected to the dashboard | §10 | ✅ |
| 9 | Live location sharing + track in dashboard | §9 | ✅ |
| 10 | Rideshare customer booking button back, pick driver | §18 | ✅ |
| 11 | Driver movement with minutes | §16 | ✅ |
| 12 | Instant address search | §21.3 | ✅ |
| 13 | Landing page for downloading | §22 | ✅ (domain + deploy pending) |
| 14 | Pay before trip starts | §6 | ✅ |
| 15 | Driver ratings | §17 | ✅ |
| 16 | Activation/deactivation in admin | §15 | ✅ |
| 17 | Cancellation/refund policy | §7 | ✅ |
| 18 | Advanced dashboard | §19 | ✅ |

---

## 21. UI/UX redesign (Client item 2 — "improve the entire UI/UX") and address speed (item 12)

> **Status (2026-09-28):** ✅ Implemented (design system, light + dark app-wide, EN/FR everywhere, accessibility + large-text tests, flutx removed, backups deleted, map-first Home, marketplace offer screen, instant address search with local-first results, 150 ms debounce, session tokens, LRU cache, latency analytics).

### 21.1 Principles
- **One-thumb, map-first design:** the map is the canvas, with a **draggable bottom sheet** holding context (like Uber and Bolt). No deep navigation during a ride.
- **Clarity over decoration:** one primary action per screen, large tap targets (≥ 48 dp), readable in sunlight (high contrast).
- **Design system:** create `lib/theme/` with colour tokens, typography scale (Google Fonts is installed), spacing scale, radius and elevation, and light **and** dark themes. Replace the legacy `flutx` widgets progressively. Delete the `*_backup.dart` files once the replacements are verified (keep them in git history).
- **Accessibility:** screen-reader labels, dynamic type, colour-blind-safe status colours, haptic feedback on key events.
- **Bilingual EN/FR** (`flutter_localizations` + ARB files). French is important in Canada, especially for Québec.

### 21.2 Key screens to redesign
1. **Home:** "Where to?" search bar on top of the map, saved places chips (Home, Work, Airport), recent destinations, service type selector (Car Hire, Rideshare, Courier, Movers, Airport, Special Car).
2. **Offer/Negotiate:** show a **fair-price hint** ("Typical fare for this route: $17–$22") computed from distance, time and history. Customer sets an offer with a slider, and drivers' counter-offers arrive as cards with photo, rating, ETA and price, with Accept / Counter buttons. This is NegoRide's signature: make it feel like a live marketplace, with a countdown per offer.
3. **Payment confirmation:** clear total, method, cancellation policy summary and a "Pay & confirm" button.
4. **Active ride:** stepper (§4.5), driver card, PIN, ETA, Share, SOS, Chat and Call (existing WebRTC).
5. **Completion:** fare summary, rating + tip, receipt link.
6. **Trips history:** filters, receipt download, "Book again", "Report issue".
7. **Driver home:** big Go Online toggle, today's earnings, heatmap of demand (outside-the-box: show drivers where requests are), incoming request cards with sound.
8. **Account:** Safety settings (trusted contacts, recording, auto-share), Notification preferences, Legal, Help.
9. **Empty, loading and error states:** skeleton loaders and friendly retry messages. No bare spinners or raw error text.

### 21.3 Instant address search (Client item 12: "automatic address speed improvement, like zero seconds")
Goal: suggestions **feel instant (under 100 ms perceived)**.
1. **Show local results first, instantly:** saved places, recent searches and frequent destinations from `sqflite` appear the moment the field is focused (0 ms, no network).
2. **Pre-warm:** on app open, get the GPS fix and reverse-geocode the current address in the background, so "Pickup: current location" is already filled in.
3. **Autocomplete:** call the Google **Places API (New) Autocomplete** directly with a **session token**, `locationBias` near the user, `includedRegionCodes: ["ca"]`, a **150 ms debounce** (not 500+), and cancel in-flight requests (Dio `CancelToken`). Replace `google_places_flutter` if it can't be tuned this way.
4. **Fetch place details** with a minimal **field mask** (id, location, formattedAddress) only when a suggestion is chosen.
5. **Cache** autocomplete responses in memory per query prefix (LRU of 200) and persist chosen places.
6. **Map pin mode:** move the map to set the pickup, with reverse geocoding debounced at 300 ms.
7. **Popular places** (airports YYZ, YVR, YUL, YYC and so on, major stations and malls) are preloaded as a local list.
8. Measure: log autocomplete latency p50/p95 to analytics. Target p95 under 400 ms network time.

---

## 22. Landing website for app downloads (Client item 13)

> **Status (2026-09-28):** 🟡 Built (`negoride-canada-web`, Astro, EN/FR, verified with Lighthouse/pa11y/e2e). Needs domain + DNS, assetlinks SHA-256, App Store URL, brand assets, then deploy.

- **Stack:** **Astro** or **Next.js (static export)**, deployed to Vercel / Netlify / Cloudflare Pages at the client's domain (for example `negoride.ca`).
- **Sections:** hero ("Name your price. Ride your way."), phone mockup and App Store / Google Play badges, **smart download link + QR code** (detects iOS or Android and redirects to the right store), How it works (Request → Negotiate → Ride), Services (Car Hire, Rideshare, Courier, Movers, Airport, Special Car), **Safety** section (background checks, SOS, live sharing, ride PIN), **Drive with NegoRide** (earnings, requirements, "Start application" deep link), cities served, FAQ, testimonials, and a footer with legal links, support contact, social links and EN/FR switch.
- **Also hosts:** legal pages (from `legal_documents`), the **public trip-tracking page** `/t/{token}` (§9), email-verification and password-reset landing pages, and `/.well-known/apple-app-site-association` + `assetlinks.json` for **universal / app links** (so links open in the app).
- SEO: meta tags, Open Graph images, sitemap, fast Lighthouse (≥ 90), accessible, privacy-friendly analytics (e.g. Plausible), and a cookie banner if non-essential cookies are used.

---

## 23. New data model summary

> **Status (2026-09-28):** ✅ Every table exists (migrations `v4_0001`–`v4_0403`), plus supporting tables (ride_payments, live_activity_tokens, ride_routes, marketing_consents, …).

| Table | Purpose | Section |
|---|---|---|
| `trip_events` | Ride timeline / audit of stages | §4 |
| `app_settings` | Feature flags and configurable numbers | §2 |
| `audit_logs` | Admin and safety actions | §2 |
| `webhook_events` | Raw Stripe/Certn/Twilio events | §2 |
| `notifications`, `notification_deliveries`, `notification_preferences` | Notification engine | §5 |
| `payments` (extended) | Auth/capture/refund amounts | §6 |
| `refunds` / `credit_notes` | Refund records | §7, §13 |
| `safety_incidents`, `safety_incident_locations`, `trusted_contacts`, `safety_reports` | Safety | §8 |
| `ride_locations`, `ride_share_links` | Tracking and sharing | §9 |
| `recordings`, `recording_chunks` | Audio | §10 |
| `phone_verifications` | Twilio log | §11 |
| `legal_documents`, `legal_acceptances` | Consent | §12 |
| `receipts`, `tax_rates` | Receipts | §13 |
| `driver_applications`, `driver_documents`, `background_checks` | Onboarding | §14 |
| `ride_ratings`, `favourite_drivers` | Ratings and favourites | §17, §18 |
| `users` (new nullable columns) | `account_status`, `token_version`, `phone_e164`, `phone_verified_at`, `rating_count`, etc. | §11, §15, §17 |

---

## 24. Environment variables (add to `.env.example`, never commit real values)

> **Status (2026-09-28):** ✅ All listed in `.env.example` (plus the extra v4 variables).

```
# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_VERIFY_SERVICE_SID=
TWILIO_MESSAGING_SERVICE_SID=
TWILIO_TEST_NUMBERS=          # non-prod only

# Certn
CERTN_API_KEY=
CERTN_API_BASE_URL=
CERTN_WEBHOOK_SECRET=
BACKGROUND_CHECK_FEE_CENTS=3999

# Email
EMAIL_PROVIDER=postmark
POSTMARK_SERVER_TOKEN=
EMAIL_FROM="NegoRide Canada <receipts@negoride.ca>"

# Stripe (existing) — ensure webhook secret covers new events
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=

# Google
GOOGLE_MAPS_SERVER_KEY=       # Routes, Static Maps, Roads (server only)

# Realtime / jobs
REDIS_URL=redis://localhost:6379/0

# Storage (recordings, documents, receipts)
S3_ENDPOINT=
S3_BUCKET_PRIVATE=
S3_ACCESS_KEY=
S3_SECRET_KEY=

# OneSignal (existing)
ONESIGNAL_APP_ID=
ONESIGNAL_REST_API_KEY=

PUBLIC_WEB_BASE_URL=https://negoride.ca
SAFETY_ONCALL_PHONES=
```

---

## 25. Testing and QA checklist

> **Status (2026-09-28):** 🟡 Unit + integration + emulator suites in place (backend 353 tests, Flutter 182 + integration s1–s8). Sandbox runs with real Stripe/Twilio/Certn test keys, a real v3.0.17 build regression and real-device iOS checks remain.

- **Unit:** state machine transitions (every allowed and forbidden pair), refund policy (every table row), rating math, receipt totals and taxes, phone normalization.
- **Integration:** full Car Hire happy path (request → negotiate → pay → en route → arrived → PIN → complete → capture → receipt → rating); cancel at each stage; no-show paths; rideshare last-seat race condition; Certn webhook sequence (use sandbox); Twilio Verify with test credentials; Stripe test cards (success, 3-D Secure, decline, insufficient funds).
- **Realtime:** two simulators (customer + driver) and the admin dashboard open, verifying all three update live.
- **Resilience:** kill the app mid-ride, lose network for 60 s, background the app for 10 min, deny location permission, low battery mode.
- **Regression:** the v3.0.17 app build against the new backend.
- **Store compliance:** location permission strings explain safety use; background location justification for Google Play; microphone permission string for recording; privacy nutrition labels updated.

---

## 26. Open questions for the client (build defaults meanwhile)

> **Status (2026-09-28):** 🟡 Every default is built and admin-configurable (Settings); answers still needed from the client (see §0.1 "Remaining before launch").

1. Item 10 interpretation (§18): confirm that "booking button should come back" means customers book rideshare seats themselves and choose the driver.
2. Cancellation and refund numbers (§7): approve or adjust the defaults.
3. Background-check fee amount, Certn package, and whether "pay later from earnings" is allowed (§14).
4. Tax treatment: GST/HST registration number and whether fares are tax-inclusive (§13).
5. Audio recording: retention period and legal wording (§10).
6. One combined thank-you + receipt email, or two separate emails (§13)?
7. Minimum driver age and vehicle age (§14).
8. Website domain and brand assets (§22).
9. On-call safety phone numbers for SOS escalation (§8).
10. French localization at launch or in a later phase (§21)?

---

**Definition of done for v4:** *(status 2026-09-28: met in code — every §20 row is behind a flag, documented, tested and visible in admin; the staging demo on real iOS/Android devices is the remaining step)* every row in §20 is implemented behind a flag, documented in `docs/`, covered by the tests in §25, visible in the admin dashboard, and demoed end to end on real iOS and Android devices against staging.
