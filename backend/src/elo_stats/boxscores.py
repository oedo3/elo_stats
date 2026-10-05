"""Per-game box scores: the reliable (if slower) way to download a season.

stats.nba.com's bulk ``leaguegamelog`` endpoint frequently times out, while the season schedule
and individual box scores answer in well under a second. Box score rows are converted into the
same shape as ``leaguegamelog`` rows so both paths share one storage format.
"""

from __future__ import annotations

from typing import Any

from elo_stats.nba_client import Row

GAME_ID_PREFIX = {"Regular Season": "002", "Playoffs": "004"}
FINAL_STATUS = 3


def scheduled_games(schedule: list[Row], season_type: str) -> list[Row]:
    """Final games of ``season_type``.

    Only final games count: schedules also list placeholders for "if necessary" playoff games
    that were never played, which have no box score.
    """
    prefix = GAME_ID_PREFIX[season_type]
    return [
        game
        for game in schedule
        if game["game_id"].startswith(prefix) and game["status"] == FINAL_STATUS
    ]


def _team_points(team: dict[str, Any]) -> int:
    stats = team.get("statistics") or {}
    if stats.get("points") is not None:
        return int(stats["points"])
    return sum(int((p.get("statistics") or {}).get("points") or 0) for p in team["players"])


def _player_name(player: dict[str, Any]) -> str:
    return f"{player.get('firstName', '')} {player.get('familyName', '')}".strip()


def box_score_rows(box: dict[str, Any], game_date: str) -> list[Row]:
    """Convert a ``boxscoretraditionalv3`` game into leaguegamelog-shaped player rows.

    Returns [] for games with no data (e.g. a cancelled game) or without a winner.
    """
    home, away = box.get("homeTeam") or {}, box.get("awayTeam") or {}
    if not home.get("teamId") or not away.get("teamId"):
        return []
    home_pts, away_pts = _team_points(home), _team_points(away)
    if home_pts == away_pts:
        return []

    rows: list[Row] = []
    for team, opponent, is_home in ((home, away, True), (away, home, False)):
        won = (home_pts > away_pts) == is_home
        separator = " vs. " if is_home else " @ "
        for player in team.get("players") or []:
            stats = player.get("statistics") or {}
            if not stats.get("minutes"):
                continue  # did not play
            rows.append(
                {
                    "GAME_ID": str(box["gameId"]),
                    "PLAYER_ID": player["personId"],
                    "PLAYER_NAME": _player_name(player),
                    "TEAM_ID": team["teamId"],
                    "TEAM_ABBREVIATION": team["teamTricode"],
                    "GAME_DATE": game_date,
                    "MATCHUP": f"{team['teamTricode']}{separator}{opponent['teamTricode']}",
                    "WL": "W" if won else "L",
                    "MIN": stats.get("minutes"),
                    "PTS": stats.get("points"),
                    "REB": stats.get("reboundsTotal"),
                    "AST": stats.get("assists"),
                    "PLUS_MINUS": stats.get("plusMinusPoints"),
                }
            )
    return rows
