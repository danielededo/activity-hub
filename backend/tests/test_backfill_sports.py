"""Re-applying the sport catalogue to activities already stored."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Workout
from scripts.backfill_sports import backfill
from tests.fit_builder import ride

START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


def upload(client, user_id: int, content: bytes, filename: str):
    response = client.post(
        f"/api/upload?user_id={user_id}",
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def strength_stored_as_other(client, user, db_session):
    """A strength session as it was stored before strength existed."""
    workout_id = upload(client, user["id"], ride(START, sport=10, sub_sport=20), "gym.fit")
    workout = db_session.get(Workout, workout_id)
    workout.sport_type = "other"
    workout.name = f"Other {START.date().isoformat()}"
    db_session.commit()
    return workout_id


def test_a_strength_session_moves_out_of_other(strength_stored_as_other, db_session):
    outcome = backfill(db_session)

    workout = db_session.get(Workout, strength_stored_as_other)
    assert workout.sport_type == "strength"
    assert workout.name == f"Strength {START.date().isoformat()}"
    assert outcome.moved == {("other", "strength"): 1}
    assert outcome.renamed == 1


def test_it_works_without_the_declared_sport(strength_stored_as_other, db_session):
    """Stored before the declared sport was kept: the sub-sport is enough."""
    workout = db_session.get(Workout, strength_stored_as_other)
    workout.raw_data = {k: v for k, v in workout.raw_data.items() if k != "declared_sport"}
    db_session.commit()

    backfill(db_session)

    assert db_session.get(Workout, strength_stored_as_other).sport_type == "strength"


def test_a_name_somebody_chose_is_kept(strength_stored_as_other, db_session):
    db_session.get(Workout, strength_stored_as_other).name = "Leg day"
    db_session.commit()

    outcome = backfill(db_session)

    assert db_session.get(Workout, strength_stored_as_other).name == "Leg day"
    assert outcome.renamed == 0


def test_a_dry_run_changes_nothing(strength_stored_as_other, db_session):
    outcome = backfill(db_session, dry_run=True)

    assert outcome.moved == {("other", "strength"): 1}
    assert db_session.get(Workout, strength_stored_as_other).sport_type == "other"


def test_activities_already_right_are_left_alone(client, user, db_session, sample_gpx, sample_tcx):
    upload(client, user["id"], sample_gpx, "run.gpx")
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], ride(START, sport=1), "run.fit")
    before = db_session.execute(select(Workout.id, Workout.sport_type, Workout.name)).all()

    outcome = backfill(db_session)

    assert outcome.considered == 3
    assert not outcome.moved
    after = db_session.execute(select(Workout.id, Workout.sport_type, Workout.name)).all()
    assert after == before


def test_running_it_twice_moves_nothing_the_second_time(strength_stored_as_other, db_session):
    backfill(db_session)

    assert not backfill(db_session).moved
