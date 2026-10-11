"""A minimal FIT writer, so the FIT parser can be tested against real bytes.

FIT is binary, so there is no way to write a fixture by hand the way a TCX or a
GPX one is written. Encoding the handful of message types the parser reads is
cheaper than vendoring sample files from a device — and it means a test can
build the awkward case on purpose rather than hoping a donated file contains it.

Only what the parser needs is here: a 12-byte header, definition and data
messages for one local type at a time, and the FIT CRC. No compressed
timestamps, no developer fields, no multi-byte arrays.

The layout follows the FIT file format: a header naming the payload size, then
records, then a CRC over everything before it. Each record is either a
*definition* — which fields follow, in which order, at which width — or the
*data* matching the definition most recently given for its local type.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta

#: FIT counts seconds from this instant, not from the Unix epoch.
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=UTC)

# FIT base types, as (identifier, struct code, width).
ENUM = (0x00, "B", 1)
UINT8 = (0x02, "B", 1)
UINT16 = (0x84, "H", 2)
UINT32 = (0x86, "I", 4)
SINT32 = (0x85, "i", 4)

# Global message numbers.
FILE_ID, RECORD, SESSION, LAP, ACTIVITY, SPORT = 0, 20, 18, 19, 34, 12

#: The nibble-wise CRC table from the FIT specification.
CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip


def fit_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        for _ in range(2):
            carry = CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ carry ^ CRC_TABLE[byte & 0xF]
            byte >>= 4
    return crc


def fit_time(moment: datetime) -> int:
    return int((moment - FIT_EPOCH).total_seconds())


def semicircles(degrees: float) -> int:
    """Degrees to the signed count FIT stores positions as."""
    return int(degrees * (2**31) / 180)


def altitude(metres: float) -> int:
    """Metres to FIT's stored altitude: scaled by 5, offset by 500."""
    return int(round((metres + 500) * 5))


class FitBuilder:
    """Accumulates messages, then emits a complete FIT file."""

    def __init__(self) -> None:
        self._body = bytearray()
        self._defined: dict[int, tuple] = {}

    def message(self, local: int, global_number: int, fields: list[tuple]) -> FitBuilder:
        """Append one message. `fields` is a list of (field number, type, value).

        A definition record is emitted only when this local type's shape changes,
        which is how a real file avoids repeating the definition for every one of
        several thousand records.
        """
        shape = tuple((number, base) for number, base, _ in fields)
        if self._defined.get(local) != shape:
            self._defined[local] = shape
            self._body.append(0x40 | local)
            self._body += struct.pack("<BBHB", 0, 0, global_number, len(fields))
            for number, base, _ in fields:
                identifier, _code, width = base
                self._body += struct.pack("<BBB", number, width, identifier)

        self._body.append(local)
        for _number, base, value in fields:
            _identifier, code, _width = base
            self._body += struct.pack("<" + code, value)
        return self

    def build(self) -> bytes:
        header = struct.pack("<BBHI4s", 12, 0x20, 2140, len(self._body), b".FIT")
        whole = header + bytes(self._body)
        return whole + struct.pack("<H", fit_crc(whole))


def ride(
    start: datetime,
    *,
    points: int = 3,
    sport: int = 2,
    sub_sport: int | None = None,
    with_position: bool = True,
    with_heart_rate: bool = True,
    local_offset_hours: int | None = 2,
    session_totals: bool = True,
    manufacturer: int = 1,
) -> bytes:
    """A small but complete activity file, with the awkward parts switchable.

    `sport` is FIT's own enum: 1 running, 2 cycling, 10 training, 11 walking,
    17 hiking. `sub_sport` likewise: 20 is strength training.
    """
    builder = FitBuilder()
    builder.message(
        0,
        FILE_ID,
        [(0, ENUM, 4), (1, UINT16, manufacturer), (4, UINT32, fit_time(start))],
    )

    for index in range(points):
        when = start + timedelta(seconds=10 * index)
        fields = [(253, UINT32, fit_time(when))]
        if with_position:
            fields += [
                (0, SINT32, semicircles(45.0 + index * 0.001)),
                (1, SINT32, semicircles(7.0)),
            ]
        fields.append((2, UINT16, altitude(100.0 + index)))
        if with_heart_rate:
            fields.append((3, UINT8, 140 + index))
        fields.append((4, UINT8, 85))
        builder.message(1, RECORD, fields)

    last = start + timedelta(seconds=10 * max(points - 1, 0))
    sport_fields = [(5, ENUM, sport)]
    if sub_sport is not None:
        sport_fields.append((6, ENUM, sub_sport))
    if session_totals:
        builder.message(
            3,
            SESSION,
            [
                (253, UINT32, fit_time(last)),
                (2, UINT32, fit_time(start)),
                *sport_fields,
                # Deliberately unlike the samples, which span 20 seconds: the
                # parser is supposed to take the device's figure, not derive one.
                (8, UINT32, 1_800_000),  # total_timer_time: 1800 s, scaled by 1000
                (9, UINT32, 1_234_000),  # total_distance: 12340 m, scaled by 100
                (16, UINT8, 141),  # avg_heart_rate
                (17, UINT8, 152),  # max_heart_rate
                (18, UINT8, 85),  # avg_cadence
                (22, UINT16, 210),  # total_ascent
                (23, UINT16, 190),  # total_descent
            ],
        )
    else:
        builder.message(3, SESSION, [(253, UINT32, fit_time(last)), *sport_fields])

    activity_fields = [(253, UINT32, fit_time(last))]
    if local_offset_hours is not None:
        activity_fields.append((5, UINT32, fit_time(last) + local_offset_hours * 3600))
    builder.message(4, ACTIVITY, activity_fields)
    return builder.build()
