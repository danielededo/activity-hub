"""Archive imports: answered at once, worked through afterwards, followed by polling."""

from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models import ArchiveImport
from tests.test_archives import gpx, make_zip, post_archive


def three_rides() -> bytes:
    return make_zip(
        {
            "a.gpx": gpx("2026-06-01T07:00:00Z", "cycling"),
            "b.gpx": gpx("2026-06-02T07:00:00Z", "running"),
            "notes.csv": b"id\n",
        }
    )


def read_import(client, user_id: int, import_id: int):
    return client.get(f"/api/upload/archive/{import_id}?user_id={user_id}")


def a_running_import(db_session, user_id: int, *, quiet_for: timedelta) -> ArchiveImport:
    """An import whose worker last reported `quiet_for` ago."""
    job = ArchiveImport(
        user_id=user_id,
        filename="earlier.zip",
        status="running",
        total=10,
        processed=3,
        members=[],
        heartbeat_at=datetime.now(UTC) - quiet_for,
    )
    db_session.add(job)
    db_session.commit()
    return job


# -- the upload answers before the work ---------------------------------


def test_the_upload_is_answered_before_anything_is_imported(client, user):
    """The response is the import as it was accepted, not as it ended."""
    response = post_archive(client, user["id"], three_rides())

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert (body["total"], body["processed"], body["stored"]) == (3, 0, 0)
    assert body["filename"] == "export.zip"


def test_the_import_finishes_with_every_file_accounted_for(client, user):
    accepted = post_archive(client, user["id"], three_rides()).json()

    body = read_import(client, user["id"], accepted["id"]).json()

    assert body["status"] == "done"
    assert body["processed"] == body["total"] == 3
    assert (body["stored"], body["skipped"]) == (2, 1)
    assert body["finished_at"] is not None
    assert body["error"] is None
    stored = client.get(f"/api/workouts?user_id={user['id']}").json()
    assert stored["total"] == 2


def test_a_refused_archive_creates_no_import(client, user, db_session, monkeypatch):
    """Whatever refuses the archive as a whole is still the upload's own answer."""
    monkeypatch.setattr(settings, "max_archive_members", 1)

    response = post_archive(client, user["id"], three_rides())

    assert response.status_code == 422
    assert db_session.query(ArchiveImport).count() == 0


# -- one at a time -------------------------------------------------------


def test_a_second_archive_waits_for_the_first(client, user, db_session):
    """Two imports at once could store one session twice, from different files."""
    running = a_running_import(db_session, user["id"], quiet_for=timedelta(seconds=5))

    response = post_archive(client, user["id"], three_rides())

    assert response.status_code == 409
    assert f"import {running.id} is still running" in response.json()["detail"]


def test_another_users_import_does_not_block(client, user, other_user, db_session):
    a_running_import(db_session, other_user["id"], quiet_for=timedelta(seconds=5))

    assert post_archive(client, user["id"], three_rides()).status_code == 202


# -- an import whose worker is gone --------------------------------------


def test_a_silent_import_reads_as_interrupted(client, user, db_session):
    """A worker that died with the backend never got to say so."""
    gone_quiet = timedelta(seconds=settings.archive_import_stale_seconds + 1)
    job = a_running_import(db_session, user["id"], quiet_for=gone_quiet)

    body = read_import(client, user["id"], job.id).json()

    assert body["status"] == "interrupted"
    assert "Send the archive again" in body["error"]
    assert body["processed"] == 3


def test_a_silent_import_does_not_block_the_next(client, user, db_session):
    gone_quiet = timedelta(seconds=settings.archive_import_stale_seconds + 1)
    job = a_running_import(db_session, user["id"], quiet_for=gone_quiet)

    assert post_archive(client, user["id"], three_rides()).status_code == 202
    db_session.refresh(job)
    assert job.status == "interrupted"


def test_a_slow_import_is_not_mistaken_for_a_dead_one(client, user, db_session):
    job = a_running_import(db_session, user["id"], quiet_for=timedelta(seconds=30))

    assert read_import(client, user["id"], job.id).json()["status"] == "running"


# -- failures ------------------------------------------------------------


def test_a_failure_outside_any_file_is_recorded(client, user, monkeypatch):
    """Nobody is waiting on the request any more: the row is where it shows."""

    def database_gone(*_args, **_kwargs):
        raise RuntimeError("connection lost")

    monkeypatch.setattr("app.services.imports.store_archive", database_gone)
    accepted = post_archive(client, user["id"], three_rides()).json()

    body = read_import(client, user["id"], accepted["id"]).json()

    assert body["status"] == "failed"
    assert body["error"] == "connection lost"
    assert body["finished_at"] is not None


# -- reading an import ---------------------------------------------------


def test_an_import_is_private_to_its_user(client, user, other_user):
    accepted = post_archive(client, user["id"], three_rides()).json()

    assert read_import(client, other_user["id"], accepted["id"]).status_code == 404


def test_an_unknown_import_is_404(client, user):
    assert read_import(client, user["id"], 4242).status_code == 404
