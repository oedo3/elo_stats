import pytest

from elo_stats.boxscores import box_score_rows, scheduled_games
from elo_stats.nba_client import parse_box_score, parse_schedule


def player(pid, first, last, minutes, points):
    return {
        "personId": pid,
        "firstName": first,
        "familyName": last,
        "statistics": {
            "minutes": minutes,
            "points": points,
            "reboundsTotal": 4,
            "assists": 2,
            "plusMinusPoints": 3.0,
        },
    }


BOX = {
    "gameId": "0029600001",
    "homeTeam": {
        "teamId": 1610612738,
        "teamTricode": "BOS",
        "statistics": {"points": 107},
        "players": [player(1, "Dino", "Radja", "36:12", 20), player(2, "Bench", "Guy", "", 0)],
    },
    "awayTeam": {
        "teamId": 1610612741,
        "teamTricode": "CHI",
        "statistics": {"points": 98},
        "players": [player(23, "Michael", "Jordan", "40:00", 33)],
    },
}


class TestBoxScoreRows:
    def test_converts_to_game_log_rows(self):
        rows = box_score_rows(BOX, "1996-11-01")
        assert [(r["PLAYER_NAME"], r["MATCHUP"], r["WL"]) for r in rows] == [
            ("Dino Radja", "BOS vs. CHI", "W"),
            ("Michael Jordan", "CHI @ BOS", "L"),
        ]
        assert rows[0]["GAME_DATE"] == "1996-11-01"
        assert rows[0]["MIN"] == "36:12" and rows[1]["PTS"] == 33

    def test_skips_players_who_did_not_play(self):
        assert all(r["PLAYER_ID"] != 2 for r in box_score_rows(BOX, "1996-11-01"))

    def test_falls_back_to_summing_player_points(self):
        box = {**BOX, "homeTeam": {**BOX["homeTeam"], "statistics": {}}}
        rows = box_score_rows(box, "1996-11-01")
        assert {r["WL"] for r in rows if r["TEAM_ID"] == 1610612738} == {"L"}  # 20 < 98

    @pytest.mark.parametrize(
        "box",
        [
            {"gameId": "x", "homeTeam": {"teamId": 0}, "awayTeam": {"teamId": 0}},
            {"gameId": "x"},
            {
                **BOX,
                "awayTeam": {**BOX["awayTeam"], "statistics": {"points": 107}},
            },
        ],
    )
    def test_empty_or_undecided_games_yield_nothing(self, box):
        assert box_score_rows(box, "1996-11-01") == []


class TestSchedule:
    SCHEDULE = [
        {"game_id": "0019600001", "game_date": "1996-10-10", "status": 3},
        {"game_id": "0029600001", "game_date": "1996-11-01", "status": 3},
        {"game_id": "0029600002", "game_date": "1997-04-20", "status": 1},
        {"game_id": "0049600011", "game_date": "1997-04-26", "status": 3},
    ]

    def test_keeps_only_final_games_of_the_type(self):
        regular = scheduled_games(self.SCHEDULE, "Regular Season")
        assert [g["game_id"] for g in regular] == ["0029600001"]
        playoffs = scheduled_games(self.SCHEDULE, "Playoffs")
        assert [g["game_id"] for g in playoffs] == ["0049600011"]

    def test_skips_unplayed_if_necessary_placeholders(self):
        schedule = [
            *self.SCHEDULE,
            {"game_id": "0040401000", "game_date": "2005-06-27", "status": 0},
        ]
        assert [g["game_id"] for g in scheduled_games(schedule, "Playoffs")] == ["0049600011"]

    def test_parse_schedule(self):
        payload = {
            "leagueSchedule": {
                "gameDates": [
                    {
                        "games": [
                            {
                                "gameId": "0029600001",
                                "gameDateEst": "1996-11-01T00:00:00Z",
                                "gameStatus": 3,
                            }
                        ]
                    }
                ]
            }
        }
        assert parse_schedule(payload) == [
            {"game_id": "0029600001", "game_date": "1996-11-01", "status": 3}
        ]

    def test_parse_box_score_requires_body(self):
        assert parse_box_score({"boxScoreTraditional": BOX}) is BOX
        with pytest.raises(ValueError):
            parse_box_score({"boxScoreTraditional": None})
