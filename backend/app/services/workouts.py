"""Turning an uploaded file into a stored workout.

Kept out of the router so the whole path — parse, summarise, deduplicate,
persist — can be tested and reused without going through HTTP.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TrackPoint, User, Workout, WorkoutBest
from app.services.analyzer import compute_metrics
from app.services.archives import read_archive
from app.services.parsers import ParserError, parse_file
from app.services.records import fastest_windows
from app.services.zones import heart_rate_seconds


class WorkoutServiceError(Exception):
    """Base class for failures the API turns into 4xx responses."""


class UserNotFoundError(WorkoutServiceError):
    def __init__(self, user_id: int) -> None:
        super().__init__(f"User {user_id} not found")
        self.user_id = user_id


class DuplicateWorkoutError(WorkoutServiceError):
    def __init__(self, existing_id: int, reason: str) -> None:
        super().__init__(f"Already stored as workout {existing_id} ({reason})")
        self.existing_id = existing_id
        self.reason = reason


def find_duplicate(db: Session, user_id: int, parsed, file_hash: str) -> tuple[int, str] | None:
    """Find an existing workout that is the same session as `parsed`.

    Two questions, because they need different answers. Byte-identical files
    are caught by their hash — exact, cheap, and enforced by the database.
    The same ride exported from Garmin as TCX and from Strava as GPX has
    different bytes and a different `source`, so it can only be recognised by
    what it describes: same sport, starting at practically the same moment.
    """
    exact = db.execute(
        select(Workout.id).where(Workout.user_id == user_id, Workout.file_hash == file_hash)
    ).scalar_one_or_none()
    if exact is not None:
        return exact, "identical file"

    window = timedelta(seconds=settings.duplicate_window_seconds)
    near = db.execute(
        select(Workout.id)
        .where(
            Workout.user_id == user_id,
            Workout.sport_type == parsed.sport_type,
            Workout.start_time >= parsed.start_time - window,
            Workout.start_time <= parsed.start_time + window,
        )
        .order_by(Workout.id)
        .limit(1)
    ).scalar_one_or_none()
    if near is not None:
        return near, f"same sport starting within {settings.duplicate_window_seconds}s"
    return None


def store_workout(db: Session, user_id: int, filename: str | None, content: bytes) -> Workout:
    """Parse `content`, summarise it and persist it for `user_id`.

    Raises UserNotFoundError, DuplicateWorkoutError, or ParserError when the
    file cannot be read.
    """
    if db.execute(select(User.id).where(User.id == user_id)).scalar_one_or_none() is None:
        raise UserNotFoundError(user_id)

    parsed = parse_file(filename, content)

    file_hash = hashlib.sha256(content).hexdigest()
    duplicate = find_duplicate(db, user_id, parsed, file_hash)
    if duplicate is not None:
        raise DuplicateWorkoutError(*duplicate)

    metrics = compute_metrics(parsed)
    workout = Workout(
        user_id=user_id,
        source=parsed.source,
        name=parsed.name,
        sport_type=parsed.sport_type,
        start_time=parsed.start_time,
        utc_offset_minutes=parsed.utc_offset_minutes,
        file_format=parsed.file_format,
        file_hash=file_hash,
        raw_data=parsed.raw_data,
        # Computed here for the same reason the windows are: the samples are
        # already in memory. Empty rather than null when there is no heart rate,
        # so the backfill knows this one has been looked at.
        hr_seconds={
            str(bpm): seconds for bpm, seconds in heart_rate_seconds(parsed.track_points).items()
        },
        total_distance=metrics.total_distance,
        total_elevation_gain=metrics.total_elevation_gain,
        total_elevation_loss=metrics.total_elevation_loss,
        total_time=metrics.total_time,
        avg_heart_rate=metrics.avg_heart_rate,
        max_heart_rate=metrics.max_heart_rate,
        avg_cadence=metrics.avg_cadence,
    )
    db.add(workout)
    db.flush()

    if parsed.track_points:
        # One multi-row INSERT rather than thousands of ORM objects.
        db.execute(
            insert(TrackPoint),
            [
                {
                    "workout_id": workout.id,
                    "sequence": point.sequence,
                    "timestamp": point.timestamp,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "elevation": point.elevation,
                    "heart_rate": point.heart_rate,
                    "cadence": point.cadence,
                }
                for point in parsed.track_points
            ],
        )

    # Computed here rather than on request: the samples are in memory now, and
    # answering "fastest 5 km" later would mean re-reading every track point of
    # every activity to produce a figure that never changes.
    windows = fastest_windows(parsed.track_points)
    if windows:
        db.execute(
            insert(WorkoutBest),
            [
                {"workout_id": workout.id, "distance_m": metres, "duration_s": duration}
                for metres, duration in windows.items()
            ],
        )

    db.commit()
    db.refresh(workout)
    return workout


def track_point_count(db: Session, workout_id: int) -> int:
    """How many samples are stored for a workout."""
    return (
        db.execute(
            select(func.count(TrackPoint.id)).where(TrackPoint.workout_id == workout_id)
        ).scalar()
        or 0
    )


# -- archives ------------------------------------------------------------

#: What happened to one file inside an archive.
STORED = "stored"
DUPLICATE = "duplicate"
SKIPPED = "skipped"
FAILED = "failed"


@dataclass(slots=True)
class MemberOutcome:
    filename: str
    outcome: str
    workout_id: int | None = None
    detail: str | None = None


@dataclass(slots=True)
class ArchiveOutcome:
    stored: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: int = 0
    members: list[MemberOutcome] = field(default_factory=list)

    def record(self, member: MemberOutcome) -> None:
        self.members.append(member)
        counter = {
            STORED: "stored",
            DUPLICATE: "duplicates",
            SKIPPED: "skipped",
            FAILED: "failed",
        }[member.outcome]
        setattr(self, counter, getattr(self, counter) + 1)


def store_archive(
    db: Session,
    user_id: int,
    content: bytes,
    on_member: Callable[[MemberOutcome, ArchiveOutcome], None] | None = None,
) -> ArchiveOutcome:
    """Store every activity file in an archive, reporting each one.

    Members are processed one at a time on purpose. The near-duplicate check
    reads before it writes, so two files describing the same session could both
    pass it if they were handled concurrently — the unique constraint would not
    catch them either, since their bytes differ. Sequential is load-bearing
    here, not merely simple.

    A member that fails is recorded and skipped over: an export with one corrupt
    file should still import the other three hundred.

    `on_member` is called after each file with its outcome and the running
    totals, which is how a background import reports progress.
    """
    if db.execute(select(User.id).where(User.id == user_id)).scalar_one_or_none() is None:
        raise UserNotFoundError(user_id)

    outcome = ArchiveOutcome()

    def record(member_outcome: MemberOutcome) -> None:
        outcome.record(member_outcome)
        if on_member is not None:
            on_member(member_outcome, outcome)

    for member in read_archive(
        content,
        max_members=settings.max_archive_members,
        max_extracted_bytes=settings.max_archive_extracted_bytes,
        max_member_bytes=settings.max_upload_bytes,
    ):
        if not member.usable:
            record(MemberOutcome(member.name, SKIPPED, detail=member.skipped))
            continue

        try:
            workout = store_workout(db, user_id, member.name, member.content)
        except DuplicateWorkoutError as exc:
            record(MemberOutcome(member.name, DUPLICATE, exc.existing_id, exc.reason))
        except ParserError as exc:
            record(MemberOutcome(member.name, FAILED, detail=str(exc)))
        except IntegrityError as exc:
            # Leave the session usable for the remaining members.
            db.rollback()
            record(MemberOutcome(member.name, FAILED, detail=str(exc.orig)))
        else:
            record(MemberOutcome(member.name, STORED, workout.id, workout.name))

    return outcome
