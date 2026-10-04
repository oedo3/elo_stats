"""Read queries over the Elo tables plus a small JSON cache for upstream API responses."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from elo_stats.text import normalize_name

logger = logging.getLogger(__name__)

LeaderboardSort = Literal["current", "peak"]


def has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM player_ratings LIMIT 1").fetchone() is not None


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def latest_season(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(last_season) FROM player_ratings").fetchone()
    return row[0]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_players(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    needle = _escape_like(normalize_name(query))
    rows = conn.execute(
        r"""
        SELECT player_id, player_name, rating, peak_rating, games, team_abbr,
               first_game_date, last_game_date, last_season
        FROM player_ratings
        WHERE search_name LIKE ? ESCAPE '\'
        ORDER BY
            CASE WHEN search_name LIKE ? ESCAPE '\' THEN 0 ELSE 1 END,
            games DESC
        LIMIT ?
        """,
        (f"%{needle}%", f"{needle}%", limit),
    )
    return [dict(r) for r in rows]


def player_exists(conn: sqlite3.Connection, player_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM player_ratings WHERE player_id = ?", (player_id,))
    return row.fetchone() is not None


def get_player(conn: sqlite3.Connection, player_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM player_ratings WHERE player_id = ?", (player_id,)).fetchone()
    if row is None:
        return None
    player = dict(row)
    player.pop("search_name", None)
    current = latest_season(conn)
    player["is_active"] = player["last_season"] == current
    player["active_rank"] = (
        conn.execute(
            "SELECT COUNT(*) + 1 FROM player_ratings WHERE last_season = ? AND rating > ?",
            (current, player["rating"]),
        ).fetchone()[0]
        if player["is_active"]
        else None
    )
    player["peak_rank"] = conn.execute(
        "SELECT COUNT(*) + 1 FROM player_ratings WHERE peak_rating > ?", (player["peak_rating"],)
    ).fetchone()[0]
    return player


def get_elo_history(conn: sqlite3.Connection, player_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT game_id, game_date, season, team_abbr, opponent_abbr, won,
               rating_before, rating_after
        FROM elo_history
        WHERE player_id = ?
        ORDER BY game_date, game_id
        """,
        (player_id,),
    )
    return [{**dict(r), "won": bool(r["won"])} for r in rows]


def leaderboard(
    conn: sqlite3.Connection,
    *,
    sort: LeaderboardSort,
    active_only: bool,
    min_games: int,
    limit: int,
) -> list[dict[str, Any]]:
    order_column = "rating" if sort == "current" else "peak_rating"
    where = ["games >= ?"]
    params: list[Any] = [min_games]
    if active_only:
        where.append("last_season = ?")
        params.append(latest_season(conn))
    rows = conn.execute(
        f"""
        SELECT player_id, player_name, rating, peak_rating, peak_date, games, team_abbr,
               first_game_date, last_game_date, last_season
        FROM player_ratings
        WHERE {" AND ".join(where)}
        ORDER BY {order_column} DESC, player_id
        LIMIT ?
        """,  # noqa: S608 - order_column comes from a Literal, never from user text
        (*params, limit),
    )
    return [{**dict(r), "rank": i} for i, r in enumerate(rows, start=1)]


def cache_get(conn: sqlite3.Connection, key: str, max_age: timedelta) -> Any | None:
    row = conn.execute(
        "SELECT payload, fetched_at FROM api_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    if datetime.now(UTC) - datetime.fromisoformat(row["fetched_at"]) > max_age:
        return None
    return json.loads(row["payload"])


def cache_put(conn: sqlite3.Connection, key: str, payload: Any) -> None:
    """Best effort: a busy database (e.g. during an Elo recompute) must not fail the request."""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)",
            (key, json.dumps(payload), datetime.now(UTC).isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.OperationalError as exc:
        logger.warning("Could not cache %s: %s", key, exc)
