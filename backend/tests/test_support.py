from datetime import UTC, datetime, timedelta

import pytest
import requests

from elo_stats import repository
from elo_stats.config import load_settings
from elo_stats.db import open_db
from elo_stats.nba_client import NbaApiError, NbaStatsClient, result_sets_to_rows
from elo_stats.ratelimit import RateLimiter


class TestResultSets:
    def test_list_shape(self):
        payload = {"resultSets": [{"name": "A", "headers": ["X", "Y"], "rowSet": [[1, 2]]}]}
        assert result_sets_to_rows(payload) == {"A": [{"X": 1, "Y": 2}]}

    def test_single_result_set_shape(self):
        payload = {"resultSet": {"name": "B", "headers": ["X"], "rowSet": [[3]]}}
        assert result_sets_to_rows(payload) == {"B": [{"X": 3}]}

    def test_bad_shape(self):
        with pytest.raises(NbaApiError):
            result_sets_to_rows({"nope": 1})


class TestClientRetries:
    def test_retries_with_new_attempt_index_then_succeeds(self):
        sleeps: list[float] = []
        client = NbaStatsClient(min_interval=0, sleep=sleeps.append)
        attempts: list[int] = []

        def fetch(attempt):
            attempts.append(attempt)
            if attempt < 2:
                raise requests.ConnectionError("nope")
            return {"resultSets": [{"name": "A", "headers": ["X"], "rowSet": [[1]]}]}

        assert client._call("test", fetch) == {"A": [{"X": 1}]}
        assert attempts == [0, 1, 2]
        assert sleeps == [2, 4]

    def test_gives_up(self):
        client = NbaStatsClient(min_interval=0, max_retries=2, sleep=lambda _s: None)

        def fetch(_attempt):
            raise ValueError("bad json")

        with pytest.raises(NbaApiError, match="after 2 attempts"):
            client._call("test", fetch)

    def test_busy_client_fails_fast(self):
        client = NbaStatsClient(min_interval=0, lock_timeout=0.01)
        client._lock.acquire()
        try:
            with pytest.raises(NbaApiError, match="busy"):
                client._call("test", lambda _a: {})
        finally:
            client._lock.release()

    def test_malformed_payload_is_an_api_error(self):
        client = NbaStatsClient(min_interval=0, max_retries=1, sleep=lambda _s: None)
        bad = {"resultSets": [{"name": "A", "headers": None, "rowSet": [[1]]}]}
        with pytest.raises(NbaApiError):
            client._call("test", lambda _a: bad)


class TestRateLimiter:
    def test_window_slides(self):
        now = [0.0]
        limiter = RateLimiter(2, window_seconds=60, clock=lambda: now[0])
        assert limiter.allow("a") and limiter.allow("a")
        assert not limiter.allow("a")
        assert limiter.allow("b")
        now[0] = 61
        assert limiter.allow("a")


class TestCache:
    def test_round_trip_and_expiry(self, tmp_path):
        with open_db(tmp_path / "db.sqlite3") as conn:
            repository.cache_put(conn, "k", {"v": 1})
            assert repository.cache_get(conn, "k", timedelta(hours=1)) == {"v": 1}
            stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
            conn.execute("UPDATE api_cache SET fetched_at = ?", (stale,))
            assert repository.cache_get(conn, "k", timedelta(hours=1)) is None
            assert repository.cache_get(conn, "missing", timedelta(hours=1)) is None


class TestSettings:
    def test_env_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ELO_STATS_DB", str(tmp_path / "x.db"))
        monkeypatch.setenv("ELO_STATS_CORS_ORIGINS", "https://a.example, https://b.example")
        monkeypatch.setenv("ELO_STATS_RATE_LIMIT_PER_MINUTE", "5")
        settings = load_settings()
        assert settings.db_path == tmp_path / "x.db"
        assert settings.cors_origins == ("https://a.example", "https://b.example")
        assert settings.rate_limit_per_minute == 5

    @pytest.mark.parametrize("value", ["abc", "0", "-1"])
    def test_rejects_bad_integers(self, monkeypatch, value):
        monkeypatch.setenv("ELO_STATS_CACHE_TTL_HOURS", value)
        with pytest.raises(ValueError, match="ELO_STATS_CACHE_TTL_HOURS"):
            load_settings()
