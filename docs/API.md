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
| GET | `/api/carhire/requests/{id}` | the customer, or an offered driver | customer: `request` (with `live_offers`); driver: `incoming card` |
| POST | `/api/carhire/requests/{id}/offers/{offer_id}/accept` | customer | take a driver's live counter → `{request, negotiation}` (negotiation at PRICE_AGREED → AWAITING_PAYMENT, agreed price = the counter, every other offer withdrawn). Errors 409 `offer_expired`, `not_acceptable` (not a live driver counter), `not_open`, `driver_unavailable`; 404 for other customers |
| POST | `/api/carhire/requests/{id}/offers/{offer_id}/counter` | customer | body `{price_cents}` → `{request_id, offer}` (offer `customer_countered`, driver's turn); errors `bad_counter`, `same_price`, 409 `not_counterable`, `offer_expired`, `not_open` |
| POST | `/api/carhire/requests/{id}/cancel` | customer | `request` (status `cancelled`) |
| GET | `/api/carhire/requests/incoming` | driver | `{requests:[incoming card]}` |
| POST | `/api/carhire/requests/{id}/accept` | offered driver | body `{counter_cents?}`. **No counter** → match at once at the customer's price (or at the customer's counter when the offer is `customer_countered`): `{request_id, negotiation}` (PRICE_AGREED → AWAITING_PAYMENT). **Counter** (≠ price on the table) → **no match**: `{request_id, negotiation: null, offer}` with offer `countered`; the request stays open for other drivers. Errors 409 `already_taken`, `not_available`, `awaiting_customer` (your counter is waiting for the rider, `data.counter_cents`); `bad_counter` |
| POST | `/api/carhire/requests/{id}/decline` | offered driver | `{request_id}` (favourite declining → immediate broadcast) |
| GET | `/api/favourite-drivers` | customer | `{drivers:[{driver_id, first_name, avatar, rating, rating_count, car, online, added_at}]}` |
| POST | `/api/favourite-drivers` | customer | body `{driver_id}` → 201 same list |
| DELETE | `/api/favourite-drivers/{driver_id}` | customer | same list |

**request** = `{id, mode, status: favourite|broadcasting|matched|expired|cancelled|no_drivers, service_type, pickup,
dropoff, offer_cents, currency, note, favourite_driver:{id,first_name,avatar,rating,rating_count}|null,
favourite_until, broadcast_at, expires_at, negotiation_id, matched_driver|null, matched_at,
offers:{sent, open, declined, countered}, live_offers:[offer], counter_offer_ttl_s, created_at}`.
**offer** (customer view of one driver's offer) = `{offer_id, status: countered|customer_countered|…, turn:
customer|driver, driver:{id, first_name, avatar, rating, rating_count, vehicle:{make, model, color, year}},
counter_cents, customer_counter_cents, counter_round, eta_min, distance_m, expires_at, accept_endpoint,
counter_endpoint}` — `live_offers` lists only unexpired counters, newest first.
**incoming card** = `{request_id, service_type, offer_cents, currency, note, pickup, dropoff, trip_distance_m,
distance_to_pickup_m, eta_to_pickup_s, is_favourite, respond_by, customer:{id, first_name, avatar, rating,
rating_count}, offer_status, my_counter_cents, customer_counter_cents, counter_expires_at}` (drivers see requests
with offer status `offered` or `customer_countered`).

Flow: `direct` creates the Negotiation immediately (REQUESTED, `negotiation.new_request` push to the driver —
same as `/api/negotiations-create`). `favourite_first` offers to the favourite for `carhire.favourite_first_s`
(45 s), then broadcasts. `broadcast` offers to the nearest `carhire.broadcast_max_drivers` (10) online approved
drivers within `carhire.broadcast_radius_km` (15); unanswered after `carhire.broadcast_timeout_s` (180) → expired
(`ride.expired` notification).

**Counter-offer marketplace (§21.2.2).** The first driver who *accepts the customer's price* wins at once. A driver
*counter* does not match: the customer receives it as a card (`carhire.request_countered`) and can accept it,
counter back, or wait for other drivers. Each live counter expires after `carhire.counter_offer_ttl_s` (90 s) and
keeps the request open at least that long. When the customer accepts one offer the negotiation is created with that
driver at PRICE_AGREED (agreed price = the counter) and every other offer is withdrawn. After matching, continue
with `/api/rides/carhire/{id}/pay`.

**Realtime** (`user:{id}` rooms): `carhire.request_offered` (driver, incoming card),
`carhire.request_withdrawn` `{request_id, reason: taken|cancelled|expired}` (driver),
`carhire.request_matched` `{request_id, negotiation_id, counter_cents, agreed, driver:<nearby card>}` (customer),
`carhire.request_updated` (customer, request),
`carhire.request_countered` `{request_id, …offer}` (customer — offer fields above: `offer_id, driver`
(first name, avatar, rating, rating_count, vehicle), `counter_cents, eta_min, distance_m, expires_at`),
`carhire.customer_countered` (driver, incoming card), `carhire.offer_updated` `{request_id, …offer}` (customer: a
counter expired or the driver declined). Push: `negotiation.new_request` with
`{ride_type:"carhire_request", request_id, price, distance_km, favourite}`; `carhire.request_countered` /
`carhire.customer_countered` with `{request_id, offer_id, price}` (deep link `negoride://carhire_request/{request_id}`).

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

**Client headers (v4 app):** `X-App-Version: 4.0.0` (enables v4-only rules: consent ticks, phone-required sign-up,
sensitive re-verify, restricted login for suspended accounts, legal re-acceptance gate), `X-Device-Id: <stable
install id>` (new-device step-up), optional `Accept-Language: fr`. v3 builds send neither and keep the old
behaviour **only while `app.legacy_clients_allowed` = true** (public in `/api/app/config`); when an admin turns it
off every request is treated as v4 whatever headers it sends. **Contract for the mobile app:** send
`X-App-Version` (and `X-Device-Id`) on *every* request, including `/api/users/login`, `/api/users/register`,
payout-account calls and `/api/profile/*`.

**Auth failures (every `@jwt_required_with_user` endpoint):**
401 `{code:0, message:"Unauthorized"}` (no/invalid token) · 401 `data:{error_code:"session_revoked"}` (token
revoked by password reset / role change, or a restricted token after reactivation → log in again) · 403
`data:{error_code:"account_blocked", account_status, status_reason_code, reason_code, reason_category,
reason_label, suspended_until, can_appeal}` (inactive account — also when an old token of a now-suspended account
is used, so the app shows the suspended screen instead of the login) · 403 `data:{error_code:"legal_pending",
blocking:true, items:[pending doc…], pending:[…]}` (v4: a policy published with "requires re-acceptance" is not
accepted yet; show the blocking modal → `POST /api/legal/accept`). Exempt from `legal_pending`: `/api/legal`,
`/api/users/me`, `/api/account`, `/api/app/config`, `/api/notifications`, `/api/notification-preferences`,
`/api/devices`, `/api/rides/*`, `/api/support`, `/api/safety`, `/api/sos`, `/api/update-location`,
`/api/tracking`, `/api/verify`, `/api/calls`, `/api/stream`, `/api/profile/delete-account`, admin endpoints.

### Phone verification — Twilio Verify (§11)

`purpose` ∈ `signup | login | change_phone | driver_onboarding | new_device | password_reset | sensitive_action`.
`channel` ∈ `sms | call | whatsapp` (call only after `otp.voice_after_failed_sms` SMS in the last hour; WhatsApp only
when `otp.whatsapp_enabled`). Auth is optional except for `change_phone`, `driver_onboarding`, `sensitive_action`
(JWT) and `new_device` (`step_up_ticket` from login). For `sensitive_action` / `new_device` the phone comes from the
account (omit `phone`).

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| POST | `/api/verify/phone/start` | optional | `{phone, purpose, channel?, step_up_ticket?, locale?, app_hash?}` (`app_hash` = 11-char Android SMS Retriever hash, or header `X-App-Hash`; falls back to `TWILIO_ANDROID_APP_HASH`; forwarded to Twilio Verify as `AppHash`, SMS only) → `{verification_id, phone:"+14165550123", phone_masked, purpose, channel, expires_in_s:600, resend_after_s:30, voice_available:bool, whatsapp_available:bool, max_attempts:5, test_mode:bool, line_type_warning:"voip"\|null, line_type_warning_message:string\|null}` (`line_type_warning` only for purpose `signup`). For `purpose:"login"` an unknown number gets the **same** success answer (nothing is sent; the check then fails with `no_pending_code`) — no account enumeration. Rate limits apply before any account lookup |
| POST | `/api/verify/phone/check` | optional | `{phone, purpose, code, step_up_ticket?}` → `{verification_token:"pvt_…" \| null, expires_in_s:900, phone, phone_masked, purpose, line_type, applied:bool, user?}` — when a logged-in user checks `driver_onboarding` or `signup`, the number is applied to the account at once (`applied:true`, token `null`, `user` = updated user) |
| POST | `/api/otp-request` | optional | legacy alias of start: `{phone_number, purpose?='signup', channel?}` |
| POST | `/api/otp-verify` | optional | legacy alias of check: `{phone_number, otp, purpose?='signup'}` |

`verification_token` is single use, valid 15 min, and only its SHA-256 is stored. Error `data.error_code`s (HTTP):
`invalid_phone`, `country_not_allowed` (CA/US only, `otp.allowed_countries`; +1 Caribbean/territory area codes
242, 246, 264, 268, 284, 340, 345, 441, 473, 649, 658, 664, 670, 671, 684, 721, 758, 767, 784, 787, 809, 829, 849,
868, 869, 876, 939 are refused unless listed in `otp.allowed_nanp_regions` or their ISO code is in
`otp.allowed_countries`), `premium_blocked` (NANP 500, 533, 544, 566, 577, 588, 700, 710, 900, 976),
`phone_in_use` 409 (`login_instead:true`), `same_phone`,
`voip_not_allowed` (drivers; Lookup line type), `line_type_unknown` 503 (driver_onboarding in production when
Lookup gives no answer — fail closed), `resend_too_soon` 429 (`retry_after_s`), `rate_limited_phone` 429
(5/phone/h), `rate_limited_ip` 429 (10/IP/h), `voice_not_available`, `channel_unavailable`, `invalid_code`
(`attempts_left`), `too_many_attempts` 429, `code_expired` 410, `no_pending_code`, `send_failed` 502,
`sms_unavailable` 503 (production without Twilio), `step_up_expired` 401, `no_verified_phone`.
Consumers of a token answer `verification_required`, `invalid_verification_token`, `verification_used`,
`verification_expired`, `verification_wrong_purpose`, `phone_mismatch`.

**Test mode:** `TWILIO_TEST_NUMBERS="+15555550100:123456,+15555550101:654321"` → fixed codes, nothing sent —
only when `TWILIO_TEST_MODE_ENABLED=1` **and** FLASK_ENV is `development`/`dev`/`testing`/`test`/`local` (any other
value, or none, is production). `TWILIO_TEST_VOIP_NUMBERS` makes a test number look like VoIP. Without
Twilio credentials in non-production a random code is generated and written to the server log.

**Scenario endpoints**

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| POST | `/api/users/register` | — | v4 + `ff.legal_consent_required`: `accepted_terms_id`, `accepted_privacy_id`, `accepted_guidelines_id` (ids from `/api/legal/documents`, or `true`/`"current"`), or `acceptances:[{type, document_id}]`; `marketing_opt_in` (CASL, default false) + optional `marketing_consent_version` (the wording version the app showed — `legal.marketing_consent_version` / `legal.marketing_consent_text[_fr]` in `/api/app/config`); `phone_verification_token` (purpose `signup`; **required** when `ff.phone_required_signup` and v4); `language` en/fr; `province`; `device_id`. Missing ticks → `consent_required` + `missing:[types]` + `documents:[…]`. A verified phone already on another account (DB-unique) → 409 `phone_in_use` (`login_instead:true`). → 201 user + `token`, `requires_email_verification`, `requires_phone_verification`, `legal_accepted:[types]`. A marketing opt-in writes a CASL proof row (`marketing_consents`) |
| POST | `/api/users/login` | — | `{email\|phone_number\|username, password, device_id?, verification_token?}` → user + `token` + `requires_phone_verification:bool` (true when `ff.phone_required_signup` and no verified phone — send the user to phone verification, purpose `signup` while logged in). v4 extras: `legal_pending:[…]`. **Suspended / deactivated / banned / pending_review**: v4 → HTTP **403** `code 0`, `data = {error_code:"account_blocked", account_status, status_reason_code, reason_code, reason_category, reason_label, suspended_until, can_appeal, token, access_token, remember_token, restricted:true, token_expires_in_s:7200, user}` — the restricted token works only on `/api/users/me`, `/api/account/status`, `/api/account/appeal`, `/api/support`, `/api/legal`, `/api/app/config`, `/api/rides/*`, `/api/notifications`; v3 → `code 0 "Your account has been blocked"` + `data.account_status`. With `ff.step_up_new_device` and an unseen device (a login **without** a device id counts as unseen once the account has a trusted device): HTTP 200 `code 0`, `data {error_code:"step_up_required", requires_step_up:true, step_up_ticket, phone_masked, purpose:"new_device"}` → verify with `step_up_ticket` → repeat login with `verification_token` |
| POST | `/api/auth/login/phone` | — | passwordless (`ff.passwordless_login`): `{phone, verification_token (purpose login), device_id?}` → user + `token` + `legal_pending` + `requires_phone_verification`; inactive account → same 403 `account_blocked` payload as `/api/users/login` |
| POST | `/api/auth/forgot-password` | — | `{email}` → always success; emails (EN/FR by `preferred_language`) a link to `{PUBLIC_WEB_BASE_URL}/reset-password?token=…&email=…` (1 h) |
| POST | `/api/auth/reset-password` | — | `{token (full token — no short codes), password, email?}` (the website page posts both) → revokes every session; 400 `invalid_token`, 410 `token_expired` |
| POST | `/api/email/verify` | — | `{token, email?}` — called by the website page `{PUBLIC_WEB_BASE_URL}/verify-email?token=…&email=…` (verification emails link there, EN/FR) → `{verified:true, already_verified:bool}`; 400 `invalid_token`, 410 `token_expired`. `GET /api/email/verify/{token}` (HTML page) stays for old emails |
| POST | `/api/profile/update` | JWT | profile fields; `email` change → 409 `email_in_use` or unverifies + sends a new verification email; **`phone_number` changes are refused** → 400 `{error_code:"use_update_phone", purpose:"change_phone", endpoint:"/api/profile/update-phone"}` (sending the current number is fine) |
| POST | `/api/auth/reset-password/phone` | — | `{phone, verification_token (purpose password_reset), password}` → revokes all sessions |
| POST | `/api/profile/update-phone` | JWT | `{phone_number, verification_token (purpose change_phone)}` → user; the **old** number gets an SMS. v4 clients (all clients once `app.legacy_clients_allowed` is off) must send the token; v3 keeps an **unverified** update (clears `phone_e164`/`phone_verified_at`, SMS to the old number). 409 `phone_in_use` |
| POST | `/api/profile/delete-account` | JWT | `{password, verification_token (purpose sensitive_action)}` — token required for v4 clients whenever the account has a phone number, verified or not (`ff.sensitive_action_reverify`) → otherwise 403 `{error_code, requires_verification:true, purpose:"sensitive_action"}` |
| POST/GET | `/api/payout-account/create-stripe` · `/preferences` · `/deactivate` · `/reactivate` · `/onboarding-link` · `GET /dashboard-link` | JWT | same sensitive-action rule (`verification_token` in body, `X-Verification-Token` header, or `?verification_token=` for the GET) |
| POST | `/api/negotiations-create`, `/api/negotiations`, `/api/bookings`, `/api/bookings/courier-batch`, `/api/trips-bookings-create`, `/api/rideshare/trips/{id}/book` | JWT | with `ff.phone_required_signup` (v4 clients / legacy disallowed, non-admins) an account without a verified phone → 403 `{error_code:"phone_verification_required", requires_phone_verification:true, purpose:"signup"}` |
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

**CASL proof:** every marketing opt-in / opt-out (registration, `PUT /api/notification-preferences
{marketing_opt_in, marketing_consent_version?}`, SMS STOP) appends a `marketing_consents` row `{user_id, action:
grant|withdraw, channels, source: registration|preferences|sms_stop, wording_version, wording_text, language, ip,
user_agent, app_version, created_at}`.

### Driver onboarding (§14) — see `docs/DRIVER_ONBOARDING.md`

| Method | Path | Auth | Body → `data` |
|---|---|---|---|
| GET | `/api/driver/onboarding?lang=` | JWT | **Overview** `{application, steps:[{key, number, title, status, detail}], current_step, progress_pct, can_submit, submit_blockers:[{step, message, …}], documents:[doc], background_check: bgc\|null, renewal_due:bool, insurance_endorsement_required:bool, requirements:{min_driver_age, min_vehicle_year, allowed_licence_classes, allowed_provinces, required_documents:[{type,title,title_fr,expiry_required}], service_types, bgc_fee_cents, bgc_pay_later_available, bgc_refund_note, bgc_start_delay_min, rideshare_endorsement_provinces, orientation_pass_score}, can_go_online:{ok, reason}}`. Step `phone_verified` is `done` only when the phone is verified **and** its line type is known and not VoIP; otherwise `action_needed` with `detail.issue` `line_type_unknown`\|`voip` (verify again with purpose `driver_onboarding`) |
| POST | `/api/driver/onboarding/prequal` | JWT | `{date_of_birth:"YYYY-MM-DD", licence_class, vehicle_year, province, has_valid_insurance?}` → overview + `prequal:{passed, reasons:[{field,message}], answers, at}` |
| POST/PUT | `/api/driver/onboarding/profile` | JWT | any of `legal_first_name, legal_last_name, date_of_birth, address_line, city, province, postal_code, service_types:[car_hire\|rideshare\|courier\|movers\|airport\|special_car], licence_class, licence_number, licence_expires_at, vehicle_make, vehicle_model, vehicle_year, vehicle_color, vehicle_plate, vehicle_seats` → overview; 422 `validation_failed` + `fields:{name: message}`; 409 `application_locked` while under review |
| POST | `/api/driver/onboarding/agreements` | JWT | `{signature_name}` → accepts Driver Agreement + Safety Policy (e-signature) → overview + `accepted` |
| GET | `/api/driver/onboarding/documents` | JWT | `{items:[doc], requirements}` |
| POST | `/api/driver/onboarding/documents` | JWT, multipart | `type` (`licence_front, licence_back, registration, insurance, vehicle_front, vehicle_back, vehicle_left, vehicle_right, vehicle_interior, selfie`), `file` (JPG/PNG/HEIC/WEBP/PDF ≤ 10 MB), `expires_at` (required for licence_front, insurance), `attestation_rideshare_endorsement=true` (insurance, required when the province is in `onboarding.rideshare_endorsement_provinces` → else 422 `endorsement_attestation_required` + `province`) → 201 overview + `document:{id, application_id, user_id, type, mime_type, expires_at, status, reviewer_note, reviewed_at, reminders_sent, meta, face_match_status, face_match_score, face_match_provider, face_match_checked_at, face_match_detail, created_at, updated_at, title}`. Files go to private storage only |
| GET | `/api/driver/onboarding/background-check` | JWT | `{background_check, fee_cents, pay_later_available}` |
| POST | `/api/driver/onboarding/background-check/consent` | JWT | `{signature_name, consent?:true}` → overview + `background_check` (status `awaiting_payment`); 409 `prequal_required` |
| POST | `/api/driver/onboarding/background-check/pay` | JWT, Idempotency-Key | `{pay_later?:bool}` → overview + `{background_check, pay_later, checkout_url?, ride_payment_id?, amount_cents?}` — open `checkout_url` in the WebView |
| POST | `/api/driver/onboarding/background-check/sync` | JWT | poll after Checkout returns → overview + `background_check` |
| POST | `/api/driver/onboarding/background-check/cancel` | JWT, Idempotency-Key | `{reason?}` — only before the check is submitted to Certn (`start_after` window, `onboarding.bgc_start_delay_min`, default 30 min after payment) → overview + `{background_check (status cancelled), refunded_cents}` (card fee refunded in full; pay-later deduction waived); 409 `nothing_to_cancel` / `already_submitted` |
| POST | `/api/driver/onboarding/submit` | JWT, Idempotency-Key | → overview; 422 `incomplete` + `blockers` |
| GET | `/api/driver/onboarding/orientation?lang=` | JWT | `{cards:[{title, body}×5], questions:[{index, question, options:[…]}×5], pass_score}` |
| POST | `/api/driver/onboarding/orientation` | JWT | `{answers:[int×5]}` → overview + `orientation_result:{score, passed, wrong_questions, pass_score}` |
| POST | `/api/driver/onboarding/referral` | JWT | `{code}` → overview |
| POST | `/api/payout-requests` | JWT, Idempotency-Key | `{amount (dollars), payout_method?, description?}` — pay-later background-check fees are recovered from the wallet first (partial recovery allowed); while any remains → 409 `{error_code:"bgc_fee_outstanding", outstanding_cents}`. A repeated `Idempotency-Key` returns the first response |
| GET/POST | `/api/webhooks/certn` | Certn | GET echoes `?challenge=`; POST verified with `X-Signature` = hex HMAC-SHA256(body, `CERTN_WEBHOOK_SECRET`), stored in `webhook_events` (provider `certn`, unique `event_id`), processed by `onboarding_service.process_certn_event` |

**Background check object** `{id, user_id, application_id, provider:"certn", provider_application_id, package, status:
awaiting_payment|paid|initiated|pending|clear|consider|failed|cancelled|expired, result, invite_url, fee_cents,
fee_payment_id, fee_paid_at, paid_by: driver|platform|earnings, consent_acceptance_id, consent_evidence:{…},
start_after, refunded_cents, refunded_at, cancelled_at, deducted_cents, receipt_emailed_at, initiated_at,
completed_at, expires_at, deduction_status, deduction_settled_at, recheck_reminded_at, created_at, updated_at,
timeline:[{event, at}], typical_turnaround}` (`report_url` is never returned; admins get a short-lived link).

`/api/go-on-off` and `/api/update-location` refuse to put a driver online (`error_code: cannot_go_online`, message
explains) when the account is not active, a status change is pending, a licence/insurance/registration expired,
the background check failed/expired, or (v4 applicants) the safety orientation is not done.

### Account status & appeals (§15)

| Method | Path | Auth | → `data` |
|---|---|---|---|
| GET | `/api/account/status` | JWT (allowed while suspended) | `{account_status: active\|suspended\|deactivated\|banned\|pending_review, is_active, reason_code, reason_category, reason_label, suspended_until, changed_at, pending_account_status, can_appeal, can_go_online, go_online_block_reason, support_email}` |
| POST | `/api/account/appeal` | JWT (allowed while suspended), Idempotency-Key | `{message, subject?}` → 201 `{ticket, created:true}` (or 200 `created:false` — added to the open appeal) |

Any other endpoint answers **403** `account_blocked` (shape above) for an inactive account; a status change
revokes every JWT — an old token of a now-inactive account gets the same 403 `account_blocked`, other revocations
get 401 `session_revoked`. Socket.IO `/rt` receives `account.status_changed {account_status, is_active,
reason_code, reason_category, reason_label, suspended_until, can_appeal, pending_account_status}` and is
disconnected; the call-signalling socket (namespace `/`) is disconnected too and its `authenticate` answers
`auth_error {error, error_code: session_revoked|account_blocked}` for revoked tokens / inactive accounts. The SSE
stream `/api/stream/events` re-checks every ~15 s and ends with `data: {"type":"auth_revoked","error_code":
"session_revoked"|"account_blocked","account_status"}`. `can_appeal` is true for suspended, deactivated, banned
and pending_review. A failed background check of an approved driver sets `pending_review`
(`failed_background_check`).

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
| GET | `/api/admin/users/{id}/history` | same (audited) | paginated audit_logs about the user, by the user, and about the user's driver application, driver documents, background checks, safety incidents and support tickets (`actor_name` added) |
| POST | `/api/admin/users/{id}/toggle-status` · `/api/admin/users/{id}/update` (with `status`) | legacy admin | now require `reason_code` (from the reasons list) + `reason_text` → otherwise `reason_required` / `reason_text_required`; the legacy editor no longer changes `ready_for_trip` |
| GET | `/api/admin/users/{id}/strikes` | same | `{items, window_days, warn_after, suspend_after}` |
| GET | `/api/admin/onboarding/applications?status=&step=&q=&page=` | super_admin, ops, safety_reviewer | paginated `[application + user card + background_check_status + documents_pending]` |
| GET | `/api/admin/onboarding/applications/{id}` | same (audited) | `{application, user, steps, submit_blockers, documents (all versions, with meta + face_match_*), background_checks (with consent_evidence), legal_acceptances, face_match:{status, score, provider, checked_at, detail, selfie_document_id, licence_document_id, threshold, advisory_only:true}\|null, insurance_endorsement_required, renewal_due}` |
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
| GET | `/api/admin/legal/stats?type=` | any admin | `{total_users, items:[{…document, status, acceptances, audience_users, acceptance_rate_pct}]}` — the rate's denominator is `audience_users` = live users in the document's audience (all/customer/driver) **and** language (FR docs → users with preferred language fr; EN → everyone else) |
| GET | `/api/admin/legal/documents/{id}/acceptances` | people roles (audited) | paginated acceptances + user card |
| GET | `/api/admin/support/tickets?status=&type=&priority=&assigned_to=me\|none\|id&overdue=1&user_id=` | super_admin, ops, support, safety_reviewer, finance | paginated tickets (+ `user`) and `data.counts` by status, SLA-sorted |
| GET | `/api/admin/support/tickets/{id}` | same (audited) | ticket + all messages (incl. `internal`) |
| POST | `/api/admin/support/tickets/{id}/assign` | same | `{admin_id?='me', priority?}` |
| POST | `/api/admin/support/tickets/{id}/reply` | same | `{body, internal?}` → notifies the user (`support.reply`) unless internal |
| POST | `/api/admin/support/tickets/{id}/status` | same | `{status, resolution?}` — resolving/closing a `dispute` ticket with a ride sets the ride's `dispute_resolved_at` (evidence retention clock) |
| GET | `/api/admin/admin-users` | super_admin | `{roles, items:[{id, name, email, phone, user_type, account_status, avatar, roles}]}` |
| PUT | `/api/admin/admin-users/{id}/roles` | super_admin | `{roles:[super_admin\|ops\|safety_reviewer\|finance\|support]}` (bumps the user's token_version) |

---

## Safety, live location, tracking, recordings — v4.1 additions (spec §8, §9, §10, §16)

Full design in `docs/SAFETY.md`. Source: `routes/safety.py`, `routes/location.py`, `routes/tracking_share.py`,
`routes/recordings.py`, `routes/admin_safety.py`, services `safety_service.py`, `safety_detection.py`,
`safety_jobs.py`, `tracking.py`, `live_share.py`, `recording_service.py`, `geo_routes.py`, `eta.py`.

### Location updates (driver + customer apps)

`POST /api/update-location` and socket `location:update` (namespace `/rt`) accept one point and/or a batch:
```json
{"lat":43.65,"lng":-79.38,"speed":8.2,"heading":90,"accuracy":6,"recorded_at":"2026-09-28T14:03:05Z",
 "points":[{"lat":43.64,"lng":-79.38,"speed":0,"heading":0,"accuracy":9,"recorded_at":"2026-09-28T13:55:00Z"}]}
```
`latitude`/`longitude` aliases still work; `recorded_at` is ISO-8601 or epoch s/ms (omit → server time).
≤ 500 points per request. Points older than `tracking.max_point_age_s` (600) or not newer than the last live
point are **stored as breadcrumbs but not used live**. Re-sent points (same user + `recorded_at`) are deduped.

HTTP response `data` (old fields kept): `{latitude, longitude, current_address, updated_at, points_received,
points_stored, points_rejected, live}`. Socket ack: `{ok, live, stored, received, rejected}`.

### Ride PIN lock

`POST /api/rides/{type}/{id}/start` wrong PIN → 400 `{error_code:'pin_invalid', attempts_left}`. After
`safety.pin_max_attempts` (5) wrong PINs within `safety.pin_lock_window_s` (600 s) → **429**
`{error_code:'pin_locked', retry_after:<seconds>}` (also for the right PIN until the window passes). The locking
attempt writes audit `ride.pin_locked`, emits `alert {kind:'pin_locked', ride_type, ride_id, driver_id, attempts,
retry_after_s, message}` to `admin:ops` + `admin:sos`, and notifies ops/safety admins (`safety.pin_locked`).
Admin transitions bypass the lock.

### Vehicle verification card

`rides.vehicle_card(driver, ride_type=, ride=, viewer=)` adds `photo_url` (5-min signed URL of the approved
`vehicle_front` document) for a party of the ride while the stage is CONFIRMED…IN_PROGRESS / RIDING; otherwise
`photo_url: null`. Safety toolkit `ride.vehicle.photo_url` uses it.
**Rides agent:** pass `ride_type=ride_type, ride=ride, viewer=<request user>` in `ride_actions.py` (ride
detail `vehicle`) to show it on the ride screen.

### SOS

`POST /api/safety/sos` never fails because of the ride reference: an unknown / foreign / malformed
`ride_type`+`ride_id` is ignored (the caller's active ride, or no ride, is used) and noted on the incident
(`notes`, audit meta `rejected_ride`). Response unchanged (201).

### Trusted contacts

`POST /api/safety/trusted-contacts` — `auto_share` now defaults to **true**. Auto-share (night / always) sends to
contacts flagged `auto_share`; when none is flagged, to **all** trusted contacts.

### Recording status (any party)

`GET /api/rides/{type}/{id}/recording-status` → adds `ever_recorded`, `other_party_ever_recorded`, and
`recordings` now lists every non-deleted recording: `[{id, role, status: recording|stopped, is_mine, started_at,
stopped_at}]` (never URLs). The toolkit's `recording` block carries `ever_recorded` and `recordings` too.

### Public tracking

* `GET /api/public/track/{token}` — rate-limited per IP (`tracking.public_rate_limit_per_min`, 60) **and per
  token** (`tracking.public_rate_limit_per_token_per_min`, 120) → 429 `{error_code:'rate_limited', retry_after:60}`.
  `?lang=fr` localises `status_text` (also `ride.status_text` on SOS links) and `eta.text`.
  `eta`: `{minutes, arrives_at, target, distance_m, source, text:"4 min · 1.2 km away"}`.
  `driver_location` comes from the live position store while the trip runs, only from the trip's last
  breadcrumb after it ended.
* `GET /t/{token}` — same rate limits; **302** to `PUBLIC_WEB_BASE_URL/t/{token}` (keeps `?lang`) when that
  base URL is set and on another host; otherwise the fallback page.
* Client IP = `request.remote_addr` after ProxyFix (`TRUSTED_PROXY_COUNT`, default 1).

### Admin (Safety Center / Live map)

| Method | Path | Roles | Response `data` |
|---|---|---|---|
| GET | `/api/admin/live/rides` | ops, safety_reviewer, support, finance | see below |
| GET | `/api/admin/live/drivers?include_offline_active=0\|1` | same | default 1 (drivers on an active ride are shown even when offline); 0 = online only |
| GET | `/api/admin/safety/recordings/{id}/chunks/{seq}` | safety_reviewer | audio/mp4 bytes; `Range: bytes=a-b` → 206; audited `recording.chunk_streamed` on EVERY fetch |
| GET | `/api/admin/safety/recordings/{id}` | safety_reviewer | each chunk now also has `stream_url` (prefer it; the signed `url` stays) |
| GET | `/api/admin/rides/{type}/{id}/route?snap=1` | ops… | adds `snapped: {snapped, polyline, points}` (Roads API, cached; `snapped:false` without a server key) and `planned_routes: [{target, polyline, distance_m, duration_s, source, created_at}]` |

`GET /api/admin/live/rides`:
```json
{"requests":[{"kind":"ride_request|negotiation","id":1,"ride_type":"carhire","status":"broadcasting|REQUESTED|NEGOTIATING",
   "mode":"broadcast","service_type":"car","pickup":{"lat":43.65,"lng":-79.38,"address":"…"},"dropoff":{…},
   "offer_cents":1500,"customer":{"id":7,"first_name":"Ana"},"negotiation_id":null,"driver_id":null,
   "created_at":"…Z","expires_at":"…Z"}],
 "rideshare_trips":[{"trip_id":3,"ride_type":"rideshare_trip","stage":"BOARDING|IN_PROGRESS","driver":{"id":9,"first_name":"Ben"},
   "position":{"lat":…,"lng":…,"heading":90,"at":"…Z","source":"live|last_known"},"start":{lat,lng,address},"end":{…},
   "passengers":2,"seats":3,"departure_at":"…Z","started_at":"…Z"}],
 "sos":[{"incident_id":5,"kind":"sos","status":"open|acknowledged","severity":"critical","silent":false,
   "user":{"id":7,"first_name":"Ana","role":"customer|driver"},"ride_type":null,"ride_id":null,
   "position":{"lat":…,"lng":…,"at":"…Z","accuracy_m":12,"source":"incident"},"battery_pct":55,
   "created_at":"…Z","acknowledged_at":null,"escalated_at":null}],
 "counts":{"requests":1,"rideshare_trips":1,"sos":1},"generated_at":"…Z","refresh_s":10}
```
Realtime for the map: `live.sos_location` (room `admin:ops`) on every SOS position `{incident_id, status, lat, lng,
accuracy_m, heading, speed_mps, battery_pct, at, type:'location', user_id, role, ride_type, ride_id}`;
`driver.location` (existing) for drivers; `alert {kind:'oncall_not_configured', incident_id, level:'critical', message}`
when an SOS escalates with no on-call phones. Poll `/live/rides` every `refresh_s` for requests/trips.

### Cross-agent hooks

* `safety_service.readiness_checks()` → `[{key, area:'safety', level:'ok|warning|critical', message}]`
  (keys `safety.oncall_phones`, `safety.support_phone`, `safety.twilio`, `safety.redis`) — for `/api/admin/readiness`.
* `safety_service.mark_dispute_resolved(ride_type, ride_id, at=None, actor=None)` → bool (caller commits) — call it
  when an admin resolves/closes a support ticket of type `dispute`. Retention also treats a `dispute` ticket with
  status resolved/closed as a closed case.
* ETA → `backend.services.notify.live_activity.push_update(ride_type, ride_id, payload)` is called after every
  `ride.eta_updated` when that module exists (payload = the `ride.eta_updated` body).


---

## Trips, payments, receipts & notifications — audit additions (v4.2)

Source: `routes/admin.py` (legacy admin), `routes/admin_v4.py`, `routes/admin_finance.py`, `routes/ratings.py`,
`routes/receipts.py`, `routes/notifications.py`, `routes/trips.py`, `services/payments/payment_service.py`,
`services/receipts.py`, `services/receipt_jobs.py`, `services/notify/*`, `services/readiness.py`.

### Mobile

| Method | Path | Who | Body → response |
|---|---|---|---|
| POST | `/api/rides/{type}/{id}/tip` | rider, ride COMPLETED/DROPPED_OFF/CLOSED, within `tip.within_h` (72 h) | `{amount_cents}` (50…`tip.max_cents`) → 201 `{ride_payment_id, amount_cents, currency, status:'pending', checkout_url, reused:false}` (200 + `reused:true` when the same-amount checkout is still open). Errors `bad_amount_cents`, 403 `tip_not_allowed`, 409 `not_completed`, 410 `tip_window_closed`, `not_tippable` (rideshare_trip). Independent of the rating. When paid: driver wallet credit (100 %), `tip_receipts` row **NR-TIP-YYYY-NNNNNN** + PDF emailed (`tip.receipt`). |
| GET | `/api/rides/{type}/{id}/receipt` | parties | now also `tips: {items:[{id, number, amount_cents, currency, paid_at, issued_at, pdf_url}], total_cents}` — tips paid after the receipt (the receipt snapshot itself never changes; tips captured before issue stay in `totals.tip_cents`). |
| GET | `/api/rides/{type}/{id}/receipt.pdf` | parties | the **driver** gets a driver copy (DRIVER COPY badge, rider first name only, no payment method). |
| GET | `/api/receipts/tips/{id}.pdf` | the rider | tip receipt PDF |
| POST | `/api/devices/live-activity` | ride party | `{ride_type: carhire\|scheduled\|rideshare_booking, ride_id, activity_id, push_token, platform?}` → 201 `{id, user_id, ride_type, ride_id, activity_id, platform, status:'active', …}` (token never returned). Errors 403 `forbidden`, 404 `not_found`, `missing_fields`, `unsupported_ride_type`. The app must ALSO call OneSignal `LiveActivities.enter(activity_id, token)`. |
| DELETE | `/api/devices/live-activity/{activity_id}` | owner | `{removed}` |
| GET | `/api/app/config` | public | adds `services: ["car_hire","rideshare","courier","movers","airport","special_car"]` (setting `services.enabled`) |
| GET | `/api/rides/{type}/{id}` | parties | `payment` adds `refund_status: none\|partially_refunded\|refunded`, `provider` (`stripe`\|`offline`), `settlement_status` (`safety_review`\|`settled`\|`auto_released`\|null) |
| POST | `/api/trips-create` | driver | `publish: false` → DRAFT (`message: "Draft saved"`, legacy status `Pending`), not searchable/bookable/visible to others until `POST /api/rides/rideshare_trip/{id}/publish` |

`capture_status` values: `pending, authorized, captured, partially_captured, canceled, failed, expired` + refund overlay
**`partially_refunded`, `refunded`** (the pre-refund status is kept in `meta.capture_status_before_refund`).

Payment failures: `payment.failed` push/inbox with `{ride_type, ride_id, ride_payment_id, reason, action_required}`
(`reason` e.g. "Your card has insufficient funds."; `action_required: true` for 3-D Secure). The ride stays
AWAITING_PAYMENT / PENDING_PAYMENT until it expires; retry with `POST /api/rides/{type}/{id}/pay {force_new: true}`.

### Admin

| Method | Path | Roles | Body → response |
|---|---|---|---|
| POST | `/api/admin/negotiations/{id}/update-status` | legacy admin | `{status: Pending\|Accepted\|Started\|Completed\|Cancelled, reason (≥5), policy_reason?}` → legacy negotiation dict. Walks the state machine as admin (one trip_event per step). Errors 400 `reason_required`, 402 `payment_required` (not paid — use mark-paid / let the customer pay), 409 `invalid_transition` / `terminal` with `data.stage`. `Cancelled` = cancel below. |
| POST | `/api/admin/negotiations/{id}/cancel` | legacy admin | `{reason (≥5), policy_reason?: customer_cancel (default)\|driver_cancel\|safety\|expired\|driver_no_show}` → legacy dict; `ride_actions.cancel(actor_type='admin')`: §7 policy, hold released / fee captured in a job, parties notified, audited `ride.admin_cancel`. |
| POST | `/api/admin/trips/{id}/update-status` | legacy admin | `{status: Active\|Ongoing\|Started\|Completed\|Canceled\|Cancelled, reason}` |
| POST | `/api/admin/trips/{id}/cancel` | legacy admin | `{reason}` → CANCELLED_BY_DRIVER cascade (every passenger refunded 100 %) |
| POST | `/api/admin/bookings/{id}/update-status` | legacy admin | `{status: pending\|price_negotiating\|price_accepted\|driver_assigned\|confirmed\|in_progress\|completed\|cancelled, reason}` (same errors) |
| POST | `/api/admin/bookings/{id}/cancel` | legacy admin | `{reason, policy_reason?}` |
| POST | `/api/admin/bookings/{id}/mark-paid` | legacy admin | `{reason (≥5), amount_cents?}` → legacy booking dict (CONFIRMED). Records an offline `RidePayment` (`provider:'offline'`, `capture_method:'offline'`, `capture_status:'captured'`) then walks to CONFIRMED; 409 `already_paid` / `bad_stage`, `no_price`. Refunds of offline payments are recorded without calling Stripe. |
| POST | `/api/admin/bookings/{id}/assign-driver` | legacy admin | `{driver_id, reason? (required when replacing)}` — same rules as v4 reassign; errors `reason_required`, `driver_unavailable`, 409 `bad_stage`, `already_assigned` |
| POST | `/api/admin/rides/{type}/{id}/settle-safety` | super_admin, ops, safety_reviewer, finance | `{amount_cents (0…held), reason (≥5)}` → `{charged_cents, released_cents, refunded_cents, payment}`. Only while `settlement_status='safety_review'` (409 `not_in_review`); `bad_amount`, 502 `gateway_error`. Audited `payment.safety_settlement`. |
| POST | `/api/admin/rides/{type}/{id}/receipt/issue` | super_admin, finance, ops, support | → 200 `{queued:false, receipt:<receipt payload>}` or 202 `{queued:true, receipt:null}`; 409 `not_completed` |
| GET | `/api/admin/rides/{type}/{id}` | admin | adds `tip_receipts {items, total_cents}`, `safety_settlement {status, due_at, held_cents, decision}\|null` |
| POST | `/api/admin/receipts/{id}/resend` (+ `/finance/…`) | finance, support, ops | **202** `{id, number, queued:true, email_count, emailed_at}` — sent by the job `receipts.resend_job` (audited `receipt.resend`) |
| GET | `/api/admin/finance/tax-rates?province=` | finance | `{items:[{id, province, name, gst_bp, pst_bp, hst_bp, qst_bp, total_bp, effective_from, effective_to, current}]}` |
| POST | `/api/admin/finance/tax-rates` | finance | `{province, name?, gst_bp, pst_bp, hst_bp, qst_bp, effective_from (YYYY-MM-DD), effective_to?}` → 201 row; `bad_tax_rate`, 409 `overlap` (`data.rate_id`). HST excludes GST/PST. |
| PUT | `/api/admin/finance/tax-rates/{id}` | finance | partial update, same validation; audited before/after |
| GET | `/api/admin/finance/*?format=xlsx` | finance | every finance export is also available as Excel (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`), audited `finance.export` with `meta.format` |
| GET | `/api/admin/readiness` | any admin | `{ready, production, blockers:[check], warnings:[check], checks:[check], checked_at}`, check = `{key, ok, severity: blocker\|warning, message, fix}`. Keys: `company.gst_number`, `company.address`, `company.legal_name`, `safety.oncall_phones`, `safety.support_phone`, `twilio`, `email`, `postmark.webhook`, `certn`, `google_maps`, `stripe`, `payments.fake_gateway`, `onesignal`, `redis`, `public_web_base_url`, `app_url`, `storage` + safety module items (`safety.twilio`, `safety.redis`). |
| GET | `/api/admin/notifications/templates` | admin | items now include `overrides: {en?: override, fr?: override}` |
| GET | `/api/admin/notifications/templates/{event_key}` | admin | `{event_key, group, channels, default:{title:{en,fr}, body:{en,fr}}, overrides}` |
| PUT | `/api/admin/notifications/templates/{event_key}` | super_admin, ops | `{lang: en\|fr, title?, body?}` (Jinja2; validated) → override `{event_key, lang, title, body, updated_by, updated_at}`; `bad_template`, `too_long`, `bad_lang`; audited |
| DELETE | `/api/admin/notifications/templates/{event_key}?lang=` | super_admin, ops | `{removed}` — back to the catalogue copy |
| POST | `/api/admin/notifications/templates/{event_key}/preview` | admin | `{lang, title?, body?, context?}` → `{title, body, context}` (sample context; nothing sent) |

### Webhooks

* `POST /api/webhooks/stripe` also accepts events signed with `STRIPE_CONNECT_WEBHOOK_SECRET` (Connect endpoint):
  `transfer.created|paid|updated` (metadata `payout_id`) → `payout.sent` (dedupe per payout request),
  `payout.paid` on a connected account → `payout.sent` (dedupe per Stripe payout), `transfer.reversed` → note.
* `POST /api/webhooks/twilio/status` and `POST /api/webhooks/postmark` now only persist `webhook_events`
  (providers `twilio_status`, `postmark`, status `received`) and process in a job; failures retry via
  `platform_jobs.retry_failed_webhooks`. Postmark hard bounce (`HardBounce`, `BadEmailAddress`, `ManuallyDeactivated`,
  `Inactive:true`) or `SpamComplaint` → `users.email_bounced_at` / `email_bounce_reason`: email channel and receipt
  emails skipped for that user (inbox still delivered, delivery logged as `failed: suppressed …`).

### Cross-agent hooks (this module)

* `backend.services.notify.notify_admins(event_key, context, roles=('ops',), dedupe_key=None, realtime_event=None)`
  → admin ids; notifies every admin holding a role (super_admin always) and emits the event to `admin:ops`.
  Use `notify_admins('admin.background_check_review', {'name', 'result', 'check_id', 'user_id'}, roles=('ops','safety_reviewer'))`
  when a Certn result needs a human decision.
* `backend.services.notify.email_status.clear_email_bounce(user, commit=False)` → bool — call when the user changes
  or verifies their email. `is_email_suppressed(user)`.
* `backend.services.settings_service.enabled_services()` → ordered list of offered service types (setting
  `services.enabled`); onboarding `SERVICE_TYPES` should read it.
* `backend.services.notify.live_activity.push_update(ride_type, ride_id, payload=None, *, user_id=None, alert=None,
  priority=5)` → number of activities updated; payload may be the `ride.eta_updated` body (`seconds`/`minutes`) or
  ContentState keys. Never raises.
* `backend.services.trip_effects.local_dt(user_id, dt_utc, fmt)` / `user_zone(user_id)` — recipient-local times.
* `backend.utils.province.province_at(lat, lng)` → `'ON'|…|None`; `trip_state_machine.stamp_pickup_province(rt, ride)`.
