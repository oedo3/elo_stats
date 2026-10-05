from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elo_stats.api import create_app
from elo_stats.config import Settings
from elo_stats.db import open_db
from elo_stats.elo import EloParams
from elo_stats.ingest import compute_ratings, store_game_logs
from elo_stats.nba_client import NbaApiError

TEAMS = {1: "AAA", 2: "BBB", 3: "CCC"}
ROSTERS = {
    1: [(203999, "Nikola Jokić")] + [(100 + i, f"Alpha Player {i}") for i in range(2, 6)],
    2: [(200 + i, f"Bravo Player {i}") for i in range(1, 6)],
    3: [(300 + i, f"Charlie Player {i}") for i in range(1, 6)],
}
# (game_id, date, season, home_team, away_team, home_won)
GAMES = [
    ("0022300001", "2023-11-01", 2023, 1, 2, True),
    ("0022300002", "2023-11-03", 2023, 3, 1, False),
    ("0022400001", "2024-11-01", 2024, 2, 1, True),
]


def log_row(game_id, game_date, team_id, opp_id, is_home, won, player_id, name, minutes=48, pts=22):
    matchup = (
        f"{TEAMS[team_id]} vs. {TEAMS[opp_id]}"
        if is_home
        else (f"{TEAMS[team_id]} @ {TEAMS[opp_id]}")
    )
    return {
        "SEASON_ID": "2" + game_date[:4],
        "PLAYER_ID": player_id,
        "PLAYER_NAME": name,
        "TEAM_ID": team_id,
        "TEAM_ABBREVIATION": TEAMS[team_id],
        "GAME_ID": game_id,
        "GAME_DATE": game_date,
        "MATCHUP": matchup,
        "WL": "W" if won else "L",
        "MIN": minutes,
        "PTS": pts,
        "REB": 5,
        "AST": 5,
        "PLUS_MINUS": 10 if won else -10,
    }


def game_rows(game_id, game_date, home, away, home_won):
    rows = []
    for team, opp, is_home in ((home, away, True), (away, home, False)):
        won = home_won if is_home else not home_won
        for pid, name in ROSTERS[team]:
            rows.append(
                log_row(
                    game_id, game_date, team, opp, is_home, won, pid, name, pts=22 if won else 20
                )
            )
    return rows


def all_rows_by_season() -> dict[int, list[dict]]:
    by_season: dict[int, list[dict]] = {}
    for game_id, game_date, season, home, away, home_won in GAMES:
        by_season.setdefault(season, []).extend(game_rows(game_id, game_date, home, away, home_won))
    return by_season


INFO_ROW = {
    "PERSON_ID": 203999,
    "DISPLAY_FIRST_LAST": "Nikola Jokić",
    "POSITION": "Center",
    "HEIGHT": "6-11",
    "WEIGHT": "284",
    "JERSEY": "15",
    "BIRTHDATE": "1995-02-19T00:00:00",
    "COUNTRY": "Serbia",
    "SCHOOL": " ",
    "TEAM_CITY": "Denver",
    "TEAM_NAME": "Nuggets",
    "TEAM_ABBREVIATION": "DEN",
    "DRAFT_YEAR": "2014",
    "DRAFT_ROUND": "2",
    "DRAFT_NUMBER": "41",
    "FROM_YEAR": 2015,
    "TO_YEAR": 2026,
    "SEASON_EXP": 11,
    "ROSTERSTATUS": "Active",
    "GREATEST_75_FLAG": "N",
}

SEASON_TOTALS = {
    "SEASON_ID": "2024-25",
    "TEAM_ABBREVIATION": "DEN",
    "PLAYER_AGE": 30.0,
    "GP": 10,
    "GS": 10,
    "MIN": 350,
    "PTS": 300,
    "REB": 120,
    "AST": 100,
    "STL": 15,
    "BLK": 8,
    "TOV": 30,
    "FGM": 110,
    "FGA": 200,
    "FG_PCT": 0.55,
    "FG3M": 20,
    "FG3A": 50,
    "FG3_PCT": 0.4,
    "FTM": 60,
    "FTA": 75,
    "FT_PCT": 0.8,
}


def to_box_score(game_id: str, rows: list[dict]) -> dict:
    """Build a boxscoretraditionalv3-shaped game from leaguegamelog-shaped fixture rows."""
    teams: dict[str, dict] = {}
    for row in rows:
        side = "homeTeam" if " vs. " in row["MATCHUP"] else "awayTeam"
        team = teams.setdefault(
            side,
            {
                "teamId": row["TEAM_ID"],
                "teamTricode": row["TEAM_ABBREVIATION"],
                "statistics": {"points": 0},
                "players": [],
            },
        )
        team["statistics"]["points"] += row["PTS"]
        first, _, last = row["PLAYER_NAME"].partition(" ")
        team["players"].append(
            {
                "personId": row["PLAYER_ID"],
                "firstName": first,
                "familyName": last,
                "statistics": {
                    "minutes": f"{row['MIN']}:00",
                    "points": row["PTS"],
                    "reboundsTotal": row["REB"],
                    "assists": row["AST"],
                    "plusMinusPoints": float(row["PLUS_MINUS"]),
                },
            }
        )
    return {"gameId": game_id, **teams}


class FakeClient:
    def __init__(self, rows_by_season=None, fail_full_season=False, fail_info=False, fail_games=()):
        self.rows_by_season = rows_by_season or {}
        self.fail_full_season = fail_full_season
        self.fail_games = set(fail_games)
        self.fail_info = fail_info
        self.calls: list[tuple] = []

    def _rows(self, season: str) -> list[dict]:
        return self.rows_by_season.get(int(season[:4]), [])

    def player_game_logs(self, season, season_type, retries=None):
        self.calls.append(("logs", season, season_type))
        if self.fail_full_season:
            raise NbaApiError("boom")
        return self._rows(season) if season_type == "Regular Season" else []

    def season_schedule(self, season):
        self.calls.append(("schedule", season))
        games = {r["GAME_ID"]: r["GAME_DATE"] for r in self._rows(season)}
        return [{"game_id": g, "game_date": d, "status": 3} for g, d in games.items()]

    def box_score(self, game_id):
        self.calls.append(("box", game_id))
        if game_id in self.fail_games:
            raise NbaApiError("box score down")
        rows = [r for rs in self.rows_by_season.values() for r in rs if r["GAME_ID"] == game_id]
        return to_box_score(game_id, rows)

    def player_info(self, player_id):
        self.calls.append(("info", player_id))
        if self.fail_info:
            raise NbaApiError("down")
        return {"CommonPlayerInfo": [INFO_ROW] if player_id == 203999 else []}

    def player_career(self, player_id):
        self.calls.append(("career", player_id))
        return {
            "SeasonTotalsRegularSeason": [SEASON_TOTALS],
            "CareerTotalsRegularSeason": [{**SEASON_TOTALS, "SEASON_ID": None}],
            "SeasonTotalsPostSeason": [],
            "CareerTotalsPostSeason": [],
        }


def make_settings(db_path: Path, rate_limit: int = 1000) -> Settings:
    return Settings(
        db_path=db_path,
        cors_origins=("http://localhost:5173",),
        cache_ttl_hours=24,
        rate_limit_per_minute=rate_limit,
        nba_timeout_seconds=5,
        elo=EloParams(),
    )


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.sqlite3"
    with open_db(db_path) as conn:
        for season, rows in all_rows_by_season().items():
            store_game_logs(conn, rows, season, "Regular Season")
        compute_ratings(conn, EloParams())
    return db_path


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def api(seeded_db: Path, fake_client: FakeClient) -> Iterator[TestClient]:
    app = create_app(make_settings(seeded_db), client=fake_client)
    with TestClient(app) as client:
        yield client
