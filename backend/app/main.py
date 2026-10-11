"""FastAPI application entrypoint."""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import analysis, exports, health, sports, upload, users, workouts
from app.services.parsers import ParserError

app = FastAPI(
    title="Activity Hub API",
    description="Self-hosted fitness aggregator: upload TCX/GPX files and query your training.",
    version="0.1.0",
)

BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


@app.middleware("http")
async def reject_oversized_bodies(request: Request, call_next):  # noqa: ANN001, ANN201
    """Refuse a too-large body before anything parses or spools it.

    Without this the multipart parser writes the whole upload to a temporary
    file first, and the size limit in the route only gets to complain
    afterwards — so a hostile client could fill the disk regardless of the cap.
    """
    if request.method in BODY_METHODS:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": f"Request body exceeds {settings.max_request_bytes} bytes"},
            )
    return await call_next(request)


# Added after the guard above, which puts CORS on the outside: a rejected
# upload still comes back with CORS headers, so the browser reports the 413
# instead of a misleading cross-origin error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, sports, users, workouts, upload, analysis, exports):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.exception_handler(ParserError)
async def parser_error_handler(_: Request, exc: ParserError) -> JSONResponse:
    """A file we cannot read is a client error, not a 500."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "Activity Hub API", "docs": "/docs", "api": settings.api_prefix}
