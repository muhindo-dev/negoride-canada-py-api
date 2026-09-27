#!/usr/bin/env python3
"""Background worker: RQ job worker (with delayed-job scheduler) + the periodic
task loop. Production runs this as its own systemd service next to gunicorn
(see docs/RUNBOOK.md).

    python worker.py              # RQ worker + periodic scheduler
    python worker.py --scheduler  # periodic scheduler only (no Redis needed)
"""
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

from backend import jobs  # noqa: E402
from backend.jobs import scheduler  # noqa: E402
from backend.services import realtime  # noqa: E402


def main():
    # Worker processes emit Socket.IO events through the Redis message queue.
    realtime.use_external_emitter()

    if '--scheduler' in sys.argv or not jobs.get_redis():
        if not jobs.get_redis():
            logging.warning('Redis not available — running the periodic scheduler only; '
                            'API jobs will run in-process (thread mode).')
        scheduler.loop()
        return

    scheduler.start_in_background()
    from rq import Queue, Worker
    q = Queue('negoride', connection=jobs.get_redis())
    Worker([q], connection=jobs.get_redis()).work(with_scheduler=True)


if __name__ == '__main__':
    main()
