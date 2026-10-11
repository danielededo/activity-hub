"""FIT parser: the format Garmin devices actually write.

FIT is binary, not XML, so this parser shares the ParsedWorkout contract with
its siblings but none of their XML helpers — including `supports`, which sniffs
the file signature rather than a root element.

A Garmin bulk export keeps every activity in the format it was uploaded in, and
for anything recorded on a Garmin watch that is FIT. Without this parser the
common case — somebody arriving with their whole history — imports nothing.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import fitdecode

from app.services.parsers.base_parser import (
    BaseParser,
    ParsedTrackPoint,
    ParsedWorkout,
    ParserError,
)
from app.services.sports import sport_from_file

#: Bytes 8..12 of every FIT file. The header itself carries no other marker
#: that a sniffing check could rely on.
FIT_SIGNATURE = b".FIT"

#: Degrees per semicircle. FIT stores position as a signed 32-bit count of
#: semicircles, and the conversion is done here rather than by fitdecode's
#: StandardUnitsDataProcessor: that processor also turns session distance from
#: metres into kilometres, which would store every activity a thousand times
#: shorter than it was. Converting one field by hand is cheaper than auditing
#: every field the processor touches.
DEGREES_PER_SEMICIRCLE = 180.0 / (2**31)


class FitParser(BaseParser):
    file_format = "fit"
    default_source = "fit"

    @classmethod
    def supports(cls, filename: str | None, content: bytes | None = None) -> bool:
        """By extension, or by the signature the header carries.

        Overridden rather than inherited: the base implementation decides by
        parsing the file as XML, which a FIT file is not.
        """
        if filename and filename.lower().endswith(".fit"):
            return True
        return bool(content) and content[8:12] == FIT_SIGNATURE

    def parse(self, content: bytes, filename: str | None = None) -> ParsedWorkout:
        messages = self._read(content)

        points = self._track_points(messages["record"])
        if not points:
            raise ParserError("FIT file contains no records with a timestamp")

        session = messages["session"][0] if messages["session"] else {}
        file_id = messages["file_id"][0] if messages["file_id"] else {}
        activity = messages["activity"][0] if messages["activity"] else {}

        start_time = self._start_time(session, file_id, points)
        if start_time is None:
            raise ParserError("FIT file carries no usable start time")

        sport = self._sport(session, messages["sport"])
        return ParsedWorkout(
            source=self._source(file_id),
            file_format=self.file_format,
            name=f"{sport.capitalize()} {start_time.date().isoformat()}",
            sport_type=sport,
            start_time=start_time,
            utc_offset_minutes=self._offset_minutes(activity),
            track_points=points,
            raw_data={
                "manufacturer": file_id.get("manufacturer"),
                "product": file_id.get("product") or file_id.get("garmin_product"),
                "file_type": file_id.get("type"),
                "sub_sport": session.get("sub_sport"),
                "session_count": len(messages["session"]),
                "lap_count": len(messages["lap"]),
                "record_count": len(messages["record"]),
                "track_point_count": len(points),
                "total_ascent": session.get("total_ascent"),
                "total_descent": session.get("total_descent"),
            },
            # The device's own figures, which beat anything derived from the
            # samples. total_timer_time rather than total_elapsed_time: the
            # timer stops when you do, so it is the moving time this app means.
            total_distance=self._number(session.get("total_distance")),
            total_time=self._number(session.get("total_timer_time")),
            avg_heart_rate=self._whole(session.get("avg_heart_rate")),
            max_heart_rate=self._whole(session.get("max_heart_rate")),
            avg_cadence=self._whole(session.get("avg_cadence")),
        )

    # -- internals -------------------------------------------------------

    #: Message types worth collecting. Everything else in a FIT file — device
    #: settings, events, HRV, developer fields — is not what a training log
    #: reads, and skipping it keeps a long ride's parse cheap.
    WANTED = ("file_id", "record", "session", "lap", "activity", "sport")

    def _read(self, content: bytes) -> dict[str, list[dict[str, Any]]]:
        """Every wanted message, as plain dictionaries in file order."""
        if not content:
            raise ParserError("File is empty")

        collected: dict[str, list[dict[str, Any]]] = {name: [] for name in self.WANTED}
        try:
            # The default processor, deliberately: see DEGREES_PER_SEMICIRCLE.
            with fitdecode.FitReader(io.BytesIO(content)) as reader:
                for frame in reader:
                    if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                        continue
                    if frame.name not in collected:
                        continue
                    collected[frame.name].append(
                        {field.name: field.value for field in frame.fields}
                    )
        except fitdecode.FitError as exc:
            raise ParserError(f"Malformed FIT file: {exc}") from exc

        return collected

    def _track_points(self, records: list[dict[str, Any]]) -> list[ParsedTrackPoint]:
        """One point per record message that carries a time.

        A record without a position is kept rather than dropped: an indoor ride
        has heart rate and cadence and no GPS, and the traces are still worth
        drawing.
        """
        points: list[ParsedTrackPoint] = []
        for record in records:
            timestamp = record.get("timestamp")
            if not isinstance(timestamp, datetime):
                continue
            points.append(
                ParsedTrackPoint(
                    sequence=len(points),
                    timestamp=timestamp,
                    latitude=self._degrees(record.get("position_lat")),
                    longitude=self._degrees(record.get("position_long")),
                    # enhanced_altitude first: it is the wider-range field, and
                    # a device that writes both agrees between them.
                    elevation=self._number(record.get("enhanced_altitude", record.get("altitude"))),
                    heart_rate=self._whole(record.get("heart_rate")),
                    cadence=self._whole(record.get("cadence")),
                )
            )
        return points

    def _start_time(
        self, session: dict, file_id: dict, points: list[ParsedTrackPoint]
    ) -> datetime | None:
        """The session's own start, then the file's creation, then the samples."""
        for candidate in (session.get("start_time"), file_id.get("time_created")):
            if isinstance(candidate, datetime):
                return candidate
        return points[0].timestamp if points else None

    def _offset_minutes(self, activity: dict) -> int | None:
        """The UTC offset the file stated, from the activity message.

        FIT is the only one of the three formats that says this outright: it
        writes the same instant twice, once as UTC and once as local wall clock,
        and the difference is the offset. fitdecode hands both back tagged UTC,
        so subtracting them gives the offset directly.
        """
        local = activity.get("local_timestamp")
        utc = activity.get("timestamp")
        if not isinstance(local, datetime) or not isinstance(utc, datetime):
            return None
        return int((local - utc).total_seconds() // 60)

    def _sport(self, session: dict, sport_messages: list[dict]) -> str:
        declared = session.get("sport")
        if not declared and sport_messages:
            declared = sport_messages[0].get("sport")
        return sport_from_file("fit", declared)

    def _source(self, file_id: dict) -> str:
        """The manufacturer's name, which is the nearest thing FIT has to a creator.

        fitdecode hands back the raw number when the manufacturer is one it has
        no name for, and "267" is worse than "fit" as a source label — so only
        a name is taken.
        """
        manufacturer = file_id.get("manufacturer")
        if not isinstance(manufacturer, str) or not manufacturer.strip():
            return self.default_source
        return manufacturer.strip().lower()

    @staticmethod
    def _degrees(semicircles: Any) -> float | None:
        if not isinstance(semicircles, int | float):
            return None
        return float(semicircles) * DEGREES_PER_SEMICIRCLE

    @staticmethod
    def _number(value: Any) -> float | None:
        return float(value) if isinstance(value, int | float) else None

    @staticmethod
    def _whole(value: Any) -> int | None:
        return int(round(value)) if isinstance(value, int | float) else None
