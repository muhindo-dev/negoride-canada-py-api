# NegoRide v4 — HTTP API reference

Envelope for every endpoint: `{code: 1|0, message, data}`. Errors carry `data.error_code`.
Money is integer **cents, CAD**. Timestamps are ISO-8601 UTC (`...Z`). Auth = `Authorization: Bearer <JWT>`.

---

## Experience (spec §16, §17, §18, §21.2, §21.3, §19.1.9, §19.1.13)

Source: `routes/ratings.py`, `routes/rideshare_v4.py`, `routes/carhire_v4.py`, `routes/admin_experience.py`;
services `eta.py`, `geo_routes.py`, `ratings_service.py`, `rideshare_service.py`, `matching_service.py`,
`insights_service.py`, `popular_places.py`, `experience_jobs.py`. Flags: `ff.live_eta`, `ff.ratings_v2`,
`ff.rideshare_self_booking`, `ff.rideshare_seat_negotiation`, `ff.pick_a_driver`, `ff.favourite_first`.

### Live ETA (§16)

The server computes ETA from driver positions (`POST /api/update-location` or socket `location:update`),
throttled to one computation per ride per `eta.min_refresh_s` (30 s) or immediately when the driver moves
≥ `eta.deviation_m` further from the target. Google **Routes API** `computeRoutes` (TRAFFIC_AWARE, server key
`GOOGLE_MAPS_SERVER_KEY`) runs in a job; without a key a haversine × `eta.road_factor` / `eta.avg_speed_kmh`
estimate is used. Pickup ETA ≤ `ride.arriving_eta_s` moves the ride to `DRIVER_ARRIVING`.

**Realtime** `ride.eta_updated` → rooms `ride:{type}:{id}` and `user:{customer_id}`:
```json
{"ride_type":"carhire","ride_id":42,"seconds":260,"minutes":4,"distance_m":1200,"target":"pickup|dropoff",
 "arrives_at":"2026-09-27T14:38:00Z","updated_at":"…Z","source":"google_routes|estimate","stage":"DRIVER_EN_ROUTE","reason":"interval|deviation"}
```

| Method | Path | Auth | Response `data` |
|---|---|---|---|
| GET | `/api/rides/{type}/{id}/eta` | ride party | `{ride_type, ride_id, stage, eta: <payload above without stage/reason> \| null, driver_location: {lat,lng,at} \| null}` (polling fallback) |

### Ratings, reviews, tips (§17)

| Method | Path | Auth | Body / response |
|---|---|---|---|
| POST | `/api/rides/{type}/{id}/rating` | customer or driver of the ride (`carhire`, `scheduled`, `rideshare_booking`) | body `{stars: 1–5, tags?: [key or label], comment?: str≤1000, tip_cents?: int≥50 (customer only)}` → 201 `{rating: {id, stars, tags, comment, role, created_at, tip_cents, visible_at}, ask_what_went_wrong: bool, safety_report: {label, endpoint:"/api/safety/reports", ride_type, ride_id} \| null, tip: {ride_payment_id, amount_cents, checkout_url, status} \| {error, error_code} \| null}` |
| GET | `/api/rides/{type}/{id}/rating` | party / admin | `{ride_type, ride_id, viewer_role, can_rate, rate_until, my_rating: {…, tip_cents, tip_payment_id} \| null, other_party_rated: bool, other_rating: {id, stars, tags, comment, role, created_at} \| null, tags: {positive:[{key,en,fr}], negative:[…]}}` |
| GET | `/api/ratings/tags` | any user | `{customer: {positive, negative}, driver: {positive, negative}}` — `customer` = tags a customer gives a driver |
| GET | `/api/drivers/{id}/profile-card` | any user | `{id, first_name, avatar, rating, rating_count, total_trips, years_on_negoride, member_since:"YYYY-MM", top_compliments:[{key,label,label_fr,count}], vehicle:{make,model,year,color,seats}, badges:{verified, background_checked, phone_verified}}` |

Rules: allowed when the ride is COMPLETED / DROPPED_OFF / CLOSED and within `rating.rate_within_h` (72 h) of
the end; errors `not_completed` 409, `rating_window_closed` 410, `duplicate` 409, `bad_stars`, `bad_tags`,
`tip_not_allowed`, `tip_too_low`, `forbidden` 403. Tag keys — customer→driver: positive `safe_driving,
clean_car, great_conversation, fair_negotiator, on_time`; negative `late, unsafe_driving, rude, dirty_car,
wrong_route, price_changed`. Driver→customer: positive `respectful, on_time, great_conversation,
fair_negotiator, tidy`; negative `late, rude, messy, price_changed, unsafe_behaviour`.
Visibility: the other party's rating is hidden until both rated or 72 h after the ride ended; **customers
never see the rating a driver gave them**. Score = Bayesian `(rating.prior_mean × rating.prior_weight + Σ
stars) / (prior_weight + n)` over the last `rating.window` non-hidden ratings → `users.rating` (2 dp),
`users.rating_count`, `users.rating_avg_raw`. Both rated → ride `CLOSED`. Tip: Checkout (immediate capture),
100 % credited to the driver wallet (`transactions.category = tip`) when the payment webhook arrives.

### Rideshare self-booking (§18.1)

| Method | Path | Auth | Body / response |
|---|---|---|---|
| GET | `/api/rideshare/search?from_lat&from_lng&to_lat&to_lng&date=YYYY-MM-DD&seats=1` | user | `{trips:[card], count}`; `date` is a local day in the user's time zone (default America/Toronto); radius `rideshare.search_radius_km` |
| GET | `/api/rideshare/trips/{id}` | user | `card + {is_bookable, my_booking: booking \| null}` |
| POST | `/api/rideshare/trips/{id}/book` | customer | body `{seats: 1–8, offered_price_per_seat_cents?, pickup?: {lat,lng,address}, note?}` → 201 `{booking, next_action}`; errors `sold_out` 409, `duplicate` 409, `not_bookable` 409, `own_trip`, `offer_out_of_bounds`, `no_negotiation` |
| POST | `/api/rideshare/bookings/{id}/respond` | trip driver | body `{approve: bool, reason?}` → `{booking}` (approve → PENDING_PAYMENT, decline → DECLINED); `not_requested` 409 |
| GET | `/api/rideshare/my-bookings?scope=upcoming\|past\|all&page&per_page` | customer | `{items:[booking + trip card], page, per_page, total}` |
| GET | `/api/rideshare/trips/{id}/manifest` | trip driver | `{trip_id, stage, departure_at, seats_total, seats_left, passengers:[{booking_id, pickup_order, stage, seats, customer:{id,first_name,name,avatar,rating,rating_count}, pickup:{address,lat,lng}, note, total_cents, request_expires_at, pin_required, actions:[{action, method, endpoint}]}]}` |
| PUT | `/api/rideshare/trips/{id}/settings` | trip driver | body any of `{booking_mode: instant\|request, allow_seat_negotiation, min_seat_price_cents, pets_ok, luggage_size: none\|small\|medium\|large}` → card |

**card** = `{trip_id, stage, departure_at, departure_text, pickup:{name,address,lat,lng}, dropoff:{…}, seats_total,
seats_left, price_per_seat_cents, currency, negotiation:{allowed, min_cents, max_cents}, booking_mode,
driver:{id, first_name, avatar, rating, rating_count}, car:{model, make, color, year}, badges:{verified,
background_checked, pets_ok, luggage_size}, details, distance_from_origin_m?, distance_to_destination_m?}`.
**booking** = `{id, trip_id, stage, legacy_status, seats, price_per_seat_cents, offered_price_per_seat_cents,
total_cents, currency, request_status, request_expires_at, pickup:{address,lat,lng}, note, created_at,
next_action}`; **next_action** = `{action: "pay", endpoint: "/api/rides/rideshare_booking/{id}/pay"}` |
`{action: "wait_for_approval", expires_at}` | `{action: "none"}`.

Request to book: bookings in `request` mode, or with a negotiated seat price, start as REQUESTED and are
auto-declined (EXPIRED, seat released) after `rideshare.request_timeout_min` (30). Seat inventory is locked
(`SELECT … FOR UPDATE` on the trip + locking read of its bookings) so two customers cannot both get the last seat.
Per-passenger actions use the unified ride API: `POST /api/rides/rideshare_booking/{id}/arrived` (Arrived),
`/start {pin}` (Picked up / CHECKED_IN), `/complete` (DROPPED_OFF), `/no-show` (after departure time).
Departure reminder `rideshare.departure_reminder` goes to confirmed passengers + driver once,
`rideshare.departure_reminder_min` (60) before departure.

### Car hire — choose a driver, favourites, broadcast (§18.2)

| Method | Path | Auth | Body / response |
|---|---|---|---|
| GET | `/api/carhire/nearby-drivers?lat&lng&service_type=car` | customer | `{drivers:[{id, first_name, avatar, rating, rating_count, car:{make,model,color,year,seats}, approx_location:{lat,lng,precision_m:200}, is_favourite, distance_m (rounded to 100 m), eta_seconds, eta_minutes}], count}` — no phone, no exact position |
| POST | `/api/carhire/requests` | customer | body `{mode: direct\|favourite_first\|broadcast, driver_id? (required for direct; optional favourite for favourite_first), pickup:{lat,lng,address}, dropoff?:{lat,lng,address}, offer_cents (≥ pricing.min_fare_cents), service_type: car\|courier\|movers\|airport pickup\|…, note?}` → 201 `{request, negotiation: <legacy negotiation dict> \| null, offers_sent, favourite_unavailable}`; errors `bad_mode`, `offer_too_low`, `not_favourite`, `driver_unavailable` 409, `no_drivers` 409 (`data.request_id`), `feature_off` 403 |
| GET | `/api/carhire/requests/{id}` | the customer, or an offered driver | customer: `request`; driver: `incoming card` |
| POST | `/api/carhire/requests/{id}/cancel` | customer | `request` (status `cancelled`) |
| GET | `/api/carhire/requests/incoming` | driver | `{requests:[incoming card]}` |
| POST | `/api/carhire/requests/{id}/accept` | offered driver | body `{counter_cents?}` → `{request_id, negotiation}`; no counter → PRICE_AGREED at the customer's offer; counter → NEGOTIATING with the driver's record. Loser → 409 `already_taken`; closed → 409 `not_available` |
| POST | `/api/carhire/requests/{id}/decline` | offered driver | `{request_id}` (favourite declining → immediate broadcast) |
| GET | `/api/favourite-drivers` | customer | `{drivers:[{driver_id, first_name, avatar, rating, rating_count, car, online, added_at}]}` |
| POST | `/api/favourite-drivers` | customer | body `{driver_id}` → 201 same list |
| DELETE | `/api/favourite-drivers/{driver_id}` | customer | same list |

**request** = `{id, mode, status: favourite|broadcasting|matched|expired|cancelled|no_drivers, service_type, pickup,
dropoff, offer_cents, currency, note, favourite_driver:{id,first_name,avatar,rating,rating_count}|null,
favourite_until, broadcast_at, expires_at, negotiation_id, matched_driver|null, matched_at,
offers:{sent, open, declined}, created_at}`.
**incoming card** = `{request_id, service_type, offer_cents, currency, note, pickup, dropoff, trip_distance_m,
distance_to_pickup_m, eta_to_pickup_s, is_favourite, respond_by, customer:{id, first_name, avatar, rating,
rating_count}, offer_status}`.

Flow: `direct` creates the Negotiation immediately (REQUESTED, `negotiation.new_request` push to the driver —
same as `/api/negotiations-create`). `favourite_first` offers to the favourite for `carhire.favourite_first_s`
(45 s), then broadcasts. `broadcast` offers to the nearest `carhire.broadcast_max_drivers` (10) online approved
drivers within `carhire.broadcast_radius_km` (15); unanswered after `carhire.broadcast_timeout_s` (180) → expired
(`ride.expired` notification). The first driver to accept/counter becomes the negotiation's driver; all other
offers are withdrawn. After matching, continue with the normal negotiation / `/api/rides/carhire/{id}` flow.

**Realtime** (`user:{id}` rooms): `carhire.request_offered` (driver, incoming card),
`carhire.request_withdrawn` `{request_id, reason: taken|cancelled|expired}` (driver),
`carhire.request_matched` `{request_id, negotiation_id, counter_cents, agreed, driver:<nearby card>}` (customer),
`carhire.request_updated` (customer, request). Push: `negotiation.new_request` with
`{ride_type:"carhire_request", request_id, price, distance_km, favourite}`.

### Fair-price hint and demand heatmap (§21.2)

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/api/pricing/fair-range?from_lat&from_lng&to_lat&to_lng&service_type=car` | user | `{low_cents, high_cents, typical_cents, currency, distance_m, duration_s, basis:{distance_source: google_routes\|estimate, history_count, history_weight, service_type}, text:"Typical fare for this route: $17–$22"}` |
| GET | `/api/driver/demand-heatmap?lat&lng&radius_km=10` | approved driver | `{cell_size_deg:0.01, cell_size_m, window_hours:2, radius_km, generated_at, cells:[{lat,lng,count,intensity}]}` — request pickups of the last 2 h, no personal data |

Fair range = base + per-km + per-minute (`pricing.fair_*`) ± `pricing.fair_spread_pct`, blended (weight up to
0.7) with the p25/p50/p75 of agreed prices of completed rides of the same service type within ±20 % of the
distance (last 180 days). Distance/time from a cached Routes API result when available; otherwise the estimate
is returned and (with a server key) a job warms the cache — Google is never called inside the request.

### Instant address search support (§21.3)

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/api/places/popular?province=ON&kind=airport\|station\|mall` | none | `{places:[{id, kind, name, short_name, province, lat, lng, address}], count, version}` |
| POST | `/api/analytics/events` | optional | body `{events:[{name: /^[a-z][a-z0-9_.]{0,79}$/, value_num?, props?: object≤2 KB}]}` (≤ 50) → 202 `{accepted, dropped}`; 429 `rate_limited` above `analytics.max_events_per_min` per user/IP |

The app itself calls Places API (New) Autocomplete with a session token; log e.g.
`{"name":"autocomplete_latency_ms","value_num":184}`.

### Admin — ratings and reports (roles ops / support / super_admin; earnings also finance)

| Method | Path | Response |
|---|---|---|
| GET | `/api/admin/ratings?driver_id&rater_id&ratee_id&ride_type&ride_id&role&stars&min_stars&max_stars&hidden=0\|1&has_comment=1&tag&with_tip=1&from&to&page&per_page` | `{items:[ride_rating + rater{id,name,first_name} + ratee{…}], page, per_page, total}` |
| GET | `/api/admin/ratings/lowest-drivers?min_count=10&limit=50` | `{drivers:[{driver_id, name, avg_stars, ratings, score, rating_count}]}` |
| GET | `/api/admin/ratings/trend-alerts?drop=0.3&min_recent=3` | `{alerts:[{driver_id, name, recent_avg, recent_count, prior_avg, prior_count, drop}]}` (last 7 days vs the 28 days before) |
| POST | `/api/admin/ratings/{id}/hide` · `/unhide` | body `{reason}` (≥ 5 chars, mandatory) → `{rating, ratee_score:{rating, rating_count, rating_avg_raw}}`; audited `rating.hidden` / `rating.unhidden` |
| GET | `/api/admin/reports/demand-heatmap?from&to&cell_deg=0.01` | `{from, to, cell_size_deg, cells:[{lat,lng,count,intensity}], total_requests}` |
| GET | `/api/admin/reports/supply-demand?from&to&tz=America/Toronto` | `{timezone, series:[{hour, requests, online_drivers, engaged_drivers, requests_per_online_driver}], by_hour_of_day:[{hour_of_day, avg_requests, avg_online_drivers}], totals}` (online drivers from 10-min `driver_supply_snapshots`) |
| GET | `/api/admin/reports/negotiations?from&to` | `{negotiations, agreed, acceptance_rate_pct, avg_change_vs_customer_offer_pct, avg_discount_from_driver_initial_ask_pct, agreed_with_driver_ask, avg_rounds, avg_rounds_when_agreed, by_stage}` |
| GET | `/api/admin/reports/cohorts?from&to&weeks=8` | `{weeks, cohorts:[{cohort_week, users, weeks:[{week, active_users, pct}]}]}` (weekly sign-up cohorts → % with a completed ride in week N) |
| GET | `/api/admin/reports/earnings-distribution?from&to&bucket_cents` | `{drivers, bucket_cents, histogram:[{from_cents,to_cents,drivers}], total_cents, mean_cents, p50_cents, p90_cents}` |
| GET | `/api/admin/analytics/latency?name=autocomplete_latency_ms&days=7` | `{name, days, count, avg, min, max, p50, p95, p99, target_p95_ms:400, daily:[{date,count,avg}]}` |

Dates: `from` / `to` accept `YYYY-MM-DD` (to is inclusive) or ISO datetimes, UTC; default last 7–84 days.

---

## Identity, legal consent, driver onboarding, account status, support (spec §11, §12, §14, §15, §19.1.5/6/8/11/14)

Source: `routes/verify.py`, `routes/legal.py`, `routes/onboarding.py`, `routes/account.py`, `routes/support.py`,
`routes/admin_identity.py`, changes in `routes/auth.py`, `routes/profile.py`, `routes/payout_account.py`;
services `phone_verification.py`, `legal_service.py` (+ `legal_content.py` seed), `onboarding_service.py`,
`onboarding_jobs.py`, `certn_client.py`, `account_service.py`, `account_jobs.py`, `support_service.py`.

**Client headers (v4 app):** `X-App-Version: 4.0.0` (enables v4-only rules: consent ticks, sensitive re-verify,
restricted login for suspended accounts), `X-Device-Id: <stable install id>` (new-device step-up), optional
`Accept-Language: fr`. v3 builds send neither and keep the old behaviour.

### Phone verification — Twilio Verify (§11)

`purpose` ∈ `signup | login | change_phone | driver_onboarding | new_device | password_reset | sensitive_action`.
`channel` ∈ `sms | call | whatsapp` (call only after `otp.voice_after_failed_sms` SMS in the last hour; WhatsApp only
when `otp.whatsapp_enabled`). Auth is optional except for `change_phone`, `driver_onboarding`, `sensitive_action`
(JWT) and `new_device` (`step_up_ticket` from login). For `sensitive_action` / `new_device` the phone comes from the
account (omit `phone`).

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| POST | `/api/verify/phone/start` | optional | `{phone, purpose, channel?, step_up_ticket?, locale?}` → `{verification_id, phone:"+14165550123", phone_masked, purpose, channel, expires_in_s:600, resend_after_s:30, voice_available:bool, whatsapp_available:bool, max_attempts:5, test_mode:bool}` |
| POST | `/api/verify/phone/check` | optional | `{phone, purpose, code, step_up_ticket?}` → `{verification_token:"pvt_…" \| null, expires_in_s:900, phone, phone_masked, purpose, line_type, applied:bool, user?}` — when a logged-in user checks `driver_onboarding` or `signup`, the number is applied to the account at once (`applied:true`, token `null`, `user` = updated user) |
| POST | `/api/otp-request` | optional | legacy alias of start: `{phone_number, purpose?='signup', channel?}` |
| POST | `/api/otp-verify` | optional | legacy alias of check: `{phone_number, otp, purpose?='signup'}` |

`verification_token` is single use, valid 15 min, and only its SHA-256 is stored. Error `data.error_code`s (HTTP):
`invalid_phone`, `country_not_allowed` (CA/US only, `otp.allowed_countries`), `premium_blocked` (NANP 900/976),
`phone_in_use` 409 (`login_instead:true`), `no_account` 404 (`signup_instead:true`), `same_phone`,
`voip_not_allowed` (drivers; Lookup line type), `resend_too_soon` 429 (`retry_after_s`), `rate_limited_phone` 429
(5/phone/h), `rate_limited_ip` 429 (10/IP/h), `voice_not_available`, `channel_unavailable`, `invalid_code`
(`attempts_left`), `too_many_attempts` 429, `code_expired` 410, `no_pending_code`, `send_failed` 502,
`sms_unavailable` 503 (production without Twilio), `step_up_expired` 401, `no_verified_phone`.
Consumers of a token answer `verification_required`, `invalid_verification_token`, `verification_used`,
`verification_expired`, `verification_wrong_purpose`, `phone_mismatch`.

**Test mode:** `TWILIO_TEST_NUMBERS="+15555550100:123456,+15555550101:654321"` → fixed codes, nothing sent
(ignored when `FLASK_ENV=production`). `TWILIO_TEST_VOIP_NUMBERS` makes a test number look like VoIP. Without
Twilio credentials in non-production a random code is generated and written to the server log.

**Scenario endpoints**

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| POST | `/api/users/register` | — | v4 + `ff.legal_consent_required`: `accepted_terms_id`, `accepted_privacy_id`, `accepted_guidelines_id` (ids from `/api/legal/documents`, or `true`/`"current"`), or `acceptances:[{type, document_id}]`; `marketing_opt_in` (CASL, default false); `phone_verification_token` (purpose `signup`; **required** when `ff.phone_required_signup` and v4); `language` en/fr; `province`; `device_id`. Missing ticks → `consent_required` + `missing:[types]` + `documents:[…]`. → 201 user + `token`, `requires_email_verification`, `requires_phone_verification`, `legal_accepted:[types]` |
| POST | `/api/users/login` | — | `{email\|phone_number\|username, password, device_id?, verification_token?}`. v4 extras: `legal_pending:[…]`; suspended/deactivated **v4** users still get a (restricted) token + `account_status`; v3 → `code 0 "Your account has been blocked"` + `data.account_status`. With `ff.step_up_new_device` and an unseen device: HTTP 200 `code 0`, `data {error_code:"step_up_required", requires_step_up:true, step_up_ticket, phone_masked, purpose:"new_device"}` → verify with `step_up_ticket` → repeat login with `verification_token` |
| POST | `/api/auth/login/phone` | — | passwordless (`ff.passwordless_login`): `{phone, verification_token (purpose login), device_id?}` → user + `token` + `legal_pending` |
| POST | `/api/auth/reset-password/phone` | — | `{phone, verification_token (purpose password_reset), password}` → revokes all sessions |
| POST | `/api/profile/update-phone` | JWT | `{phone_number, verification_token (purpose change_phone)}` → user; the **old** number gets an SMS. v4 clients must send the token; v3 keeps the unverified update |
| POST | `/api/profile/delete-account` | JWT | `{password, verification_token (purpose sensitive_action)}` — token required for v4 clients with a verified phone (`ff.sensitive_action_reverify`) → otherwise 403 `{error_code, requires_verification:true, purpose:"sensitive_action"}` |
| POST | `/api/payout-account/create-stripe` · `/preferences` · `/deactivate` · `/reactivate` | JWT | same sensitive-action rule (`verification_token` in body or `X-Verification-Token` header) |
| POST | `/api/webhooks/twilio/inbound` | Twilio (`X-Twilio-Signature`) | STOP/START/HELP; logged to `webhook_events` (provider `twilio`); STOP sets `sms_opt_out_at`, clears marketing opt-in; HELP replies with TwiML. Set `TWILIO_INBOUND_URL` to the public URL Twilio signs |

### Legal documents & consent (§12)

Types: `terms, privacy, community_guidelines, driver_agreement, cancellation_policy, safety_policy, recording_notice,
background_check_consent`. Languages `en`, `fr` (FR falls back to EN). Seeded v1.0 by migration `v4_0202_legal_seed`.
Numbers in the text (fees, windows, retention days, fee amounts) are rendered from `app_settings` at read time.

| Method | Path | Auth | → `data` |
|---|---|---|---|
| GET | `/api/legal/documents?audience=customer\|driver&lang=en\|fr&full=1` | public | `{language, items:[{id, type, version, title, language, audience, requires_reacceptance, what_changed, effective_at, summary_markdown}]}` (`full=1` adds `body_markdown`) |
| GET | `/api/legal/documents/{type}?lang=&version=` | public | `{id, type, version, title, language, audience, status, summary_markdown, body_markdown, what_changed, requires_reacceptance, effective_at, published_at, updated_at}` — aliases `guidelines`, `cancellation-policy`, `safety`, `recording`, `driver-agreement` for the website |
| POST | `/api/legal/accept` | JWT (allowed while suspended) | `{document_ids?:[id], types?:[type], method?: checkbox\|modal\|esignature, app_version?, signature_name?}` (signature required for `background_check_consent`) → `{accepted:[{id, user_id, document_id, document_type, version, accepted_at, ip, user_agent, app_version, method, signature_name}], pending:[…]}`; outdated id → 409 `document_outdated` |
| GET | `/api/legal/pending?lang=` | JWT | `{blocking:bool, items:[{id, type, version, title, language, audience, requires_reacceptance, what_changed, effective_at, reason:"not_accepted"\|"updated"}]}` — show the blocking modal when `blocking` |
| GET | `/api/legal/acceptances` | JWT | `{items:[acceptance]}` |

### Driver onboarding (§14) — see `docs/DRIVER_ONBOARDING.md`

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| GET | `/api/driver/onboarding?lang=` | JWT | **Overview** `{application, steps:[{key, number, title, status, detail}], current_step, progress_pct, can_submit, submit_blockers:[{step, message, …}], documents:[doc], background_check: bgc\|null, requirements:{min_driver_age, min_vehicle_year, allowed_licence_classes, allowed_provinces, required_documents:[{type,title,title_fr,expiry_required}], service_types, bgc_fee_cents, bgc_pay_later_available, bgc_refund_note, orientation_pass_score}, can_go_online:{ok, reason}}` |
| POST | `/api/driver/onboarding/prequal` | JWT | `{date_of_birth:"YYYY-MM-DD", licence_class, vehicle_year, province, has_valid_insurance?}` → overview + `prequal:{passed, reasons:[{field,message}], answers, at}` |
| POST/PUT | `/api/driver/onboarding/profile` | JWT | any of `legal_first_name, legal_last_name, date_of_birth, address_line, city, province, postal_code, service_types:[car_hire\|rideshare\|courier\|movers\|airport\|special_car], licence_class, licence_number, licence_expires_at, vehicle_make, vehicle_model, vehicle_year, vehicle_color, vehicle_plate, vehicle_seats` → overview; 422 `validation_failed` + `fields:{name: message}`; 409 `application_locked` while under review |
| POST | `/api/driver/onboarding/agreements` | JWT | `{signature_name}` → accepts Driver Agreement + Safety Policy (e-signature) → overview + `accepted` |
| GET | `/api/driver/onboarding/documents` | JWT | `{items:[doc], requirements}` |
| POST | `/api/driver/onboarding/documents` | JWT, multipart | `type` (`licence_front, licence_back, registration, insurance, vehicle_front, vehicle_back, vehicle_left, vehicle_right, vehicle_interior, selfie`), `file` (JPG/PNG/HEIC/WEBP/PDF ≤ 10 MB), `expires_at` (required for licence_front, insurance) → 201 overview + `document:{id, application_id, user_id, type, mime_type, expires_at, status, reviewer_note, reviewed_at, reminders_sent, created_at, updated_at, title}`. Files go to private storage only |
| GET | `/api/driver/onboarding/background-check` | JWT | `{background_check, fee_cents, pay_later_available}` |
| POST | `/api/driver/onboarding/background-check/consent` | JWT | `{signature_name, consent?:true}` → overview + `background_check` (status `awaiting_payment`); 409 `prequal_required` |
| POST | `/api/driver/onboarding/background-check/pay` | JWT, Idempotency-Key | `{pay_later?:bool}` → overview + `{background_check, pay_later, checkout_url?, ride_payment_id?, amount_cents?}` — open `checkout_url` in the WebView |
| POST | `/api/driver/onboarding/background-check/sync` | JWT | poll after Checkout returns → overview + `background_check` |
| POST | `/api/driver/onboarding/submit` | JWT, Idempotency-Key | → overview; 422 `incomplete` + `blockers` |
| GET | `/api/driver/onboarding/orientation?lang=` | JWT | `{cards:[{title, body}×5], questions:[{index, question, options:[…]}×5], pass_score}` |
| POST | `/api/driver/onboarding/orientation` | JWT | `{answers:[int×5]}` → overview + `orientation_result:{score, passed, wrong_questions, pass_score}` |
| POST | `/api/driver/onboarding/referral` | JWT | `{code}` → overview |
| GET/POST | `/api/webhooks/certn` | Certn | GET echoes `?challenge=`; POST verified with `X-Signature` = hex HMAC-SHA256(body, `CERTN_WEBHOOK_SECRET`), stored in `webhook_events` (provider `certn`, unique `event_id`), processed by `onboarding_service.process_certn_event` |

**Background check object** `{id, user_id, application_id, provider:"certn", provider_application_id, package, status:
awaiting_payment|paid|initiated|pending|clear|consider|failed|cancelled|expired, result, invite_url, fee_cents,
fee_payment_id, fee_paid_at, paid_by: driver|platform|earnings, consent_acceptance_id, initiated_at, completed_at,
expires_at, deduction_status, deduction_settled_at, recheck_reminded_at, created_at, updated_at, timeline:[{event, at}],
typical_turnaround}` (`report_url` is never returned; admins get a short-lived link).

`/api/go-on-off` and `/api/update-location` refuse to put a driver online (`error_code: cannot_go_online`, message
explains) when the account is not active, a status change is pending, a licence/insurance/registration expired,
the background check failed/expired, or (v4 applicants) the safety orientation is not done.

### Account status & appeals (§15)

| Method | Path | Auth | → `data` |
|---|---|---|---|
| GET | `/api/account/status` | JWT (allowed while suspended) | `{account_status: active\|suspended\|deactivated\|banned\|pending_review, is_active, reason_code, reason_category, reason_label, suspended_until, changed_at, pending_account_status, can_appeal, can_go_online, go_online_block_reason, support_email}` |
| POST | `/api/account/appeal` | JWT (allowed while suspended), Idempotency-Key | `{message, subject?}` → 201 `{ticket, created:true}` (or 200 `created:false` — added to the open appeal) |

Any other endpoint answers **403** `{account_status, status_reason_code, suspended_until, can_appeal}` for an inactive
account; a status change revokes every JWT (401 with an old token). Socket.IO `/rt` receives
`account.status_changed {account_status}` and is disconnected.

### Support tickets (§19.1.8)

Types `general | appeal | dispute | lost_item | safety | billing`; priority `low | normal | high | urgent`
(safety/lost_item default high). SLA = first response within `support.sla_<priority>_h`.

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| GET | `/api/support/tickets?status=` | JWT | `{items:[ticket]}` |
| POST | `/api/support/tickets` | JWT, Idempotency-Key | `{type, body, subject?, priority?, ride_type?, ride_id?, attachments?}` → 201 ticket with `messages` |
| GET | `/api/support/tickets/{id}` | owner | ticket + `messages:[{id, ticket_id, author_id, author_type: user\|admin, body, attachments, created_at}]` |
| POST | `/api/support/tickets/{id}/reply` | owner | `{body}` |
| POST | `/api/support/tickets/{id}/close` | owner | — |

Ticket: `{id, user_id, type, ride_type, ride_id, subject, body, status: open|pending|resolved|closed, priority,
assigned_to, sla_due_at, resolution, first_response_at, closed_by, created_at, updated_at, resolved_at,
sla:{due_at, first_response_at, breached, remaining_s}}`.

### Admin — identity (roles: `super_admin` passes all)

| Method | Path | Roles | Body → `data` |
|---|---|---|---|
| GET | `/api/admin/account-status/reasons` | super_admin, ops, safety_reviewer, support | `{actions:[{action, status}], reasons:[{code, category, label, label_fr}]}` |
| POST | `/api/admin/users/{id}/account-status/preview` | same | `{action, reason_code, duration_days?\|duration_hours?\|until?}` → `{message:{event_key, channels, en:{title, body}, fr:{…}}, will_defer, active_ride}` |
| POST | `/api/admin/users/{id}/account-status` | same | `{action: activate\|reactivate\|suspend\|deactivate\|ban\|pending_review, reason_code (from list), reason_text (required), duration_days\|duration_hours\|until (required for suspend), notify_user?=true, force?}` → `{applied, deferred, account_status, suspended_until?, pending_account_status?, active_ride?, user}` |
| GET | `/api/admin/users/{id}/profile` | same (audited) | `{user, account, verification, strikes:{total, in_window, items}, driver_application, documents, background_checks, legal_acceptances, support_tickets}` |
| GET | `/api/admin/users/{id}/history` | same (audited) | paginated audit_logs for the user (`actor_name` added) |
| GET | `/api/admin/users/{id}/strikes` | same | `{items, window_days, warn_after, suspend_after}` |
| GET | `/api/admin/onboarding/applications?status=&step=&q=&page=` | super_admin, ops, safety_reviewer | paginated `[application + user card + background_check_status + documents_pending]` |
| GET | `/api/admin/onboarding/applications/{id}` | same (audited) | `{application, user, steps, submit_blockers, documents (all versions), background_checks, legal_acceptances}` |
| GET | `/api/admin/onboarding/documents/{id}/file?inline=1` | same (audited) | signed URL `{url, expires_in_s:300}` or the bytes (`inline=1`) |
| POST | `/api/admin/onboarding/documents/{id}/review` | same | `{decision: approve\|reject, note (required to reject), expires_at?}` |
| POST | `/api/admin/onboarding/applications/{id}/decision` | same | `{decision: approve\|reject\|needs_changes, reason (required unless approve), service_types?, override_background_check?}` → `{application, user}`. Approve sets `user_type='Driver'` + `is_<svc>`/`is_<svc>_approved='Yes'` (car_hire/rideshare/airport/special_car → car, courier/movers → delivery) |
| GET | `/api/admin/onboarding/background-checks/{id}/report` | super_admin, safety_reviewer, ops (audited) | `{url}` (Certn report, short-lived) |
| POST | `/api/admin/onboarding/background-checks/{id}/refresh` | onboarding roles | poll Certn now |
| POST | `/api/admin/onboarding/background-checks/{id}/adjudicate` | super_admin, safety_reviewer, ops | `{decision: clear\|failed, note}` |
| GET | `/api/admin/onboarding/funnel` | onboarding roles | `{total_applications, by_status, steps:[{step, title, completed, currently_at, drop_off_pct}]}` |
| GET | `/api/admin/legal/documents?type=&language=&status=` | any admin | `{items, types}` |
| GET | `/api/admin/legal/documents/{id}` | any admin | raw (unrendered) document |
| POST | `/api/admin/legal/documents` | super_admin, ops | `{type, version, language?, title?, body_markdown?, summary_markdown?, audience?, from_id?, what_changed?}` → 201 draft (copied from current when body omitted) |
| PUT | `/api/admin/legal/documents/{id}` | super_admin, ops | drafts only: `{title?, summary_markdown?, body_markdown?, what_changed?, audience?}` |
| GET/POST | `/api/admin/legal/documents/{id}/preview` | any admin | rendered (POST may pass unsaved `body_markdown`/`summary_markdown`) + `variables` |
| POST | `/api/admin/legal/documents/{id}/publish` | super_admin, ops | `{requires_reacceptance?, what_changed?, effective_at?}` → archives the previous version; with re-acceptance every affected user is notified (`legal.policy_updated`) and sees it in `/api/legal/pending` |
| GET | `/api/admin/legal/stats?type=` | any admin | `{total_users, items:[{…document, status, acceptances, acceptance_rate_pct}]}` |
| GET | `/api/admin/legal/documents/{id}/acceptances` | people roles (audited) | paginated acceptances + user card |
| GET | `/api/admin/support/tickets?status=&type=&priority=&assigned_to=me\|none\|id&overdue=1&user_id=` | super_admin, ops, support, safety_reviewer, finance | paginated tickets (+ `user`) and `data.counts` by status, SLA-sorted |
| GET | `/api/admin/support/tickets/{id}` | same (audited) | ticket + all messages (incl. `internal`) |
| POST | `/api/admin/support/tickets/{id}/assign` | same | `{admin_id?='me', priority?}` |
| POST | `/api/admin/support/tickets/{id}/reply` | same | `{body, internal?}` → notifies the user (`support.reply`) unless internal |
| POST | `/api/admin/support/tickets/{id}/status` | same | `{status, resolution?}` |
| GET | `/api/admin/admin-users` | super_admin | `{roles, items:[{id, name, email, phone, user_type, account_status, avatar, roles}]}` |
| PUT | `/api/admin/admin-users/{id}/roles` | super_admin | `{roles:[super_admin\|ops\|safety_reviewer\|finance\|support]}` (bumps the user's token_version) |
