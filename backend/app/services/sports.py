"""Every sport the app knows, and everything that differs between them.

The one place a sport is defined. The parsers look up what a file calls its
sport here, and the dashboard reads the same entries from GET /api/sports for
labels, pace or speed, cadence units and colours. Before this, the same facts
lived in three parser tables and four places in the frontend, and adding a sport
meant finding all of them.

Adding a sport is adding an entry to SPORTS. A sport a file names that is not
here is still stored under the file's own name (see `sport_from_file`), and
the dashboard treats it as a sport read by speed, in the "other" colour.
"""

from dataclasses import dataclass
from typing import Literal

FileFormat = Literal["fit", "tcx", "gpx"]

#: The four validated colour slots of the dashboard's palette. Colour follows
#: the entity, and a fifth hue picked by eye can be invisible to a colourblind
#: reader, so a sport takes one of these — usually "other" — rather than a new one.
ColorSlot = Literal["cycling", "running", "hiking", "other"]

OTHER = "other"


@dataclass(frozen=True, slots=True)
class Sport:
    """One sport, and what each file format calls it."""

    key: str
    label: str
    #: How a moving rate reads: minutes per kilometre, or kilometres per hour.
    rate: Literal["pace", "speed"]
    #: Cyclists count crank revolutions (rpm). On foot, TCX `RunCadence` and GPX
    #: `cad` are written per leg, so the figure is strides per minute (spm).
    cadence_unit: Literal["spm", "rpm"]
    color: ColorSlot
    #: False for a sport that goes nowhere — strength, say. Distance, pace,
    #: climb, the route and comparison along a distance axis mean nothing for
    #: it, and the dashboard leaves them out rather than showing a zero.
    has_distance: bool = True
    #: What each format writes for this sport, lowercased. FIT names are the
    #: ones fitdecode gives for FIT's sport enum.
    fit: tuple[str, ...] = ()
    tcx: tuple[str, ...] = ()
    gpx: tuple[str, ...] = ()
    #: FIT sub-sports that make an activity this sport whatever its sport says.
    #: Garmin records a strength session as sport "training", sub-sport
    #: "strength_training" — the sport alone cannot tell it from any other
    #: gym session.
    fit_sub: tuple[str, ...] = ()


#: In display order: the dashboard lists sports this way round.
SPORTS: tuple[Sport, ...] = (
    Sport(
        "cycling",
        "Cycling",
        rate="speed",
        cadence_unit="rpm",
        color="cycling",
        fit=("cycling",),
        tcx=("biking",),
        # "1" is Strava's numeric code for a ride.
        gpx=("1", "ride", "biking", "bike", "cycling"),
    ),
    Sport(
        "running",
        "Running",
        rate="pace",
        cadence_unit="spm",
        color="running",
        fit=("running",),
        tcx=("running",),
        # "9" is Strava's numeric code for a run.
        gpx=("9", "run", "running"),
    ),
    Sport(
        "hiking",
        "Hiking",
        rate="pace",
        cadence_unit="spm",
        color="hiking",
        fit=("hiking",),
        tcx=("hiking",),
        gpx=("hike", "hiking"),
    ),
    Sport(
        "walking",
        "Walking",
        rate="pace",
        cadence_unit="spm",
        color=OTHER,
        fit=("walking",),
        tcx=("walking",),
        gpx=("walk", "walking"),
    ),
    Sport(
        "swimming",
        "Swimming",
        rate="speed",
        cadence_unit="rpm",
        color=OTHER,
        fit=("swimming",),
        tcx=("swimming",),
    ),
    Sport(
        "strength",
        "Strength",
        # Neither applies to a sport without distance; required all the same,
        # so that every entry has the same shape.
        rate="speed",
        cadence_unit="rpm",
        color=OTHER,
        has_distance=False,
        fit_sub=("strength_training",),
    ),
    Sport(
        OTHER,
        "Other",
        rate="speed",
        cadence_unit="rpm",
        color=OTHER,
        # Garmin's catch-alls: a generic activity, gym work, a machine.
        fit=("generic", "training", "fitness_equipment"),
        tcx=("other",),
    ),
)

BY_KEY: dict[str, Sport] = {sport.key: sport for sport in SPORTS}

_ALIASES: dict[FileFormat, dict[str, str]] = {
    file_format: {alias: sport.key for sport in SPORTS for alias in getattr(sport, file_format)}
    for file_format in ("fit", "tcx", "gpx")
}

_FIT_SUB_ALIASES: dict[str, str] = {alias: sport.key for sport in SPORTS for alias in sport.fit_sub}


def _normalised(value: object) -> str:
    return str(value).strip().lower() if value else ""


def sport_from_fit_sub_sport(sub_sport: object) -> str | None:
    """The sport a FIT sub-sport alone decides, or None if it decides nothing."""
    return _FIT_SUB_ALIASES.get(_normalised(sub_sport))


def sport_from_file(file_format: FileFormat, declared: object, sub_sport: object = None) -> str:
    """The sport to store for what a file says it is.

    A FIT sub-sport the catalogue lists wins over the sport. Otherwise a name
    the catalogue does not know is kept as the file wrote it: "rowing" is more
    use than "other", and it gets the dashboard's defaults until it has an
    entry of its own. Only a file that names no sport at all is "other".
    """
    if file_format == "fit" and (by_sub_sport := sport_from_fit_sub_sport(sub_sport)):
        return by_sub_sport
    name = _normalised(declared)
    return _ALIASES[file_format].get(name, name or OTHER)
