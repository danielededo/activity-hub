"""Configuration guards and upload size limits."""

import inspect
import io
import re
from pathlib import Path

import pytest
from fastapi import UploadFile
from pydantic import ValidationError

from app.config import MULTIPART_OVERHEAD_BYTES, Settings, settings
from app.routers.upload import upload_workout
from app.services.uploads import (
    EmptyUploadError,
    UploadTooLargeError,
    read_upload,
)


def make_upload(content: bytes, *, declared_size: int | None = None) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        size=len(content) if declared_size is None else declared_size,
        filename="ride.gpx",
    )


# -- configuration -------------------------------------------------------


def test_settings_require_a_database_url(monkeypatch):
    """A missing DATABASE_URL must fail at boot, not fall back to a default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_accept_an_explicit_database_url():
    assert Settings(_env_file=None, database_url="sqlite://").database_url == "sqlite://"


def test_max_request_bytes_allows_for_multipart_framing():
    """The guard cannot know the route, so it allows the largest upload.

    An archive is far bigger than a single activity, and the request-level guard
    runs before routing, so it has to be the more generous of the two. The
    narrower per-route limits are enforced in the routes themselves.
    """
    expected = max(settings.max_upload_bytes, settings.max_archive_bytes)

    assert settings.max_request_bytes == expected + MULTIPART_OVERHEAD_BYTES


def test_the_archive_cap_is_the_one_that_dominates():
    parsed = Settings(
        _env_file=None,
        database_url="sqlite://",
        max_upload_bytes=1_000,
        max_archive_bytes=50_000,
    )

    assert parsed.max_request_bytes == 50_000 + MULTIPART_OVERHEAD_BYTES


NGINX_CONF = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"
NGINX_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


@pytest.mark.skipif(not NGINX_CONF.exists(), reason="needs the whole repository")
def test_the_proxy_admits_the_largest_body_the_api_accepts():
    """nginx sits in front of the API, so its cap has to be the looser one.

    Below the API's, a full export archive is refused by nginx with an HTML
    page before FastAPI sees it — which is how a 24m cap once stopped every
    archive over 24 MiB while the API was ready to take 200.
    """
    match = re.search(r"client_max_body_size\s+(\d+)([kmg]?);", NGINX_CONF.read_text(), re.I)
    assert match, "nginx.conf no longer sets client_max_body_size"
    proxy_limit = int(match[1]) * NGINX_UNITS[match[2].lower()]
    defaults = Settings(_env_file=None, database_url="sqlite://")

    assert proxy_limit >= defaults.max_request_bytes


def test_cors_origins_accept_a_comma_separated_string():
    parsed = Settings(_env_file=None, database_url="sqlite://", cors_origins="http://a,http://b")

    assert parsed.cors_origins == ["http://a", "http://b"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("http://a,http://b", ["http://a", "http://b"]),
        ("  http://a , , http://b ", ["http://a", "http://b"]),
        ('["http://a"]', ["http://a"]),
    ],
)
def test_cors_origins_from_the_environment(monkeypatch, raw, expected):
    """The environment source must not try to JSON-decode this first.

    It did, which meant CORS_ORIGINS failed for every value an operator would
    plausibly write — the empty string a compose file passes through, and the
    comma-separated form the .env.example documents.
    """
    monkeypatch.setenv("CORS_ORIGINS", raw)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")

    assert Settings(_env_file=None).cors_origins == expected


# -- the upload reader ---------------------------------------------------


def test_read_upload_returns_the_content():
    assert read_upload(make_upload(b"<gpx/>"), limit=1024) == b"<gpx/>"


def test_read_upload_rejects_content_over_the_limit():
    with pytest.raises(UploadTooLargeError):
        read_upload(make_upload(b"x" * 200), limit=100)


def test_read_upload_rejects_an_understated_size():
    """The chunked read is the backstop when the declared size lies."""
    upload = make_upload(b"x" * 500, declared_size=1)

    with pytest.raises(UploadTooLargeError):
        read_upload(upload, limit=100)


def test_read_upload_rejects_an_overstated_size_without_reading():
    with pytest.raises(UploadTooLargeError):
        read_upload(make_upload(b"x", declared_size=10_000), limit=100)


def test_read_upload_rejects_an_empty_file():
    with pytest.raises(EmptyUploadError):
        read_upload(make_upload(b""), limit=100)


def test_read_upload_accepts_content_exactly_at_the_limit():
    assert read_upload(make_upload(b"x" * 100), limit=100) == b"x" * 100


# -- the request-level guard --------------------------------------------


def test_oversized_body_is_rejected_before_it_is_parsed(client, monkeypatch):
    """The guard must fire on Content-Length, before multipart spools the body."""
    # Both caps, or max_request_bytes stays at the archive limit and this test
    # would build a 200 MiB body to prove a one-line comparison.
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    monkeypatch.setattr(settings, "max_archive_bytes", 1024)
    oversized = b"x" * (settings.max_request_bytes + 1)

    response = client.post(
        "/api/upload?user_id=1", files={"file": ("big.gpx", oversized, "application/xml")}
    )

    assert response.status_code == 413
    assert "Request body exceeds" in response.json()["detail"]


def test_a_normal_body_passes_the_guard(client, user, sample_gpx):
    response = client.post(
        f"/api/upload?user_id={user['id']}",
        files={"file": ("run.gpx", sample_gpx, "application/xml")},
    )

    assert response.status_code == 201


# -- event loop safety ---------------------------------------------------


def test_the_upload_route_is_synchronous():
    """An async route would run parsing and DB writes on the event loop.

    Both block, so a large upload would stall every other request. FastAPI
    hands sync routes to a threadpool instead — keep this one sync.
    """
    assert not inspect.iscoroutinefunction(upload_workout)
