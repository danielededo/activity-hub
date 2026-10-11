"""Reading activity files out of a zip without trusting the zip.

An archive from a user is hostile input. The guards here are for the three ways
that goes wrong:

* **Zip bombs** — a small archive claiming gigabytes. Both the declared total
  and each member are capped, and every read is bounded, so a lying header
  cannot turn into memory use either.
* **Member floods** — an archive with a hundred thousand entries.
* **Nested archives** — refused rather than recursed into.

Path traversal is absent by construction: members are read into memory with
`ZipFile.open`, never extracted to disk, so there is no path to traverse.
"""

from __future__ import annotations

import gzip
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO

#: What we recognise inside an archive. Anything else is reported as skipped:
#: a real export is full of CSVs and images, which is not an error.
#:
#: Keep this in step with the parsers. While `.fit` was missing here, a Garmin
#: bulk export — which keeps every activity in the format it was uploaded in,
#: and that is FIT for anything off a Garmin watch — reported stored=0 and
#: skipped=800 and looked like it had worked.
ACTIVITY_SUFFIXES = (".tcx", ".gpx", ".fit")

#: Named in the skipped reason, so the message cannot drift from the tuple.
SUFFIX_LIST = ", ".join(ACTIVITY_SUFFIXES)

ZIP_MAGIC = b"PK\x03\x04"
READ_CHUNK = 64 * 1024


class ArchiveError(ValueError):
    """The archive itself cannot be read."""


@dataclass(slots=True)
class ArchiveMember:
    """One file lifted out of an archive."""

    name: str
    content: bytes | None
    #: Set when the member was not usable; content is None then.
    skipped: str | None = None

    @property
    def usable(self) -> bool:
        return self.content is not None


def looks_like_zip(filename: str | None, content: bytes) -> bool:
    """Whether to treat this upload as an archive.

    The magic number decides, not the extension: a mislabelled `.gpx` that is
    really a zip should be handled, and vice versa.
    """
    if content[:4] == ZIP_MAGIC:
        return True
    return bool(filename) and filename.lower().endswith(".zip")


def _activity_name(name: str) -> str | None:
    """The activity suffix a member has, allowing for a gzip wrapper."""
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    for suffix in ACTIVITY_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    return None


def _read_bounded(handle, limit: int) -> bytes | None:
    """Read at most `limit` bytes, or None if there are more than that."""
    chunks: list[bytes] = []
    total = 0
    while chunk := handle.read(READ_CHUNK):
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _open(content: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Not a readable zip archive: {exc}") from exc


def _checked_entries(
    archive: zipfile.ZipFile, *, max_members: int, max_extracted_bytes: int
) -> list[zipfile.ZipInfo]:
    """The archive's files, or ArchiveError if the archive as a whole is refused."""
    entries = [info for info in archive.infolist() if not info.is_dir()]

    if len(entries) > max_members:
        raise ArchiveError(
            f"Archive holds {len(entries)} files, more than the {max_members} allowed"
        )

    declared = sum(info.file_size for info in entries)
    if declared > max_extracted_bytes:
        # Checked before reading anything: this is the zip-bomb signature.
        raise ArchiveError(
            f"Archive claims {declared} bytes uncompressed, "
            f"more than the {max_extracted_bytes} allowed"
        )
    return entries


def check_archive(content: bytes, *, max_members: int, max_extracted_bytes: int) -> int:
    """How many files `content` holds, or ArchiveError if it would be refused.

    Reads only the central directory, so it is cheap enough to answer while the
    upload request is still open — which is when a refusal is worth something.
    """
    with _open(content) as archive:
        return len(
            _checked_entries(
                archive, max_members=max_members, max_extracted_bytes=max_extracted_bytes
            )
        )


def read_archive(
    content: bytes,
    *,
    max_members: int,
    max_extracted_bytes: int,
    max_member_bytes: int,
) -> Iterator[ArchiveMember]:
    """Yield the activity files in `content`, one at a time.

    Yields a member per candidate entry, including ones that were skipped and
    why, so the caller can report an honest per-file outcome. Raises
    ArchiveError only when the archive as a whole is unusable.
    """
    with _open(content) as archive:
        entries = _checked_entries(
            archive, max_members=max_members, max_extracted_bytes=max_extracted_bytes
        )

        for info in entries:
            name = info.filename
            if name.lower().endswith(".zip"):
                yield ArchiveMember(name, None, "nested archives are not unpacked")
                continue
            if _activity_name(name) is None:
                yield ArchiveMember(name, None, f"not one of {SUFFIX_LIST}")
                continue
            if info.file_size > max_member_bytes:
                yield ArchiveMember(name, None, f"larger than the {max_member_bytes} byte limit")
                continue

            try:
                with archive.open(info) as handle:
                    raw = _read_bounded(handle, max_member_bytes)
            except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
                # RuntimeError is what zipfile raises for an encrypted member.
                yield ArchiveMember(name, None, f"could not be read: {exc}")
                continue

            if raw is None:
                # The header understated the size; the bounded read caught it.
                yield ArchiveMember(name, None, "larger than its header claimed")
                continue

            if name.lower().endswith(".gz"):
                try:
                    with gzip.GzipFile(fileobj=BytesIO(raw)) as gz:
                        raw = _read_bounded(gz, max_member_bytes)
                except (OSError, EOFError) as exc:
                    yield ArchiveMember(name, None, f"could not be decompressed: {exc}")
                    continue
                if raw is None:
                    yield ArchiveMember(name, None, "expands past the size limit")
                    continue

            yield ArchiveMember(name, raw)
