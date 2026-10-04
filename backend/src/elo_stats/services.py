"""Player bio and career stats: fetched live from stats.nba.com, shaped, and cached in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from elo_stats import repository
from elo_stats.nba_client import NbaClient, Row


class PlayerNotFoundError(LookupError):
    pass


def get_player_bio(
    conn: sqlite3.Connection, client: NbaClient, player_id: int, ttl: timedelta
) -> dict[str, Any]:
    key = f"bio:{player_id}"
    cached = repository.cache_get(conn, key, ttl)
    if cached is not None:
        return cached
    rows = client.player_info(player_id).get("CommonPlayerInfo", [])
    if not rows:
        raise PlayerNotFoundError(player_id)
    bio = shape_bio(rows[0])
    repository.cache_put(conn, key, bio)
    return bio


def get_player_career(
    conn: sqlite3.Connection, client: NbaClient, player_id: int, ttl: timedelta
) -> dict[str, Any]:
    key = f"career:{player_id}"
    cached = repository.cache_get(conn, key, ttl)
    if cached is not None:
        return cached
    sets = client.player_career(player_id)
    career = {
        "regular_season": shape_split(
            sets.get("SeasonTotalsRegularSeason", []), sets.get("CareerTotalsRegularSeason", [])
        ),
        "playoffs": shape_split(
            sets.get("SeasonTotalsPostSeason", []), sets.get("CareerTotalsPostSeason", [])
        ),
    }
    repository.cache_put(conn, key, career)
    return career


def _blank_to_none(value: Any) -> Any:
    return None if value in ("", " ", None) else value


def shape_bio(row: Row) -> dict[str, Any]:
    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    birthdate = _blank_to_none(row.get("BIRTHDATE"))
    return {
        "player_id": row.get("PERSON_ID"),
        "name": row.get("DISPLAY_FIRST_LAST"),
        "position": _blank_to_none(row.get("POSITION")),
        "height": _blank_to_none(row.get("HEIGHT")),
        "weight": as_int(row.get("WEIGHT")),
        "jersey": _blank_to_none(row.get("JERSEY")),
        "birthdate": birthdate[:10] if birthdate else None,
        "country": _blank_to_none(row.get("COUNTRY")),
        "school": _blank_to_none(row.get("SCHOOL")),
        "team_name": _blank_to_none(
            " ".join(p for p in (row.get("TEAM_CITY"), row.get("TEAM_NAME")) if p)
        ),
        "team_abbr": _blank_to_none(row.get("TEAM_ABBREVIATION")),
        "draft_year": as_int(row.get("DRAFT_YEAR")),
        "draft_round": as_int(row.get("DRAFT_ROUND")),
        "draft_number": as_int(row.get("DRAFT_NUMBER")),
        "from_year": as_int(row.get("FROM_YEAR")),
        "to_year": as_int(row.get("TO_YEAR")),
        "seasons": as_int(row.get("SEASON_EXP")),
        "is_active": row.get("ROSTERSTATUS") == "Active",
        "greatest_75": row.get("GREATEST_75_FLAG") == "Y",
    }


def _ratio(numerator: float, denominator: float, digits: int = 3) -> float | None:
    return round(numerator / denominator, digits) if denominator else None


def shape_stat_line(row: Row) -> dict[str, Any]:
    """Turn a season/career totals row into per-game averages plus shooting efficiency."""
    gp = row.get("GP") or 0
    totals = {k: row.get(k) or 0 for k in ("MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV")}
    fgm, fga = row.get("FGM") or 0, row.get("FGA") or 0
    fg3m, fta = row.get("FG3M") or 0, row.get("FTA") or 0
    return {
        "season": row.get("SEASON_ID") or "Career",
        "team_abbr": row.get("TEAM_ABBREVIATION"),
        "age": row.get("PLAYER_AGE"),
        "gp": gp,
        "gs": row.get("GS"),
        "mpg": _ratio(totals["MIN"], gp, 1),
        "ppg": _ratio(totals["PTS"], gp, 1),
        "rpg": _ratio(totals["REB"], gp, 1),
        "apg": _ratio(totals["AST"], gp, 1),
        "spg": _ratio(totals["STL"], gp, 1),
        "bpg": _ratio(totals["BLK"], gp, 1),
        "tpg": _ratio(totals["TOV"], gp, 1),
        "fg_pct": row.get("FG_PCT"),
        "fg3_pct": row.get("FG3_PCT"),
        "ft_pct": row.get("FT_PCT"),
        "efg_pct": _ratio(fgm + 0.5 * fg3m, fga),
        "ts_pct": _ratio(totals["PTS"], 2 * (fga + 0.44 * fta)),
    }


def shape_split(season_rows: list[Row], career_rows: list[Row]) -> dict[str, Any]:
    return {
        "seasons": [shape_stat_line(r) for r in season_rows],
        "career": shape_stat_line(career_rows[0]) if career_rows else None,
    }
