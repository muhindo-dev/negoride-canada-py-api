"""Background job runner (spec §2.6).

Emails, SMS, pushes, PDFs, ETA calls and Certn polling never run inside an
HTTP request. Call sites use:

    from backend import jobs
    jobs.enqueue('backend.services.notify.dispatcher.notify_now', key, ids, ctx)
    jobs.enqueue_after_commit(...)   # runs only if the current DB transaction commits
    jobs.enqueue_in(60, ...)         # delayed

Backends, chosen by JOB_MODE (default: `rq` when REDIS_URL is set and Redis
answers, otherwise `thread`):
  rq      RQ + Redis. Run workers with `python worker.py` (includes the
          scheduler for delayed jobs and the periodic loop).
  thread  In-process daemon threads (dev / single-box fallback).
  eager   Run synchronously in a fresh app context (tests). Delayed jobs are
          collected in `jobs.DEFERRED` instead of waiting.

Jobs are referenced by dotted path so any process can import and run them.
Every job runs inside an application context with its own DB session.
"""
import importlib
import logging
import os
import threading
import traceback
from datetime import timedelta

from sqlalchemy import event

log = logging.getLogger('negoride.jobs')

DEFERRED = []          # eager mode: (delay_s, path, args, kwargs)
EXECUTED = []          # eager mode: paths executed (test introspection)
_mode = None
_redis = None
_mode_lock = threading.Lock()


def redis_url():
    return os.getenv('REDIS_URL', '').strip()


def get_redis():
    """Shared Redis connection or None."""
    global _redis
    if _redis is not None:
        return _redis or None
    url = redis_url()
    if not url:
        _redis = False
        return None
    try:
        import redis
        conn = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=3)
        conn.ping()
        _redis = conn
    except Exception as exc:  # pragma: no cover - depends on infra
        log.warning('Redis unavailable (%s) — falling back to in-process jobs', exc)
        _redis = False
    return _redis or None


def mode():
    global _mode
    if _mode:
        return _mode
    with _mode_lock:
        forced = os.getenv('JOB_MODE', '').strip().lower()
        if forced in ('rq', 'thread', 'eager'):
            _mode = forced
            if forced == 'rq' and not get_redis():
                log.warning('JOB_MODE=rq but Redis is unreachable — using thread mode')
                _mode = 'thread'
        else:
            _mode = 'rq' if get_redis() else 'thread'
    return _mode


def set_mode(value):
    """Tests: jobs.set_mode('eager')."""
    global _mode
    _mode = value
    DEFERRED.clear()
    EXECUTED.clear()


def _resolve(path):
    module, _, name = path.rpartition('.')
    return getattr(importlib.import_module(module), name)


def run_job(path, args=(), kwargs=None):
    """Entry point executed by every backend. Pushes an app context."""
    from backend.app import app  # module-level app instance
    from backend.models import db
    kwargs = kwargs or {}
    with app.app_context():
        try:
            return _resolve(path)(*args, **kwargs)
        except Exception:
            db.session.rollback()
            log.error('Job %s failed:\n%s', path, traceback.format_exc())
            raise
        finally:
            db.session.remove()


def _path_of(func):
    if isinstance(func, str):
        return func
    return f'{func.__module__}.{func.__qualname__}'


def enqueue(func, *args, **kwargs):
    return enqueue_in(0, func, *args, **kwargs)


def enqueue_in(delay_s, func, *args, **kwargs):
    path = _path_of(func)
    m = mode()
    if m == 'eager':
        if delay_s and delay_s > 0:
            DEFERRED.append((delay_s, path, args, kwargs))
            return None
        EXECUTED.append(path)
        result = {}

        def _target():
            try:
                result['v'] = run_job(path, args, kwargs)
            except Exception as exc:  # surface failures to the test
                result['e'] = exc
        t = threading.Thread(target=_target)
        t.start()
        t.join()
        if 'e' in result and os.getenv('JOBS_EAGER_RAISE', '1') == '1':
            raise result['e']
        return result.get('v')
    if m == 'rq':
        from rq import Queue, Retry
        q = Queue('negoride', connection=get_redis())
        retry = Retry(max=2, interval=[10, 30])
        if delay_s and delay_s > 0:
            return q.enqueue_in(timedelta(seconds=delay_s), run_job, path, args, kwargs, retry=retry)
        return q.enqueue(run_job, path, args, kwargs, retry=retry)

    # thread mode
    def _thread_target():
        try:
            run_job(path, args, kwargs)
        except Exception:
            pass  # already logged
    if delay_s and delay_s > 0:
        t = threading.Timer(delay_s, _thread_target)
    else:
        t = threading.Thread(target=_thread_target)
    t.daemon = True
    t.start()
    return t


def run_deferred(max_delay=None):
    """Eager/test helper: run delayed jobs now (optionally only those ≤ max_delay)."""
    pending = list(DEFERRED)
    DEFERRED.clear()
    for delay, path, args, kwargs in pending:
        if max_delay is not None and delay > max_delay:
            DEFERRED.append((delay, path, args, kwargs))
            continue
        EXECUTED.append(path)
        run_job(path, args, kwargs)


# ── enqueue after commit ────────────────────────────────────────────────────

def enqueue_after_commit(func, *args, delay_s=0, **kwargs):
    """Queue a job that is dispatched only when the current transaction commits
    (so the job sees committed rows), and dropped on rollback."""
    from backend.models import db
    sess = db.session()
    sess.info.setdefault('pending_jobs', []).append((delay_s, func, args, kwargs))


def _install_session_hooks():
    from sqlalchemy.orm import Session

    @event.listens_for(Session, 'after_commit')
    def _after_commit(session):
        pending = session.info.pop('pending_jobs', None)
        if not pending:
            return
        for delay_s, func, args, kwargs in pending:
            try:
                enqueue_in(delay_s, func, *args, **kwargs)
            except Exception:
                if mode() == 'eager' and os.getenv('JOBS_EAGER_RAISE', '1') == '1':
                    raise
                log.error('Failed to dispatch job %s:\n%s', _path_of(func), traceback.format_exc())

    @event.listens_for(Session, 'after_rollback')
    def _after_rollback(session):
        session.info.pop('pending_jobs', None)


_install_session_hooks()
