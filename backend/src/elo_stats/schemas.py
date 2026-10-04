"""Pydantic response models. Every endpoint returns ``ApiResponse[T]``."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


class Health(BaseModel):
    status: str
    has_data: bool


class Meta(BaseModel):
    has_data: bool
    first_season: int | None = None
    last_season: int | None = None
    last_game_date: str | None = None
    computed_at: str | None = None
    elo_params: dict[str, float] | None = None
    missing_seasons: list[str] = []


class PlayerSearchResult(BaseModel):
    player_id: int
    player_name: str
    rating: float
    peak_rating: float
    games: int
    team_abbr: str
    first_game_date: str
    last_game_date: str
    last_season: int


class PlayerRating(BaseModel):
    player_id: int
    player_name: str
    rating: float
    peak_rating: float
    peak_date: str
    games: int
    first_game_date: str
    last_game_date: str
    last_season: int
    team_abbr: str
    is_active: bool
    active_rank: int | None
    peak_rank: int


class EloPoint(BaseModel):
    game_id: str
    game_date: str
    season: int
    team_abbr: str
    opponent_abbr: str
    won: bool
    rating_before: float
    rating_after: float


class LeaderboardEntry(BaseModel):
    rank: int
    player_id: int
    player_name: str
    rating: float
    peak_rating: float
    peak_date: str
    games: int
    team_abbr: str
    first_game_date: str
    last_game_date: str
    last_season: int


class PlayerBio(BaseModel):
    player_id: int
    name: str | None
    position: str | None
    height: str | None
    weight: int | None
    jersey: str | None
    birthdate: str | None
    country: str | None
    school: str | None
    team_name: str | None
    team_abbr: str | None
    draft_year: int | None
    draft_round: int | None
    draft_number: int | None
    from_year: int | None
    to_year: int | None
    seasons: int | None
    is_active: bool
    greatest_75: bool


class StatLine(BaseModel):
    season: str
    team_abbr: str | None
    age: float | None
    gp: int
    gs: int | None
    mpg: float | None
    ppg: float | None
    rpg: float | None
    apg: float | None
    spg: float | None
    bpg: float | None
    tpg: float | None
    fg_pct: float | None
    fg3_pct: float | None
    ft_pct: float | None
    efg_pct: float | None
    ts_pct: float | None


class CareerSplit(BaseModel):
    seasons: list[StatLine]
    career: StatLine | None


class PlayerCareer(BaseModel):
    regular_season: CareerSplit
    playoffs: CareerSplit
