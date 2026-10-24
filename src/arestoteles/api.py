"""The HTTP routes (docs/API.md). Caddy forwards /api/arestoteles/* to 127.0.0.1:8099 keeping the path."""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .auth import Access
from .edits import EditError
from .models import EDIT
from .service import NotReady, VaultService
from .texts import Text, language, text

PREFIX = "/api/arestoteles"
_BEARER = re.compile(r"Bearer\s+(\S+)", re.I)
QUERY_LENGTH = 200           # GET /search: q is 1–200 characters after trimming
LIMITS, DEFAULT_LIMIT = range(1, 31), 12


class ApiError(Exception):
    def __init__(self, status: int, key: str, extra: dict | None = None, **values: object):
        super().__init__(key)
        self.status, self.key, self.extra, self.values = status, key, extra or {}, values


def bearer(header: str | None) -> str:
    match = _BEARER.fullmatch((header or "").strip())
    return match[1] if match else ""


def _whole(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isascii() and value.isdigit() else None


def _json(data: object, status: int = 200, headers: dict | None = None) -> Response:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return Response(body, status_code=status, media_type="application/json", headers=headers)


# Bumped whenever the index's shape changes (a new field), so phones holding the same vault commit fetch it again.
INDEX_SHAPE = "2"


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    tags = [t.strip() for t in header.split(",")]
    return "*" in tags or any(t.removeprefix("W/") == etag for t in tags)


def create_app(service: VaultService, run_loops: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop = service.start_loop() if run_loops else None
        yield
        if loop is not None:
            loop.stop()

    app = FastAPI(title="Arestoteles", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)

    @app.middleware("http")
    async def request_language(request: Request, call_next):
        request.state.language = language(request.headers.get("accept-language"))
        response = await call_next(request)
        response.headers["Content-Language"] = request.state.language
        vary = response.headers.get("Vary", "")
        if "accept-language" not in {v.strip().lower() for v in vary.split(",")}:
            response.headers["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> Response:
        message = text(exc.key, **exc.values).get(request.state.language)
        return _json({"error": message, **exc.extra}, exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        key = "unknown_route" if exc.status_code in (404, 405) else "bad_request"
        return _json({"error": text(key).get(request.state.language)}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> Response:
        return _json({"error": text("bad_request").get(request.state.language)}, 400)

    def app_user(authorization: str | None = Header(default=None)) -> Access:
        access = service.auth.check(bearer(authorization))
        if not access.allowed:
            raise ApiError(access.status, access.error)
        return access

    def built():
        try:
            return service.current()
        except NotReady:
            raise ApiError(503, "not_ready") from None

    router = APIRouter(prefix=PREFIX)

    @router.get("/health")
    def health() -> Response:
        return _json(service.health())

    @router.get("/vault")
    def vault(if_none_match: str | None = Header(default=None), _: Access = Depends(app_user)) -> Response:
        current = built()
        etag = f'"{current.commit}-{INDEX_SHAPE}"'
        if _etag_matches(if_none_match, etag):
            return Response(status_code=304, headers={"ETag": etag})
        return Response(current.body, media_type="application/json", headers={"ETag": etag})

    @router.get("/notes/{note_id}/source")
    def source(note_id: str, _: Access = Depends(app_user)) -> Response:
        built()
        data = service.source(note_id)
        if data is None:
            raise ApiError(404, "unknown_note")
        return _json(data)

    @router.get("/search")
    def search(q: str | None = None, limit: str | None = None, _: Access = Depends(app_user)) -> Response:
        built()
        query = (q or "").strip()
        if not 1 <= len(query) <= QUERY_LENGTH:
            raise ApiError(400, "bad_query")
        count = DEFAULT_LIMIT if limit is None else _whole(limit)
        if count not in LIMITS:
            raise ApiError(400, "bad_limit")
        try:
            return _json(service.search.query(query, count))
        except LookupError:
            raise ApiError(503, "not_ready") from None

    @router.post("/edits")
    def edit(request: Request, payload: dict = Body(...), _: Access = Depends(app_user)) -> Response:
        try:
            parsed = EDIT.validate_python(payload)
        except ValidationError:
            raise ApiError(400, "bad_request") from None
        try:
            outcome = service.edit(parsed.model_dump())
        except NotReady:
            raise ApiError(503, "not_ready") from None
        except EditError as e:
            extra = {}
            if e.status == 409:
                current = service.built.notes.get(e.current) if service.built and e.current else None
                extra = {"current": current}
            raise ApiError(e.status, e.key, extra, **e.values) from None
        language_ = request.state.language
        warnings = [w.get(language_) if isinstance(w, Text) else w for w in outcome.warnings]
        return _json({"vault": outcome.built.vault, "changed": outcome.changed, "pushed": outcome.pushed,
                      "warnings": warnings})

    app.include_router(router)
    return app
