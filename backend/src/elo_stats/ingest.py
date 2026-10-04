"""Download NBA player game logs into SQLite and (re)compute player Elo.

Usage (from ``backend/``)::

    python -m elo_stats.ingest                 # fetch any missing seasons, then compute Elo
    python -m elo_stats.ingest --refresh       # re-download every season
    python -m elo_stats.ingest --skip-fetch    # recompute Elo from cached games only
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from elo_stats.config import FIRST_SEASON, SEASON_TYPES, load_settings
from elo_stats.db import open_db
from elo_stats.elo import EloParams, Game, PlayerLine, RatingUpdate, TeamSide, run_elo
from elo_stats.nba_client import NbaApiError, NbaClient, NbaStatsClient, Row
from elo_stats.text import normalize_name

logger = logging.getLogger("elo_stats.ingest")

INSERT_BATCH = 20_000


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def current_season_start(today: date) -> int:
    """NBA seasons tip off in October; before that we are still in last year's season."""
    return today.year if today.month >= 10 else today.year - 1


def parse_minutes(raw: Any) -> float:
    """Minutes arrive as int, float, ``"MM:SS"`` strings or None depending on the endpoint/era."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, int | float):
        value = float(raw)
    else:
        text = str(raw).strip()
        if ":" in text:
            mins, _, secs = text.partition(":")
            value = float(mins) + float(secs or 0) / 60.0
        else:
            value = float(text)
    return value if math.isfinite(value) and value > 0 else 0.0


def parse_game_log_row(row: Row, season_start: int, season_type: str) -> dict[str, Any] | None:
    """Validate one LeagueGameLog row. Returns None for rows we cannot use."""
    try:
        wl = row["WL"]
        matchup = str(row["MATCHUP"])
        if wl not in ("W", "L"):
            return None
        return {
            "game_id": str(row["GAME_ID"]),
            "player_id": int(row["PLAYER_ID"]),
            "player_name": str(row["PLAYER_NAME"]),
            "team_id": int(row["TEAM_ID"]),
            "team_abbr": str(row["TEAM_ABBREVIATION"]),
            "season": season_start,
            "season_type": season_type,
            "game_date": str(row["GAME_DATE"])[:10],
            "matchup": matchup,
            "is_home": 1 if " vs. " in matchup else 0,
            "won": 1 if wl == "W" else 0,
            "minutes": parse_minutes(row.get("MIN")),
            "pts": int(row.get("PTS") or 0),
            "reb": row.get("REB"),
            "ast": row.get("AST"),
            "plus_minus": row.get("PLUS_MINUS"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Skipping malformed row %s: %s", row, exc)
        return None


def store_game_logs(
    conn: sqlite3.Connection, rows: Iterable[Row], season_start: int, season_type: str
) -> int:
    parsed = [
        p for p in (parse_game_log_row(r, season_start, season_type) for r in rows) if p is not None
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO player_games (
            game_id, player_id, player_name, team_id, team_abbr, season, season_type, game_date,
            matchup, is_home, won, minutes, pts, reb, ast, plus_minus
        ) VALUES (
            :game_id, :player_id, :player_name, :team_id, :team_abbr, :season, :season_type,
            :game_date, :matchup, :is_home, :won, :minutes, :pts, :reb, :ast, :plus_minus
        )
        """,
        parsed,
    )
    return len(parsed)


def month_windows(season_start: int, season_type: str) -> list[tuple[date, date]]:
    """Calendar-month date windows that cover every possible game of a season type.

    Regular seasons have run as late as August (2020 bubble); playoffs as late as October.
    """
    if season_type == "Playoffs":
        first, last = date(season_start + 1, 4, 1), date(season_start + 1, 10, 31)
    else:
        first, last = date(season_start, 10, 1), date(season_start + 1, 8, 31)
    windows = []
    cursor = first
    while cursor <= last:
        next_month = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        windows.append((cursor, min(next_month - timedelta(days=1), last)))
        cursor = next_month
    return windows


MIN_WINDOW_DAYS = 2


def fetch_window(
    client: NbaClient, label: str, season_type: str, date_from: date, date_to: date
) -> list[Row]:
    """Fetch a date window, halving it on failure until it is ``MIN_WINDOW_DAYS`` long."""
    try:
        rows = client.player_game_logs(
            label, season_type, date_from=date_from, date_to=date_to, retries=2
        )
    except NbaApiError:
        if (date_to - date_from).days < MIN_WINDOW_DAYS:
            raise
        middle = date_from + (date_to - date_from) // 2
        logger.info("    splitting %s..%s", date_from, date_to)
        return fetch_window(client, label, season_type, date_from, middle) + fetch_window(
            client, label, season_type, middle + timedelta(days=1), date_to
        )
    logger.info("    %s..%s: %d rows", date_from, date_to, len(rows))
    return rows


def has_started(season_start: int, season_type: str, today: date) -> bool:
    """False for season types that cannot have games yet (e.g. playoffs before April)."""
    return month_windows(season_start, season_type)[0][0] <= today


def fetch_season_rows(
    client: NbaClient, season_start: int, season_type: str, today: date | None = None
) -> list[Row]:
    """Fetch a whole season in one request, falling back to smaller date windows.

    stats.nba.com times out (HTTP 500 after ~30s) on large requests for older seasons, while
    smaller date windows succeed.
    """
    label = season_label(season_start)
    try:
        return client.player_game_logs(label, season_type, retries=2)
    except NbaApiError:
        logger.info("  full season failed; fetching %s %s by month", label, season_type)
    today = today or date.today()
    rows: list[Row] = []
    for date_from, date_to in month_windows(season_start, season_type):
        if date_from > today:
            break
        rows.extend(fetch_window(client, label, season_type, date_from, date_to))
    return rows


def fetch_seasons(
    conn: sqlite3.Connection,
    client: NbaClient,
    seasons: Sequence[int],
    season_types: Sequence[str] = SEASON_TYPES,
    *,
    refresh: bool = False,
    live_season: int | None = None,
    today: date | None = None,
) -> list[str]:
    """Download each (season, type) not already cached; the live season is always re-fetched.

    A season that cannot be downloaded is rolled back and skipped so one bad season does not
    stop the run. Returns the ``"<season> <type>"`` labels that failed.
    """
    today = today or date.today()
    cached = _cached_seasons(conn)
    failed: list[str] = []
    for season in seasons:
        label = season_label(season)
        for season_type in season_types:
            if (
                not refresh
                and season != live_season
                and _is_complete(cached.get((label, season_type)), season, season_type)
            ):
                logger.info("Using cached %s %s", label, season_type)
                continue
            if not has_started(season, season_type, today):
                logger.info("Skipping %s %s: not started yet", label, season_type)
                continue
            logger.info("Fetching %s %s ...", label, season_type)
            try:
                rows = fetch_season_rows(client, season, season_type, today)
            except NbaApiError as exc:
                conn.rollback()
                logger.error("  skipped %s %s: %s", label, season_type, exc)
                failed.append(f"{label} {season_type}")
                continue
            stored = store_game_logs(conn, rows, season, season_type)
            conn.execute(
                "INSERT OR REPLACE INTO fetched_seasons VALUES (?, ?, ?, ?)",
                (label, season_type, stored, _now()),
            )
            conn.commit()
            logger.info("  stored %d player-game rows", stored)
    return failed


@dataclass(frozen=True)
class _FetchRecord:
    row_count: int
    fetched_on: date


def _cached_seasons(conn: sqlite3.Connection) -> dict[tuple[str, str], _FetchRecord]:
    return {
        (r["season"], r["season_type"]): _FetchRecord(
            r["row_count"], date.fromisoformat(r["fetched_at"][:10])
        )
        for r in conn.execute(
            "SELECT season, season_type, row_count, fetched_at FROM fetched_seasons"
        )
    }


def _is_complete(record: _FetchRecord | None, season: int, season_type: str) -> bool:
    """A download counts as final only if it has rows and happened after the season ended.

    Otherwise (fetched mid-season, or an empty response) it is fetched again next run.
    """
    if record is None or record.row_count == 0:
        return False
    return record.fetched_on > month_windows(season, season_type)[-1][1]


def missing_seasons(
    conn: sqlite3.Connection,
    seasons: Iterable[int],
    season_types: Sequence[str] = SEASON_TYPES,
    today: date | None = None,
) -> list[str]:
    """Started season/type pairs in ``seasons`` never downloaded, oldest first."""
    today = today or date.today()
    cached = _cached_seasons(conn)
    return [
        f"{season_label(season)} {season_type}"
        for season in sorted(seasons)
        for season_type in season_types
        if (season_label(season), season_type) not in cached
        and has_started(season, season_type, today)
    ]


def record_missing(conn: sqlite3.Connection, missing: list[str]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('missing_seasons', ?)", (json.dumps(missing),)
    )
    conn.commit()


def load_games(conn: sqlite3.Connection) -> Iterator[Game]:
    """Rebuild Game objects from cached rows in chronological order."""
    cursor = conn.execute(
        """
        SELECT game_id, game_date, season, team_id, player_id, is_home, won, minutes, pts
        FROM player_games
        ORDER BY game_date, game_id, team_id
        """
    )
    for game_id, rows in itertools.groupby(cursor, key=lambda r: r["game_id"]):
        rows = list(rows)
        sides: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            sides.setdefault(row["team_id"], []).append(row)
        if len(sides) != 2:
            logger.debug("Skipping game %s with %d team(s)", game_id, len(sides))
            continue
        built = [_build_side(team_id, side_rows) for team_id, side_rows in sides.items()]
        home = next((s for s in built if s.is_home), None)
        away = next((s for s in built if not s.is_home), None)
        if home is None or away is None or home.won == away.won:
            logger.debug("Skipping game %s with inconsistent home/result data", game_id)
            continue
        yield Game(
            game_id=game_id,
            game_date=rows[0]["game_date"],
            season=rows[0]["season"],
            home=home,
            away=away,
        )


def _build_side(team_id: int, rows: list[sqlite3.Row]) -> TeamSide:
    return TeamSide(
        team_id=team_id,
        is_home=bool(rows[0]["is_home"]),
        won=bool(rows[0]["won"]),
        points=sum(r["pts"] for r in rows),
        lines=tuple(PlayerLine(player_id=r["player_id"], minutes=r["minutes"]) for r in rows),
    )


@dataclass
class _PlayerSummary:
    rating: float
    peak_rating: float
    peak_date: str
    games: int
    first_game_date: str
    last_game_date: str
    last_season: int
    team_abbr: str


def compute_ratings(conn: sqlite3.Connection, params: EloParams) -> int:
    """Replay every cached game and rewrite elo_history / player_ratings. Returns games rated."""
    team_abbr = {
        (r["game_id"], r["team_id"]): r["team_abbr"]
        for r in conn.execute("SELECT DISTINCT game_id, team_id, team_abbr FROM player_games")
    }
    names = {
        r["player_id"]: r["player_name"]
        for r in conn.execute(
            "SELECT player_id, player_name FROM player_games ORDER BY game_date, game_id"
        )
    }

    conn.execute("DELETE FROM elo_history")
    conn.execute("DELETE FROM player_ratings")

    summaries: dict[int, _PlayerSummary] = {}
    games_rated: set[str] = set()

    def history_rows(updates: Iterable[RatingUpdate]) -> Iterator[tuple]:
        for u in updates:
            games_rated.add(u.game_id)
            abbr = team_abbr[(u.game_id, u.team_id)]
            _update_summary(summaries, u, abbr)
            yield (
                u.player_id,
                u.game_id,
                u.game_date,
                u.season,
                abbr,
                team_abbr[(u.game_id, u.opponent_team_id)],
                int(u.won),
                round(u.rating_before, 2),
                round(u.rating_after, 2),
            )

    rows = history_rows(run_elo(load_games(conn), params))
    while batch := list(itertools.islice(rows, INSERT_BATCH)):
        conn.executemany("INSERT INTO elo_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", batch)

    conn.executemany(
        "INSERT INTO player_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                pid,
                names[pid],
                normalize_name(names[pid]),
                round(s.rating, 2),
                round(s.peak_rating, 2),
                s.peak_date,
                s.games,
                s.first_game_date,
                s.last_game_date,
                s.last_season,
                s.team_abbr,
            )
            for pid, s in summaries.items()
        ],
    )
    _write_meta(conn, params)
    conn.commit()
    return len(games_rated)


def _update_summary(summaries: dict[int, _PlayerSummary], u: RatingUpdate, abbr: str) -> None:
    current = summaries.get(u.player_id)
    if current is None:
        summaries[u.player_id] = _PlayerSummary(
            rating=u.rating_after,
            peak_rating=u.rating_after,
            peak_date=u.game_date,
            games=1,
            first_game_date=u.game_date,
            last_game_date=u.game_date,
            last_season=u.season,
            team_abbr=abbr,
        )
        return
    is_peak = u.rating_after > current.peak_rating
    summaries[u.player_id] = _PlayerSummary(
        rating=u.rating_after,
        peak_rating=u.rating_after if is_peak else current.peak_rating,
        peak_date=u.game_date if is_peak else current.peak_date,
        games=current.games + 1,
        first_game_date=current.first_game_date,
        last_game_date=u.game_date,
        last_season=u.season,
        team_abbr=abbr,
    )


def _write_meta(conn: sqlite3.Connection, params: EloParams) -> None:
    span = conn.execute(
        "SELECT MIN(season), MAX(season), MAX(game_date) FROM player_games"
    ).fetchone()
    meta = {
        "computed_at": _now(),
        "first_season": span[0],
        "last_season": span[1],
        "last_game_date": span[2],
        "elo_params": json.dumps(asdict(params)),
    }
    conn.executemany(
        "INSERT OR REPLACE INTO meta VALUES (?, ?)",
        [(k, "" if v is None else str(v)) for k, v in meta.items()],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    live = current_season_start(date.today())
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-season", type=int, default=FIRST_SEASON, help="start year")
    parser.add_argument("--to-season", type=int, default=live, help="start year (inclusive)")
    parser.add_argument("--refresh", action="store_true", help="re-download cached seasons")
    parser.add_argument("--skip-fetch", action="store_true", help="only recompute Elo")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not FIRST_SEASON <= args.from_season <= args.to_season <= live:
        parser.error(f"seasons must satisfy {FIRST_SEASON} <= from <= to <= {live}")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = load_settings()
    live = current_season_start(date.today())
    with open_db(settings.db_path) as conn:
        if not args.skip_fetch:
            # Newest first: recent seasons are fast to fetch, so the app is useful sooner.
            fetch_seasons(
                conn,
                NbaStatsClient(timeout=settings.nba_timeout_seconds),
                range(args.to_season, args.from_season - 1, -1),
                refresh=args.refresh,
                live_season=live,
            )
        logger.info("Computing Elo ...")
        rated = compute_ratings(conn, settings.elo)
        missing = missing_seasons(conn, range(FIRST_SEASON, live + 1))
        record_missing(conn, missing)
        logger.info("Rated %d games. Database: %s", rated, settings.db_path)
    if missing:
        logger.warning(
            "%d season downloads are still missing (%s). Ratings are incomplete until they are "
            "fetched; re-run this command to retry them.",
            len(missing),
            ", ".join(missing),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
