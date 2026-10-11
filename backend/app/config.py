"""Application settings, loaded from the environment or a local .env file."""

import json
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Slack allowed on top of max_upload_bytes for multipart framing and headers.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # No default on purpose. A missing DATABASE_URL is a deployment mistake, and
    # a fallback DSN would let the app start and quietly talk to the wrong
    # database — or to a guessable one — instead of failing loudly at boot.
    database_url: str = Field(min_length=1)

    api_prefix: str = "/api"
    # NoDecode because the environment source would otherwise try to JSON-decode
    # this before any validator runs, which fails on both "" and the
    # comma-separated form below. With it, the raw string reaches _split_origins.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    max_upload_bytes: int = 20 * 1024 * 1024

    #: Wall-clock timezone used to bucket activities whose file states no UTC
    #: offset. An IANA name, e.g. "Europe/Rome".
    display_timezone: str = "UTC"

    # Only used by scripts.ensure_user, for headless setups that never open the
    # dashboard. The normal path is the first-run screen asking who you are.
    default_first_name: str = "Athlete"
    default_last_name: str | None = None

    #: Hard ceiling on track points returned in one response.
    max_track_points: int = 20_000

    #: Maximum heart rate for zone boundaries. Left unset, the highest beat any
    #: activity recorded is used instead — which is a floor, not a maximum: a
    #: figure nobody has ever pushed to reads low and makes every zone read
    #: high. Set it if you know yours from a test.
    max_heart_rate: int | None = None

    # A full Garmin or Strava export is a zip of hundreds of files, so it needs
    # a far larger cap than a single activity. XML compresses roughly ten to
    # one, which is also why an archive needs its own guards rather than
    # trusting this number: 200 MiB of zip can claim to be gigabytes of XML.
    max_archive_bytes: int = 200 * 1024 * 1024
    max_archive_members: int = 5_000
    #: Total *declared* uncompressed size across an archive's members.
    max_archive_extracted_bytes: int = 2 * 1024 * 1024 * 1024
    #: Members reported individually in the response; the counts are always exact.
    max_reported_members: int = 200
    #: A running archive import that has not finished a file in this long is
    #: taken to have lost its worker — a backend restart, most likely. One file
    #: takes a second or two, and even one at the size cap well under a minute.
    archive_import_stale_seconds: int = 300

    #: Two activities from the same user starting within this window and sharing
    #: a sport are treated as the same session exported twice.
    duplicate_window_seconds: int = 300

    debug: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so .env stays readable.

        An empty value means no origin needs allowing, which is the normal case:
        the dashboard proxies /api on its own origin.
        """
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("display_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Reject an unknown zone at boot rather than at query time."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value!r}") from exc
        return value

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.display_timezone)

    @property
    def max_request_bytes(self) -> int:
        """Cap for a whole request body: the largest upload plus framing.

        The guard in main.py cannot tell which route a body is heading for, so
        it allows the biggest thing any route accepts. The per-route limits are
        the narrower ones.
        """
        return max(self.max_upload_bytes, self.max_archive_bytes) + MULTIPART_OVERHEAD_BYTES


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
