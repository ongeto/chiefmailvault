"""APScheduler periodic backup jobs."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config import SYNC_INTERVAL_HOURS
from core.orchestrator import trigger_backup
from db import models

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _scheduled_sync() -> None:
    mailboxes = models.list_mailboxes()
    if mailboxes:
        logger.info("Scheduled sync starting for %d mailboxes", len(mailboxes))
        trigger_backup()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scheduled_sync,
        "interval",
        hours=SYNC_INTERVAL_HOURS,
        id="mailbox_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started: interval=%dh", SYNC_INTERVAL_HOURS)
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
