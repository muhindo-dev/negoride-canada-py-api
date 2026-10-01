# Driver onboarding & background checks (spec §14)

Endpoints: `docs/API.md` → "Driver onboarding". Code: `backend/services/onboarding_service.py`,
`onboarding_jobs.py`, `certn_client.py`, `backend/routes/onboarding.py`, admin in `routes/admin_identity.py`.
Flags: `ff.driver_onboarding_v2`, `ff.background_check`, `ff.bgc_pay_later`, `ff.bgc_platform_pays_recheck`,
`ff.referrals`. Numbers: `onboarding.*` settings (admin → Settings).

## The wizard — "Become a NegoRide driver — 7 steps"

`GET /api/driver/onboarding` returns the whole checklist; the app renders it as-is and can be left and resumed at
any time. Step status: `not_started · in_progress · under_review · done · action_needed`.

| # | key | Done when | Notes |
|---|---|---|---|
| 1 | `account_created` | the three sign-up consents are accepted | `action_needed` if a new Terms/Privacy/Guidelines version awaits acceptance |
| 2 | `phone_verified` | the server has a verified phone number for the account | OTP verification proves control of the number. Carrier line-type data is optional and must not make an already-verified user repeat verification or block onboarding. If the server has no verified phone, verify with purpose `driver_onboarding`. |
| 3 | `email_verified` | existing email verification | |
| 4 | `profile_completed` | pre-qualification passed + all profile fields + Driver Agreement & Safety Policy e-signed | **Pre-qualification first** (age ≥ `onboarding.min_driver_age`, full licence class in `onboarding.allowed_licence_classes`, vehicle year ≥ `onboarding.min_vehicle_year`, province served) — nobody can pay for a check they can't use. SIN is never collected |
| 5 | `documents_submitted` | all `onboarding.required_documents` approved | `under_review` once all are uploaded; `action_needed` if one is rejected (reviewer note shown) |
| 6 | `background_check` | Certn result `clear` (or admin cleared) | consent → pay → Certn invite (WebView) → result |
| 7 | `payout_ready` | Stripe Connect payout account `active` | Not required to submit (drivers can finish it after approval) |
| — | `review` | admin approved | `submitted → under_review → approved \| needs_changes \| rejected` |
| — | `orientation` | 5 cards + 5-question quiz passed (`onboarding.orientation_pass_score`) | Required before the first time online for v4 applicants |

`progress_pct` = done steps among the first 8 (orientation excluded). `submit_blockers` lists exactly what is missing.

### Documents

Types: `licence_front, licence_back, registration, insurance, vehicle_front, vehicle_back, vehicle_left,
vehicle_right, vehicle_interior, selfie`. JPG/PNG/HEIC/WEBP/PDF ≤ 10 MB. `expires_at` is required for the licence
(front) and insurance, optional for registration. Files are written with `private_storage.put()` under
`driver-docs/<user>/<application>/…` (Fernet-encrypted local dir or S3 with SSE) — **never** under `/uploads`.
Admins open them through `GET /api/admin/onboarding/documents/{id}/file` (short-lived signed URL, audited).
A re-upload supersedes the previous file of that type.

**Insurance — rideshare endorsement.** For provinces in `onboarding.rideshare_endorsement_provinces`
(default `ON,BC,AB,QC`) the insurance upload must include the form field `attestation_rideshare_endorsement=true`,
otherwise 422 `endorsement_attestation_required` (`data.province`, `data.field`). The attestation is stored on the
document: `meta = {attestation_rideshare_endorsement, province, endorsement_required, attested_at}` (visible to
admins in every document payload). The overview exposes `insurance_endorsement_required` and
`requirements.rideshare_endorsement_provinces`.

**Selfie face match (advisory).** When both a `selfie` and a `licence_front` exist, a job
(`face_match.run_for_application`) compares them — AWS Rekognition `CompareFaces` when `AWS_REKOGNITION_REGION` + AWS
credentials are set, otherwise `manual_review`. The result is stored on the selfie document
(`face_match_status: pending|match|no_match|no_face|manual_review|error`, `face_match_score` 0–100,
`face_match_provider`, `face_match_checked_at`, `face_match_detail`) and summarised in the admin application
detail as `face_match {status, score, provider, checked_at, detail, selfie_document_id, licence_document_id,
threshold, advisory_only:true}`. `match` = score ≥ `onboarding.face_match_threshold` (90). **It never approves or
rejects a document** — the reviewer decides.

### Expiry monitoring (daily job `onboarding_jobs.document_expiry_check`)

Reminders at 30 / 14 / 3 days (`onboarding.expiry_reminder_days`) before licence, insurance or registration
expiry — one notification per threshold (`driver_documents.reminders_sent`). On expiry the document becomes
`expired`, the driver is switched offline, and `account_service.can_go_online()` refuses until a valid document is
uploaded (and approved).

## Background check (Certn)

1. **Consent** — `POST …/background-check/consent {signature_name}` stores a `legal_acceptances` row for the
   `background_check_consent` document (method `esignature`, IP, user agent, app version) and creates a
   `background_checks` row in `awaiting_payment`. Requires a passed pre-qualification. **Every check carries its
   own evidence** in `background_checks.consent_evidence` = `{background_check_id, signature_name, signed_at, ip,
   user_agent, app_version, document_id, document_type, document_version, document_language, acceptance_id,
   acceptance_reused, is_recheck}` — a re-check signs again even when the consent version (and therefore the
   `legal_acceptances` row) is unchanged.
2. **Fee** — `POST …/background-check/pay` → Stripe Checkout (immediate capture) through
   `payment_service.start_extra_payment('background_check', 'background_check', <bgc id>, …)`; the app opens
   `checkout_url`, then calls `…/sync` (webhook fallback). The fee is `onboarding.bgc_fee_cents` (default
   $39.99 **[CONFIRM WITH CLIENT]**). A NegoRide receipt (`BGC-<year>-<id>`, template `bgc_receipt`) is emailed
   once paid (`receipt_emailed_at`). **Cancel window:** Certn is ordered only `onboarding.bgc_start_delay_min`
   (default 30) minutes after payment (`background_checks.start_after`); until then the driver can call
   `POST …/background-check/cancel {reason?}` → full card refund through the payment gateway (a `refunds` row,
   rule `bgc_cancel_before_submission`; `refunded_cents`, `refunded_at`) or, for pay-later, the deduction is
   waived (anything already recovered is credited back). After submission → 409 `nothing_to_cancel` /
   `already_submitted` (non-refundable).
   *Pay later from earnings* (`ff.bgc_pay_later`): `{pay_later:true}` → the platform fronts the fee
   (`paid_by='earnings'`, `deduction_status='pending'`); it is debited from the driver wallet
   (`background_check_fee` transactions) after rides complete, hourly, and before every payout request —
   **partially** when the balance is short (`deducted_cents` tracks the amount recovered; `settled` once it
   equals `fee_cents`). `POST /api/payout-requests` settles first and answers 409 `bgc_fee_outstanding`
   (`outstanding_cents`) while any fronted fee remains. `outstanding_deduction_cents(driver_id)` = fee − deducted.
3. **Initiate** — when paid, a job orders a CertnCentric case with the invite flow
   (`send_invite_email:false, return_invite_link:true`); `invite_url` is shown in the in-app WebView where the
   driver completes Certn's identity + consent steps.
4. **Webhooks** — `POST /api/webhooks/certn`, `X-Signature` = hex HMAC-SHA256 of the raw body with
   `CERTN_WEBHOOK_SECRET`; `GET /api/webhooks/certn?challenge=` echoes the challenge (Certn endpoint verification).
   The raw event is stored in `webhook_events` first, then `process_certn_event(id)` runs in a job (retried by
   `platform_jobs.retry_failed_webhooks`). The job re-reads the case (`GET /api/public/cases/{id}/`) to get the score.
5. **Polling fallback** — every 6 h `poll_background_checks` re-orders paid checks whose order failed and polls
   `initiated`/`pending` cases not polled for 5 h.
6. **Adjudication** — CertnCentric `overall_status`/`overall_score` → our status:
   `COMPLETE+CLEAR → clear` (auto-advance: application `submitted → under_review`),
   `COMPLETE+REVIEW/NOT_APPLICABLE/RESTRICTED → consider` (admin reviews: report link + decision with reason),
   `COMPLETE+REJECT → failed` (application rejected; the notice includes the right to a copy of the report and how
   to dispute with Certn — `onboarding.certn_dispute_contact` — and NegoRide support),
   `APPLICANT_EXPIRED/INVITE_UNDELIVERABLE → expired`, `CANCELLED → cancelled`, anything in progress → `pending`.
   Admin decisions (`adjudicated_by`) and final outcomes are never overwritten by later provider events.
7. **Re-checks** — a clear check expires after `onboarding.recheck_months` (12). Drivers are reminded
   `onboarding.recheck_reminder_days` (30) before; the overview (and admin application detail) exposes
   `renewal_due: true` from then on, and consent → pay starts the renewal while the current check is still valid.
   On expiry the check becomes `expired` and blocks going online until a new check (consent → pay, or free when
   `ff.bgc_platform_pays_recheck`) clears. A **failed** re-check of an already-approved driver moves the account to
   `pending_review` (reason `failed_background_check`, deferred until the current ride ends) — the driver goes
   offline and can appeal.

### Certn API facts (verified 2026-09-27 against https://centric-api-docs.certn.co)

* The legacy API (`api.certn.co/api/v1/hr/…`) is deprecated (2026-04-13) and returns **410 Gone** since 2026-08-05.
  We integrate CertnCentric only.
* Auth header `Authorization: Api-Key <key>`; keys expire after 365 days (rotate without downtime — several keys can
  be active).
* Base URLs: `https://api.ca.certn.co` (Canadian data residency, default), sandbox `https://api.sandbox.certn.co`.
* Rate limit 60 requests/min, 7,220/day.
* **Unverified — confirm during Certn onboarding:** exact check-type keys for the rideshare package
  (`onboarding.certn_check_types`, default `IDENTITY_VERIFICATION_1, CRIMINAL_RECORD_REPORT_1,
  MOTOR_VEHICLE_RECORD_1`; a package/bundle UUID in `onboarding.certn_package` is sent as `package`), the cancel
  path, the `report-files` response field holding the URL, and whether `CERTN_GROUP_ID` is needed.

Env: `CERTN_API_KEY`, `CERTN_API_BASE_URL`, `CERTN_WEBHOOK_SECRET`, optional `CERTN_GROUP_ID`. Without
`CERTN_API_KEY` the clearly-labelled `FakeCertnClient` is used (refuses to run with `FLASK_ENV=production`).

## Admin review

Queue: `GET /api/admin/onboarding/applications?status=submitted,under_review&step=…` (oldest submission first).
Detail shows steps, blockers, every document version (with signed file links), all checks, and legal acceptances.
Per-document approve / reject (a note is mandatory to reject; the driver is notified). Application decision:

* **approve** — requires a clear check (or `override_background_check` + reason, audited) and no rejected documents;
  pending documents are approved with it. Sets `user_type='Driver'` and legacy `is_<svc>` / `is_<svc>_approved`
  flags from the approved service types (car_hire/rideshare/airport/special_car → `car`, courier/movers →
  `delivery`), copies licence number/expiry and vehicle to the legacy columns, notifies `onboarding.approved`, and
  pays the referral bonus to the referrer when `ff.referrals`.
* **needs_changes** / **reject** — reason required, notified to the driver. **reject** also clears the legacy
  `is_<svc>='Yes'` "applied" flags set at submission (approved services are never touched) and returns a
  `Pending Driver` to `Customer`; the same cleanup runs when a failed background check auto-rejects.

Every action is audited; opening an application, a document or a Certn report is audited too.
Admins with the `ops` / `safety_reviewer` roles are notified (`admin.background_check_review`: inbox + push + email,
realtime `onboarding.bgc_review` / `onboarding.bgc_clear` / `onboarding.bgc_failed`) when a check needs
adjudication (`consider`) and when it completes. The service types offered in the wizard come from
`settings_service.enabled_services()` (setting `services.enabled`).

Funnel: `GET /api/admin/onboarding/funnel` (applicants who completed each step and the drop-off %). Step progress is
recorded whenever a step can change — wizard calls, phone/email verification, Certn outcomes, admin document
reviews and decisions (`onboarding_service.refresh_progress` job) — not only when the driver opens the overview.

## Backward compatibility

`POST /api/become-driver` (v3) still works exactly as before and additionally mirrors the form into a `submitted`
driver application so it appears in the admin queue. Legacy approvals from the old admin screens keep working;
drivers approved before v4 (no application) are only gated by account status, expired documents and checks.

## Open questions for the client

1. Background-check fee (default $39.99) and whether "pay later from earnings" is offered.
2. Certn package (criminal record + identity + driver abstract?) and annual re-check payer.
3. Minimum driver age (default 21) and oldest vehicle model year (default 2012).
4. Accepted licence classes per province (default 1–5, G; learner/probationary classes excluded).
5. Whether payout setup must be complete before an application can be submitted (default: no).
