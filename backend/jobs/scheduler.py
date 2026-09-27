"""Periodic job scheduler (spec §4.3 "Scheduled jobs every 30 s", §14 daily
expiry checks, §14.2 Certn polling every 6 h …).

Run it with the worker (`python worker.py`) or, for single-box dev, inside the
API process with RUN_SCHEDULER=1. When Redis is available each task takes a
Redis lock (SET NX EX) so running several schedulers never double-runs a task.
Missing task modules are skipped with a warning, so the list can reference
features that are switched off.
"""
import logging
import threading
import time

from backend import jobs

log = logging.getLogger('negoride.scheduler')

# (interval_seconds, dotted path)
PERIODIC = [
    (30, 'backend.services.ride_jobs.tick_lifecycle'),
    (30, 'backend.services.notify.dispatcher.retry_due'),
    (60, 'backend.services.platform_jobs.tick'),
    (30, 'backend.services.safety_jobs.tick'),
    (30, 'backend.services.experience_jobs.tick'),
    (6 * 3600, 'backend.services.onboarding_jobs.poll_background_checks'),
    (24 * 3600, 'backend.services.onboarding_jobs.document_expiry_check'),
    (3600, 'backend.services.account_jobs.tick'),
    (24 * 3600, 'backend.services.safety_jobs.retention_cleanup'),
    (7 * 24 * 3600, 'backend.services.receipt_jobs.weekly_driver_statements'),
]

_last_run = {}
_stop = threading.Event()


def _acquire(path, interval):
    r = jobs.get_redis()
    if r is not None:
        try:
            return bool(r.set(f'negoride:sched:{path}', '1', nx=True, ex=max(1, interval - 1)))
        except Exception:
            pass
    now = time.monotonic()
    if now - _last_run.get(path, -1e9) < interval - 0.5:
        return False
    _last_run[path] = now
    return True


def run_due_once():
    ran = []
    for interval, path in PERIODIC:
        if not _acquire(path, interval):
            continue
        try:
            jobs._resolve(path)
        except (ImportError, AttributeError):
            log.debug('Periodic task %s not available — skipped', path)
            continue
        try:
            jobs.run_job(path)
            ran.append(path)
        except Exception:
            pass  # run_job logs
    return ran


def loop(tick_seconds=5):
    log.info('Scheduler started (%d periodic tasks)', len(PERIODIC))
    while not _stop.is_set():
        run_due_once()
        _stop.wait(tick_seconds)


def start_in_background():
    t = threading.Thread(target=loop, name='negoride-scheduler', daemon=True)
    t.start()
    return t


def stop():
    _stop.set()
