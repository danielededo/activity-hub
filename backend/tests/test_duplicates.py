"""Duplicate detection: identical bytes, and the same session exported twice."""

import pytest

from app.config import settings


def gpx_ride(when: str, sport: str = "cycling", name: str = "Ride") -> bytes:
    """A minimal GPX, so a session can be re-described with small variations."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{name}</name><type>{sport}</type><trkseg>
    <trkpt lat="45.07" lon="7.68"><ele>240</ele><time>{when}</time></trkpt>
    <trkpt lat="45.08" lon="7.69"><ele>250</ele><time>{when}</time></trkpt>
  </trkseg></trk>
</gpx>
""".encode()


def upload(client, user_id: int, content: bytes, filename: str):
    return client.post(
        f"/api/upload?user_id={user_id}", files={"file": (filename, content, "application/xml")}
    )


# -- identical bytes -----------------------------------------------------


def test_the_same_bytes_are_rejected_under_a_different_name(client, user, sample_gpx):
    assert upload(client, user["id"], sample_gpx, "run.gpx").status_code == 201

    second = upload(client, user["id"], sample_gpx, "run-copy-2.gpx")

    assert second.status_code == 409
    assert "identical file" in second.json()["detail"]


def test_identical_bytes_are_recognised_without_parsing(client, user, sample_gpx, monkeypatch):
    """Parsing is most of the cost of a file, and a re-sent export is all repeats.

    Measured on a 150-activity archive, the second send took 130 s with nothing
    to store — long enough to time out at the proxy on its own.
    """
    assert upload(client, user["id"], sample_gpx, "run.gpx").status_code == 201

    def parse_must_not_run(*_args, **_kwargs):
        raise AssertionError("an identical file was parsed")

    monkeypatch.setattr("app.services.workouts.parse_file", parse_must_not_run)
    second = upload(client, user["id"], sample_gpx, "run-again.gpx")

    assert second.status_code == 409
    assert "identical file" in second.json()["detail"]


def test_the_same_file_is_allowed_for_a_different_user(client, user, other_user, sample_gpx):
    """The hash is scoped per user: two people may ride together."""
    assert upload(client, user["id"], sample_gpx, "run.gpx").status_code == 201

    assert upload(client, other_user["id"], sample_gpx, "run.gpx").status_code == 201


# -- the same session, exported twice -----------------------------------


def test_the_same_ride_from_two_services_is_one_workout(client, user, sample_tcx):
    """The TCX from Garmin and the GPX from Strava share no bytes at all.

    Only what they describe gives them away: same sport, same starting moment.
    """
    assert upload(client, user["id"], sample_tcx, "ride.tcx").status_code == 201

    # The TCX sample starts at 06:30:00Z; two minutes of drift between exports.
    second = upload(client, user["id"], gpx_ride("2026-05-04T06:32:00Z"), "ride.gpx")

    assert second.status_code == 409
    assert "same sport starting within" in second.json()["detail"]


def test_a_different_sport_at_the_same_time_is_kept(client, user, sample_tcx):
    """A brick session: ride and run back to back are two activities."""
    assert upload(client, user["id"], sample_tcx, "ride.tcx").status_code == 201

    running = upload(client, user["id"], gpx_ride("2026-05-04T06:30:00Z", "running"), "run.gpx")

    assert running.status_code == 201


def test_the_same_sport_outside_the_window_is_kept(client, user, sample_tcx):
    """Two laps of the same loop, started ten minutes apart, are two rides."""
    assert settings.duplicate_window_seconds < 600, "the fixture assumes a window under 10 min"
    assert upload(client, user["id"], sample_tcx, "ride.tcx").status_code == 201

    later = upload(client, user["id"], gpx_ride("2026-05-04T06:40:00Z"), "ride-2.gpx")

    assert later.status_code == 201


@pytest.mark.parametrize("drift_seconds", [0, 1, 299])
def test_drift_within_the_window_still_counts_as_one(client, user, drift_seconds):
    first = gpx_ride("2026-06-01T07:00:00Z")
    assert upload(client, user["id"], first, "a.gpx").status_code == 201

    minute, second = divmod(drift_seconds, 60)
    shifted = gpx_ride(f"2026-06-01T07:{minute:02d}:{second:02d}Z", name="Same ride")

    assert upload(client, user["id"], shifted, "b.gpx").status_code == 409
