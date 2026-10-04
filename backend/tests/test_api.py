from fastapi.testclient import TestClient

from elo_stats.api import create_app
from tests.conftest import FakeClient, make_settings


def ok(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True and body["error"] is None
    return body["data"]


def failed(response, status):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is False and body["data"] is None and body["error"]
    return body["error"]


def test_health(api):
    assert ok(api.get("/api/health")) == {"status": "ok", "has_data": True}


def test_meta(api):
    data = ok(api.get("/api/meta"))
    assert data["has_data"] is True
    assert (data["first_season"], data["last_season"]) == (2023, 2024)
    assert data["elo_params"]["k_factor"] == 20.0
    assert data["missing_seasons"] == []


def test_meta_reports_missing_seasons(api, seeded_db):
    from elo_stats.db import open_db
    from elo_stats.ingest import record_missing

    with open_db(seeded_db) as conn:
        record_missing(conn, ["1996-97 Playoffs"])
    assert ok(api.get("/api/meta"))["missing_seasons"] == ["1996-97 Playoffs"]


def test_empty_database_returns_503_with_instructions(tmp_path):
    app = create_app(make_settings(tmp_path / "empty.sqlite3"), client=FakeClient())
    with TestClient(app) as client:
        assert ok(client.get("/api/health"))["has_data"] is False
        assert "elo_stats.ingest" in failed(client.get("/api/leaderboard"), 503)


class TestSearch:
    def test_accent_insensitive(self, api):
        data = ok(api.get("/api/players/search", params={"q": "jokic"}))
        assert [p["player_name"] for p in data] == ["Nikola Jokić"]

    def test_prefix_matches_rank_first(self, api):
        data = ok(api.get("/api/players/search", params={"q": "bravo"}))
        assert len(data) == 5 and all(p["player_name"].startswith("Bravo") for p in data)

    def test_query_too_short_after_normalizing(self, api):
        failed(api.get("/api/players/search", params={"q": " ́a "}), 422)

    def test_like_wildcards_are_literal(self, api):
        assert ok(api.get("/api/players/search", params={"q": "%%"})) == []

    def test_query_too_short(self, api):
        assert "q" in failed(api.get("/api/players/search", params={"q": "a"}), 422)

    def test_limit(self, api):
        assert len(ok(api.get("/api/players/search", params={"q": "player", "limit": 3}))) == 3


class TestPlayer:
    def test_active_player_has_rank(self, api):
        data = ok(api.get("/api/players/203999"))
        assert data["is_active"] is True
        assert data["active_rank"] >= 1
        assert data["games"] == 3

    def test_inactive_player_has_no_active_rank(self, api):
        data = ok(api.get("/api/players/301"))
        assert data["is_active"] is False and data["active_rank"] is None

    def test_unknown_player(self, api):
        failed(api.get("/api/players/999999"), 404)

    def test_invalid_id(self, api):
        failed(api.get("/api/players/0"), 422)

    def test_elo_history_is_chronological_and_chained(self, api):
        response = api.get("/api/players/203999/elo")
        history = ok(response)
        assert [h["game_date"] for h in history] == ["2023-11-01", "2023-11-03", "2024-11-01"]
        assert history[0]["rating_before"] == 1500.0
        assert history[1]["rating_before"] == history[0]["rating_after"]
        assert response.json()["meta"] == {"total": 3}


class TestLeaderboard:
    def test_active_only_excludes_old_players(self, api):
        data = ok(api.get("/api/leaderboard", params={"min_games": 0}))
        assert {p["player_id"] // 100 for p in data if p["player_id"] < 1000} <= {1, 2}
        assert all(p["last_season"] == 2024 for p in data)

    def test_sorted_and_ranked(self, api):
        data = ok(api.get("/api/leaderboard", params={"min_games": 0, "active_only": False}))
        ratings = [p["rating"] for p in data]
        assert ratings == sorted(ratings, reverse=True)
        assert [p["rank"] for p in data] == list(range(1, len(data) + 1))

    def test_peak_sort(self, api):
        data = ok(api.get("/api/leaderboard", params={"sort": "peak", "min_games": 0}))
        peaks = [p["peak_rating"] for p in data]
        assert peaks == sorted(peaks, reverse=True)

    def test_rejects_unknown_sort(self, api):
        failed(api.get("/api/leaderboard", params={"sort": "name; DROP TABLE"}), 422)

    def test_min_games_filters(self, api):
        assert ok(api.get("/api/leaderboard", params={"min_games": 4})) == []


class TestBioAndCareer:
    def test_bio_is_shaped_and_cached(self, api, fake_client):
        first = ok(api.get("/api/players/203999/bio"))
        second = ok(api.get("/api/players/203999/bio"))
        assert first == second
        assert first["position"] == "Center" and first["weight"] == 284
        assert first["school"] is None and first["birthdate"] == "1995-02-19"
        assert first["team_name"] == "Denver Nuggets"
        assert [c for c in fake_client.calls if c[0] == "info"] == [("info", 203999)]

    def test_unrated_players_never_reach_upstream(self, api, fake_client):
        failed(api.get("/api/players/12345/bio"), 404)
        failed(api.get("/api/players/12345/career"), 404)
        assert fake_client.calls == []

    def test_cache_write_failure_does_not_fail_request(self, api, monkeypatch):
        import sqlite3

        from elo_stats import repository

        def busy(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(repository.json, "dumps", busy)
        assert ok(api.get("/api/players/203999/career"))["playoffs"]["career"] is None

    def test_upstream_failure_is_502(self, seeded_db):
        app = create_app(make_settings(seeded_db), client=FakeClient(fail_info=True))
        with TestClient(app) as client:
            assert "unavailable" in failed(client.get("/api/players/203999/bio"), 502)

    def test_career_per_game_and_efficiency(self, api):
        data = ok(api.get("/api/players/203999/career"))
        season = data["regular_season"]["seasons"][0]
        assert season["ppg"] == 30.0 and season["rpg"] == 12.0 and season["mpg"] == 35.0
        assert season["efg_pct"] == 0.6  # (110 + 0.5*20) / 200
        assert season["ts_pct"] == round(300 / (2 * (200 + 0.44 * 75)), 3)
        assert data["regular_season"]["career"]["season"] == "Career"
        assert data["playoffs"] == {"seasons": [], "career": None}


def test_rate_limit(seeded_db):
    app = create_app(make_settings(seeded_db, rate_limit=2), client=FakeClient())
    with TestClient(app) as client:
        ok(client.get("/api/health"))
        ok(client.get("/api/health"))
        failed(client.get("/api/health"), 429)


def test_rate_limited_responses_keep_cors_headers(seeded_db):
    app = create_app(make_settings(seeded_db, rate_limit=1), client=FakeClient())
    origin = {"Origin": "http://localhost:5173"}
    with TestClient(app) as client:
        client.get("/api/health", headers=origin)
        response = client.get("/api/health", headers=origin)
    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_concurrent_requests_share_nothing(seeded_db):
    import asyncio

    import httpx

    app = create_app(make_settings(seeded_db), client=FakeClient())

    async def hammer():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(client.get("/api/players/203999") for _ in range(200))
            )
        return {r.status_code for r in responses}

    assert asyncio.run(hammer()) == {200}


def test_cors_allows_configured_origin(api):
    response = api.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
