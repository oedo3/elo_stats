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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from elo_stats.boxscores import box_score_rows, scheduled_games
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


def season_bounds(season_start: int, season_type: str) -> tuple[date, date]:
    """Earliest and latest dates a season type's games can fall on.

    Regular seasons have run as late as August (2020 bubble); playoffs as late as October.
    """
    if season_type == "Playoffs":
        return date(season_start + 1, 4, 1), date(season_start + 1, 10, 31)
    return date(season_start, 10, 1), date(season_start + 1, 8, 31)


def has_started(season_start: int, season_type: str, today: date) -> bool:
    """False for season types that cannot have games yet (e.g. playoffs before April)."""
    return season_bounds(season_start, season_type)[0] <= today


@dataclass(frozen=True)
class FetchOptions:
    # Request start rate is capped by the client; extra workers only stop slow responses
    # from holding up the queue.
    workers: int = 6
    # The bulk endpoint returns a whole season in seconds when it works, but often times out
    # (~30s per attempt). Box scores are the slow, reliable fallback.
    try_bulk: bool = True
    bulk_attempts: int = 2


def fetch_via_box_scores(
    conn: sqlite3.Connection,
    client: NbaClient,
    season: int,
    season_type: str,
    today: date,
    workers: int,
) -> int:
    """Download every played game of a season one box score at a time.

    Each game is stored (and recorded in ``fetched_games``) as soon as it arrives, so an
    interrupted run resumes where it stopped. Returns how many games could not be fetched.
    """
    label = season_label(season)
    games = scheduled_games(client.season_schedule(label), season_type, today)
    done = {
        r[0]
        for r in conn.execute(
            "SELECT game_id FROM fetched_games WHERE season = ? AND season_type = ?",
            (label, season_type),
        )
    }
    todo = [g for g in games if g["game_id"] not in done]
    logger.info(
        "  %d games scheduled, %d already stored, %d to fetch", len(games), len(done), len(todo)
    )

    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.box_score, g["game_id"]): g for g in todo}
        for count, future in enumerate(as_completed(futures), start=1):
            game = futures[future]
            try:
                rows = box_score_rows(future.result(), game["game_date"])
            except NbaApiError as exc:
                failures += 1
                logger.warning("    %s: %s", game["game_id"], exc)
                continue
            store_game_logs(conn, rows, season, season_type)
            conn.execute(
                "INSERT OR REPLACE INTO fetched_games VALUES (?, ?, ?, ?, ?)",
                (game["game_id"], label, season_type, len(rows), _now()),
            )
            if count % 100 == 0:
                conn.commit()
                logger.info("    %d/%d games", count, len(todo))
    conn.commit()
    return failures


def _fetch_one(
    conn: sqlite3.Connection,
    client: NbaClient,
    season: int,
    season_type: str,
    today: date,
    options: FetchOptions,
) -> bool:
    """Fetch one season type, bulk first then box scores. Returns True when complete."""
    label = season_label(season)
    if options.try_bulk:
        try:
            rows = client.player_game_logs(label, season_type, retries=options.bulk_attempts)
        except NbaApiError:
            logger.info("  bulk endpoint failed; using per-game box scores")
        else:
            store_game_logs(conn, rows, season, season_type)
            conn.commit()
            return True
    return fetch_via_box_scores(conn, client, season, season_type, today, options.workers) == 0


def fetch_seasons(
    conn: sqlite3.Connection,
    client: NbaClient,
    seasons: Sequence[int],
    season_types: Sequence[str] = SEASON_TYPES,
    *,
    refresh: bool = False,
    live_season: int | None = None,
    today: date | None = None,
    options: FetchOptions | None = None,
) -> list[str]:
    """Download each (season, type) not already complete; the live season is always re-fetched.

    A season that cannot be fully downloaded keeps whatever games did arrive and is reported,
    so one bad season does not stop the run. Returns the ``"<season> <type>"`` labels that
    are still incomplete.
    """
    today = today or date.today()
    options = options or FetchOptions()
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
                complete = _fetch_one(conn, client, season, season_type, today, options)
            except NbaApiError as exc:  # e.g. the schedule itself could not be loaded
                conn.commit()
                logger.error("  %s %s incomplete: %s", label, season_type, exc)
                complete = False
            if not complete:
                failed.append(f"{label} {season_type}")
                continue
            stored = conn.execute(
                "SELECT COUNT(*) FROM player_games WHERE season = ? AND season_type = ?",
                (season, season_type),
            ).fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO fetched_seasons VALUES (?, ?, ?, ?)",
                (label, season_type, stored, _now()),
            )
            conn.commit()
            logger.info("  complete: %d player-game rows", stored)
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
    return record.fetched_on > season_bounds(season, season_type)[1]


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
    parser.add_argument(
        "--workers", type=int, default=6, help="parallel box score downloads (1-16, default 6)"
    )
    parser.add_argument(
        "--no-bulk",
        action="store_true",
        help="skip the bulk game-log endpoint and download box scores only",
    )
    parser.add_argument(
        "--rate", type=float, default=1.5, help="max requests started per second (default 1.5)"
    )
    parser.add_argument(
        "--passes", type=int, default=3, help="retry rounds for incomplete seasons (default 3)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not FIRST_SEASON <= args.from_season <= args.to_season <= live:
        parser.error(f"seasons must satisfy {FIRST_SEASON} <= from <= to <= {live}")
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    if not 0.2 <= args.rate <= 10:
        parser.error("--rate must be between 0.2 and 10")
    if not 1 <= args.passes <= 10:
        parser.error("--passes must be between 1 and 10")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.db_path.parent / "ingest.log", encoding="utf-8"),
        ],
    )
    live = current_season_start(date.today())
    with open_db(settings.db_path) as conn:
        if not args.skip_fetch:
            # Newest first: recent seasons are fast to fetch, so the app is useful sooner.
            client = NbaStatsClient(
                timeout=settings.nba_timeout_seconds, min_interval=1 / args.rate
            )
            options = FetchOptions(workers=args.workers, try_bulk=not args.no_bulk)
            seasons = list(range(args.to_season, args.from_season - 1, -1))
            for attempt in range(1, args.passes + 1):
                failed = fetch_seasons(
                    conn,
                    client,
                    seasons,
                    refresh=args.refresh and attempt == 1,
                    live_season=live,
                    options=options,
                )
                if not failed:
                    break
                logger.warning("Pass %d left %d season downloads incomplete", attempt, len(failed))
                seasons = sorted({int(label[:4]) for label in failed}, reverse=True)
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
