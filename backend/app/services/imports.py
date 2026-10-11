"""Importing an export archive behind the request that uploaded it.

A full export is hundreds of activities at a second or more each. Measured on
150 FIT files, the import took four minutes; nginx gave up on the request at
two, the browser was told it had failed, and the import carried on regardless
and finished with nobody watching. So the upload request now only checks the
archive and records an import, and the work happens after the response, with
progress written to the import's row for the dashboard to poll.

One import per user at a time, for the same reason the members inside one are
processed in order: the near-duplicate check reads before it writes, so two
imports racing could both store the same session from different files.
"""

import logging
import threading
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import ArchiveImport, User
from app.models.archive_import import DONE, FAILED, INTERRUPTED, RUNNING
from app.services.workouts import (
    ArchiveOutcome,
    MemberOutcome,
    UserNotFoundError,
    WorkoutServiceError,
    store_archive,
)

logger = logging.getLogger(__name__)

#: Makes "is one running? if not, start one" a single step within this process.
_start_lock = threading.Lock()

INTERRUPTED_DETAIL = (
    "The import stopped before it finished, most likely because the backend restarted. "
    "Send the archive again: files already stored are recognised in moments."
)


class ImportInProgressError(WorkoutServiceError):
    def __init__(self, import_id: int) -> None:
        super().__init__(f"Archive import {import_id} is still running")
        self.import_id = import_id


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite hands timezone-aware columns back naive; they were stored as UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def settle_if_stale(db: Session, job: ArchiveImport) -> ArchiveImport:
    """Mark a running import interrupted if its worker has stopped reporting.

    Nothing else can: a worker that dies with the process has no chance to say
    so, and without this its import would read "running" forever and block the
    next one.
    """
    quiet_for = _now() - _aware(job.heartbeat_at)
    if job.status == RUNNING and quiet_for > timedelta(
        seconds=settings.archive_import_stale_seconds
    ):
        job.status = INTERRUPTED
        job.error = INTERRUPTED_DETAIL
        job.finished_at = _now()
        db.commit()
    return job


def start_import(db: Session, user_id: int, filename: str, total: int) -> ArchiveImport:
    """Record a new import, or refuse while another is still running."""
    if db.execute(select(User.id).where(User.id == user_id)).scalar_one_or_none() is None:
        raise UserNotFoundError(user_id)

    with _start_lock:
        running = db.scalars(
            select(ArchiveImport).where(
                ArchiveImport.user_id == user_id, ArchiveImport.status == RUNNING
            )
        ).all()
        for job in running:
            settle_if_stale(db, job)
            if job.status == RUNNING:
                raise ImportInProgressError(job.id)

        job = ArchiveImport(
            user_id=user_id,
            filename=filename[:255],
            status=RUNNING,
            total=total,
            members=[],
            heartbeat_at=_now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def run_import(import_id: int, content: bytes, session_factory: sessionmaker) -> None:
    """Work through an archive, writing progress to its import after every file.

    Runs after the upload has been answered, in a session of its own: the
    request's session is closed by then.
    """
    db = session_factory()
    try:
        job = db.get(ArchiveImport, import_id)

        def progress(member: MemberOutcome, totals: ArchiveOutcome) -> None:
            job.processed = len(totals.members)
            job.stored = totals.stored
            job.duplicates = totals.duplicates
            job.skipped = totals.skipped
            job.failed = totals.failed
            if len(job.members) < settings.max_reported_members:
                # A new list, not an append: an in-place change to a JSON
                # column is invisible to SQLAlchemy and would never be written.
                job.members = [*job.members, asdict(member)]
            else:
                job.truncated = True
            job.heartbeat_at = _now()
            db.commit()

        store_archive(db, job.user_id, content, on_member=progress)
        job.status = DONE
        job.finished_at = _now()
        db.commit()
    except Exception as exc:
        # Nothing is waiting on this call to raise to: the response went out
        # long ago. The import's row is the only place a failure can be seen.
        logger.exception("Archive import %s failed", import_id)
        db.rollback()
        job = db.get(ArchiveImport, import_id)
        if job is not None:
            job.status = FAILED
            job.error = str(exc) or type(exc).__name__
            job.finished_at = _now()
            db.commit()
    finally:
        db.close()
