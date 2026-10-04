"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from elo_stats.elo import EloParams

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BACKEND_ROOT / "data" / "elo_stats.sqlite3"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

# 1996-97 is the first season where stats.nba.com player game logs carry reliable minutes.
FIRST_SEASON = 1996
SEASON_TYPES = ("Regular Season", "Playoffs")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    cors_origins: tuple[str, ...]
    cache_ttl_hours: int
    rate_limit_per_minute: int
    nba_timeout_seconds: int
    elo: EloParams


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def load_settings() -> Settings:
    origins = os.environ.get("ELO_STATS_CORS_ORIGINS")
    return Settings(
        db_path=Path(os.environ.get("ELO_STATS_DB", DEFAULT_DB_PATH)),
        cors_origins=(
            tuple(o.strip() for o in origins.split(",") if o.strip())
            if origins
            else DEFAULT_CORS_ORIGINS
        ),
        cache_ttl_hours=_int_env("ELO_STATS_CACHE_TTL_HOURS", 24),
        rate_limit_per_minute=_int_env("ELO_STATS_RATE_LIMIT_PER_MINUTE", 120),
        nba_timeout_seconds=_int_env("ELO_STATS_NBA_TIMEOUT", 60),
        elo=EloParams(),
    )
