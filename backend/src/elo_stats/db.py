"""SQLite storage: cached NBA game logs plus the computed Elo tables."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS fetched_seasons (
    season       TEXT NOT NULL,
    season_type  TEXT NOT NULL,
    row_count    INTEGER NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (season, season_type)
);

CREATE TABLE IF NOT EXISTS fetched_games (
    game_id      TEXT PRIMARY KEY,
    season       TEXT NOT NULL,
    season_type  TEXT NOT NULL,
    row_count    INTEGER NOT NULL,
    fetched_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetched_games_season ON fetched_games (season, season_type);

CREATE TABLE IF NOT EXISTS player_games (
    game_id      TEXT NOT NULL,
    player_id    INTEGER NOT NULL,
    player_name  TEXT NOT NULL,
    team_id      INTEGER NOT NULL,
    team_abbr    TEXT NOT NULL,
    season       INTEGER NOT NULL,
    season_type  TEXT NOT NULL,
    game_date    TEXT NOT NULL,
    matchup      TEXT NOT NULL,
    is_home      INTEGER NOT NULL,
    won          INTEGER NOT NULL,
    minutes      REAL NOT NULL,
    pts          INTEGER NOT NULL,
    reb          INTEGER,
    ast          INTEGER,
    plus_minus   INTEGER,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_player_games_date ON player_games (game_date, game_id);

CREATE TABLE IF NOT EXISTS elo_history (
    player_id      INTEGER NOT NULL,
    game_id        TEXT NOT NULL,
    game_date      TEXT NOT NULL,
    season         INTEGER NOT NULL,
    team_abbr      TEXT NOT NULL,
    opponent_abbr  TEXT NOT NULL,
    won            INTEGER NOT NULL,
    rating_before  REAL NOT NULL,
    rating_after   REAL NOT NULL,
    PRIMARY KEY (player_id, game_id)
);
CREATE INDEX IF NOT EXISTS idx_elo_history_player_date ON elo_history (player_id, game_date);

CREATE TABLE IF NOT EXISTS player_ratings (
    player_id       INTEGER PRIMARY KEY,
    player_name     TEXT NOT NULL,
    search_name     TEXT NOT NULL,
    rating          REAL NOT NULL,
    peak_rating     REAL NOT NULL,
    peak_date       TEXT NOT NULL,
    games           INTEGER NOT NULL,
    first_game_date TEXT NOT NULL,
    last_game_date  TEXT NOT NULL,
    last_season     INTEGER NOT NULL,
    team_abbr       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_player_ratings_rating ON player_ratings (rating DESC);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key   TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may open, use and close a request's connection on different threadpool threads.
    # Each connection is used by one request at a time, so disabling the thread check is safe.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()
