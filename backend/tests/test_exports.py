"""Getting the data back out: the CSV, the GPX, and the zip of both."""

import csv
import io
import zipfile
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.services.analyzer import compute_metrics
from app.services.parsers import parse_file

EPOCH = datetime(2026, 6, 22, 6, 30, tzinfo=UTC)


def upload(client, user_id, content, filename):
    return client.post(
        f"/api/upload?user_id={user_id}",
        files={"file": (filename, content, "application/octet-stream")},
    )


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text)))


def as_utc(moment):
    """The same instant, comparably.

    SQLite has no timezone, so a stored timestamp comes back naive while a
    freshly parsed one is aware. On PostgreSQL both are aware. Comparing the
    instants rather than the objects keeps the test about the export.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


# -- the activity CSV ----------------------------------------------------


def test_the_csv_has_a_header_and_a_row_per_activity(client, user, sample_tcx, sample_gpx):
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], sample_gpx, "run.gpx")

    response = client.get(f"/api/export/activities.csv?user_id={user['id']}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "activities.csv" in response.headers["content-disposition"]
    rows = rows_of(response.text)
    assert len(rows) == 2
    assert {row["sport"] for row in rows} == {"cycling", "running"}


def test_the_csv_carries_the_figures_a_spreadsheet_would_want(client, user, sample_tcx):
    upload(client, user["id"], sample_tcx, "ride.tcx")

    row = rows_of(client.get(f"/api/export/activities.csv?user_id={user['id']}").text)[0]

    assert float(row["distance_m"]) == pytest.approx(12_000.0)
    assert float(row["moving_time_s"]) == pytest.approx(1_800.0)
    assert int(row["avg_heart_rate"]) == 142
    assert row["start_time_utc"].endswith("Z")


def test_an_absent_figure_is_an_empty_cell_not_the_word_none(client, user):
    """ "None" in a spreadsheet is text that breaks every formula in the column."""
    gpx = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="phone" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>No strap</name><type>running</type><trkseg>
    <trkpt lat="45.07" lon="7.68"><ele>240</ele><time>2026-06-22T06:30:00Z</time></trkpt>
    <trkpt lat="45.08" lon="7.69"><ele>250</ele><time>2026-06-22T06:35:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
    upload(client, user["id"], gpx, "run.gpx")

    row = rows_of(client.get(f"/api/export/activities.csv?user_id={user['id']}").text)[0]

    assert row["avg_heart_rate"] == ""
    assert row["utc_offset_minutes"] == ""


def test_a_measured_distance_is_rounded_to_something_a_spreadsheet_can_show(client, user):
    """Fifteen decimal places of a metre reads as a bug, not a measurement."""
    gpx = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Measured</name><type>cycling</type><trkseg>
    <trkpt lat="45.0700000" lon="7.6869000"><ele>240</ele><time>2026-06-22T06:30:00Z</time></trkpt>
    <trkpt lat="45.0703110" lon="7.6871230"><ele>241</ele><time>2026-06-22T06:30:10Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
    upload(client, user["id"], gpx, "ride.gpx")

    row = rows_of(client.get(f"/api/export/activities.csv?user_id={user['id']}").text)[0]

    assert len(row["distance_m"].split(".")[1]) <= 2
    assert float(row["distance_m"]) > 0


def test_the_csv_honours_the_same_filters_as_the_list(client, user, sample_tcx, sample_gpx):
    """Exporting the whole library while the screen shows one sport is a trap."""
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], sample_gpx, "run.gpx")

    filtered = client.get(f"/api/export/activities.csv?user_id={user['id']}&sport_type=running")

    rows = rows_of(filtered.text)
    assert [row["sport"] for row in rows] == ["running"]


def test_a_reversed_date_range_is_refused_here_too(client, user):
    response = client.get(
        f"/api/export/activities.csv?user_id={user['id']}&date_from=2026-08-01&date_to=2026-07-01"
    )

    assert response.status_code == 422


def test_an_empty_library_still_exports_its_header(client, user):
    response = client.get(f"/api/export/activities.csv?user_id={user['id']}")

    assert response.text.strip().splitlines() == [
        "id,name,sport,source,file_format,start_time_utc,utc_offset_minutes,"
        "distance_m,moving_time_s,elevation_gain_m,elevation_loss_m,"
        "avg_heart_rate,max_heart_rate,avg_cadence"
    ]


def test_the_csv_is_refused_for_an_unknown_user(client):
    assert client.get("/api/export/activities.csv?user_id=9999").status_code == 404


def test_the_csv_does_not_leak_between_users(client, user, other_user, sample_tcx):
    upload(client, user["id"], sample_tcx, "ride.tcx")

    assert rows_of(client.get(f"/api/export/activities.csv?user_id={other_user['id']}").text) == []


# -- one activity as GPX -------------------------------------------------


def test_every_sample_round_trips_through_this_apps_own_parser(
    client, user, sample_tcx, db_session
):
    """The guarantee worth having: the samples come back exactly.

    A TCX goes in, a GPX comes out, and every stored point reads back with the
    same position, time, elevation, heart rate and cadence.
    """
    from app.models import TrackPoint

    created = upload(client, user["id"], sample_tcx, "ride.tcx").json()
    stored = (
        db_session.execute(
            select(TrackPoint)
            .where(TrackPoint.workout_id == created["id"])
            .order_by(TrackPoint.sequence)
        )
        .scalars()
        .all()
    )

    exported = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={user['id']}")
    reparsed = parse_file("export.gpx", exported.content)

    assert reparsed.name == created["name"]
    assert reparsed.sport_type == created["sport_type"]
    assert len(reparsed.track_points) == len(stored)
    for before, after in zip(stored, reparsed.track_points, strict=True):
        assert after.latitude == pytest.approx(before.latitude)
        assert after.longitude == pytest.approx(before.longitude)
        assert after.elevation == pytest.approx(before.elevation)
        assert as_utc(after.timestamp) == as_utc(before.timestamp)
        assert after.heart_rate == before.heart_rate
        assert after.cadence == before.cadence


def test_a_gpx_cannot_carry_the_totals_a_tcx_declared(client, user, sample_tcx):
    """A real limitation of the format, asserted rather than discovered later.

    TCX states its own distance and average heart rate per lap; GPX has nowhere
    to put either, so a reader has to recompute them from the samples and gets
    slightly different figures. That is why the CSV exists: it carries the
    summary this app stored, and the GPX carries the samples. Between them
    nothing is lost.
    """
    created = upload(client, user["id"], sample_tcx, "ride.tcx").json()

    exported = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={user['id']}")
    recomputed = compute_metrics(parse_file("export.gpx", exported.content))

    # 142 was the figure the device wrote; 145 is the mean of the four samples.
    assert created["avg_heart_rate"] == 142
    assert recomputed.avg_heart_rate == 145

    row = rows_of(client.get(f"/api/export/activities.csv?user_id={user['id']}").text)[0]
    assert int(row["avg_heart_rate"]) == 142
    assert float(row["distance_m"]) == pytest.approx(created["total_distance"])


def test_the_gpx_keeps_the_offset_the_original_file_stated(client, user):
    """Normalising everything to Z would throw away the local hour."""
    tcx = b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities><Activity Sport="Running">
    <Id>2026-05-04T08:30:00+02:00</Id>
    <Lap StartTime="2026-05-04T08:30:00+02:00">
      <TotalTimeSeconds>1800</TotalTimeSeconds><DistanceMeters>5000</DistanceMeters>
      <Track>
        <Trackpoint><Time>2026-05-04T08:30:00+02:00</Time>
          <Position><LatitudeDegrees>45.07</LatitudeDegrees>
          <LongitudeDegrees>7.68</LongitudeDegrees></Position></Trackpoint>
        <Trackpoint><Time>2026-05-04T09:00:00+02:00</Time>
          <Position><LatitudeDegrees>45.08</LatitudeDegrees>
          <LongitudeDegrees>7.69</LongitudeDegrees></Position></Trackpoint>
      </Track>
    </Lap>
  </Activity></Activities>
</TrainingCenterDatabase>
"""
    created = upload(client, user["id"], tcx, "ride.tcx").json()
    assert created["utc_offset_minutes"] == 120

    exported = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={user['id']}")

    assert "+02:00" in exported.text
    assert parse_file("export.gpx", exported.content).utc_offset_minutes == 120


def test_a_name_with_an_ampersand_produces_parseable_xml(client, user):
    """Interpolating a name straight in produces XML nothing can read."""
    gpx = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Hills &amp; intervals &lt;hard&gt;</name><type>cycling</type><trkseg>
    <trkpt lat="45.07" lon="7.68"><ele>240</ele><time>2026-06-22T06:30:00Z</time></trkpt>
    <trkpt lat="45.08" lon="7.69"><ele>250</ele><time>2026-06-22T06:35:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
    created = upload(client, user["id"], gpx, "ride.gpx").json()
    assert created["name"] == "Hills & intervals <hard>"

    exported = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={user['id']}")

    assert parse_file("export.gpx", exported.content).name == "Hills & intervals <hard>"


def test_the_gpx_is_named_by_date_sport_and_id_not_by_the_activity_name(client, user, sample_tcx):
    """A name can hold anything; a filename cannot."""
    created = upload(client, user["id"], sample_tcx, "ride.tcx").json()

    exported = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={user['id']}")

    assert (
        f'filename="2026-05-04-cycling-{created["id"]}.gpx"'
        in (exported.headers["content-disposition"])
    )


def test_another_users_activity_cannot_be_exported(client, user, other_user, sample_tcx):
    created = upload(client, user["id"], sample_tcx, "ride.tcx").json()

    response = client.get(f"/api/workouts/{created['id']}/export.gpx?user_id={other_user['id']}")

    assert response.status_code == 404


# -- the whole library as a zip ------------------------------------------


def test_the_zip_holds_one_gpx_per_activity(client, user, sample_tcx, sample_gpx):
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], sample_gpx, "run.gpx")

    response = client.get(f"/api/export/activities.zip?user_id={user['id']}")

    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert all(name.endswith(".gpx") for name in names)


def test_the_zip_this_app_writes_is_one_this_app_can_read(
    client, user, other_user, sample_tcx, sample_gpx
):
    """The mirror image of the archive upload, checked by doing the round trip."""
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], sample_gpx, "run.gpx")
    exported = client.get(f"/api/export/activities.zip?user_id={user['id']}").content

    restored = client.post(
        f"/api/upload/archive?user_id={other_user['id']}",
        files={"file": ("activities.zip", exported, "application/zip")},
    )

    assert restored.status_code == 202
    body = client.get(
        f"/api/upload/archive/{restored.json()['id']}?user_id={other_user['id']}"
    ).json()
    assert (body["status"], body["stored"], body["failed"]) == ("done", 2, 0)


def test_the_zip_honours_the_filters(client, user, sample_tcx, sample_gpx):
    upload(client, user["id"], sample_tcx, "ride.tcx")
    upload(client, user["id"], sample_gpx, "run.gpx")

    response = client.get(f"/api/export/activities.zip?user_id={user['id']}&sport_type=hiking")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == []


def test_the_zip_is_refused_for_an_unknown_user(client):
    assert client.get("/api/export/activities.zip?user_id=9999").status_code == 404
