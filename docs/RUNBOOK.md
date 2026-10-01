# NegoRide Canada — Operations runbook (v4)

## 1. Components

| Process | Command | Notes |
|---|---|---|
| API (HTTP + Socket.IO) | `gunicorn -k eventlet -w 1 -b 127.0.0.1:5004 wsgi:application` | one eventlet worker (Socket.IO); nginx proxies `/`, `/api`, `/socket.io` (websocket upgrade headers!) |
| Worker | `.venv/bin/python worker.py` | RQ jobs (emails, SMS, pushes, PDFs, Stripe/Certn calls, ETA) **and** the periodic scheduler |
| Redis | `redis-server` | job queue + Socket.IO message queue + rate limits + latest positions |
| MySQL | `negoride` | additive migrations only |

Without Redis the API falls back to in-process threads (`JOB_MODE=thread`) and `RUN_SCHEDULER=1` runs the
periodic jobs inside the API — acceptable for a single small box, not recommended for production.

## 2. Deploy

Follow [LIVE_DEPLOYMENT.md](LIVE_DEPLOYMENT.md) for the verified production layout, release gates, backups,
schema-only migration rehearsal, staged cutover, smoke checks, Redis/worker setup, and rollback. Do not use
`migrate.py rollback` as a routine deployment rollback: MySQL DDL may be non-transactional, and down migrations
can delete data written after deployment. Restore application code independently; recover the database only as
an incident response after reviewing writes made since the backup.

Regenerate API docs when routes change: `.venv/bin/python scripts/gen_openapi.py`.

## 3. Webhooks

| Provider | URL | Events / notes |
|---|---|---|
| Stripe (Connect) | `/api/webhooks/stripe` | Second endpoint for **connected accounts** (`transfer.created`, `transfer.paid`, `transfer.reversed`, `payout.paid`, `payout.failed`) → `payout.sent` pushes. Its signing secret → `STRIPE_CONNECT_WEBHOOK_SECRET`. |
| Stripe | `/api/webhooks/stripe` | `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.expired`, `payment_intent.amount_capturable_updated`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`. Signing secret → `STRIPE_WEBHOOK_SECRET`. **Add the new events to the existing endpoint.** |
| Certn | `/api/webhooks/certn` | HMAC `X-Signature`; answers the verification challenge. Secret → `CERTN_WEBHOOK_SECRET`. |
| Twilio | `/api/webhooks/twilio/status`, `/api/webhooks/twilio/inbound` | Messaging Service status callback (provider `twilio_status`) + STOP/HELP (provider `twilio`). |
| Postmark | `/api/webhooks/postmark` | Delivery, Open, Bounce, SpamComplaint; basic auth `POSTMARK_WEBHOOK_USER` / `POSTMARK_WEBHOOK_PASSWORD` in the URL. Hard bounces suppress email for the user (`admin_users.email_bounced_at`). |

All webhooks store the raw event in `webhook_events` first (unique id) and are processed by the worker;
failed ones retry automatically (`platform_jobs.retry_failed_webhooks`, 5 attempts). Admin → Payments → Webhook events.

## 4. Feature flags

Every v4 feature is behind `ff.*` in Admin → Settings (effective within 5 s, no deploy). Suggested rollout:
notifications → pay-before-trip → receipts → safety → identity/onboarding → experience features.
`GET /api/app/config` shows what apps see.

## 5. On-call: SOS

1. A new SOS plays an alarm and shows a red banner in the admin (Safety Center, `admin:sos` socket room).
2. **Acknowledge within 60 s** — otherwise the system SMSes and calls `safety.oncall_phones`.
3. Open the incident: live location (3 s updates), ride, vehicle, parties. Use *Call* (audited) to reach the user.
   If there is danger to life, call **911** with the location shown.
4. Add notes, resolve or mark false alarm. Export the incident PDF for police/insurance when asked.
5. Recordings attached to incidents are kept (legal hold) — only safety reviewers can play them; every play is audited.

## 6. Money incidents

* Captures failing: Admin → Payments → ride payments with `failure_reason`; retry by re-running the completion job
  (`jobs.enqueue('backend.services.trip_effects.complete_payment_and_receipt', type, id)` in a flask shell).
* Authorizations expire after ~7 days — rides confirmed but not completed within that window need a new payment.
* Refund: Admin → Rides → ride → Refund (reason required, idempotent, audited, credit note emailed).
* Reconciliation: Admin → Finance → Reconciliation compares `ride_payments` with Stripe.

## 7. Monitoring checklist (daily)

`webhook_events` with status `failed`, `notification_deliveries` failure rate by channel, open SOS/incidents,
disputes past SLA, drivers with expiring documents, background checks stuck in `pending` > 3 days, worker alive
(`systemctl status negoride-worker`), Redis memory.

## 8. Privacy (PIPEDA / Québec Law 25)

Admin access to personal data is written to `audit_logs`. Retention: ride breadcrumbs 90 days, recordings 7 days
(unless held), background-check reports stay with Certn (links are short-lived). Data-subject requests: export the
user's rows from the admin (user profile → history) and delete via the account deletion flow.

## 9. Identity hardening switches (admin → Settings)

| Setting | Default | Effect |
|---|---|---|
| `app.legacy_clients_allowed` | `true` | `false` = every client is treated as v4 (a missing `X-App-Version` no longer skips consent ticks at registration, phone-required sign-up, sensitive-action OTP, the unverified `update-phone` fallback or the legal re-acceptance gate). Turn off once the v4 app is the store minimum (`app.min_supported_version`). |
| `legal.enforce_reacceptance` | `true` | v4 requests answer 403 `legal_pending` until a policy version published with "requires re-acceptance" is accepted (exempt: legal, account, users/me, app config, notifications, devices, rides, support, safety/SOS, tracking, calls, stream, verify, delete-account). |
| `otp.allowed_nanp_regions` | empty | +1 Caribbean/territory area codes are refused (SMS-pumping). List area codes or ISO codes (e.g. `876,JM`) to allow some. |
| `onboarding.bgc_start_delay_min` | 30 | cancel + refund window before Certn is ordered. |
| `onboarding.rideshare_endorsement_provinces` | `ON,BC,AB,QC` | provinces where the insurance upload needs the rideshare-endorsement attestation. |
| `onboarding.face_match_threshold` | 90 | Rekognition similarity flagged `match` (advisory only). |

Admin status changes from the legacy users page (`toggle-status`, user editor `status`) now require
`reason_code` (from `/api/admin/account-status/reasons`) and `reason_text`; the legacy editor no longer sets
`ready_for_trip` (drivers go online through the `can_go_online` gate).

## 10. Twilio console setup (phone verification, spec §11.2 #10/#13)

Do this once per Twilio account (Console → the sections named below). The code enforces CA/US-only and the premium
blocklist too, but the console settings stop fraud before a message is billed.

1. **Verify service** (Verify → Services → *NegoRide*; SID → `TWILIO_VERIFY_SERVICE_SID`)
   * Code length 6, expiry 10 min (defaults), friendly name "NegoRide".
   * **Fraud Guard**: on (Verify → Services → *NegoRide* → Fraud Guard; "Standard" or "Max" protection). It blocks
     SMS-pumping traffic automatically; review blocked attempts in the Fraud Guard dashboard weekly.
   * **Geo permissions for Verify** (Verify → Settings → Geo permissions): allow **Canada** and **United States**
     only; untick every other country, including the +1 Caribbean destinations (Jamaica, Dominican Republic,
     Bahamas, Puerto Rico, Trinidad & Tobago …). If `otp.allowed_nanp_regions` is ever widened, enable the same
     countries here.
   * Voice channel ("Call me instead"): Voice → Settings → Geo permissions → Canada + United States only;
     disable "high-risk special services" / premium numbers.
   * Rate limits (Verify → Services → Rate limits) as a second line: e.g. 5 / phone / hour and 10 / IP / hour,
     matching `otp.max_sends_per_phone_h` / `otp.max_sends_per_ip_h`.
2. **Messaging** (transactional SMS: driver arrived, trip share, SOS, phone-changed notice)
   * Messaging → Settings → Geo permissions: Canada + United States only.
   * Messaging Service (SID → `TWILIO_MESSAGING_SERVICE_SID`) with the sender pool below; **Opt-Out Management →
     Advanced Opt-Out** on, with EN + FR STOP/START/HELP replies (STOP/ARRET, START, HELP/AIDE). Our inbound
     webhook (`TWILIO_INBOUND_URL` = `https://<api>/api/webhooks/twilio/inbound`) records STOP/START on the user
     (`sms_opt_out_at`, marketing withdrawal proof row) and answers HELP.
   * Status callback → `https://<api>/api/webhooks/twilio/status` (`TWILIO_STATUS_CALLBACK_URL`).
3. **Canadian sender**: add a Canadian **long code** (local 10-digit number; no 10DLC registration in Canada, but
   keep volumes person-to-person-like) **or** a **toll-free** number — toll-free numbers must pass **Toll-Free
   Verification** (Phone Numbers → Regulatory Compliance → Toll-Free Verification: business info, use case
   "account notifications / 2FA", sample messages, opt-in description = "user enters their phone number in the
   NegoRide app"). Unverified toll-free traffic to CA/US is blocked. US recipients from a US long code need A2P 10DLC
   registration; prefer toll-free for mixed CA/US traffic.
4. **Android SMS Retriever (auto-fill)**: the app computes its 11-character app hash from the **release signing
   certificate** (with Play App Signing, the Play-generated certificate — not the upload key; debug builds have a
   different hash). Put the release hash in `TWILIO_ANDROID_APP_HASH` (the app may also send `app_hash` in
   `POST /api/verify/phone/start`, which takes precedence). The API forwards it to Verify as `AppHash` (SMS only),
   and Twilio appends it to the message so the code is read automatically. iOS needs nothing (one-time-code
   autofill works with the default Verify template).
5. **Lookup** (line type intelligence) must be enabled on the account — driver numbers whose line type cannot be
   looked up are refused in production (`line_type_unknown`), VoIP numbers are refused for drivers
   (`otp.block_voip_drivers`) and flagged at customer sign-up (`line_type_warning: "voip"`).
6. Test mode for App Store / Play reviewers: set `TWILIO_TEST_NUMBERS` + `TWILIO_TEST_MODE_ENABLED=1` only on a
   staging server with `FLASK_ENV=development|testing` — never in production.


## 9. Launch readiness & new periodic jobs (v4.2)

* **Admin → Readiness** (`GET /api/admin/readiness`) lists launch blockers: empty GST/HST number with tax-inclusive
  fares, placeholder company address, empty on-call / support phones, missing Twilio / Postmark / Certn / Google /
  Stripe / OneSignal keys, `PAYMENTS_GATEWAY=fake`, Redis missing in production, `PUBLIC_WEB_BASE_URL` unset.
* The API logs a **critical** warning at start when `FLASK_ENV=production` and Redis is absent/unreachable, and an
  error when `REDIS_URL` is set but `redis`/`rq` cannot be imported.
* New periodic jobs (`jobs/scheduler.py`): `receipt_jobs.sweep_missing_receipts` (60 s),
  `payment_service.auto_release_safety_holds` (5 min). Counter-offer expiry runs inside `experience_jobs.tick`.
* Safety-ended rides keep the card hold for `safety.settle_hold_h` (24 h): decide them in Admin → Rides → ride →
  "Settle safety" (charge a pro-rated amount or 0), otherwise they are released automatically.
* Replace `backend/static/brand/logo.png` with the final logo (emails + PDFs). Set `APP_URL` (logo URL) or `EMAIL_LOGO_URL`.
* `BACKGROUND_CHECK_FEE_CENTS` seeds the default background-check fee (an admin setting still wins).
* Migrations `v4_0402_ops_gaps`, `v4_0403_counter_offers` (additive). `pip install -r requirements.txt` adds `openpyxl`.
