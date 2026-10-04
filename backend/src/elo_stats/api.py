"""FastAPI application.

Run from ``backend/`` with ``uvicorn elo_stats.api:create_app --factory --reload``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from elo_stats import repository, services
from elo_stats.config import Settings, load_settings
from elo_stats.db import connect, init_schema
from elo_stats.nba_client import NbaApiError, NbaClient, NbaStatsClient
from elo_stats.ratelimit import RateLimiter
from elo_stats.schemas import (
    ApiResponse,
    EloPoint,
    Health,
    LeaderboardEntry,
    Meta,
    PlayerBio,
    PlayerCareer,
    PlayerRating,
    PlayerSearchResult,
)
from elo_stats.text import normalize_name

logger = logging.getLogger("elo_stats.api")

NO_DATA_MESSAGE = "No Elo data yet. Run `python -m elo_stats.ingest` in the backend folder."
PlayerId = Annotated[int, Path(ge=1, le=99_999_999)]


def _error(status: int, message: str) -> JSONResponse:
    body = ApiResponse[None](success=False, error=message).model_dump()
    return JSONResponse(status_code=status, content=body)


def create_app(settings: Settings | None = None, client: NbaClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="ELO Stats API", version="0.2.0")
    app.state.settings = settings
    # Interactive requests get fewer retries than ingestion so a slow upstream fails fast.
    app.state.client = client or NbaStatsClient(timeout=settings.nba_timeout_seconds, max_retries=2)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)

    conn = connect(settings.db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            client_key = request.client.host if request.client else "unknown"
            if not request.app.state.limiter.allow(client_key):
                return _error(429, "Too many requests. Please slow down.")
        return await call_next(request)

    # Added last so it is the outermost middleware and 429 responses also carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()
        )
        return _error(422, f"Invalid request - {problems}")

    @app.exception_handler(NbaApiError)
    async def upstream_error(_request: Request, exc: NbaApiError) -> JSONResponse:
        logger.warning("Upstream NBA stats error: %s", exc)
        return _error(502, "NBA stats service is unavailable right now. Try again shortly.")

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "Something went wrong on our side.")

    _register_routes(app)
    return app


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _require_data(conn: sqlite3.Connection) -> None:
    if not repository.has_data(conn):
        raise HTTPException(status_code=503, detail=NO_DATA_MESSAGE)


def _require_rated_player(conn: sqlite3.Connection, player_id: int) -> None:
    """Only players we rate may trigger upstream calls, which bounds cache growth and load."""
    _require_data(conn)
    if not repository.player_exists(conn, player_id):
        raise HTTPException(status_code=404, detail="Player not found.")


def _cache_ttl(request: Request) -> timedelta:
    return timedelta(hours=request.app.state.settings.cache_ttl_hours)


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health", response_model=ApiResponse[Health])
    def health(conn: Conn) -> ApiResponse[Health]:
        return ApiResponse(data=Health(status="ok", has_data=repository.has_data(conn)))

    @app.get("/api/meta", response_model=ApiResponse[Meta])
    def meta(conn: Conn) -> ApiResponse[Meta]:
        raw = repository.get_meta(conn)
        data: dict[str, Any] = {"has_data": repository.has_data(conn)}
        for key in ("first_season", "last_season"):
            if raw.get(key):
                data[key] = int(raw[key])
        for key in ("last_game_date", "computed_at"):
            if raw.get(key):
                data[key] = raw[key]
        for key in ("elo_params", "missing_seasons"):
            if raw.get(key):
                data[key] = json.loads(raw[key])
        return ApiResponse(data=Meta(**data))

    @app.get("/api/players/search", response_model=ApiResponse[list[PlayerSearchResult]])
    def search(
        conn: Conn,
        q: Annotated[str, Query(min_length=2, max_length=60)],
        limit: Annotated[int, Query(ge=1, le=25)] = 10,
    ) -> ApiResponse[list[PlayerSearchResult]]:
        _require_data(conn)
        if len(normalize_name(q)) < 2:
            raise HTTPException(status_code=422, detail="Invalid request - q: too short")
        rows = repository.search_players(conn, q, limit)
        return ApiResponse(data=[PlayerSearchResult(**r) for r in rows])

    @app.get("/api/players/{player_id}", response_model=ApiResponse[PlayerRating])
    def player(conn: Conn, player_id: PlayerId) -> ApiResponse[PlayerRating]:
        _require_data(conn)
        row = repository.get_player(conn, player_id)
        if row is None:
            raise HTTPException(status_code=404, detail="No Elo rating for that player.")
        return ApiResponse(data=PlayerRating(**row))

    @app.get("/api/players/{player_id}/elo", response_model=ApiResponse[list[EloPoint]])
    def elo_history(conn: Conn, player_id: PlayerId) -> ApiResponse[list[EloPoint]]:
        _require_data(conn)
        history = repository.get_elo_history(conn, player_id)
        if not history:
            raise HTTPException(status_code=404, detail="No Elo history for that player.")
        return ApiResponse(data=[EloPoint(**h) for h in history], meta={"total": len(history)})

    @app.get("/api/players/{player_id}/bio", response_model=ApiResponse[PlayerBio])
    def bio(request: Request, conn: Conn, player_id: PlayerId) -> ApiResponse[PlayerBio]:
        _require_rated_player(conn, player_id)
        try:
            data = services.get_player_bio(
                conn, request.app.state.client, player_id, _cache_ttl(request)
            )
        except services.PlayerNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Player not found.") from exc
        return ApiResponse(data=PlayerBio(**data))

    @app.get("/api/players/{player_id}/career", response_model=ApiResponse[PlayerCareer])
    def career(request: Request, conn: Conn, player_id: PlayerId) -> ApiResponse[PlayerCareer]:
        _require_rated_player(conn, player_id)
        data = services.get_player_career(
            conn, request.app.state.client, player_id, _cache_ttl(request)
        )
        return ApiResponse(data=PlayerCareer(**data))

    @app.get("/api/leaderboard", response_model=ApiResponse[list[LeaderboardEntry]])
    def leaderboard(
        conn: Conn,
        sort: Annotated[repository.LeaderboardSort, Query()] = "current",
        active_only: bool = True,
        min_games: Annotated[int, Query(ge=0, le=2000)] = 82,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> ApiResponse[list[LeaderboardEntry]]:
        _require_data(conn)
        rows = repository.leaderboard(
            conn, sort=sort, active_only=active_only, min_games=min_games, limit=limit
        )
        return ApiResponse(data=[LeaderboardEntry(**r) for r in rows])
