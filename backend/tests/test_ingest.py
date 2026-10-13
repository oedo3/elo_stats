import json
from datetime import date

import pytest

from elo_stats.db import open_db
from elo_stats.elo import EloParams
from elo_stats.ingest import (
    FetchOptions,
    compute_ratings,
    current_season_start,
    fetch_seasons,
    has_started,
    load_games,
    missing_seasons,
    parse_game_log_row,
    parse_minutes,
    record_missing,
    season_bounds,
    season_label,
    store_game_logs,
)
from elo_stats.text import normalize_name
from tests.conftest import FakeClient, all_rows_by_season, log_row


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0.0),
        ("", 0.0),
        (34, 34.0),
        (33.5, 33.5),
        ("36:30", 36.5),
        ("12", 12.0),
        (-3, 0.0),
        ("nan", 0.0),
        (float("inf"), 0.0),
    ],
)
def test_parse_minutes(raw, expected):
    assert parse_minutes(raw) == pytest.approx(expected)


def test_season_label():
    assert season_label(1996) == "1996-97"
    assert season_label(1999) == "1999-00"
    assert season_label(2025) == "2025-26"


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 10, 4), 2026), (date(2026, 9, 30), 2025), (date(2026, 1, 15), 2025)],
)
def test_current_season_start(today, expected):
    assert current_season_start(today) == expected


def test_normalize_name_strips_accents():
    assert normalize_name("Nikola Jokić") == "nikola jokic"
    assert normalize_name("  Luka DONČIĆ ") == "luka doncic"


class TestParseRow:
    def test_home_and_result(self):
        row = log_row("g", "2024-01-01", 1, 2, True, True, 7, "X")
        parsed = parse_game_log_row(row, 2023, "Regular Season")
        assert parsed["is_home"] == 1 and parsed["won"] == 1 and parsed["season"] == 2023

    def test_away(self):
        row = log_row("g", "2024-01-01", 1, 2, False, False, 7, "X")
        assert parse_game_log_row(row, 2023, "Regular Season")["is_home"] == 0

    def test_rejects_missing_result(self):
        row = {**log_row("g", "2024-01-01", 1, 2, True, True, 7, "X"), "WL": None}
        assert parse_game_log_row(row, 2023, "Regular Season") is None

    def test_rejects_malformed(self):
        row = {**log_row("g", "2024-01-01", 1, 2, True, True, 7, "X"), "PLAYER_ID": "abc"}
        assert parse_game_log_row(row, 2023, "Regular Season") is None


class TestSeasonBounds:
    def test_regular_season_runs_october_to_august(self):
        assert season_bounds(2019, "Regular Season") == (date(2019, 10, 1), date(2020, 8, 31))

    def test_playoffs_run_april_to_october(self):
        assert season_bounds(2019, "Playoffs") == (date(2020, 4, 1), date(2020, 10, 31))

    def test_has_started(self):
        assert has_started(2026, "Regular Season", date(2026, 10, 4))
        assert not has_started(2026, "Playoffs", date(2026, 10, 4))


REGULAR = ["Regular Season"]


class TestFetch:
    def test_uses_bulk_endpoint_when_it_works(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            assert fetch_seasons(conn, client, [2023], REGULAR) == []
            stored = conn.execute("SELECT COUNT(*) FROM player_games").fetchone()[0]
        assert stored == len(all_rows_by_season()[2023])
        assert [c[0] for c in client.calls] == ["logs"]

    def test_falls_back_to_box_scores(self, tmp_path):
        client = FakeClient(all_rows_by_season(), fail_full_season=True)
        with open_db(tmp_path / "db.sqlite3") as conn:
            assert fetch_seasons(conn, client, [2023], REGULAR) == []
            rows = conn.execute(
                "SELECT game_id, player_id, is_home, won, minutes, pts FROM player_games"
                " ORDER BY game_id, player_id"
            ).fetchall()
            complete = conn.execute("SELECT row_count FROM fetched_seasons").fetchone()[0]
        expected = sorted(
            (
                r["GAME_ID"],
                r["PLAYER_ID"],
                int(" vs. " in r["MATCHUP"]),
                int(r["WL"] == "W"),
                float(r["MIN"]),
                r["PTS"],
            )
            for r in all_rows_by_season()[2023]
        )
        assert [tuple(r) for r in rows] == expected
        assert complete == len(expected)
        assert {c[0] for c in client.calls} == {"logs", "schedule", "box"}

    def test_box_score_progress_survives_failures(self, tmp_path):
        rows = all_rows_by_season()
        flaky = FakeClient(rows, fail_full_season=True, fail_games={"0022300002"})
        with open_db(tmp_path / "db.sqlite3") as conn:
            assert fetch_seasons(conn, flaky, [2023], REGULAR) == ["2023-24 Regular Season"]
            assert (
                conn.execute("SELECT COUNT(DISTINCT game_id) FROM player_games").fetchone()[0] == 1
            )
            assert missing_seasons(conn, [2023], REGULAR) == ["2023-24 Regular Season"]

            healthy = FakeClient(rows, fail_full_season=True)
            assert fetch_seasons(conn, healthy, [2023], REGULAR) == []
            assert [c[1] for c in healthy.calls if c[0] == "box"] == ["0022300002"]
            assert missing_seasons(conn, [2023], REGULAR) == []

    def test_box_scores_only_option(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2023], REGULAR, options=FetchOptions(try_bulk=False))
        assert "logs" not in {c[0] for c in client.calls}

    def test_skips_cached_seasons_but_refetches_live(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2023, 2024], REGULAR, live_season=2024)
            first_calls = len(client.calls)
            fetch_seasons(conn, client, [2023, 2024], REGULAR, live_season=2024)
            second_calls = client.calls[first_calls:]
        assert {c[1] for c in second_calls} == {"2024-25"}

    def test_skips_season_types_that_have_not_started(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            failed = fetch_seasons(conn, client, [2026], live_season=2026, today=date(2026, 10, 4))
            assert failed == []
            assert [c[2] for c in client.calls] == ["Regular Season"]
            assert missing_seasons(conn, [2026], today=date(2026, 10, 4)) == []

    def test_failed_season_is_skipped_and_reported(self, tmp_path):
        all_games = {r["GAME_ID"] for r in all_rows_by_season()[2023]}
        client = FakeClient(all_rows_by_season(), fail_full_season=True, fail_games=all_games)
        with open_db(tmp_path / "db.sqlite3") as conn:
            failed = fetch_seasons(conn, client, [2023], ["Regular Season"])
            assert failed == ["2023-24 Regular Season"]
            assert conn.execute("SELECT COUNT(*) FROM player_games").fetchone()[0] == 0
            assert missing_seasons(conn, [2023], ["Regular Season"]) == failed

    def test_missing_seasons_lists_uncached_oldest_first(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2024], ["Regular Season"])
            missing = missing_seasons(conn, [2024, 2022, 2023], ["Regular Season"])
            record_missing(conn, missing)
            stored = conn.execute("SELECT value FROM meta WHERE key='missing_seasons'").fetchone()
        assert missing == ["2022-23 Regular Season", "2023-24 Regular Season"]
        assert json.loads(stored[0]) == missing

    def test_refetches_seasons_downloaded_before_they_ended(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2023], ["Regular Season"])
            conn.execute("UPDATE fetched_seasons SET fetched_at = '2024-03-01T00:00:00+00:00'")
            conn.commit()
            before = len(client.calls)
            fetch_seasons(conn, client, [2023], ["Regular Season"])
        assert len(client.calls) == before + 1

    def test_refetches_empty_downloads(self, tmp_path):
        client = FakeClient({})
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2023], ["Regular Season"])
            fetch_seasons(conn, client, [2023], ["Regular Season"])
        assert len(client.calls) == 2

    def test_refresh_refetches_everything(self, tmp_path):
        client = FakeClient(all_rows_by_season())
        with open_db(tmp_path / "db.sqlite3") as conn:
            fetch_seasons(conn, client, [2023], live_season=2024)
            before = len(client.calls)
            fetch_seasons(conn, client, [2023], live_season=2024, refresh=True)
        assert len(client.calls) > before


class TestCompute:
    def test_rates_every_game(self, seeded_db):
        with open_db(seeded_db) as conn:
            assert compute_ratings(conn, EloParams()) == 3
            assert conn.execute("SELECT COUNT(*) FROM player_ratings").fetchone()[0] == 15
            assert conn.execute("SELECT COUNT(*) FROM elo_history").fetchone()[0] == 30

    def test_recompute_is_idempotent(self, seeded_db):
        with open_db(seeded_db) as conn:
            before = conn.execute("SELECT rating FROM player_ratings ORDER BY player_id").fetchall()
            compute_ratings(conn, EloParams())
            after = conn.execute("SELECT rating FROM player_ratings ORDER BY player_id").fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after]

    def test_summary_tracks_games_and_team(self, seeded_db):
        with open_db(seeded_db) as conn:
            row = conn.execute("SELECT * FROM player_ratings WHERE player_id = 203999").fetchone()
        assert row["games"] == 3
        assert row["last_season"] == 2024
        assert row["team_abbr"] == "AAA"
        assert row["search_name"] == "nikola jokic"
        assert row["peak_rating"] >= row["rating"]

    def test_writes_meta(self, seeded_db):
        with open_db(seeded_db) as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["first_season"] == "2023"
        assert meta["last_game_date"] == "2024-11-01"

    def test_load_games_skips_one_sided_games(self, tmp_path):
        rows = [log_row("lonely", "2024-01-01", 1, 2, True, True, 7, "X")]
        with open_db(tmp_path / "db.sqlite3") as conn:
            store_game_logs(conn, rows, 2023, "Regular Season")
            assert list(load_games(conn)) == []
