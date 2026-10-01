# Payments and refunds

> Spec: `NEGORIDE_CANADA_V4_UPGRADE_SPEC.md` §6 (pay before trip), §7 (cancellation and refunds), §13 (receipts), §19.1.7 (finance admin).
> All amounts are **integer cents, CAD**.

<!-- The authorization / capture / cancellation / refund-engine section is maintained by the lead (payment_service.py). -->

## 1. Pay before the trip (spec §6)

Code: `backend/services/payments/payment_service.py`, provider layer `gateway.py`. Money: integer cents, CAD.

| Step | What happens |
|---|---|
| PRICE_AGREED | State machine auto-moves to **AWAITING_PAYMENT** (5-min timeout, setting `ride.payment_timeout_s`). If `ff.pay_before_trip` is off it goes straight to CONFIRMED (pay later). |
| Customer taps *Pay & confirm* | `POST /api/rides/{type}/{id}/pay` (v3: `/api/negotiations-refresh-payment`) → `RidePayment` + Stripe Checkout with `payment_intent_data.capture_method=manual` (an authorization **hold**). Amount = fare + `pricing.booking_fee_cents`. |
| Stripe `checkout.session.completed` / `payment_intent.amount_capturable_updated` | Webhook stores the raw event in `webhook_events` (unique event id) and processes it in a job: `record_intent()` → `capture_status=authorized`, `auth_expires_at` from `capture_before`, legacy `stripe_paid='Yes'` for v3 apps, ride → **CONFIRMED**, Ride PIN generated. Polling fallback: `/payment/sync` or v3 `/api/negotiations-check-payment`. |
| Hard rule | `trip_state_machine` refuses CONFIRMED, EN_ROUTE, ARRIVED, IN_PROGRESS and COMPLETED unless the payment is secured — enforced server-side for v3 and v4 endpoints (test `test_payment_bypass_is_impossible`). |
| COMPLETED / DROPPED_OFF | Job `capture_for_completion()` captures (never more than authorized), credits the driver wallet net of `pricing.commission_pct` (idempotent reference `earning-neg-{id}` / `earning-booking-{id}` / `earning-scheduled-{id}`), then issues the receipt. |
| Paid after the ride expired | Hold released (or refunded) immediately. |
| Far-future bookings | Rideshare seats and scheduled rides more than `rideshare.charge_now_after_days` (6) ahead are charged immediately (`capture_method=automatic`) because card holds expire after ~7 days; refunds then follow policy. |

Tips and background-check fees use `start_extra_payment()` (immediate capture). Tips credit 100 % to the driver.

### Payment status overlay, failures, offline payments

* **Refund overlay (§4.1 REFUNDED / PARTIALLY_REFUNDED)**: after a money-back refund `capture_status` becomes
  `partially_refunded` or `refunded` (pre-refund value in `meta.capture_status_before_refund`). Code that means
  "money was captured" uses `models.money.CAPTURED_STATES`; `is_secured` = authorized / captured /
  partially_captured / partially_refunded. The ride API exposes `payment.refund_status`.
* **Failures**: a declined card (`requires_payment_method`, e.g. `insufficient_funds`) → `capture_status='failed'`,
  `meta.decline_code`; 3-D Secure pending (`requires_action`) → stays `pending`, `failure_reason='authentication_required'`.
  Both send `payment.failed` once per attempt (with `reason` / `action_required`); the ride stays
  AWAITING_PAYMENT / PENDING_PAYMENT and the customer retries with `POST …/pay {force_new: true}`. `FakeGateway.simulate_customer_pays(session, decline=True|'insufficient_funds'|'expired_card', requires_action=True)`.
* **Offline payments** (admin mark-paid): `RidePayment(provider='offline', capture_method='offline',
  capture_status='captured')`; completion credits the driver as usual; refunds are recorded without calling Stripe
  (ops returns the money the way it was received); reconciliation skips them.

### Safety endings (§7.1 "pro-rated or $0 after admin review")

A cancellation with rule `safety_review` does **not** move money: the payment gets `settlement_status='safety_review'`
and `settle_due_at = now + safety.settle_hold_h` (24 h), the admin room gets `payment.safety_review`. The admin decides
with `POST /api/admin/rides/{type}/{id}/settle-safety {amount_cents, reason}`: an authorized hold is partially captured
(rest released) or cancelled; captured money is refunded down to `amount_cents`; the driver is credited the fare share
of the charged amount (net of commission), a receipt is issued when something was charged, `refund.issued` goes to the
customer, audit `payment.safety_settlement`. `payment_service.auto_release_safety_holds` (every 5 min) releases holds
nobody decided in time (`settlement_status='auto_released'`).

## 2. Cancellation & refund engine (spec §7)

`backend/services/refund_policy.py` is a **pure function** `evaluate(ctx, now, cfg) → Decision{allowed, rule_id, fee_cents, refund_cents, driver_share_cents, credit_cents, strike, needs_admin_review, explanation}`; one unit test per policy row (`tests/test_refund_policy.py`). All numbers live in `app_settings` (category *cancellation*) and are editable in admin.

| rule_id | Situation | Customer pays |
|---|---|---|
| before_payment / before_en_route | cancel before payment or before the driver starts driving | $0 |
| free_window | within `cancel.free_window_s` (2 min) of confirmation | $0 (hold released) |
| en_route_fee | after the window while driver en route | min($5, 10 % of fare) |
| after_arrival | after DRIVER_ARRIVED | $5 + waiting (35¢/min after 2 free min) |
| customer_no_show | driver marks no-show after the 5-min wait window | $7 |
| driver_cancelled / driver_ended_trip | driver cancels | $0 + driver strike |
| driver_no_show | not arrived by ETA + 15 min (auto-detected every 30 s) | $0 + $5 ride credit + strike |
| safety_review | trip ended for safety | $0, admin review |
| rideshare_over_24h / 2_to_24h / under_2h / no_show | seat cancellations | 100 % / 50 % / 0 % / 0 % refund |
| rideshare_driver_cancelled | driver cancels the trip | 100 % to every passenger + one strike |

`GET /api/rides/{type}/{id}/cancel-preview` returns the Decision before the user confirms. On cancel the decision is stored on the trip event and `settle_cancellation()` (job) applies it:
* authorized hold, fee > 0 → **partial capture** of the fee (Stripe releases the rest) + `refunds` row kind `release`;
* authorized hold, fee = 0 → **PaymentIntent cancel** (instant release);
* captured money → **Stripe refund** of `paid − fee` (+ credit note);
* driver share credited as `cancel-fee-{type}-{id}`; apology credit as `credit-{type}-{id}`; strikes → `account_service.evaluate_strikes`.

Admin manual refunds: `POST /api/admin/ride-payments/{id}/refund {amount_cents, reason (≥5 chars), clawback?}` with `Idempotency-Key`; audited; optional clawback debits the driver's wallet share.

Every provider call uses a deterministic idempotency key (`rp-{id}-capture`, `rp-{id}-cancel`, …) and every DB effect is guarded by a unique key, so webhooks and jobs may run more than once.


## Receipts, credit notes and driver statements (§13)

### What happens when a ride ends

1. The ride reaches `COMPLETED` (car hire, scheduled) or `DROPPED_OFF` (rideshare seat booking).
2. `trip_effects` queues `complete_payment_and_receipt`. It captures the payment, then calls `receipts.issue_and_send(ride_type, ride_id)` when the flag `ff.receipts_email` is on.
3. `issue_and_send` creates the receipt, renders the PDF and sends **one** email: "Thanks for riding with NegoRide, {first_name} 🚗", with the receipt section and the PDF attached. This takes about 1 s (the PDF renders in about 0.5 s), well within the 60 s target.
4. The job is idempotent. Running it again returns the same receipt and sends no second email. Only one worker can claim the first send, using an atomic `UPDATE … WHERE emailed_at IS NULL`. A failed send is released and retried up to 3 times (after 2 min, then 4 min).

Receipts are issued for `carhire`, `scheduled` and `rideshare_booking` rides. There is **one receipt per seat booking** and none for the driver's `rideshare_trip`. Rides paid through the legacy v3 path, which have no `ride_payments` row, still get a receipt (fare from `rides.fare_cents`, payment method "Card"). If a ride has no captured payment, no receipt is issued.

### Sweeper, admin issue, tips after the receipt

* `receipt_jobs.sweep_missing_receipts` (every 60 s): rides COMPLETED / DROPPED_OFF / CLOSED with a captured ride
  payment older than `receipts.sweep_after_s` (120 s, last 14 days) and no receipt get one (a worker died between
  capture and receipt). Cancelled rides with a fee capture are not receipted.
* `POST /api/admin/rides/{type}/{id}/receipt/issue` issues it on demand (job; 202 when queued).
* **Tips after the ride**: `POST /api/rides/{type}/{id}/tip {amount_cents}` (rider, within `tip.within_h`), independent
  of the rating. When paid a **tip receipt** `NR-TIP-YYYY-NNNNNN` (`tip_receipts`, own `document_sequences` row
  `doc_type='tip'`) is rendered, stored (`tip_receipts/{year}/{number}.pdf`) and emailed (`tip.receipt`). The ride
  receipt is never edited; its API payload gets a `tips` section listing the tip receipts.
* **Driver copy**: `GET …/receipt.pdf` by the driver renders on the fly without the rider's full name or payment method.
* **Resend** from admin is a job (HTTP 202).

### Numbering

| Document | Format | Sequence (`document_sequences`) |
|---|---|---|
| Receipt | `NR-2026-000123` | `doc_type='receipt'`, per year |
| Credit note | `NR-CN-2026-000045` | `doc_type='credit_note'`, per year |
| Tip receipt | `NR-TIP-2026-000007` | `doc_type='tip'`, per year |
| Driver statement | `NR-ST-2026-W38-{driver_id}` | deterministic (unique per driver and ISO week) |

The number is allocated with `SELECT … FOR UPDATE` on the sequence row, in the **same transaction** that inserts the document:

- A rollback also rolls back the increment, so numbers have no gaps.
- The row lock serializes allocation, so there are no duplicates.
- The unique key `(ride_type, ride_id)` guarantees one receipt per ride. If two workers issue the same ride at once, one of them inserts and the other gives its number back.
- The sequence row is created beforehand in its own short transaction, so no gap locks or deadlocks occur. Deadlocks and lock timeouts are retried.

Numbers are never reused, including after test data is deleted.

### Totals (the "perfect receipt")

`receipts.compute_totals()` builds an immutable JSON snapshot, which is stored in `receipts.totals`:

| Key | Meaning |
|---|---|
| `lines[]` | Line items: negotiated fare / seat fare, waiting time, booking/service fee, tolls/airport fee, discounts/credits (negative), and an `adjustment` line if the captured amount differs from the items (it is never hidden). `amount_cents` is before tax; `amount_incl_tax_cents` is the price as charged. |
| `subtotal_cents` | Σ `lines[].amount_cents` (before tax) |
| `taxes[]` | `{code: GST/HST/PST/QST, label, rate_bp, amount_cents}` for the **pickup province** |
| `tax_cents` | Σ `taxes` |
| `ride_total_cents` | `subtotal + tax` = the captured ride amount |
| `tip_cents` | Captured tips (`ride_payments.purpose='tip'`). Not taxable and shown separately. |
| `total_cents` | `ride_total + tip` = total charged |
| `payment_method` | e.g. `Visa •••• 4242`, plus `authorized_at` and `captured_at` |
| `refunds[]`, `refunded_cents`, `net_total_cents` | Refunds that already exist at issue time. Later refunds become credit notes. |
| `negotiation` | `initial_ask_cents` (the driver's first counter-offer, else the initial price; for rideshare, the posted seat price) and `saved_cents` |
| `ride` | Ride ref, rider, driver (first name and last initial), vehicle, addresses, times (UTC ISO), distance and duration, province time zone |
| `registration`, `company` | GST/HST and QST numbers, legal name, address, support contact (from settings) |
| `internal` | **Admin only.** Ride payment id, intent id, commission % and cents, driver fare (feeds the driver statements) |

**Tax math.** Rates live in `tax_rates` in basis points (seeded: ON HST 13 %, QC GST 5 % + QST 9.975 %, AB GST 5 %, and so on), editable in admin (`GET/POST/PUT /api/admin/finance/tax-rates`, effective-dated, no overlaps per province, audited). The province comes from `ride.pickup_province` (stamped at creation from the pickup lat/lng by `utils/province.py`), then a lat/lng lookup for older rides (`province_source: 'geo'`), then the pickup address (", QC H2X…" / "Québec"), then the setting `tax.default_province`.

With `pricing.tax_inclusive = true` (the default), the tax is **extracted** from the charged amount:

```
pre_tax   = round_half_up(amount × 10000 / (10000 + Σbp))
tax_total = amount − pre_tax
component = round_half_up(pre_tax × bp / 10000)   (the rounding remainder goes on the largest component)
```

This makes `pre_tax + Σcomponents == amount` exact for every amount (unit-tested over thousands of values). The pre-tax subtotal is then allocated to the line items by largest remainder, so the line items also add up exactly. Examples for $22.00:

- ON: $19.47 + HST $2.53
- QC: $19.13 + GST $0.96 + QST $1.91
- AB: $20.95 + GST $1.05

With `pricing.tax_inclusive = false`, taxes are computed on top of the subtotal. ⚠️ `payment_service` does not currently add tax to the authorized amount. The receipt then records `warnings: ['tax_exclusive_total_differs_from_captured_amount']` and the reconciliation report flags it. Keep this setting `true` until the accountant confirms the treatment (see Open items below).

### The email (§13.2)

Templates: `backend/templates/email/ride_receipt.html` and `.txt`. They are table-based, use inline styles and dark-mode classes, and extend `_layout.html`. The email contains:

- the route map (Google Static Maps with an encoded polyline from the `ride_locations` breadcrumbs, or A→B markers)
- pickup → drop-off with times, date, duration and distance
- the driver's first name, photo and car
- the fare summary
- "You negotiated and saved $X" (only if something was saved)
- five one-tap star links: `{PUBLIC_WEB_BASE_URL}/open?link=negoride://rate/{type}/{id}?stars=N`
- an "Add a tip" button (`negoride://tip/{type}/{id}`)
- "Lost an item?" and "Report an issue" (`negoride://support/new?category=…&ride_type=…&ride_id=…`), and the cancellation-policy link
- the receipt section, with the PDF attached

Branding: the layout shows the logo (`EMAIL_LOGO_URL`, else `{APP_URL}/api/brand/logo.png` served from
`backend/static/brand/logo.png`) with an alt-text wordmark fallback when images are blocked; PDFs embed the same PNG as
a data URI. The "Add a tip" button has an Outlook VML (`v:roundrect`) version; dark-mode variants cover the savings box
and totals (`prefers-color-scheme` and Outlook.com `[data-ogsc]`). Reply-To is `EMAIL_REPLY_TO`, else
`safety.support_email`. Replace `logo.png` (and `logo.svg`) with the final artwork — same names.

If `GOOGLE_MAPS_STATIC_KEY` / `GOOGLE_MAPS_SERVER_KEY` is missing, the map is omitted. The key appears in the email HTML, so use a key restricted to the Static Maps API and set `GOOGLE_MAPS_URL_SIGNING_SECRET` so the URLs are signed.

When `ff.combined_receipt_email = false`, two emails are sent: the thank-you email (no attachment) and "Your NegoRide receipt NR-…" (with the PDF).

Each send is logged as a `notifications` row (`event_key='ride.receipt'`, group `payment`, one inbox delivery) plus one `notification_deliveries` row per email with its status and provider message id. The admin notification log shows them. Resends add delivery rows to the same notification. Credit notes use `refund.credit_note` and statements use `driver.statement`. These catalogue keys are logged only; do **not** call `notify()` with them, because the generic email would go out without the PDF.

### PDFs and storage

WeasyPrint renders `backend/templates/pdf/{receipt,credit_note,statement}.html`. The page is US Letter with a page x/y footer. The renderer never fetches remote resources (its fetcher blocks http).

Files are stored through the shared `backend/services/private_storage.py`: Fernet-encrypted on local disk (`PRIVATE_STORAGE_DIR`) or on S3 with server-side encryption. Keys follow the patterns `receipts/{year}/{number}.pdf`, `credit_notes/…` and `statements/…`. Nothing is under `/uploads`.

A missing file is re-rendered from the stored snapshot, with the same number and the same content.

### Credit notes (refunds after a receipt)

`payment_service._provider_refund` queues `issue_credit_note_for_refund(refund_id)` after commit. The credit note applies to refunds of kind `refund` (money returned after capture) on rides that have a receipt. Releases of authorization holds are not charges, so they get no credit note.

- The credit note's tax is extracted from the refund amount using the receipt's own rates.
- It shows the original total, earlier credits and the new net total.
- It is emailed with its PDF and is unique per refund, so the job is idempotent.
- `refunds.credit_note_id` is set.
- The receipt is never edited.

### Driver weekly statements

`receipt_jobs.weekly_driver_statements(week_start=None)` is scheduled weekly and defaults to the last full ISO week (Monday to Monday, UTC). It is gated by `ff.driver_statements`. For each driver with receipts, wallet activity or payouts that week, it creates one `driver_statements` row (unique per driver and week), a PDF and an email.

The figures are:

| Figure | Source |
|---|---|
| Ride fares | Receipt snapshots |
| Commission | The rate frozen on each receipt |
| Tips, cancellation-fee shares, bonuses | Wallet ledger credits |
| Other fees | Clawbacks, penalties, background-check fees |
| Net | fares + credits − commission − fees |
| Payouts | Completed payouts, with pending payouts listed separately |

Admins can re-run a week with `POST /api/admin/finance/statements/run {week_start}`.

### API

Customer and driver endpoints use a Bearer JWT and the `{code, message, data}` envelope:

| Method | Path | Who | Response |
|---|---|---|---|
| GET | `/api/rides/{type}/{id}/receipt` | Rider or driver of the ride (others 403; not issued yet → 404 `receipt_not_ready`) | `{id, number, ride_type, ride_id, currency, issued_at, total_cents, total, credited_cents, net_total_cents, emailed_at, totals{…without internal; the driver also doesn't see payment_method}, credit_notes[], pdf_url}` |
| GET | `/api/rides/{type}/{id}/receipt.pdf` | same | `application/pdf` (`?download=1` for an attachment) |
| GET | `/api/receipts?page=&per_page=` | Rider | Paginated list of the payload above |
| GET | `/api/receipts/{id}/credit-notes/{cn_id}.pdf` | Rider | PDF |
| GET | `/api/driver/statements` | Driver | Paginated `{id, number, period_start, period_end, gross_cents, commission_cents, fees_cents, net_cents, payouts_cents, totals, pdf_url}` |
| GET | `/api/driver/statements/{id}.pdf` | Owner | PDF |

Admin endpoints require the role `finance` (`super_admin` always passes). Resend also allows `support` and `ops`.

- Every call is audited: `finance.view`, `personal_data.view`, `finance.export`, `finance.reconciliation`, `receipt.resend`, `finance.statements_run`.
- Every list accepts `from` / `to` (YYYY-MM-DD, UTC, inclusive), `page` / `per_page` and `format=csv` or `format=xlsx` (Excel, openpyxl; formula-injection safe).

| Method | Path | Notes |
|---|---|---|
| GET | `/api/admin/finance/receipts` | `q` (number), `customer_id`, `driver_id`, `ride_id`, `ride_type`. Each row has credited and net totals. |
| GET | `/api/admin/finance/receipts/{id}` | Full snapshot (incl. `internal`), payment, refunds, credit notes |
| GET | `/api/admin/finance/receipts/{id}/pdf` | |
| POST | `/api/admin/receipts/{id}/resend` (also `/api/admin/finance/receipts/{id}/resend`) | Same number and totals; `{number, email_count, emailed_at}`; 502 `email_failed` if the provider refused |
| GET | `/api/admin/finance/credit-notes`, `/credit-notes/{id}/pdf` | |
| GET | `/api/admin/finance/payments` | `capture_status`, `purpose`, `ride_type` |
| GET | `/api/admin/finance/payments/summary` | Authorized, captured, refunded, released, open holds, holds expiring in 24 h; totals by status and by purpose |
| GET | `/api/admin/finance/refunds` | `kind=refund|release` |
| GET | `/api/admin/finance/payouts` | Overview by status plus a list (`status`) |
| GET | `/api/admin/finance/commission` | Per day: rides, fares, commission, booking fees, revenue |
| GET | `/api/admin/finance/tax` | Per province: taxable amount, tax, credited tax, net tax, and GST / HST / PST / QST |
| GET | `/api/admin/finance/statements`, `/statements/{id}/pdf`; POST `/statements/run` | |
| GET | `/api/admin/finance/reconciliation` | For each captured payment: DB captured and refunded vs the provider (`gateway.retrieve_payment_totals`) vs the receipt. Status `ok|mismatch|error`, `only=issues`, at most 100 payments per page (provider calls are synchronous, so page through). |

### Settings

| Key | Default | Purpose |
|---|---|---|
| `ff.receipts_email` | true | Issue and email receipts at completion |
| `ff.combined_receipt_email` | true | One combined email, or two [CONFIRM WITH CLIENT] |
| `ff.driver_statements` | true | Weekly driver statements (new) |
| `pricing.tax_inclusive` | true | Fares include GST/HST [CONFIRM WITH ACCOUNTANT] |
| `tax.default_province` | ON | Used when the pickup province is unknown (new) |
| `company.legal_name`, `company.address`, `company.gst_number`, `company.qst_number`, `company.website` | | Printed on every document |
| `safety.support_email`, `safety.support_phone` | | Support contact on documents |

### Open items for the client

- The GST/HST registration number (`company.gst_number`) and the QST number (if operating in QC) are empty. Receipts omit the registration line until they are set.
- Confirm tax-inclusive pricing. If fares must be tax-exclusive, the charge in `payment_service.start_payment` must add the tax first.
- Confirm the legal name and address for documents, and one vs two emails.
- Set up a Static Maps key restricted to the Static Maps API, plus a signing secret.
- Waiting-time, tolls and discount lines appear only when the payment actually charged them (`ride_payments.meta.waiting_fee_cents`, `tolls_cents`, `discount_cents`) — zero lines are never printed. The capture currently charges fare + booking fee only, so riders normally see fare (+ fee) only; tolls/discounts are not part of the spec-facing output until a feature populates them.
