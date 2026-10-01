# NegoRide live backend deployment

This runbook covers the NegoRide API currently hosted at `negoride.ugnews24.info` on `162.0.236.86`.
The API shares its VPS with other sites and services. Deploy only NegoRide files and its systemd unit; do not
restart or edit shared services unless the step below specifically requires it.

## Production layout

| Item | Live value |
|---|---|
| App directory | `/var/www/negoride.ugnews24.info/app` |
| systemd API unit | `negoride.service` |
| API bind | `127.0.0.1:5004` |
| Nginx | `/etc/nginx/conf.d/negoride.ugnews24.info.conf` (verify actual path with `nginx -T`) |
| Environment file | `/var/www/negoride.ugnews24.info/app/.env` |
| Database | MariaDB database `negoride` on the VPS |
| Public endpoint | `https://negoride.ugnews24.info` |

The current service runs Gunicorn with one Eventlet worker. Confirm the deployed unit and reverse-proxy config
before every release; do not assume these values remain unchanged.

## Current production state (2026-10-01)

Release `20260930T215250Z` is live. The `app` path is a symlink into `releases/`, the API service is active, and
all 18 migrations are recorded as applied. The production database and previous app tree are backed up under
`/root/negoride-backups/20260930T215250Z/` and `/var/www/negoride.ugnews24.info/previous-20260930T215250Z`.
Public English and French legal document APIs, `/api/app/config`, `/api/docs`, `/`, and the Socket.IO polling
handshake returned successful responses after cutover. The API still runs as root; Redis and the worker are not
configured, and provider-dependent features must be reviewed before enabling them.

## Release gates

Do not deploy until all of these are true:

1. The API diff and migration files have been reviewed; no credentials, database dumps, customer uploads,
   `private_storage`, local virtual environments, or `.env` files are in the release bundle.
2. The production requirements and OS libraries are available, and the exact release has passed the checks in
   `RUNBOOK.md` against an isolated staging database. The normal pytest fixture deletes its throwaway rows and
   must never point at the production database.
3. A schema-only clone of the current live database has been used to verify pending migrations. Do not copy
   production rows to a developer machine or staging database.
4. All required third-party settings have been checked without printing their values. Keep features requiring
   unconfigured providers disabled until those providers are set up and verified.
5. There is enough free disk space for a full app backup, a database backup, the release bundle, and temporary
   files. Both backups are restricted to root (`0700` directory, `0600` files).

## Build a release bundle on the development machine

Run from the backend repository root. Preserve all existing workspace changes; review the full staged bundle
before sending it to the server.

```sh
cd frontend
npm ci
npm run build
cd ..

release_id=$(date -u +%Y%m%dT%H%M%SZ)
tar -czf "/tmp/negoride-${release_id}.tar.gz" \
  --exclude='./.git' --exclude='*/.git' \
  --exclude='./dist' \
  --exclude='./.env' --exclude='./.env.production' --exclude='./.env.local' \
  --exclude='*/.env' --exclude='*/.env.production' --exclude='*/.env.local' \
  --exclude='*/.env.*.local' --exclude='./vps-credentials.txt' \
  --exclude='./negoride_db_dump.sql' --exclude='./private_storage' \
  --exclude='./.venv' --exclude='./venv' --exclude='*/node_modules' \
  --exclude='./backend/uploads' --exclude='*/__pycache__' \
  --exclude='./._*' --exclude='*/._*' --exclude='./.DS_Store' --exclude='*/.DS_Store' \
  .
tar -tzf "/tmp/negoride-${release_id}.tar.gz" | less
```

The archive must include `backend/`, `frontend/build/`, `migrate.py`, `worker.py`, `wsgi.py`, `requirements.txt`,
and the deployment documentation. It must not include app uploads. Keep the bundle in a private directory and
remove it after deployment. Transfer it over SSH/SCP; never paste secrets into the command line or shell history.

## Preflight on the server

Log in with a named operator account where possible, then use `sudo` for privileged commands. Do not print the
production `.env` or database rows. Capture the current service and config without secret values:

```sh
sudo systemctl status negoride.service --no-pager
sudo systemctl cat negoride.service
sudo nginx -t
sudo nginx -T 2>/dev/null | grep -nE 'server_name|proxy_pass|ssl_certificate|location /socket.io|location /api/stream'
df -h /var/www /root
sudo systemctl is-active mariadb || sudo systemctl is-active mysql
```

Verify `negoride.service` is healthy before changing anything. If it is already failing, stop and diagnose that
failure first. Confirm DNS resolves the public hostname before using the normal HTTPS smoke checks.

## Back up and stage

The following commands create a private, timestamped backup. Run them before installing dependencies, changing
service files, or running migrations.

```sh
release_id=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="/root/negoride-backups/${release_id}"
sudo install -d -m 0700 "$backup_dir"
sudo tar -czpf "$backup_dir/app.tar.gz" -C /var/www/negoride.ugnews24.info app
sudo sh -c "umask 077; mysqldump --single-transaction --routines --triggers --events --hex-blob negoride > '$backup_dir/negoride.sql'"
sudo gzip -t "$backup_dir/app.tar.gz" 2>/dev/null || tar -tzf "$backup_dir/app.tar.gz" >/dev/null
sudo test -s "$backup_dir/negoride.sql"
sudo chmod 0600 "$backup_dir/app.tar.gz" "$backup_dir/negoride.sql"
```

If the database dump command cannot authenticate through the local MariaDB root socket, configure a temporary
client option file with mode `0600` using an authorized database account. Do not put a password in the command
arguments. Do not continue unless the dump succeeds and the archive can be listed. Keep app and database backup
files together under the same release ID.

Extract the transferred bundle to a new staging directory beside `app`, never over the live app:

```sh
sudo install -d -m 0750 "/var/www/negoride.ugnews24.info/releases/${release_id}"
sudo tar -xzf "/tmp/negoride-${release_id}.tar.gz" \
  -C "/var/www/negoride.ugnews24.info/releases/${release_id}"
```

Link the existing production `.env` into the staged tree with root ownership and mode `0600`; link the existing
`backend/uploads` directory as persistent storage. Do not copy either into the release archive. Keep permissions
and ownership aligned with the API service account.

Driver documents and other private files use the encrypted local filesystem backend by default; S3 is optional.
Keep `PRIVATE_STORAGE_KEY` in the root-owned shared production env file and set `PRIVATE_STORAGE_DIR` to
`/var/www/negoride.ugnews24.info/shared/private_storage`. Create that directory with mode `0700` and preserve it
between releases. Never rotate the storage key while files exist unless those files are re-encrypted with the new
key. Verify local storage with a temporary write/read/delete smoke check after deployment.

Create the staged virtual environment using the production Python version, install the exact requirements, and
run Python compilation/import checks before cutover. This VPS currently uses Python 3.9. Keep the WeasyPrint pin
compatible with that runtime and make sure Pango is installed for PDF generation. On this AlmaLinux host, the
required system library was installed with `sudo dnf install pango.x86_64`; the
[WeasyPrint 66.0 installation guide](https://doc.courtbouillon.org/weasyprint/v66.0/first_steps.html) confirms
that release supports Python 3.9 and requires Pango. Do not update global Python packages.

## Database review and migration

Run `migrate.py status` and `migrate.py migrate --dry-run` from the staged directory with the production
environment file loaded. These commands are read-only: status and dry-run must not create `py_migrations` or
change any table. Review every pending migration against the schema-only staging copy before production.

Migration scripts may contain non-transactional DDL. The SQL backup is the recovery point; never assume a failed
migration can be rolled back by `migrate.py rollback`. Do not run `reset`, `rollback`, or `seed` in production.
After the staging migration and API checks pass, schedule a low-traffic window, re-run the dry-run, then execute
`migrate.py migrate` once. Capture its complete success/failure output. If any migration fails, stop immediately;
do not restart into a partially migrated state or run rollback. Restore the database only as a coordinated
incident response after assessing writes made since the backup.

## Run the API as a dedicated service account

The verified unit currently runs as `root`. Correct that before the V4 cutover. First confirm every write path
used by the app (uploads, private receipt/document storage, and Gunicorn log files) and ensure no other app shares
those paths. Then create the isolated account and transfer ownership of only the NegoRide app tree and its
NegoRide log files:

```sh
sudo useradd --system --home-dir /var/www/negoride.ugnews24.info/app \
  --shell /sbin/nologin negoride
sudo chown -R negoride:negoride /var/www/negoride.ugnews24.info/app
sudo chmod 0600 /var/www/negoride.ugnews24.info/app/.env
sudo chown negoride:negoride /var/log/negoride-access.log /var/log/negoride-error.log
```

Add a NegoRide-only systemd drop-in with the service account and filesystem limits. Adjust writable paths only
after confirming the storage layout:

```ini
[Service]
User=negoride
Group=negoride
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/var/www/negoride.ugnews24.info/app/backend/uploads
ReadWritePaths=/var/www/negoride.ugnews24.info/app/private_storage
ReadWritePaths=/var/log/negoride-access.log
ReadWritePaths=/var/log/negoride-error.log
```

Run `systemd-analyze verify` on the resulting unit, `daemon-reload`, then restart only `negoride.service` and
verify it runs as `negoride`. If the app reports a permission error, stop and add only the specific NegoRide
write path; do not run it as root as a workaround. The previous unit and backup allow restoration if startup
fails.

## Cutover and smoke checks

The systemd unit keeps its stable `WorkingDirectory` and `EnvironmentFile` paths under `app`; the `app` path is
switched atomically between versioned release directories. Keep environment and user uploads outside release
archives. Back up the current tree first, stage the exact release, give it a release-specific virtual environment,
and link its `.env` to a root-owned file under `shared/`. Preserve `backend/uploads` by linking it to the prior
tree. After reviewing and applying migrations, stop only `negoride.service` and switch the symlink:

```sh
base=/var/www/negoride.ugnews24.info
app="$base/app"
stage="$base/releases/${release_id}"
previous="$base/previous-${release_id}"
sudo systemctl stop negoride.service
sudo mv "$app" "$previous"
sudo ln -s "$stage" "$app"
sudo systemctl restart negoride.service
sudo systemctl is-active --quiet negoride.service
```

If startup or smoke checks fail, stop the service, remove the `app` symlink, move `previous` back to `app`, and
start the previous release. Do not automatically roll back database DDL; investigate and restore the verified
database backup only as a coordinated recovery.

Run migrations from the staged release only after reviewing the dry-run and confirming both backups:

```sh
cd "$stage"
sudo "$stage/.venv/bin/python" migrate.py status
sudo "$stage/.venv/bin/python" migrate.py migrate --dry-run
sudo "$stage/.venv/bin/python" migrate.py migrate
```

Record command output. Only change the NegoRide unit; run `daemon-reload` if and only if its file changed. Before
restarting, check `nginx -t` if Nginx configuration changed; normally no Nginx change is needed.

```sh
sudo systemctl restart negoride.service
sudo systemctl is-active --quiet negoride.service
curl --fail --silent --show-error https://negoride.ugnews24.info/api/app/config
curl --fail --silent --show-error https://negoride.ugnews24.info/api/docs
curl --fail --silent --show-error https://negoride.ugnews24.info/
```

Also verify the API logs for startup errors, WebSocket/Socket.IO connectivity through Nginx, admin sign-in, mobile
configuration, and one provider sandbox path where credentials are configured. Never test a real payment, SMS,
identity check, or emergency call in production. Confirm other hosted sites and services remain active.

## Worker and Redis

The API can run in thread fallback mode, but production V4 background jobs, rate limits, and cross-process
Socket.IO events require Redis and a worker. Before enabling them, verify Redis persistence, authentication and
loopback-only binding; set `REDIS_URL=redis://127.0.0.1:6379/0` in the protected environment file; and add this
`/etc/systemd/system/negoride-worker.service` after the API service account and paths are confirmed:

```ini
[Unit]
Description=NegoRide background jobs and scheduler
After=network-online.target redis.service
Wants=network-online.target

[Service]
Type=simple
User=negoride
Group=negoride
WorkingDirectory=/var/www/negoride.ugnews24.info/app
EnvironmentFile=/var/www/negoride.ugnews24.info/app/.env
ExecStart=/var/www/negoride.ugnews24.info/app/.venv/bin/python worker.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/var/www/negoride.ugnews24.info/app/backend/uploads
ReadWritePaths=/var/www/negoride.ugnews24.info/app/private_storage

[Install]
WantedBy=multi-user.target
```

Keep `RUN_SCHEDULER=0` in the API process; `worker.py` runs the scheduler once alongside its RQ worker. Then
`systemd-analyze verify` the unit, `daemon-reload`, enable it, and check its journal. Confirm Redis listens only
on loopback (`ss -ltnp`), verify Redis persistence and a harmless queued job end-to-end, and watch memory/queue
depth before opening features that depend on it. Do not expose Redis publicly.

Do not enable unconfigured payment, SMS, email, identity, map, or push integrations. A successful process start
does not prove those external systems are usable.

## Rollback

If smoke checks fail, restore the backed up app directory and restart `negoride.service`. Restore the prior
application virtual environment as well if dependencies changed. Do not roll back the
database automatically: migrations can be destructive to newly written rows even when a down migration exists.
If the old application cannot run against the migrated schema, keep the service in the safest available state
and restore the database only after an incident review and a write-reconciliation plan.

Keep the backup until the release has passed the agreed observation period. Then move it to the secured backup
retention location; do not leave production dumps on a developer workstation.

## Current live assessment (2026-09-30)

Read-only verification on 2026-10-01 found the old API active at `/var/www/negoride.ugnews24.info/app`, without
the V4 route modules, worker, or Python migration files. The API runs as `root`; `negoride-worker.service` is
missing and Redis is inactive. Only Stripe and core Flask/JWT secrets are present in the production environment;
V4 email, SMS, identity, map, and push provider settings are not configured. The production hostname's A record
was still absent from both authoritative HostGator nameservers. On the live database, the two legacy migrations
are recorded and all 16 V4 migrations are pending; the production status/dry-run check made no changes.

Pango has been installed on the VPS. All 18 migrations passed on a temporary schema-only MariaDB clone, all 360
backend tests passed there, and staged checks returned HTTP 200 for app config, API docs, admin root, and the
Socket.IO handshake. Temporary QA databases, credentials, and stage files were removed afterward. Complete DNS,
service-user hardening, provider readiness, backup review, and the remaining release gates before applying the
16 production migrations or switching production to the current workspace.
