# NegoRide v4 — Backend developer guide

How the v4 foundation works and the rules every feature must follow. Read this
before adding code. Spec: `NEGORIDE_CANADA_V4_UPGRADE_SPEC.md` (repo root of the
mobile app and this repo).

## Run

```bash
.venv/bin/python migrate.py migrate            # apply v4_* migrations (idempotent)
.venv/bin/python run.py                        # API on :5001 (SERVER_PORT)
.venv/bin/python worker.py                     # RQ worker + periodic scheduler (needs REDIS_URL)
RUN_SCHEDULER=1 .venv/bin/python run.py        # single-box dev: scheduler inside the API
.venv/bin/python -m pytest -q                  # tests (local MySQL, no external calls)
PAYMENTS_GATEWAY=fake .venv/bin/python run.py  # local QA without Stripe (never in production)
```

## Conventions

| Topic | Rule |
|---|---|
| Envelope | `{code: 1|0, message, data}` via `success_response` / `error_response` / `paginated_response`. Errors put a machine code in `data.error_code`. |
| Money | **Integer cents, CAD** in all v4 tables. Helpers in `backend/utils/money.py` (`pct_of`, `bp_of`, `fmt`, `to_cents`). Never float math. Legacy `negotiations.agreed_price` (DECIMAL) actually holds cents; use `rides.fare_cents()`. Wallet ledger (`user_wallets`, `transactions`) is DOLLARS — go through `wallet_service` only. |
| Time | Store naive **UTC** (`datetime.utcnow()`); v4 JSON uses ISO-8601 `...Z` (`models/base.iso`). |
| Schema | Additive only. New migration per change: `backend/database/migrations/v4_NNNN_name.py` using `backend/database/schema_helpers.py`. The local DB is shared with the Truckeroo backend — never drop columns you didn't create. |
| Models | v4 models subclass `SerializeMixin` (column-driven `to_dict()`, `_hidden` for secrets). |
| Auth | `@jwt_required_with_user` (user first arg), `@admin_role_required('ops', ...)` (roles: super_admin, ops, safety_reviewer, finance, support; super_admin passes all), tokens from `issue_token(user)` (carries `tv` = token_version for revocation). Suspended users get 403 `data.error_code=account_blocked` except on `INACTIVE_ALLOWED_PREFIXES` (a revoked token of an inactive account gets the same 403; other revocations 401 `session_revoked`); `issue_restricted_token(user)` = 2 h token limited to those prefixes. v4 requests also pass the legal re-acceptance gate (`legal_service.gate_response`, 403 `legal_pending`, exempt prefixes in `REACCEPT_EXEMPT_PREFIXES`). v4-only rules use `client_info.is_v4_client()` — it is true for every client when `app.legacy_clients_allowed` is off. Ride/booking creation calls `phone_verification.require_phone_for_rides(user, data)` (`ff.phone_required_signup`). |
| Idempotency | Add `@idempotent` (after the auth decorator) to state-changing endpoints; honours the `Idempotency-Key` header. |
| Audit | `backend.services.audit.audit(action, actor, entity_type, entity_id, before, after, meta)` for every admin action, safety event and admin access to personal data. Caller commits. |
| Settings / flags | `backend.services.settings_service` — `S.flag('sos')`, `S.get_int('ride.wait_window_s')`. Add new keys to `DEFAULTS` (key: default, type, category, description, public). Public keys are served to apps at `GET /api/app/config`. |
| Jobs | Never do email/SMS/push/PDF/HTTP-to-vendors inside a request. `from backend import jobs`; `jobs.enqueue_after_commit('dotted.path', *args)` (runs only if the transaction commits), `jobs.enqueue_in(seconds, path, ...)`, `jobs.enqueue(path, ...)`. Periodic tasks: add `(interval_s, 'dotted.path')` to `backend/jobs/scheduler.py:PERIODIC`. Modes: rq (Redis), thread, eager (tests). |
| Realtime | `backend.services.realtime`: `to_user(uid, event, data)`, `to_ride(type, id, event, data)`, `to_admins(event, data, room='admin:ops'|'admin:sos')`. Socket.IO namespace `/rt`, JWT on connect. |
| Notifications | `from backend.services.notify import notify`; `notify('ride.driver_arrived', [user_id], context)`. Add events to `services/notify/catalogue.py` (group, channels, critical, route, EN/FR copy). Queued after commit; inbox + deliveries logged; SMS escalation for critical events. |
| Admin alerts / Live Activities | `notify_admins(event, ctx, roles=('ops',))` for ops-console notifications; `notify.live_activity.push_update(ride_type, ride_id, payload)` to refresh iOS Live Activities (never raises). |
| Payment states | Use `models.money.CAPTURED_STATES` / `rp.took_money` for "money was captured" (the refund overlay adds `partially_refunded` / `refunded`). |
| Vendors | Twilio: `services/twilio_client.py`. Email: `services/notify/email_provider.send(to, subject, html, text, attachments=[(name, bytes, mime)])`, templates in `backend/templates/email/` rendered by `services/notify/templates.render(name, ctx)`. Payments: `services/payments/payment_service.py` (never call Stripe directly). |
| Webhooks | Verify signature → insert `WebhookEvent(provider, event_id unique)` → `jobs.enqueue(processor, row.id)` → return 200. Retries by `platform_jobs.retry_failed_webhooks` (add your provider path there). |

## Rides

`backend/services/rides.py` is one adapter over four models:

| ride_type | model | stages |
|---|---|---|
| `carhire` | Negotiation | REQUESTED → NEGOTIATING → PRICE_AGREED → AWAITING_PAYMENT → CONFIRMED → DRIVER_EN_ROUTE → DRIVER_ARRIVING → DRIVER_ARRIVED → IN_PROGRESS → COMPLETED → CLOSED (+ EXPIRED, CANCELLED_BY_CUSTOMER/DRIVER, CUSTOMER_NO_SHOW, DRIVER_NO_SHOW) |
| `scheduled` | ScheduledBooking | same graph as carhire |
| `rideshare_trip` | Trip | DRAFT → PUBLISHED → BOARDING → IN_PROGRESS → COMPLETED → CLOSED (+ CANCELLED_BY_DRIVER) |
| `rideshare_booking` | TripBooking | REQUESTED → PENDING_PAYMENT → CONFIRMED → DRIVER_ARRIVED → CHECKED_IN → RIDING → DROPPED_OFF → CLOSED (+ DECLINED, EXPIRED, NO_SHOW, CANCELLED_*) |

Helpers: `R.load(type, id, lock=False)`, `R.role_of(user, type, ride)`, `R.customer_ids`, `R.driver_id`,
`R.pickup_point`, `R.dropoff_point`, `R.addresses`, `R.fare_cents`, `R.current_stage`, `R.user_card`, `R.vehicle_card`, `R.haversine_m`.

### State machine — `backend/services/trip_state_machine.py`

* `transition(ride_type, ride_id, to_stage, actor=user|None, actor_type=None, lat=, lng=, pin=, meta={}, commit=True)`
  is the ONLY way to change a stage. Raises `TransitionError(message, code, status, data)`.
* `record_creation(ride_type, ride, actor, actor_type, stage=None)` — opening event for a new ride (caller commits).
* `walk_to(...)` — legacy endpoints walk intermediate stages (one event each).
* `ride_actions.cancel(ride_type, id, actor, reason=..., reason_code=, note=)` applies `refund_policy` and moves to the right terminal stage; money moves in a job.
* Hooks: `@TSM.on_transition` (inside the transaction, fast) and `@trip_effects.after_hook` (after commit, in a job: `fn(event, ride)`). Location hooks: `@tracking.location_hook` → `fn(user, ride_type, ride, point)`.
  Location hooks get only the LIVE point; recent points for a ride/user come from `tracking.recent_points(...)`
  (breadcrumbs are buffered and bulk-inserted every few seconds, so don't read `ride_locations` for "the last point").
* `R.vehicle_card(driver, ride_type=, ride=, viewer=)` adds a short-lived `photo_url` (vehicle_front) for ride parties
  of a confirmed ride; without those kwargs it is unchanged.
* Safety hooks for other areas: `safety_service.readiness_checks()`, `safety_service.mark_dispute_resolved(type, id)`
  (see docs/SAFETY.md). ETA calls `notify.live_activity.push_update(type, id, payload)` when that module exists.

### Payments — `backend/services/payments/payment_service.py`

`start_payment` (Checkout, `capture_method=manual`), `record_intent` (webhook/poll → CONFIRMED),
`capture_for_completion`, `settle_cancellation`, `manual_refund`, `start_extra_payment(purpose='tip'|'background_check', ...)`.
Tip → driver wallet credit; `background_check` → calls `onboarding_service.on_background_check_fee_paid(rp)`.
Tests use `FakeGateway` (`gw.simulate_customer_pays(session_id)` returns a Stripe-shaped event).

## HTTP API added by the foundation

Rides: `GET /api/rides/active`, `GET /api/rides/{type}/{id}`, `/timeline`, `POST .../en-route|arrived|start|complete|publish|boarding|cancel|no-show|driver-no-show|pay|payment/sync|dispute`, `GET .../cancel-preview`.
Notifications: `GET /api/notifications`, `/unread-count`, `POST /api/notifications/{id}/read|opened`, `/read-all`, `GET|PUT /api/notification-preferences`, `POST /api/devices/register`, `GET /api/app/config`.
Admin: `/api/admin/settings`, `/audit-logs`, `/notifications` (+`/stats`, `/broadcast`), `/rides` (+ detail, `/transition`, `/cancel`), `/ride-payments` (+`/{id}/refund`), `/refunds`, `/webhook-events`, `/command-center`, `/alerts`.

## Tests

`tests/conftest.py` gives `client`, `auth(user)`, `make_user('customer'|'driver'|'admin')`, `sign_stripe(payload)`.
Everything is created under throw-away `v4test_*` users and deleted at session end. MySQL runs
REPEATABLE READ: call `db.session.rollback()` before re-reading rows that a request/job changed.
