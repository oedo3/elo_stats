"""Thin, paced wrapper around nba_api that returns plain dicts (no pandas)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import requests
from nba_api.stats.endpoints import (
    boxscoretraditionalv3,
    commonplayerinfo,
    leaguegamelog,
    playercareerstats,
    scheduleleaguev2,
)

logger = logging.getLogger(__name__)

Row = dict[str, Any]
ResultSets = dict[str, list[Row]]
T = TypeVar("T")

# Errors that mean "this attempt failed, try again": network trouble, empty or non-JSON bodies
# (stats.nba.com answers overload with an empty HTTP 500) and unexpected payload shapes.
RETRYABLE = (requests.RequestException, ValueError, KeyError, TypeError, AttributeError)


class NbaApiError(RuntimeError):
    """stats.nba.com could not be reached or returned something unusable."""


class NbaClient(Protocol):
    def player_game_logs(
        self, season: str, season_type: str, retries: int | None = None
    ) -> list[Row]: ...

    def season_schedule(self, season: str) -> list[Row]: ...

    def box_score(self, game_id: str) -> dict[str, Any]: ...

    def player_info(self, player_id: int) -> ResultSets: ...

    def player_career(self, player_id: int) -> ResultSets: ...


def result_sets_to_rows(payload: dict[str, Any]) -> ResultSets:
    """Convert nba_api's ``{"resultSets": [{name, headers, rowSet}]}`` into named row lists."""
    sets = payload.get("resultSets") or payload.get("resultSet")
    if isinstance(sets, dict):
        sets = [sets]
    if not isinstance(sets, list):
        raise NbaApiError("Unexpected response shape from stats.nba.com")
    return {
        rs["name"]: [dict(zip(rs["headers"], row, strict=False)) for row in rs["rowSet"]]
        for rs in sets
    }


def parse_schedule(payload: dict[str, Any]) -> list[Row]:
    """Flatten ``scheduleleaguev2`` into ``{game_id, game_date, status}`` rows."""
    dates = payload["leagueSchedule"]["gameDates"]
    return [
        {
            "game_id": str(game["gameId"]),
            "game_date": str(game["gameDateEst"])[:10],
            "status": int(game.get("gameStatus") or 0),
        }
        for day in dates
        for game in day["games"]
    ]


def parse_box_score(payload: dict[str, Any]) -> dict[str, Any]:
    box = payload["boxScoreTraditional"]
    if not isinstance(box, dict):
        raise ValueError("boxScoreTraditional missing")
    return box


class NbaStatsClient:
    """Paces request start times so stats.nba.com does not throttle us.

    Several threads may have requests in flight at once; only their start times are spaced
    ``min_interval`` seconds apart, so a slow response never blocks other callers.

    A circuit breaker backs off when the site starts failing everything (it throttles clients
    that send many requests): after ``breaker_threshold`` consecutive failures every caller
    pauses for ``cooldown`` seconds, doubling up to ``max_cooldown`` while failures continue.
    """

    def __init__(
        self,
        timeout: int = 60,
        min_interval: float = 1.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        breaker_threshold: int = 6,
        cooldown: float = 300.0,
        max_cooldown: float = 1800.0,
    ) -> None:
        self._timeout = timeout
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._pace_lock = threading.Lock()
        self._next_slot = 0.0
        self._breaker_threshold = breaker_threshold
        self._base_cooldown = cooldown
        self._cooldown = cooldown
        self._max_cooldown = max_cooldown
        self._consecutive_failures = 0

    def _wait_turn(self) -> None:
        with self._pace_lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._min_interval
        if slot > now:
            self._sleep(slot - now)

    def _record_success(self) -> None:
        with self._pace_lock:
            self._consecutive_failures = 0
            self._cooldown = self._base_cooldown

    def _record_failure(self) -> None:
        with self._pace_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures < self._breaker_threshold:
                return
            resume = self._clock() + self._cooldown
            self._next_slot = max(self._next_slot, resume)
            logger.warning(
                "stats.nba.com is failing every request; pausing %d s before retrying",
                self._cooldown,
            )
            self._cooldown = min(self._cooldown * 2, self._max_cooldown)
            self._consecutive_failures = 0

    def _request(
        self,
        description: str,
        fetch: Callable[[int], dict[str, Any]],
        parse: Callable[[dict[str, Any]], T],
        retries: int | None = None,
    ) -> T:
        """Run ``parse(fetch(attempt_index))`` with pacing, retries and exponential backoff.

        The attempt index lets callers vary a harmless query parameter: the NBA CDN caches
        5xx responses per URL, so retrying the identical URL can keep returning the same error.
        """
        max_retries = retries or self._max_retries
        last_error: Exception | None = None
        for attempt in range(max_retries):
            self._wait_turn()
            try:
                result = parse(fetch(attempt))
            except RETRYABLE as exc:
                last_error = exc
                self._record_failure()
                logger.debug(
                    "%s failed (attempt %d/%d): %s", description, attempt + 1, max_retries, exc
                )
                if attempt + 1 < max_retries:
                    self._sleep(2 ** (attempt + 1))
            else:
                self._record_success()
                return result
        raise NbaApiError(f"{description} failed after {max_retries} attempts") from last_error

    def _call(
        self,
        description: str,
        fetch: Callable[[int], dict[str, Any]],
        retries: int | None = None,
    ) -> ResultSets:
        return self._request(description, fetch, result_sets_to_rows, retries)

    def player_game_logs(
        self, season: str, season_type: str, retries: int | None = None
    ) -> list[Row]:
        sets = self._call(
            f"game logs {season} {season_type}",
            lambda attempt: leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation="P",
                counter=attempt,
                timeout=self._timeout,
            ).get_dict(),
            retries=retries,
        )
        return sets.get("LeagueGameLog", [])

    def season_schedule(self, season: str) -> list[Row]:
        return self._request(
            f"schedule {season}",
            lambda _attempt: scheduleleaguev2.ScheduleLeagueV2(
                season=season, timeout=self._timeout
            ).get_dict(),
            parse_schedule,
        )

    def box_score(self, game_id: str) -> dict[str, Any]:
        return self._request(
            f"box score {game_id}",
            lambda _attempt: boxscoretraditionalv3.BoxScoreTraditionalV3(
                game_id=game_id, timeout=self._timeout
            ).get_dict(),
            parse_box_score,
        )

    def player_info(self, player_id: int) -> ResultSets:
        return self._call(
            f"player info {player_id}",
            lambda _attempt: commonplayerinfo.CommonPlayerInfo(
                player_id=player_id, timeout=self._timeout
            ).get_dict(),
        )

    def player_career(self, player_id: int) -> ResultSets:
        return self._call(
            f"career stats {player_id}",
            lambda _attempt: playercareerstats.PlayerCareerStats(
                player_id=player_id, timeout=self._timeout
            ).get_dict(),
        )
