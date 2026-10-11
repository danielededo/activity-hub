"""Workout, upload and analysis response models."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkoutBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    source: str
    name: str
    sport_type: str
    start_time: datetime
    utc_offset_minutes: int | None
    total_distance: float
    total_elevation_gain: float
    total_elevation_loss: float
    total_time: float
    avg_heart_rate: int | None
    max_heart_rate: int | None
    avg_cadence: int | None
    file_format: str
    created_at: datetime
    updated_at: datetime


class WorkoutSummary(WorkoutBase):
    """List representation: everything except the raw file metadata."""


class WorkoutRead(WorkoutBase):
    """Detail representation."""

    raw_data: dict[str, Any]
    track_point_count: int = 0


class WorkoutList(BaseModel):
    items: list[WorkoutSummary]
    total: int
    limit: int
    offset: int


class TrackPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    timestamp: datetime | None
    latitude: float | None
    longitude: float | None
    elevation: float | None
    heart_rate: int | None
    cadence: int | None


class TrackPointSeries(BaseModel):
    """A workout's samples, downsampled to something a chart can draw."""

    workout_id: int
    #: Samples stored for this workout.
    total: int
    returned: int
    #: 1 means every sample; n means every nth, plus the final one.
    stride: int
    items: list[TrackPointRead]


class ArchiveMemberRead(BaseModel):
    """What happened to one file inside an uploaded archive."""

    filename: str
    #: stored | duplicate | skipped | failed
    outcome: str
    workout_id: int | None = None
    detail: str | None = None


class ArchiveImportRead(BaseModel):
    """An export archive's import: where it has got to, or how it ended.

    The counts are always exact. `members` is capped, because a full export can
    hold thousands of files and nobody reads a thousand-line JSON list.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    #: running | done | failed | interrupted
    status: str
    total: int
    processed: int
    stored: int
    duplicates: int
    skipped: int
    failed: int
    members: list[ArchiveMemberRead]
    truncated: bool = False
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class SportBreakdown(BaseModel):
    sport_type: str
    workout_count: int
    total_distance: float
    total_time: float


class AnalysisSummary(BaseModel):
    user_id: int
    workout_count: int
    total_distance: float
    total_time: float
    total_elevation_gain: float
    avg_distance: float
    avg_duration: float
    avg_heart_rate: float | None
    max_heart_rate: int | None
    longest_workout_id: int | None
    first_workout_at: datetime | None
    last_workout_at: datetime | None
    by_sport: list[SportBreakdown]


class WeeklyBucket(BaseModel):
    week_start: date
    iso_year: int
    iso_week: int
    workout_count: int
    total_distance: float
    total_time: float
    total_elevation_gain: float


class WeeklyAnalysis(BaseModel):
    user_id: int
    weeks: int
    buckets: list[WeeklyBucket]


class RecordHolder(BaseModel):
    """The activity that holds a record, and the figure it holds it with.

    `value` is metres for a distance record, seconds for a duration one and
    metres of ascent for a climb — whatever the record it belongs to measures.
    """

    workout_id: int
    workout_name: str
    start_time: datetime
    utc_offset_minutes: int | None
    value: float


class DistanceBest(BaseModel):
    """The fastest a standard distance was ever covered, and where."""

    label: str
    distance_m: int
    duration_s: float
    workout_id: int
    workout_name: str
    start_time: datetime
    utc_offset_minutes: int | None


class SportRecords(BaseModel):
    """One sport's records. Each is null until an activity qualifies."""

    sport_type: str
    workout_count: int
    longest_distance: RecordHolder | None
    longest_duration: RecordHolder | None
    biggest_climb: RecordHolder | None
    distance_bests: list[DistanceBest]


class YearlyTotals(BaseModel):
    """A calendar year of training, in local years."""

    year: int
    workout_count: int
    total_distance: float
    total_time: float
    total_elevation_gain: float


class ZoneBandRead(BaseModel):
    """One heart-rate zone and the time spent in it."""

    zone: int
    name: str
    min_bpm: int
    #: None for the top zone, which has no ceiling.
    max_bpm: int | None
    seconds: float


class WorkoutZones(BaseModel):
    """One activity's time in zone. Empty when it recorded no heart rate."""

    workout_id: int
    max_heart_rate: int | None
    #: configured | observed | unknown — observed is a floor, not a maximum.
    max_heart_rate_source: str
    zones: list[ZoneBandRead]
    #: Time under the floor of zone one: real, but not training.
    seconds_below_zones: float
    #: Edwards' TRIMP: minutes in each zone weighted by the zone.
    load: float


class WeeklyZoneSeconds(BaseModel):
    zone: int
    seconds: float


class WeeklyZoneBucket(BaseModel):
    week_start: date
    load: float
    seconds: list[WeeklyZoneSeconds]


class ZoneSummary(BaseModel):
    user_id: int
    max_heart_rate: int | None
    max_heart_rate_source: str
    weeks: int
    zones: list[ZoneBandRead]
    seconds_below_zones: float
    total_load: float
    #: Oldest first, quiet weeks zero-filled, each carrying its own load.
    weekly: list[WeeklyZoneBucket]


class FormDay(BaseModel):
    """One calendar day of the fitness-and-fatigue series."""

    day: date
    #: Edwards' TRIMP earned on this day; 0.0 on a rest day.
    load: float
    #: The 42-day exponential average of load.
    fitness: float
    #: The 7-day exponential average of load.
    fatigue: float
    #: Yesterday's fitness minus yesterday's fatigue — freshness before today.
    form: float


class FormSummary(BaseModel):
    user_id: int
    max_heart_rate: int | None
    #: configured | observed | unknown — observed is a floor, not a maximum.
    max_heart_rate_source: str
    days: int
    #: Oldest first, one entry per calendar day including rest days.
    series: list[FormDay]
    #: Days of history walked before the window, so both averages start warm.
    warmup_days: int
    #: Activities in the window with no heart rate. They contribute no load, so
    #: they read as rest days rather than merely going missing.
    untracked_activities: int


class RecordsSummary(BaseModel):
    user_id: int
    by_sport: list[SportRecords]
    #: Most recent year first.
    yearly: list[YearlyTotals]
