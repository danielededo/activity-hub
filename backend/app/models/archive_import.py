"""An export archive being imported, or imported already.

An archive is worked through after its upload request has been answered: a
full export is hundreds of activities at a second or more each, far past any
proxy's patience. This row is how the dashboard follows along, and how the
outcome stays readable once it is over.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

#: Still being worked through.
RUNNING = "running"
#: Every member has an outcome.
DONE = "done"
#: Stopped by an error that was not any one member's fault.
FAILED = "failed"
#: Stopped without saying so, most likely because the backend restarted.
INTERRUPTED = "interrupted"


class ArchiveImport(Base, TimestampMixin):
    __tablename__ = "archive_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RUNNING)
    #: Files in the archive, known before the first one is read.
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Per-file outcomes, capped at max_reported_members; the counts are exact.
    members: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Written by the worker after every file. A running import whose heartbeat
    #: has gone quiet is one whose worker is gone.
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
