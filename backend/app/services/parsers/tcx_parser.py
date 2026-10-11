"""Garmin Training Center (TCX) parser."""

from datetime import datetime

from app.services.parsers.base_parser import (
    BaseParser,
    ParsedTrackPoint,
    ParsedWorkout,
    ParserError,
)
from app.services.sports import sport_from_file


class TcxParser(BaseParser):
    file_format = "tcx"
    default_source = "garmin"
    root_tag = "TrainingCenterDatabase"

    def parse(self, content: bytes, filename: str | None = None) -> ParsedWorkout:
        root = self._parse_xml(content)
        activity = self._node(root, "Activities/Activity")
        if activity is None:
            raise ParserError("No <Activity> element found in TCX file")

        sport_type = self._sport_type(activity)
        laps = self._nodes(activity, "Lap")
        trackpoints = self._descendants(activity, "Trackpoint")
        points = self._track_points(trackpoints)
        start_time, utc_offset_minutes = self._start(activity, laps, trackpoints)

        total_time = sum(t for t in (self._float(lap, "TotalTimeSeconds") for lap in laps) if t)
        total_distance = sum(d for d in (self._float(lap, "DistanceMeters") for lap in laps) if d)
        lap_max_hr = [
            hr
            for hr in (self._int(lap, "MaximumHeartRateBpm/Value") for lap in laps)
            if hr is not None
        ]
        lap_avg_hr = [
            hr
            for hr in (self._int(lap, "AverageHeartRateBpm/Value") for lap in laps)
            if hr is not None
        ]

        creator = self._text(activity, "Creator/Name")
        return ParsedWorkout(
            source=self.default_source,
            file_format=self.file_format,
            name=self._name(activity, sport_type, start_time),
            sport_type=sport_type,
            start_time=start_time,
            utc_offset_minutes=utc_offset_minutes,
            track_points=points,
            raw_data={
                "creator": creator,
                "author": self._text(root, "Author/Name"),
                "activity_id": self._text(activity, "Id"),
                "declared_sport": activity.get("Sport"),
                "lap_count": len(laps),
                "track_point_count": len(points),
                "laps": [self._lap_summary(lap) for lap in laps],
            },
            total_distance=total_distance or None,
            total_time=total_time or None,
            avg_heart_rate=round(sum(lap_avg_hr) / len(lap_avg_hr)) if lap_avg_hr else None,
            max_heart_rate=max(lap_max_hr) if lap_max_hr else None,
        )

    # -- internals -------------------------------------------------------

    def _sport_type(self, activity) -> str:
        return sport_from_file("tcx", activity.get("Sport"))

    def _name(self, activity, sport_type: str, start_time: datetime) -> str:
        notes = self._text(activity, "Notes")
        if notes:
            return notes[:255]
        return f"{sport_type.capitalize()} {start_time.date().isoformat()}"

    def _start(self, activity, laps: list, trackpoints: list) -> tuple[datetime, int | None]:
        """Start instant plus whatever UTC offset the file stated.

        Garmin writes the activity id as a timestamp; the lap start and the
        first sample are the fallbacks.
        """
        candidates = [self._text(activity, "Id")]
        if laps:
            candidates.append(laps[0].get("StartTime"))
        if trackpoints:
            candidates.append(self._text(trackpoints[0], "Time"))

        start_time, offset = self._first_timestamp(candidates)
        if start_time is None:
            raise ParserError("TCX file carries no usable start time")
        return start_time, offset

    def _track_points(self, trackpoints: list) -> list[ParsedTrackPoint]:
        points: list[ParsedTrackPoint] = []
        for index, node in enumerate(trackpoints):
            extensions = self._node(node, "Extensions")
            cadence = self._int(node, "Cadence")
            if cadence is None and extensions is not None:
                # Running dynamics put cadence under Extensions/TPX/RunCadence.
                cadence = self._int(extensions, "TPX/RunCadence")
            points.append(
                ParsedTrackPoint(
                    sequence=index,
                    timestamp=self._parse_timestamp(self._text(node, "Time")),
                    latitude=self._float(node, "Position/LatitudeDegrees"),
                    longitude=self._float(node, "Position/LongitudeDegrees"),
                    elevation=self._float(node, "AltitudeMeters"),
                    heart_rate=self._int(node, "HeartRateBpm/Value"),
                    cadence=cadence,
                )
            )
        return points

    def _lap_summary(self, lap) -> dict:
        start = self._parse_timestamp(lap.get("StartTime"))
        return {
            "start_time": start.isoformat() if start else None,
            "total_time": self._float(lap, "TotalTimeSeconds"),
            "distance": self._float(lap, "DistanceMeters"),
            "calories": self._int(lap, "Calories"),
            "avg_heart_rate": self._int(lap, "AverageHeartRateBpm/Value"),
            "max_heart_rate": self._int(lap, "MaximumHeartRateBpm/Value"),
            "intensity": self._text(lap, "Intensity"),
        }
