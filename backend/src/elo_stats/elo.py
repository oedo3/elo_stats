"""Game-by-game player Elo.

Each player carries a rating. For every game:

1. Each team's strength is the minutes-weighted mean of its players' pre-game ratings.
2. The home side gets ``home_advantage`` points when computing the expected result.
3. The team-level change is ``K * mov_multiplier * (actual - expected)`` (FiveThirtyEight-style
   margin-of-victory multiplier, which damps rating inflation for heavy favourites).
4. Every player receives that change scaled by the share of the game they were on the floor,
   so a 48-minute starter moves fully and a 6-minute reserve barely moves.

At the start of each new season a player's rating regresses part of the way back to the mean.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

PLAYERS_ON_COURT = 5


@dataclass(frozen=True)
class EloParams:
    initial_rating: float = 1500.0
    k_factor: float = 20.0
    home_advantage: float = 100.0
    season_reversion: float = 0.25


@dataclass(frozen=True)
class PlayerLine:
    player_id: int
    minutes: float


@dataclass(frozen=True)
class TeamSide:
    team_id: int
    is_home: bool
    won: bool
    points: int
    lines: tuple[PlayerLine, ...]

    @property
    def total_minutes(self) -> float:
        return sum(line.minutes for line in self.lines if line.minutes > 0)


@dataclass(frozen=True)
class Game:
    game_id: str
    game_date: str
    season: int  # season start year, e.g. 2024 for 2024-25
    home: TeamSide
    away: TeamSide


@dataclass(frozen=True)
class RatingUpdate:
    player_id: int
    game_id: str
    game_date: str
    season: int
    team_id: int
    opponent_team_id: int
    won: bool
    rating_before: float
    rating_after: float


def expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_rating - rating) / 400.0))


def mov_multiplier(margin: float, winner_elo_diff: float) -> float:
    """FiveThirtyEight NBA margin-of-victory multiplier."""
    return ((abs(margin) + 3) ** 0.8) / (7.5 + 0.006 * winner_elo_diff)


def team_rating(lines: Iterable[PlayerLine], ratings: Mapping[int, float], initial: float) -> float:
    weighted = [(ratings.get(line.player_id, initial), line.minutes) for line in lines]
    total = sum(minutes for _, minutes in weighted if minutes > 0)
    if total <= 0:
        return initial
    return sum(rating * minutes for rating, minutes in weighted if minutes > 0) / total


def _effective_rating(side: TeamSide, ratings: Mapping[int, float], params: EloParams) -> float:
    base = team_rating(side.lines, ratings, params.initial_rating)
    return base + (params.home_advantage if side.is_home else 0.0)


def rate_game(game: Game, ratings: Mapping[int, float], params: EloParams) -> dict[int, float]:
    """Return post-game ratings for every player who logged minutes. Does not modify ``ratings``."""
    home_eff = _effective_rating(game.home, ratings, params)
    away_eff = _effective_rating(game.away, ratings, params)
    home_expected = expected_score(home_eff, away_eff)

    winner_diff = home_eff - away_eff if game.home.won else away_eff - home_eff
    margin = game.home.points - game.away.points
    home_team_delta = (
        params.k_factor
        * mov_multiplier(margin, winner_diff)
        * ((1.0 if game.home.won else 0.0) - home_expected)
    )

    game_length = max(game.home.total_minutes, game.away.total_minutes) / PLAYERS_ON_COURT
    if game_length <= 0:
        return {}

    new_ratings: dict[int, float] = {}
    for side, team_delta in ((game.home, home_team_delta), (game.away, -home_team_delta)):
        for line in side.lines:
            if line.minutes <= 0:
                continue
            share = min(line.minutes / game_length, 1.0)
            before = ratings.get(line.player_id, params.initial_rating)
            new_ratings[line.player_id] = before + team_delta * share
    return new_ratings


def regress_to_mean(rating: float, params: EloParams) -> float:
    return rating + (params.initial_rating - rating) * params.season_reversion


def run_elo(games: Iterable[Game], params: EloParams) -> Iterator[RatingUpdate]:
    """Replay games in the order given (callers sort chronologically) and yield every update.

    Running state is kept local to this generator; ``rate_game`` itself is pure.
    """
    ratings: dict[int, float] = {}
    last_season: dict[int, int] = {}

    for game in games:
        pre_game: dict[int, float] = {}
        for side in (game.home, game.away):
            for line in side.lines:
                pid = line.player_id
                rating = ratings.get(pid, params.initial_rating)
                if pid in last_season and last_season[pid] < game.season:
                    rating = regress_to_mean(rating, params)
                pre_game[pid] = rating

        post_game = rate_game(game, pre_game, params)

        for side, opponent in ((game.home, game.away), (game.away, game.home)):
            for line in side.lines:
                pid = line.player_id
                if pid not in post_game:
                    continue
                yield RatingUpdate(
                    player_id=pid,
                    game_id=game.game_id,
                    game_date=game.game_date,
                    season=game.season,
                    team_id=side.team_id,
                    opponent_team_id=opponent.team_id,
                    won=side.won,
                    rating_before=pre_game[pid],
                    rating_after=post_game[pid],
                )
                ratings[pid] = post_game[pid]
                last_season[pid] = game.season
