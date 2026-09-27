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

## 2. Deploy (VPS: app dir is not a git repo)

1. Back up: `mysqldump negoride > /root/negoride-backups/<ts>/db.sql` and copy the app dir.
2. Copy changed files (backend/, docs/, scripts/, migrate.py, worker.py, requirements.txt, frontend/build).
3. `.venv/bin/pip install -r requirements.txt` (WeasyPrint needs `libpango-1.0-0 libpangoft2-1.0-0` on Debian/Ubuntu).
4. `.venv/bin/python migrate.py migrate` — v4 migrations are additive and idempotent (`migrate.py status` to review).
5. Add the v4 variables to `.env` (see `.env.example`: REDIS_URL, POSTMARK/EMAIL, TWILIO_*, CERTN_*, GOOGLE_MAPS_SERVER_KEY,
   PRIVATE_STORAGE_KEY or S3_*, PUBLIC_WEB_BASE_URL, SAFETY_ONCALL_PHONES, CORS_ORIGINS). Never commit real values.
6. Create the worker service `negoride-worker.service` (same user/venv/EnvironmentFile as `negoride.service`,
   `ExecStart=/…/.venv/bin/python worker.py`, `Restart=always`), `systemctl enable --now negoride-worker`.
7. `systemctl restart negoride.service`; check `negoride-worker`, and that the neighbours (etag-api, truckfully, school) are still `active`.
8. Smoke test: `GET /api/app/config`, log in, `GET /api/rides/active`, admin Command Center loads, `/api/docs`.
9. Regenerate API docs when routes change: `.venv/bin/python scripts/gen_openapi.py`.

Rollback: restore the copied app dir and restart. Migrations do not need rolling back (additive); if required,
`migrate.py rollback` drops only v4-created columns/tables (never shared ones).

## 3. Webhooks

| Provider | URL | Events / notes |
|---|---|---|
| Stripe | `/api/webhooks/stripe` | `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.expired`, `payment_intent.amount_capturable_updated`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `payment_intent.canceled`. Signing secret → `STRIPE_WEBHOOK_SECRET`. **Add the new events to the existing endpoint.** |
| Certn | `/api/webhooks/certn` | HMAC `X-Signature`; answers the verification challenge. Secret → `CERTN_WEBHOOK_SECRET`. |
| Twilio | `/api/webhooks/twilio/status`, `/api/webhooks/twilio/inbound` | Messaging Service status callback + STOP/HELP. |

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
