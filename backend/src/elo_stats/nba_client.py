"""Thin, throttled wrapper around nba_api that returns plain dict rows (no pandas)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

import requests
from nba_api.stats.endpoints import commonplayerinfo, leaguegamelog, playercareerstats

logger = logging.getLogger(__name__)

Row = dict[str, Any]
ResultSets = dict[str, list[Row]]


class NbaApiError(RuntimeError):
    """stats.nba.com could not be reached or returned something unusable."""


class NbaClient(Protocol):
    def player_game_logs(
        self,
        season: str,
        season_type: str,
        date_from: date | None = None,
        date_to: date | None = None,
        retries: int | None = None,
    ) -> list[Row]: ...

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


def _format_date(value: date | None) -> str:
    return value.strftime("%m/%d/%Y") if value else ""


class NbaStatsClient:
    """Serialises calls and spaces them out so stats.nba.com does not throttle us."""

    def __init__(
        self,
        timeout: int = 60,
        min_interval: float = 1.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        lock_timeout: float = 90.0,
    ) -> None:
        self._timeout = timeout
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._lock = threading.Lock()
        self._lock_timeout = lock_timeout
        self._last_call = 0.0

    def _call(
        self,
        description: str,
        fetch: Callable[[int], dict[str, Any]],
        retries: int | None = None,
    ) -> ResultSets:
        """Run ``fetch(attempt_index)`` with spacing, retries and exponential backoff.

        The attempt index lets callers vary a harmless query parameter: the NBA CDN caches
        5xx responses per URL, so retrying the identical URL can keep returning the same error.
        """
        max_retries = retries or self._max_retries
        # Bounded wait so callers queued behind a slow upstream give up instead of pinning
        # server threads indefinitely.
        if not self._lock.acquire(timeout=self._lock_timeout):
            raise NbaApiError(f"{description}: NBA stats client is busy")
        try:
            last_error: Exception | None = None
            for attempt in range(max_retries):
                wait = self._min_interval - (time.monotonic() - self._last_call)
                if wait > 0:
                    self._sleep(wait)
                try:
                    return result_sets_to_rows(fetch(attempt))
                except (
                    requests.RequestException,
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ) as exc:
                    last_error = exc
                    logger.warning(
                        "%s failed (attempt %d/%d): %s", description, attempt + 1, max_retries, exc
                    )
                    if attempt + 1 < max_retries:
                        self._sleep(2 ** (attempt + 1))
                finally:
                    self._last_call = time.monotonic()
            raise NbaApiError(f"{description} failed after {max_retries} attempts") from last_error
        finally:
            self._lock.release()

    def player_game_logs(
        self,
        season: str,
        season_type: str,
        date_from: date | None = None,
        date_to: date | None = None,
        retries: int | None = None,
    ) -> list[Row]:
        window = f" {date_from}..{date_to}" if date_from or date_to else ""
        sets = self._call(
            f"game logs {season} {season_type}{window}",
            lambda attempt: leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star=season_type,
                player_or_team_abbreviation="P",
                date_from_nullable=_format_date(date_from),
                date_to_nullable=_format_date(date_to),
                counter=attempt,
                timeout=self._timeout,
            ).get_dict(),
            retries=retries,
        )
        return sets.get("LeagueGameLog", [])

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
