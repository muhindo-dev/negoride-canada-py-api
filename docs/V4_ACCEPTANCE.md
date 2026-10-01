# NegoRide v4 — acceptance & traceability

Maps every client item (spec §20) and every acceptance checkbox to where it is implemented and how it is
verified. Backend tests: `.venv/bin/python -m pytest -q` (local MySQL, no external calls). App tests:
`flutter test`. Admin/website: verified in headless Chrome against the real API.

## Client items (spec §20)

| # | Client item | Backend | Admin | App | Website | Verified by |
|---|---|---|---|---|---|---|
| 1 | Emergency/help button, red button to dashboard, help contacts, 911 | `routes/safety.py`, `services/safety_service.py`, `safety_jobs.py` (60 s escalation), `help_contacts` | Safety Center with alarm + banner | Safety Toolkit sheet (hold-to-call 911, SOS, help contacts incl. 988) | — | `tests/test_safety.py`, admin browser test (banner in ≈300 ms), `safety_call_911_test.dart` |
| 2 | Driver-arrived notification, Uber-like steps, API + docs | `trip_state_machine.py`, `trip_effects.py`, `/api/rides/*` | Rides timeline, Command Center | ActiveRideScreen (stepper / contextual driver button / PIN / wait timer) | — | `tests/test_carhire_flow.py`, live socket E2E (driver_arrived in 1.1 s), `docs/TRIP_STATE_MACHINE.md` |
| 2 | Notification logic, listeners, libraries | `services/notify/*`, Socket.IO `/rt` | Notifications log, templates, broadcast | NotificationCenter, inbox, preferences, deep links | — | `tests/test_notifications_realtime.py`, `docs/NOTIFICATIONS.md` |
| 2 | Improve the entire UI/UX | — | new console | `lib/theme`, EN/FR, map-first Home, redesigned flows | — | Flutter widget tests, analyzer |
| 3 | Thank-you email | `services/receipts.py` (combined email) | resend | — | — | `tests/test_receipts.py` |
| 4 | Payment receipt by email, perfect | receipts + credit notes + PDF (WeasyPrint), tax by province | Finance module | Receipt screen + PDF | — | totals email = PDF = API = Stripe to the cent (`test_receipts.py`) |
| 5 | Certn background check, driver pays, clear steps | `services/onboarding_service.py`, `certn_client.py` (CertnCentric API), webhook + polling | Onboarding queue, adjudication, funnel | 7-step wizard | Drive section | `tests/test_onboarding.py` |
| 6 | Twilio Verify, SMS scenarios | `services/phone_verification.py`, `routes/verify.py` (14 scenarios) | — | OTP screen (autofill, voice fallback) | — | `tests/test_identity.py`, `otp_input_test.dart` |
| 7 | Guidelines / privacy / terms checkboxes | `services/legal_service.py`, 8 documents EN/FR, acceptances with version/IP/app version | Legal editor, acceptance stats | Sign-up with 3 unticked boxes, reader, re-acceptance modal | /terms /privacy /guidelines … | `consent_gating_test.dart`, identity tests |
| 8 | Optional audio recording to dashboard | `services/recording_service.py`, encrypted private storage, 7-day retention | Recordings tab (safety_reviewer, audited) | Record button, chunk queue, banner for other party | — | safety tests, `recording_chunk_queue_test.dart` |
| 9 | Live location sharing + track in dashboard | `services/live_share.py`, `tracking.py`, `/api/public/track` | Live Operations Map + replay | Share trip | `/t/{token}` | safety tests, website mock test |
| 10 | Rideshare booking button back, pick driver | `rideshare_service.py`, `routes/rideshare_v4.py`, `routes/carhire_v4.py` | — | Rideshare search/book, choose-a-driver, favourites | — | `tests/test_rideshare_v4.py` (last-seat race), `test_carhire_v4.py` |
| 11 | Driver movement with minutes | `services/eta.py` (Google Routes, throttled), `ride.eta_updated` | — | smooth car + "4 min · 1.2 km" + Live Activity | tracking page ETA | `tests/test_eta.py` |
| 12 | Instant address search | `/api/places/popular`, analytics latency p50/p95 | Latency report | local-first search, 150 ms debounce, session tokens, LRU | — | `experience_address_search_test.dart` |
| 13 | Landing page for downloads | — | — | — | Astro site EN/FR, smart download, QR | Lighthouse 96–100 |
| 14 | Pay before trip starts | `payment_service.py` (manual capture) + hard guard | Payments | Pay & confirm sheet | — | `test_payment_bypass_is_impossible` |
| 15 | Driver ratings | `ratings_service.py` (Bayesian, visibility, tips) | Ratings explorer, hide | Rate & tip screen | — | `tests/test_ratings.py` |
| 16 | Activation/deactivation in admin | `services/account_service.py` (token_version revocation, deferred during rides) | Users → status modal | Suspended screen + appeal | — | `tests/test_account_status.py` |
| 17 | Cancellation/refund policy | `refund_policy.py` (pure), settlement, policy document | Settings (numbers), refunds | Cancel sheet with fee preview | /cancellation-policy | `tests/test_refund_policy.py` (every row) |
| 18 | Advanced dashboard | `admin_v4.py`, `admin_safety.py`, `admin_finance.py`, `admin_identity.py`, `admin_experience.py` | 14 modules | — | — | headless Chrome run of every module |

## Acceptance checkboxes

| Spec | Criterion | Status |
|---|---|---|
| §4.6 | Invalid transitions return code 0 and change nothing | ✅ `test_full_happy_path`, unit graph tests |
| §4.6 | "I've arrived" rejected > 150 m | ✅ geofence test |
| §4.6 | One trip_events row, one realtime event, configured notifications per transition | ✅ happy-path + live E2E (unique event ids) |
| §4.6 | Legacy status correct; v3 app works end to end | ✅ `test_legacy_v3_flow_still_works`, legacy endpoint script |
| §4.6 | Kill/reopen app mid-trip returns to the right screen | ✅ `/api/rides/active` + app restore on launch (unit tested; device test pending) |
| §5.5 | Driver arrived < 3 s via socket/push, SMS fallback within 60 s | ✅ 1.1 s measured live; escalation test |
| §5.5 | Every notification in inbox + admin log with delivery status | ✅ |
| §5.5 | Tap from killed app opens the right screen | ✅ cold-start queue in DeepLinkRouter (device test pending) |
| §5.5 | Mute marketing/non-critical; safety/transactional always delivered | ✅ preferences tests |
| §6 | Driver can't pass CONFIRMED until authorized (backend test, app bypassed) | ✅ |
| §8.5 | SOS on dashboard < 2 s with live updates | ✅ ≈300 ms in admin browser test |
| §8.5 | 911 needs a deliberate gesture, works offline | ✅ 3-s hold/slide, `tel:` dialer |
| §8.5 | SOS works with ended/no ride | ✅ safety tests |
| §12 | Impossible to register without 3 ticks; stored with version/timestamp/IP | ✅ (for v4 clients; v3 clients keep working — deliberate) |
| §13.4 | Totals match to the cent across email/PDF/app/Stripe | ✅ automated |
| §13.4 | Receipt within 60 s; resend reuses the number | ✅ (~1 s) |
| §13.4 | Renders in Gmail/Outlook/Apple Mail light+dark | ⚠️ table-based, dark-mode-safe HTML; needs a real-client check (Litmus/Email on Acid) before launch |

## Deliberate deviations

* Car hire legacy `status` keeps `Active` / `Cancelled` (v3 app depends on them) instead of `Pending` / `Canceled`.
* Email templates are hand-written responsive table HTML + Jinja2 instead of an MJML build step (same output, no Node dependency on the server).
* Consent-at-registration is enforced for v4 clients (`X-App-Version ≥ 4.0.0`); v3 builds can still register until they update.
* Route deviation uses a pickup→drop-off corridor (no route polyline is stored).
* Saved card / one-tap payment (§6.6, "later") not built.

## Needs the client before launch (§26)

Twilio (Verify + Messaging), Certn (API key, package, webhook secret), Postmark (or keep SMTP), Google server + browser keys,
Redis + worker service on the VPS, `PRIVATE_STORAGE_KEY` or S3, on-call SOS phones, GST/HST (+QST) numbers and tax-inclusive
confirmation, fees (cancellation, no-show, background check), minimum driver/vehicle age, legal review of the 8 documents,
website domain (+ `CORS_ORIGINS`, AASA/assetlinks fingerprint), App Store URL, brand assets, launch cities, French review.
