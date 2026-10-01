# Trip state machine (spec §4)

Code: `backend/services/trip_state_machine.py` — `transition()` is the **only** function that changes a ride's stage.
Every call locks the ride row (`SELECT … FOR UPDATE`), validates the graph, the actor and the guards, writes
`trip_stage` **and** the legacy `status` (so v3 apps keep working), inserts exactly one `trip_events` row and,
after commit, emits one `ride.stage_changed` realtime event and the catalogue notifications (`trip_effects.py`).

## Car hire (and scheduled bookings)

```
REQUESTED → NEGOTIATING → PRICE_AGREED → AWAITING_PAYMENT → CONFIRMED → DRIVER_EN_ROUTE
   → DRIVER_ARRIVING (auto: ETA ≤ 2 min or ≤ 500 m) → DRIVER_ARRIVED (150 m geofence, wait timer)
   → IN_PROGRESS (Ride PIN) → COMPLETED (capture, receipt) → CLOSED (both rated or 72 h)
Branches: EXPIRED · CANCELLED_BY_CUSTOMER · CANCELLED_BY_DRIVER · CUSTOMER_NO_SHOW · DRIVER_NO_SHOW
Overlays: disputed_at (POST /dispute within 72 h) · payment status on ride_payments / refunds
```

| From | To | Who may request | Legacy `status` written |
|---|---|---|---|
| REQUESTED | NEGOTIATING | customer, driver, system + admin | Active |
| REQUESTED | PRICE_AGREED | customer, driver, system + admin | Accepted |
| REQUESTED | EXPIRED | system + admin | Cancelled |
| REQUESTED | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| REQUESTED | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| NEGOTIATING | PRICE_AGREED | customer, driver, system + admin | Accepted |
| NEGOTIATING | EXPIRED | system + admin | Cancelled |
| NEGOTIATING | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| NEGOTIATING | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| PRICE_AGREED | AWAITING_PAYMENT | customer, driver, system + admin | Accepted |
| PRICE_AGREED | CONFIRMED | system + admin | Accepted |
| PRICE_AGREED | EXPIRED | system + admin | Cancelled |
| PRICE_AGREED | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| PRICE_AGREED | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| AWAITING_PAYMENT | CONFIRMED | system + admin | Accepted |
| AWAITING_PAYMENT | EXPIRED | system + admin | Cancelled |
| AWAITING_PAYMENT | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| AWAITING_PAYMENT | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| CONFIRMED | DRIVER_EN_ROUTE | driver + admin | Started |
| CONFIRMED | DRIVER_NO_SHOW | customer, system + admin | Cancelled |
| CONFIRMED | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| CONFIRMED | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| DRIVER_EN_ROUTE | DRIVER_ARRIVING | driver, system + admin | Started |
| DRIVER_EN_ROUTE | DRIVER_ARRIVED | driver + admin | Started |
| DRIVER_EN_ROUTE | DRIVER_NO_SHOW | customer, system + admin | Cancelled |
| DRIVER_EN_ROUTE | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| DRIVER_EN_ROUTE | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| DRIVER_ARRIVING | DRIVER_ARRIVED | driver + admin | Started |
| DRIVER_ARRIVING | DRIVER_NO_SHOW | customer, system + admin | Cancelled |
| DRIVER_ARRIVING | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| DRIVER_ARRIVING | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| DRIVER_ARRIVED | IN_PROGRESS | driver + admin | Started |
| DRIVER_ARRIVED | CUSTOMER_NO_SHOW | driver, system + admin | Cancelled |
| DRIVER_ARRIVED | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| DRIVER_ARRIVED | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| IN_PROGRESS | COMPLETED | driver + admin | Completed |
| IN_PROGRESS | CANCELLED_BY_CUSTOMER | customer, system + admin | Cancelled |
| IN_PROGRESS | CANCELLED_BY_DRIVER | driver, system + admin | Cancelled |
| COMPLETED | CLOSED | system + admin | Completed |

## Rideshare trip (driver journey)

| From | To | Who may request | Legacy `status` written |
|---|---|---|---|
| DRAFT | PUBLISHED | driver + admin | Active |
| DRAFT | CANCELLED_BY_DRIVER | driver + admin | Canceled |
| PUBLISHED | BOARDING | driver, system + admin | Active |
| PUBLISHED | IN_PROGRESS | driver + admin | Ongoing |
| PUBLISHED | CANCELLED_BY_DRIVER | driver + admin | Canceled |
| BOARDING | IN_PROGRESS | driver + admin | Ongoing |
| BOARDING | CANCELLED_BY_DRIVER | driver + admin | Canceled |
| IN_PROGRESS | COMPLETED | driver + admin | Completed |
| COMPLETED | CLOSED | system + admin | Completed |

Cascades: trip IN_PROGRESS → checked-in bookings RIDING; COMPLETED → riding bookings DROPPED_OFF, never-boarded
bookings NO_SHOW; CANCELLED_BY_DRIVER → every booking CANCELLED_BY_DRIVER (100 % refund, one strike).

## Rideshare seat booking

| From | To | Who may request | Legacy `status` written |
|---|---|---|---|
| REQUESTED | PENDING_PAYMENT | driver, system + admin | Pending |
| REQUESTED | DECLINED | driver, system + admin | Canceled |
| REQUESTED | EXPIRED | system + admin | Canceled |
| REQUESTED | CANCELLED_BY_CUSTOMER | customer + admin | Canceled |
| REQUESTED | CANCELLED_BY_DRIVER | driver, system + admin | Canceled |
| PENDING_PAYMENT | CONFIRMED | system + admin | Reserved |
| PENDING_PAYMENT | EXPIRED | system + admin | Canceled |
| PENDING_PAYMENT | CANCELLED_BY_CUSTOMER | customer + admin | Canceled |
| PENDING_PAYMENT | CANCELLED_BY_DRIVER | driver, system + admin | Canceled |
| CONFIRMED | DRIVER_ARRIVED | driver + admin | Reserved |
| CONFIRMED | CHECKED_IN | driver + admin | Reserved |
| CONFIRMED | NO_SHOW | driver, system + admin | Canceled |
| CONFIRMED | CANCELLED_BY_CUSTOMER | customer + admin | Canceled |
| CONFIRMED | CANCELLED_BY_DRIVER | driver, system + admin | Canceled |
| DRIVER_ARRIVED | CHECKED_IN | driver + admin | Reserved |
| DRIVER_ARRIVED | NO_SHOW | driver, system + admin | Canceled |
| DRIVER_ARRIVED | CANCELLED_BY_CUSTOMER | customer + admin | Canceled |
| DRIVER_ARRIVED | CANCELLED_BY_DRIVER | driver, system + admin | Canceled |
| CHECKED_IN | RIDING | driver, system + admin | Reserved |
| CHECKED_IN | DROPPED_OFF | driver, system + admin | Completed |
| RIDING | DROPPED_OFF | driver, system + admin | Completed |
| DROPPED_OFF | CLOSED | system + admin | Completed |

## Guards

| Guard | Rule | Error code |
|---|---|---|
| Payment secured | CONFIRMED and every later stage require an authorized/captured payment (`ff.pay_before_trip`) | `payment_required` (402) |
| Arrival geofence | DRIVER_ARRIVED only within `ride.arrival_geofence_m` (150 m) of pickup (`ff.arrival_geofence`) | `outside_geofence`, `location_required` |
| Ride PIN | IN_PROGRESS / CHECKED_IN need the customer's 4-digit PIN when `ff.ride_pin` and the customer runs app ≥ 4.0 | `pin_required`, `pin_invalid` |
| Wait window | CUSTOMER_NO_SHOW only after `ride.wait_window_s` (5 min) | `wait_window` |
| Driver no-show | customer may report after ETA + `ride.driver_no_show_grace_s` (15 min) | `too_early` |
| Actor | each target stage lists the roles allowed to request it; admin may request any graph-legal stage (with a reason, audited) | `forbidden_actor` |
| Graph | anything not in the tables above | `invalid_transition` (409) |
| Same stage | double taps | `already_in_stage` (409) |

Invalid requests return `{code: 0, message, data: {error_code, stage, allowed}}` and change nothing.

## Legacy status mapping

Car hire keeps the strings the v3 app already uses: an open negotiation is **`Active`** and a cancelled ride is
**`Cancelled`** (the spec table suggests `Pending`/`Canceled`, but the v3 SSE feed and HomeScreen filter on the
existing values — changing them would break installed apps). Scheduled bookings use their lowercase statuses
(`pending … completed / cancelled`), seat bookings `Pending / Reserved / Completed / Canceled`, trips
`Pending / Active / Ongoing / Completed / Canceled`.

Legacy endpoints (`/api/negotiations-accept` `Started`, `/api/negotiations-complete`, `/api/bookings/{id}/start|complete`,
`/api/trips-booking-status-update`, `/api/trips-update`) call `walk_to()`, which walks the intermediate v4 stages
(one event each, meta `legacy: true`), so v3 and v4 apps produce the same timeline.

## Scheduled jobs (every 30 s — `backend/services/ride_jobs.py`)

Expire unpaid AWAITING_PAYMENT / PENDING_PAYMENT (5 min), expire stale requests (30 min) and unanswered
request-to-book (30 min), detect DRIVER_NO_SHOW, auto DRIVER_ARRIVING, auto-close after 72 h, rideshare BOARDING
30 min before departure.

## API

`GET /api/rides/active` · `GET /api/rides/{type}/{id}` · `GET …/timeline` · `POST …/en-route | arrived | start |
complete | cancel | no-show | driver-no-show | pay | payment/sync | dispute | publish | boarding` · `GET …/cancel-preview`.
`{type}` = `carhire | scheduled | rideshare_trip | rideshare_booking`.


## Admin changes (legacy admin pages included)

Every admin stage change goes through the state machine with `actor_type='admin'` (guards bypassed, graph enforced,
one `trip_events` row per step, reason required and audited):

| Endpoint | What it does |
|---|---|
| `POST /api/admin/rides/{type}/{id}/transition` `{to_stage, reason}` | one graph step |
| `POST /api/admin/rides/{type}/{id}/cancel` `{reason, policy_reason}` | `ride_actions.cancel(actor_type='admin')` |
| legacy `POST /api/admin/negotiations/{id}/update-status`, `/api/admin/trips/{id}/update-status`, `/api/admin/bookings/{id}/update-status` `{status, reason}` | legacy status → target stage (`Accepted` → PRICE_AGREED, or CONFIRMED when paid; `Started`/`Ongoing`/`in_progress` → IN_PROGRESS; `Completed` → COMPLETED; `confirmed` → CONFIRMED; `Active` → PUBLISHED; cancelled → cancel) and `walk_to()`; unpaid payment-gated targets → 402 `payment_required`; unreachable → 409 `invalid_transition` with `data.stage` |
| legacy `POST /api/admin/{negotiations,trips,bookings}/{id}/cancel` `{reason}` | policy cancellation (hold released / fee captured in a job, parties notified) |
| legacy `POST /api/admin/bookings/{id}/mark-paid` `{reason}` | offline `RidePayment` (captured) + walk to CONFIRMED |
| legacy `POST /api/admin/bookings/{id}/assign-driver` | `ride_actions.reassign_driver()` (same as v4 reassign) |

The legacy Stripe `checkout.session.completed` handler for pre-v4 seat bookings also confirms through `walk_to()`.

## Drafts, province, tests

* `POST /api/trips-create` with `publish=false` creates a **DRAFT** (not searchable, not bookable, trip detail
  404 for other users) — publish with `POST /api/rides/rideshare_trip/{id}/publish`.
* `record_creation()` stamps `pickup_province` from the pickup point (`utils/province.py`, offline polygons) for
  every ride type — used for sales tax on receipts.
* `tests/test_state_machine_matrix.py` walks the full (from, to) matrix of all four graphs through `transition()` on
  real rows (legal pairs pass, illegal → `invalid_transition` 409, same stage → `already_in_stage`, unlisted actors
  → `forbidden_actor`), cancellation before payment and after arrival (fee + waiting time) over HTTP, and one
  end-to-end ride from the request to CLOSED (counter-offer → pay → PIN → capture → receipt → both rated).
