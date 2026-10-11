"""The sport catalogue: one definition, read by the parsers and the dashboard."""

import json
from pathlib import Path

import pytest

from app.services.sports import OTHER, SPORTS, sport_from_file

FRONTEND_COPY = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "sports.json"


# -- the catalogue itself ------------------------------------------------


def test_every_sport_has_one_key():
    keys = [sport.key for sport in SPORTS]

    assert len(keys) == len(set(keys))
    assert OTHER in keys


@pytest.mark.parametrize("file_format", ["fit", "tcx", "gpx"])
def test_no_alias_names_two_sports(file_format):
    """An alias claimed twice would silently go to whichever came last."""
    aliases = [alias for sport in SPORTS for alias in getattr(sport, file_format)]

    assert len(aliases) == len(set(aliases))
    assert all(alias == alias.strip().lower() for alias in aliases)


# -- reading what a file says ---------------------------------------------


@pytest.mark.parametrize(
    ("file_format", "declared", "expected"),
    [
        ("tcx", "Biking", "cycling"),
        ("gpx", "Ride", "cycling"),
        ("gpx", "9", "running"),
        ("gpx", " hike ", "hiking"),
        ("fit", "training", "other"),
        ("fit", "fitness_equipment", "other"),
    ],
)
def test_a_known_name_becomes_its_sport(file_format, declared, expected):
    assert sport_from_file(file_format, declared) == expected


def test_a_fit_sub_sport_the_catalogue_lists_wins_over_the_sport():
    assert sport_from_file("fit", "training", "strength_training") == "strength"
    # Any sport at all: some devices file gym work under fitness_equipment.
    assert sport_from_file("fit", "fitness_equipment", "Strength_Training") == "strength"


def test_a_sub_sport_it_does_not_list_changes_nothing():
    assert sport_from_file("fit", "fitness_equipment", "indoor_rowing") == "other"
    assert sport_from_file("fit", "cycling", "road") == "cycling"


def test_sub_sports_are_a_fit_matter():
    assert sport_from_file("gpx", "running", "strength_training") == "running"


def test_no_sub_sport_alias_names_two_sports():
    aliases = [alias for sport in SPORTS for alias in sport.fit_sub]

    assert len(aliases) == len(set(aliases))


def test_only_sports_that_go_somewhere_have_a_distance():
    assert {sport.key for sport in SPORTS if not sport.has_distance} == {"strength"}


def test_aliases_belong_to_their_own_format():
    """Strava's "9" means a run in GPX; nothing says it does in TCX."""
    assert sport_from_file("gpx", "9") == "running"
    assert sport_from_file("tcx", "9") == "9"


def test_an_unknown_name_is_kept_as_written():
    """'rowing' is more use than 'other', and needs no entry to be stored."""
    assert sport_from_file("fit", "Rowing") == "rowing"


@pytest.mark.parametrize("declared", [None, "", "   "])
def test_no_name_at_all_is_other(declared):
    assert sport_from_file("gpx", declared) == OTHER


# -- what the dashboard is told ------------------------------------------


def test_the_api_lists_the_catalogue_in_order(client):
    response = client.get("/api/sports")

    assert response.status_code == 200
    body = response.json()
    assert [sport["key"] for sport in body] == [sport.key for sport in SPORTS]
    running = next(sport for sport in body if sport["key"] == "running")
    assert running == {
        "key": "running",
        "label": "Running",
        "rate": "pace",
        "cadence_unit": "spm",
        "color": "running",
        "has_distance": True,
    }


def test_the_api_keeps_file_aliases_to_itself(client):
    assert all("gpx" not in sport for sport in client.get("/api/sports").json())


@pytest.mark.skipif(not FRONTEND_COPY.exists(), reason="needs the whole repository")
def test_the_frontend_tests_use_the_real_catalogue(client):
    """The frontend tests run without a server, so they read a copy.

    A copy is how the catalogue would start living in two places again, so
    this fails the moment the two disagree. Regenerate it with
    `python -m scripts.export_sports`.
    """
    assert json.loads(FRONTEND_COPY.read_text()) == client.get("/api/sports").json()
