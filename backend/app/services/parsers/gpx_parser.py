"""GPX parser, covering Strava and Komoot exports."""

from app.services.parsers.base_parser import (
    BaseParser,
    ParsedTrackPoint,
    ParsedWorkout,
    ParserError,
)
from app.services.sports import sport_from_file

#: Substrings in the gpx/@creator attribute that identify the exporting service.
CREATOR_SOURCES = (
    ("strava", "strava"),
    ("komoot", "komoot"),
    ("garmin", "garmin"),
    ("runkeeper", "runkeeper"),
    ("wahoo", "wahoo"),
)

#: Extension element names carrying heart rate / cadence, in priority order.
HEART_RATE_KEYS = ("hr", "heartrate", "heart_rate", "bpm")
CADENCE_KEYS = ("cad", "cadence")


class GpxParser(BaseParser):
    file_format = "gpx"
    default_source = "gpx"
    root_tag = "gpx"

    def parse(self, content: bytes, filename: str | None = None) -> ParsedWorkout:
        root = self._parse_xml(content)
        tracks = self._nodes(root, "trk")
        if not tracks:
            raise ParserError("No <trk> element found in GPX file")

        track = tracks[0]
        trackpoints = self._descendants(root, "trkpt")
        points = self._track_points(trackpoints)
        if not points:
            raise ParserError("GPX file contains no track points")

        creator = root.get("creator")
        timestamps = [point.timestamp for point in points if point.timestamp]
        # Read the offset off the raw text: the parsed points are already UTC.
        first_point_time = next(
            (text for text in (self._text(node, "time") for node in trackpoints) if text), None
        )
        start_time, utc_offset_minutes = self._first_timestamp(
            [first_point_time, self._text(root, "metadata/time")]
        )
        if start_time is None:
            raise ParserError("GPX file carries no usable start time")

        total_time = (
            (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) > 1 else None
        )
        segments = self._nodes(track, "trkseg")
        return ParsedWorkout(
            source=self._source(creator),
            file_format=self.file_format,
            name=self._name(track, start_time),
            sport_type=self._sport_type(track),
            start_time=start_time,
            utc_offset_minutes=utc_offset_minutes,
            track_points=points,
            raw_data={
                "creator": creator,
                "metadata_name": self._text(root, "metadata/name"),
                "declared_type": self._text(track, "type"),
                "track_count": len(tracks),
                "segment_count": len(segments),
                "track_point_count": len(points),
            },
            # GPX states no totals; distance and elevation come from the analyzer.
            total_time=total_time,
        )

    # -- internals -------------------------------------------------------

    def _source(self, creator: str | None) -> str:
        lowered = (creator or "").lower()
        for needle, source in CREATOR_SOURCES:
            if needle in lowered:
                return source
        return self.default_source

    def _sport_type(self, track) -> str:
        return sport_from_file("gpx", self._text(track, "type"))

    def _name(self, track, start_time) -> str:
        name = self._text(track, "name")
        if name:
            return name[:255]
        return f"Activity {start_time.date().isoformat()}"

    def _track_points(self, trackpoints: list) -> list[ParsedTrackPoint]:
        points: list[ParsedTrackPoint] = []
        for index, node in enumerate(trackpoints):
            extensions = self._node(node, "extensions")
            values = self._leaf_values(extensions) if extensions is not None else {}
            points.append(
                ParsedTrackPoint(
                    sequence=index,
                    timestamp=self._parse_timestamp(self._text(node, "time")),
                    latitude=self._to_float(node.get("lat")),
                    longitude=self._to_float(node.get("lon")),
                    elevation=self._float(node, "ele"),
                    heart_rate=self._first_int(values, HEART_RATE_KEYS),
                    cadence=self._first_int(values, CADENCE_KEYS),
                )
            )
        return points

    @staticmethod
    def _to_float(value: str | None) -> float | None:
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    @staticmethod
    def _first_int(values: dict[str, str], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            if key in values:
                try:
                    return int(round(float(values[key])))
                except ValueError:
                    continue
        return None
