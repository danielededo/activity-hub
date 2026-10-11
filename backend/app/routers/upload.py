"""TCX/GPX upload endpoints, for one file or a whole export archive."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import get_db, get_session_factory
from app.models import ArchiveImport
from app.schemas import ArchiveImportRead, WorkoutRead
from app.services.archives import SUFFIX_LIST, ArchiveError, check_archive, looks_like_zip
from app.services.imports import ImportInProgressError, run_import, settle_if_stale, start_import
from app.services.parsers import SUPPORTED_FORMATS, ParserError
from app.services.uploads import EmptyUploadError, UploadTooLargeError, read_upload
from app.services.workouts import (
    DuplicateWorkoutError,
    UserNotFoundError,
    store_workout,
    track_point_count,
)

router = APIRouter(prefix="/upload", tags=["upload"])


# Deliberately sync: parsing and the SQLAlchemy writes both block, and an
# `async def` route runs on the event loop, so a large upload would stall every
# other request. A sync route runs in the threadpool instead.
@router.post("", response_model=WorkoutRead, status_code=status.HTTP_201_CREATED)
def upload_workout(
    user_id: int = Query(..., ge=1),
    file: UploadFile = File(..., description=f"One of: {', '.join(SUPPORTED_FORMATS)}"),
    db: Session = Depends(get_db),
) -> WorkoutRead:
    try:
        content = read_upload(file, settings.max_upload_bytes)
    except EmptyUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    if looks_like_zip(file.filename, content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That looks like an archive. Send it to /api/upload/archive instead.",
        )

    try:
        workout = store_workout(db, user_id, file.filename, content)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except DuplicateWorkoutError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ParserError as exc:
        # Unsupported extension and malformed content are both the client's problem.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This workout is already stored"
        ) from exc

    return WorkoutRead.model_validate(workout).model_copy(
        update={"track_point_count": track_point_count(db, workout.id)}
    )


@router.post("/archive", response_model=ArchiveImportRead, status_code=status.HTTP_202_ACCEPTED)
def upload_archive(
    background: BackgroundTasks,
    user_id: int = Query(..., ge=1),
    file: UploadFile = File(..., description=f"A .zip holding {SUFFIX_LIST} files"),
    db: Session = Depends(get_db),
    session_factory: sessionmaker = Depends(get_session_factory),
) -> ArchiveImportRead:
    """Accept an export archive and import it after answering.

    202, and an import to poll at GET /upload/archive/{id}: a full export takes
    minutes, far past what a proxy holds a request open for. Everything that
    can refuse the archive as a whole — size, not a zip, too many files, a zip
    bomb, an unknown user, an import already running — is checked first, so a
    refusal still comes back as this request's answer.

    Sync for the same reason as the single-file route. The import itself runs
    in the threadpool too, after the response, one file at a time.
    """
    try:
        content = read_upload(file, settings.max_archive_bytes)
    except EmptyUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    if not looks_like_zip(file.filename, content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Not an archive. Send a single {SUFFIX_LIST} file to /api/upload instead.",
        )

    try:
        total = check_archive(
            content,
            max_members=settings.max_archive_members,
            max_extracted_bytes=settings.max_archive_extracted_bytes,
        )
        job = start_import(db, user_id, file.filename or "archive.zip", total)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except ArchiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ImportInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc}: wait for it to finish before sending another archive",
        ) from exc

    background.add_task(run_import, job.id, content, session_factory)
    return ArchiveImportRead.model_validate(job)


@router.get("/archive/{import_id}", response_model=ArchiveImportRead)
def get_archive_import(
    import_id: int,
    user_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> ArchiveImportRead:
    """Where an archive import has got to, or how it ended."""
    job = db.get(ArchiveImport, import_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    return ArchiveImportRead.model_validate(settle_if_stale(db, job))
