# NegoRide v4 — Safety, live sharing and audio recording

Spec §8 (SOS + Safety Toolkit), §9 (live location sharing, admin live map, replay),
§10 (optional audio recording). Flags: `ff.sos`, `ff.live_share`, `ff.audio_recording`,
`ff.route_deviation`.

## Code map

| Area | File |
|---|---|
| User API (SOS, contacts, settings, reports, checks, toolkit) | `backend/routes/safety.py` |
| Share links, public JSON, public page `/t/<token>` | `backend/routes/tracking_share.py`, `backend/services/live_share.py` |
| Recordings API, signed private-file route | `backend/routes/recordings.py`, `backend/services/recording_service.py` |
| Admin Safety Center, live map, replay | `backend/routes/admin_safety.py` |
| SOS core, SMS to non-users, help contacts | `backend/services/safety_service.py` |
| Route deviation / long stop / auto-share / trip-end hooks | `backend/services/safety_detection.py` |
| Escalation + retention jobs | `backend/services/safety_jobs.py` (`tick` every 30 s, `retention_cleanup` daily) |
| Private encrypted storage | `backend/services/private_storage.py` |
| Tests | `tests/test_safety.py` |

## SOS flow

1. The app calls `POST /api/safety/sos` with an `Idempotency-Key` header and
   `{ride_type?, ride_id?, lat, lng, accuracy, battery, silent}`. SOS works:
   * with no ride (the incident has no ride),
   * during a ride (the active ride is detected when none is passed),
   * after the ride ended (the app passes the ride explicitly; the caller must have been a party),
   * for suspended accounts (safety comes first),
   * without GPS (the last known position is used).
2. In the request the server:
   * creates `safety_incidents` (the unique `(user_id, idempotency_key)` makes retries replay the same incident),
   * stores the first `safety_incident_locations` point and writes the audit row `safety.sos_triggered`,
   * creates an SOS live link (`ride_share_links.ride_type='incident'`) that shows the person's live position,
   * emits `safety.sos` to `admin:sos` and `admin:ops`,
   * auto-starts a recording row when the user pre-consented (`auto_record_on_sos`).
3. After commit, jobs send:
   * an SMS to every trusted contact, with the live link (catalogue `safety.sos_triggered`). Each SMS is logged in the owner's inbox with an `sms` delivery row,
   * the catalogue event `safety.sos_triggered` to admins (socket, push, SMS, email and inbox).
4. The app switches to high-frequency location: `POST /api/safety/incidents/{id}/location`
   every `safety.sos_location_interval_s` (3 s) while `keep_sending_location` is true. Each point
   emits `safety.sos_updated` (`type: location`) to `admin:sos`.
5. **Escalation.** If no admin acknowledges within `safety.sos_ack_timeout_s` (60 s), a delayed job
   runs `escalate_incident`, with `tick()` as a fallback. It:
   * sends an SMS and a voice alert (Twilio Calls API) to `safety.oncall_phones` (fallback env `SAFETY_ONCALL_PHONES`),
   * sets `escalated_at` and writes the audit row,
   * emits `safety.sos_updated` (`type: escalated`) and an `alert` event,
   * notifies admins with `safety.sos_escalated`.
6. The admin acknowledges, then resolves or marks it a false alarm. The user can cancel it
   (`false_alarm`, audited as `safety.sos_cancelled_by_user`). Closing an incident:
   * expires its live link after 30 min,
   * holds its recordings for `recording.hold_after_case_days` (90 days).

### "Are you OK?" checks (§8.4)

The driver's positions during `IN_PROGRESS` / `RIDING` go through `tracking.location_hook`.

**Route deviation.** A check fires when two consecutive points are both farther than
`max(safety.route_deviation_m, 20 % of the trip length)` from the straight pickup → drop-off
corridor. No route polyline is stored yet, so the straight corridor with a tolerance is used.

**Long stop.** A check fires when the driver stays within `safety.long_stop_radius_m` for
`safety.long_stop_s`. Points within 200 m of the pickup or drop-off are ignored.

When a check fires:
* a `safety_checks` row is created per rider, at most one per ride per `safety.check_throttle_s` (600 s),
* the rider gets a push with `check_id`, and `safety.check` goes to their socket.

How the rider's answer is handled:
* **`help`** creates an SOS incident, and the full SOS flow runs.
* **No answer** within `safety.check_response_s` (60 s): the check becomes `escalated`, an incident is created (`kind=check_in_timeout`, severity high), `safety.sos` is emitted and admins get `safety.check_unanswered`.

### Auto-share (§8.4, §9.1)

When a ride reaches `IN_PROGRESS` (car hire / scheduled) or `RIDING` (seat booking), the rider's
link is created or reused and SMSed to their `auto_share` trusted contacts. This happens when the
rider has one of these settings on:
* `auto_share_all`,
* `auto_share_night`, and it is currently between `night_start` and `night_end` (21:00–05:00) in the
  rider's time zone. The time zone is `users.timezone`, else the province, else Toronto.

## Live trip sharing

* `POST /api/rides/{type}/{id}/share` is for ride parties only. It is allowed from CONFIRMED until
  the ride ends. It returns a 32-char token and the URL `PUBLIC_WEB_BASE_URL + '/t/' + token`.
  `PUBLIC_WEB_BASE_URL` falls back to the `company.website` setting.
* **Before the landing website is live**, set `PUBLIC_WEB_BASE_URL` to the API host. Flask serves
  a minimal page at `/t/<token>`:
  * noindex and no-referrer headers,
  * Google Maps when `GOOGLE_MAPS_BROWSER_KEY` is set, otherwise Leaflet + OpenStreetMap,
  * it polls the JSON every 5 s.
* `GET /api/public/track/{token}` needs no auth. It is rate limited per IP
  (`tracking.public_rate_limit_per_min`, Redis or in-memory) and sent with `Cache-Control: no-store`.
  * It returns **only** the stage, driver first name / avatar / rating, vehicle make / model / colour / plate,
    pickup and drop-off, the latest driver position, breadcrumbs and polyline, ETA, `trip_ended` and `expires_at`.
  * It never returns phone numbers, emails, fares, payment data or the PIN.
  * Revoked or expired links return 404.
* **Expiry.** A link expires `tracking.share_expiry_after_end_min` (30) after the trip ends. The
  trip_effects after-hook sets this. While the trip runs, a link is capped at `tracking.share_max_hours` (12 h).

## Audio recording privacy rules (§10)

* **Opt-in.**
  * `trigger=manual`: the Record button. Pressing it is consent.
  * `trigger=always`: needs the Safety setting `record_audio=always`.
  * `sos`: needs `auto_record_on_sos`.
* **Transparency.** Every start and stop emits `recording.status` to `ride:{type}:{id}` and to the
  other parties' `user:` rooms. `GET /api/rides/{type}/{id}/recording-status` returns the banner
  "🔴 Audio recording is on for safety".
* **Storage.**
  * Audio arrives as 1-min AAC/M4A chunks, uploaded to `POST /api/recordings/{id}/chunks`, at most 5 MB each.
  * Each chunk's `sha256` is verified.
  * A re-upload of the same seq with the same hash is idempotent. A different hash for the same seq returns 409.
  * Chunks are stored in private storage (below). They never have a public URL.
* **Access.**
  * The owner can fetch their own audio (`GET /api/recordings/{id}` → signed URLs, 5 min).
  * Other parties get 403. They can only see that a recording exists, and must go through support for it.
  * Admins need **`safety_reviewer`** (or super_admin).
  * Every URL issue is audited as `recording.access`, and every file fetch as `private_file.download`.
* **Retention** (`retention_cleanup`, daily).
  * Recordings older than `recording.retention_days` (7) are purged: audio is deleted and the
    metadata row is kept as `deleted`, with an audit row.
  * **Kept** while under `legal_hold`.
  * **Kept** while linked to an incident, safety report or ride dispute that is still open. After the
    case closes they are kept for `recording.hold_after_case_days` (90) more days.
* Rides that end stop any running recordings.
* **Breadcrumbs.** `ride_locations` older than `tracking.retention_days` (90) are deleted unless the
  ride has an incident, report or dispute. Share links dead for more than 30 days are purged.

### Private storage

`private_storage.put/get/delete/signed_url(key, ttl_s)` can also be used for driver documents and receipts.

| | S3-compatible | Local |
|---|---|---|
| When | `S3_BUCKET_PRIVATE`, `S3_ACCESS_KEY` and `S3_SECRET_KEY` are set | Otherwise |
| Settings | `S3_ENDPOINT`, `S3_REGION`, `S3_SSE` (default `AES256`, empty to disable) | Directory `PRIVATE_STORAGE_DIR` (default `<repo>/private_storage`, git-ignored, never web-served) |
| Encryption | Server-side encryption | Fernet at rest, key `PRIVATE_STORAGE_KEY` |
| Download links | Presigned GETs | HMAC-signed, expiring `/api/private-files/<token>` |

Without `PRIVATE_STORAGE_KEY`, a dev key is generated at `private_storage/.dev_fernet_key` with a
warning. Production refuses to start local storage without the key.

## Admin (roles `ops` / `safety_reviewer`; super_admin passes)

* **Safety Center**
  * Incidents list with open ones first.
  * Incident detail: locations, a timeline merging trip events, audit rows and checks, reports, recordings and share links.
  * Actions: acknowledge / resolve / false-alarm / notes. All are audited and emit `safety.sos_updated`.
  * `contact` gives the party phone numbers for a one-click call. It is audited as `personal_data.access`.
  * `report.pdf` is a WeasyPrint export for police or insurance.
* **Reports review.**
* **Recordings** tab (safety_reviewer only).
* **Help contacts** CRUD.
* **Live map:** `GET /api/admin/live/drivers`, with states idle / en_route / on_trip / sos.
* **Replay:** `GET /api/admin/rides/{type}/{id}/route`.
* Trusted contacts are never listed in bulk. Admins only see how many contacts a link was sent to.

## On-call runbook

1. Configure **Settings → safety.oncall_phones** (E.164, comma-separated) and make sure Twilio
   is set up:
   * `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   * `TWILIO_MESSAGING_SERVICE_SID` or `TWILIO_FROM_NUMBER`,
   * `TWILIO_VOICE_FROM` for voice alerts.
2. Keep the worker running (`python worker.py`): it runs the escalation and retention jobs.
   Without Redis, run the API with `RUN_SCHEDULER=1`.
3. When an SOS alarm arrives (dashboard banner, push or SMS):
   1. Open the incident and **Acknowledge** it. This stops escalation.
   2. Check the live map and trail.
   3. Use **Contact** to call the person. If life is at risk, tell them to call 911, or call 911 for them with the location.
4. Keep notes on the incident. Resolve it, or mark it a false alarm, only once the person is safe.
   Export the PDF when police or insurance ask for it.
5. For a case needing evidence, put the recordings on **legal hold**.
6. If escalation SMS or voice alerts are not arriving, check:
   * `audit_logs` for `safety.sos_escalated`,
   * the Twilio console,
   * that `safety_jobs.tick` runs (scheduler logs).
