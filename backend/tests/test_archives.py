"""Reading a zip from a user, and the ways that can be abused."""

import io
import zipfile
from datetime import UTC, datetime

import pytest

from app.config import settings
from app.services.archives import (
    ArchiveError,
    _read_bounded,
    looks_like_zip,
    read_archive,
)
from tests.fit_builder import ride

LIMITS = {
    "max_members": 100,
    "max_extracted_bytes": 10 * 1024 * 1024,
    "max_member_bytes": 1024 * 1024,
}


def fit(start: datetime) -> bytes:
    """A FIT member, built rather than vendored: see tests/fit_builder.py."""
    return ride(start)


def gpx(when: str, sport: str = "cycling", name: str = "Ride") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{name}</name><type>{sport}</type><trkseg>
    <trkpt lat="45.07" lon="7.68"><ele>240</ele><time>{when}</time></trkpt>
    <trkpt lat="45.08" lon="7.69"><ele>250</ele><time>{when}</time></trkpt>
  </trkseg></trk>
</gpx>
""".encode()


def make_zip(members: dict[str, bytes], *, directories: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in directories:
            archive.writestr(zipfile.ZipInfo(directory), b"")
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def members_of(content: bytes, **overrides):
    return list(read_archive(content, **{**LIMITS, **overrides}))


# -- what it accepts -----------------------------------------------------


def test_reads_activity_members():
    content = make_zip(
        {
            "activities/ride.gpx": gpx("2026-06-01T07:00:00Z"),
            "activities/run.tcx": b"<TrainingCenterDatabase/>",
        }
    )

    found = {m.name: m for m in members_of(content)}

    assert set(found) == {"activities/ride.gpx", "activities/run.tcx"}
    assert all(m.usable for m in found.values())


def test_reads_a_fit_member():
    """A Garmin bulk export is FIT, not GPX.

    While `.fit` was missing from ACTIVITY_SUFFIXES an export of eight hundred
    rides reported stored=0, skipped=800, and looked like it had worked.
    """
    content = make_zip({"activities/12345.fit": fit(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))})

    [member] = members_of(content)

    assert member.usable
    assert member.content[8:12] == b".FIT"


def test_reads_a_gzipped_member():
    """Some exporters gzip each file inside the archive."""
    import gzip

    payload = gpx("2026-06-01T07:00:00Z")
    content = make_zip({"activities/ride.gpx.gz": gzip.compress(payload)})

    [member] = members_of(content)

    assert member.usable
    assert member.content == payload


def test_directories_are_not_members():
    content = make_zip(
        {"activities/ride.gpx": gpx("2026-06-01T07:00:00Z")}, directories=("activities/",)
    )

    assert [m.name for m in members_of(content)] == ["activities/ride.gpx"]


# -- what it skips, and says why ----------------------------------------


def test_non_activity_files_are_skipped_not_failed():
    """A real export is full of CSVs and images. That is not an error."""
    content = make_zip(
        {
            "activities.csv": b"id,name\n1,Ride\n",
            "profile.jpg": b"\xff\xd8\xff",
            "activities/ride.gpx": gpx("2026-06-01T07:00:00Z"),
        }
    )

    skipped = {m.name: m.skipped for m in members_of(content) if not m.usable}

    assert set(skipped) == {"activities.csv", "profile.jpg"}
    assert all("not one of" in reason for reason in skipped.values())


def test_nested_archives_are_refused_not_recursed():
    inner = make_zip({"ride.gpx": gpx("2026-06-01T07:00:00Z")})
    content = make_zip({"inner.zip": inner})

    [member] = members_of(content)

    assert not member.usable
    assert "nested" in member.skipped


def test_a_member_over_the_size_cap_is_skipped():
    content = make_zip({"huge.gpx": b"<gpx/>" + b" " * 5_000})

    [member] = members_of(content, max_member_bytes=1_000)

    assert not member.usable
    assert "limit" in member.skipped


# -- what it refuses outright -------------------------------------------


def test_a_zip_bomb_is_refused_before_anything_is_read():
    """The declared uncompressed total is the bomb signature.

    A megabyte of zeros compresses to almost nothing, which is exactly how a
    small archive claims to be enormous.
    """
    content = make_zip({"bomb.gpx": b"\0" * (1024 * 1024)})
    assert len(content) < 10_000, "the fixture should compress hard"

    with pytest.raises(ArchiveError, match="uncompressed"):
        members_of(content, max_extracted_bytes=100_000)


def test_too_many_members_is_refused():
    content = make_zip({f"ride-{index}.gpx": b"<gpx/>" for index in range(20)})

    with pytest.raises(ArchiveError, match="more than the 10 allowed"):
        members_of(content, max_members=10)


def test_something_that_is_not_a_zip_is_refused():
    with pytest.raises(ArchiveError, match="Not a readable zip"):
        members_of(b"<gpx>this is not an archive</gpx>")


def test_a_bounded_read_stops_at_the_limit():
    """The backstop for a header that understates a member's size."""
    assert _read_bounded(io.BytesIO(b"x" * 100), 100) == b"x" * 100
    assert _read_bounded(io.BytesIO(b"x" * 101), 100) is None


# -- detection -----------------------------------------------------------


def test_zip_detection_prefers_the_magic_number_over_the_name():
    archive = make_zip({"ride.gpx": gpx("2026-06-01T07:00:00Z")})

    # Mislabelled as an activity, but still an archive.
    assert looks_like_zip("export.gpx", archive)
    # Named like an archive but plainly XML.
    assert looks_like_zip("export.zip", b"<gpx/>")
    assert not looks_like_zip("ride.gpx", b"<gpx/>")
    assert not looks_like_zip(None, b"<gpx/>")


# -- through the API -----------------------------------------------------


def post_archive(client, user_id: int, content: bytes, name: str = "export.zip"):
    return client.post(
        f"/api/upload/archive?user_id={user_id}",
        files={"file": (name, content, "application/zip")},
    )


def import_archive(client, user_id: int, content: bytes) -> dict:
    """Upload an archive and read its import once it has finished.

    The import runs after the upload is answered; the test client runs that
    background work before returning, so one read afterwards sees the end.
    """
    accepted = post_archive(client, user_id, content)
    assert accepted.status_code == 202, accepted.text
    finished = client.get(f"/api/upload/archive/{accepted.json()['id']}?user_id={user_id}")
    assert finished.status_code == 200, finished.text
    body = finished.json()
    assert body["status"] == "done", body
    return body


def test_an_export_imports_every_activity(client, user):
    content = make_zip(
        {
            "activities/a.gpx": gpx("2026-06-01T07:00:00Z", "cycling"),
            "activities/b.gpx": gpx("2026-06-02T07:00:00Z", "running"),
            "activities/c.gpx": gpx("2026-06-03T07:00:00Z", "hiking"),
        }
    )

    body = import_archive(client, user["id"], content)

    assert body["stored"] == 3
    assert body["duplicates"] == 0
    assert body["failed"] == 0
    assert {m["outcome"] for m in body["members"]} == {"stored"}
    assert all(m["workout_id"] for m in body["members"])


def test_a_garmin_export_of_fit_files_imports(client, user):
    """The end of the bug: a FIT-only export used to import nothing at all."""
    content = make_zip(
        {
            "12345.fit": fit(datetime(2026, 6, 1, 7, 0, tzinfo=UTC)),
            "12346.fit": fit(datetime(2026, 6, 2, 7, 0, tzinfo=UTC)),
            "activities.csv": b"id,name\n12345,Ride\n",
        }
    )

    body = import_archive(client, user["id"], content)

    assert body["stored"] == 2
    assert body["failed"] == 0
    outcomes = {m["filename"]: m["outcome"] for m in body["members"]}
    assert outcomes["12345.fit"] == "stored"
    assert outcomes["12346.fit"] == "stored"
    assert outcomes["activities.csv"] == "skipped"


def test_reimporting_the_same_export_stores_nothing_twice(client, user):
    content = make_zip({"a.gpx": gpx("2026-06-01T07:00:00Z")})
    assert import_archive(client, user["id"], content)["stored"] == 1

    body = import_archive(client, user["id"], content)

    assert body["stored"] == 0
    assert body["duplicates"] == 1
    assert body["members"][0]["detail"]


def test_one_corrupt_file_does_not_stop_the_rest(client, user):
    """An export with a bad file should still import the good ones."""
    content = make_zip(
        {
            "good-1.gpx": gpx("2026-06-01T07:00:00Z", "cycling"),
            "broken.gpx": b"<gpx><trk>",
            "good-2.gpx": gpx("2026-06-02T07:00:00Z", "running"),
        }
    )

    body = import_archive(client, user["id"], content)

    assert body["stored"] == 2
    assert body["failed"] == 1
    failed = next(m for m in body["members"] if m["outcome"] == "failed")
    assert "Malformed XML" in failed["detail"]


def test_a_mixed_export_reports_each_kind(client, user):
    content = make_zip(
        {
            "activities/a.gpx": gpx("2026-06-01T07:00:00Z"),
            "activities.csv": b"id,name\n",
            "nested.zip": make_zip({"x.gpx": b"<gpx/>"}),
            "broken.gpx": b"not xml",
        }
    )

    body = import_archive(client, user["id"], content)

    assert (body["stored"], body["skipped"], body["failed"]) == (1, 2, 1)


def test_an_empty_archive_is_not_an_error(client, user):
    body = import_archive(client, user["id"], make_zip({}))

    counts = ("total", "processed", "stored", "duplicates", "skipped", "failed")
    assert {key: body[key] for key in counts} == dict.fromkeys(counts, 0)
    assert body["members"] == []
    assert body["truncated"] is False


def test_the_member_list_is_capped_but_the_counts_are_not(client, user, monkeypatch):
    monkeypatch.setattr(settings, "max_reported_members", 2)
    content = make_zip({f"skip-{index}.csv": b"x" for index in range(5)})

    body = import_archive(client, user["id"], content)

    assert body["skipped"] == 5
    assert len(body["members"]) == 2
    assert body["truncated"] is True


def test_a_zip_bomb_is_rejected_by_the_endpoint(client, user, monkeypatch):
    monkeypatch.setattr(settings, "max_archive_extracted_bytes", 100_000)
    content = make_zip({"bomb.gpx": b"\0" * (1024 * 1024)})

    response = post_archive(client, user["id"], content)

    assert response.status_code == 422
    assert "uncompressed" in response.json()["detail"]


def test_an_unknown_user_is_404(client):
    assert post_archive(client, 4242, make_zip({})).status_code == 404


# -- the two routes point at each other ---------------------------------


def test_an_archive_sent_to_the_single_file_route_is_redirected(client, user, sample_gpx):
    content = make_zip({"a.gpx": sample_gpx})

    response = client.post(
        f"/api/upload?user_id={user['id']}",
        files={"file": ("export.zip", content, "application/zip")},
    )

    assert response.status_code == 422
    assert "/api/upload/archive" in response.json()["detail"]


def test_a_plain_file_sent_to_the_archive_route_is_redirected(client, user, sample_gpx):
    response = post_archive(client, user["id"], sample_gpx, name="run.gpx")

    assert response.status_code == 422
    assert "/api/upload" in response.json()["detail"]
