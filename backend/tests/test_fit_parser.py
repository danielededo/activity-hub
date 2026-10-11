"""FIT parser behaviour, against bytes built by tests/fit_builder.py."""

from datetime import UTC, datetime

import pytest
from fitdecode.profile import FIELD_TYPES

from app.models import Workout
from app.services.parsers import FitParser, ParserError, get_parser
from tests.fit_builder import RECORD, SPORT, UINT8, UINT32, FitBuilder, fit_time, ride

START = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)


def test_parses_header_fields():
    workout = FitParser().parse(ride(START), filename="ride.fit")

    assert workout.source == "garmin"  # manufacturer 1
    assert workout.file_format == "fit"
    assert workout.sport_type == "cycling"
    assert workout.name == "Cycling 2026-06-01"
    assert workout.start_time == START


def test_totals_come_from_the_session_not_the_samples():
    workout = FitParser().parse(ride(START))

    # The samples span 20 seconds; the session states 1800, and the session wins.
    assert workout.total_time == pytest.approx(1800.0)
    assert workout.avg_heart_rate == 141
    assert workout.max_heart_rate == 152
    assert workout.avg_cadence == 85


def test_distance_stays_in_metres():
    """The rest of the app works in metres, and so must this.

    fitdecode's StandardUnitsDataProcessor would hand back 12.34 here. This
    pins the choice of processor: with the wrong one every activity is stored a
    thousand times shorter than it was, and nothing else in the app notices.
    """
    assert FitParser().parse(ride(START)).total_distance == pytest.approx(12340.0)


def test_positions_are_converted_from_semicircles():
    points = FitParser().parse(ride(START)).track_points

    assert len(points) == 3
    assert points[0].latitude == pytest.approx(45.0, abs=1e-6)
    assert points[0].longitude == pytest.approx(7.0, abs=1e-6)
    assert points[2].latitude == pytest.approx(45.002, abs=1e-6)


def test_parses_samples():
    points = FitParser().parse(ride(START)).track_points

    assert [p.sequence for p in points] == [0, 1, 2]
    assert points[0].timestamp == START
    assert points[2].timestamp == datetime(2026, 6, 1, 7, 0, 20, tzinfo=UTC)
    assert points[0].heart_rate == 140
    assert points[2].heart_rate == 142
    assert points[0].cadence == 85
    assert points[0].elevation == pytest.approx(100.0)
    assert points[2].elevation == pytest.approx(102.0)


def test_utc_offset_comes_from_the_local_timestamp():
    """FIT is the only format of the three that states the offset outright."""
    assert FitParser().parse(ride(START, local_offset_hours=2)).utc_offset_minutes == 120
    assert FitParser().parse(ride(START, local_offset_hours=-7)).utc_offset_minutes == -420


def test_offset_is_none_when_the_file_does_not_say():
    assert FitParser().parse(ride(START, local_offset_hours=None)).utc_offset_minutes is None


def test_indoor_records_without_a_position_are_kept():
    """An indoor ride has heart rate and cadence and no GPS, and still counts."""
    workout = FitParser().parse(ride(START, with_position=False))

    assert len(workout.track_points) == 3
    assert all(p.latitude is None and p.longitude is None for p in workout.track_points)
    assert workout.track_points[0].heart_rate == 140


def test_records_without_heart_rate():
    points = FitParser().parse(ride(START, with_heart_rate=False)).track_points

    assert all(p.heart_rate is None for p in points)
    assert all(p.cadence == 85 for p in points)


def test_session_without_totals_leaves_them_to_the_analyzer():
    workout = FitParser().parse(ride(START, session_totals=False))

    assert workout.total_distance is None
    assert workout.total_time is None
    assert workout.avg_heart_rate is None
    # The session states no start_time either, so the file_id's stands in.
    assert workout.start_time == START
    assert len(workout.track_points) == 3


def test_raw_data_records_what_was_read():
    raw = FitParser().parse(ride(START)).raw_data

    assert raw["manufacturer"] == "garmin"
    assert raw["file_type"] == "activity"
    assert raw["session_count"] == 1
    assert raw["record_count"] == 3
    assert raw["track_point_count"] == 3
    assert raw["total_ascent"] == 210
    assert raw["total_descent"] == 190


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(1, "running"), (2, "cycling"), (11, "walking"), (17, "hiking"), (0, "other")],
)
def test_sport_enum_is_mapped(declared, expected):
    assert FitParser().parse(ride(START, sport=declared)).sport_type == expected


def test_sport_falls_back_to_the_sport_message():
    """Some files leave the session's sport unset and state it once, separately."""
    builder = FitBuilder()
    builder.message(0, SPORT, [(0, UINT8, 1)])  # running
    builder.message(1, RECORD, [(253, UINT32, fit_time(START)), (3, UINT8, 150)])

    assert FitParser().parse(builder.build()).sport_type == "running"


def test_a_garmin_strength_session_is_strength():
    """Sport "training" alone is any gym session; the sub-sport says which."""
    parsed = FitParser().parse(ride(START, sport=10, sub_sport=20, with_position=False))

    assert parsed.sport_type == "strength"
    assert parsed.name.startswith("Strength ")


def test_training_without_a_known_sub_sport_is_still_other():
    assert FitParser().parse(ride(START, sport=10)).sport_type == "other"


def test_the_sub_sport_can_come_from_the_sport_message():
    builder = FitBuilder()
    builder.message(0, SPORT, [(0, UINT8, 10), (1, UINT8, 20)])  # training, strength
    builder.message(1, RECORD, [(253, UINT32, fit_time(START)), (3, UINT8, 110)])

    assert FitParser().parse(builder.build()).sport_type == "strength"


def test_the_declared_sport_is_kept_for_later_reclassification():
    raw = FitParser().parse(ride(START, sport=10, sub_sport=20)).raw_data

    assert (raw["declared_sport"], raw["sub_sport"]) == ("training", "strength_training")


def test_unnamed_manufacturer_does_not_become_the_source():
    """fitdecode returns the raw number for a manufacturer it has no name for."""
    assert FitParser().parse(ride(START, manufacturer=64_000)).source == "fit"


# -- recognition ---------------------------------------------------------


def test_recognised_by_extension_without_content():
    assert FitParser.supports("ride.fit")
    assert FitParser.supports("RIDE.FIT")
    assert not FitParser.supports("ride.gpx")


def test_recognised_by_signature_without_a_name():
    """A Strava export names members by activity id, with no extension at all."""
    assert FitParser.supports(None, ride(START))
    assert not FitParser.supports(None, b"<gpx/>")
    assert not FitParser.supports(None, b"")


def test_factory_picks_it():
    assert isinstance(get_parser("ride.fit"), FitParser)
    assert isinstance(get_parser("12345", ride(START)), FitParser)


# -- rejection -----------------------------------------------------------


def test_empty_file_is_rejected():
    with pytest.raises(ParserError, match="empty"):
        FitParser().parse(b"")


def test_truncated_file_is_rejected():
    with pytest.raises(ParserError, match="Malformed FIT"):
        FitParser().parse(ride(START)[:40])


def test_xml_is_rejected_rather_than_crashing():
    with pytest.raises(ParserError):
        FitParser().parse(b"<gpx creator='test'/>")


def test_file_without_records_is_rejected():
    """A settings or monitoring file from the same watch is not an activity."""
    builder = FitBuilder()
    builder.message(0, SPORT, [(0, UINT8, 2)])

    with pytest.raises(ParserError, match="no records"):
        FitParser().parse(builder.build())


def test_every_manufacturer_name_fits_the_source_column():
    """The source column is 32 characters and the longest FIT name is 28.

    Close enough to be worth a guard: FIT's manufacturer list grows with every
    profile revision, and a name too long to store would fail at the insert,
    long after the parse that produced it.
    """
    limit = Workout.__table__.columns["source"].type.length
    longest = max(len(str(name)) for name in FIELD_TYPES["manufacturer"].enum.values())

    assert longest <= limit, f"a manufacturer name is {longest} characters, the column is {limit}"
