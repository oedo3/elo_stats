import math

import pytest

from elo_stats.elo import (
    EloParams,
    Game,
    PlayerLine,
    TeamSide,
    expected_score,
    mov_multiplier,
    rate_game,
    run_elo,
    team_rating,
)

PARAMS = EloParams()


def make_side(team_id, player_ids, *, is_home, won, points, minutes=48):
    lines = tuple(PlayerLine(player_id=pid, minutes=minutes) for pid in player_ids)
    return TeamSide(team_id=team_id, is_home=is_home, won=won, points=points, lines=lines)


def make_game(game_id="g1", season=2020, date="2020-12-23", home_won=True, margin=10):
    home_pts, away_pts = (110, 110 - margin) if home_won else (110 - margin, 110)
    return Game(
        game_id=game_id,
        game_date=date,
        season=season,
        home=make_side(1, [11, 12, 13, 14, 15], is_home=True, won=home_won, points=home_pts),
        away=make_side(2, [21, 22, 23, 24, 25], is_home=False, won=not home_won, points=away_pts),
    )


class TestExpectedScore:
    def test_equal_ratings_is_half(self):
        assert expected_score(1500, 1500) == pytest.approx(0.5)

    def test_400_point_edge_is_ten_to_one(self):
        assert expected_score(1900, 1500) == pytest.approx(10 / 11)

    def test_symmetry(self):
        assert expected_score(1600, 1450) + expected_score(1450, 1600) == pytest.approx(1.0)


class TestMovMultiplier:
    def test_grows_with_margin(self):
        assert mov_multiplier(20, 0) > mov_multiplier(5, 0)

    def test_shrinks_when_favourite_wins(self):
        assert mov_multiplier(10, 200) < mov_multiplier(10, -200)

    def test_known_value(self):
        assert mov_multiplier(10, 0) == pytest.approx(13**0.8 / 7.5)


class TestTeamRating:
    def test_minutes_weighted(self):
        lines = (PlayerLine(1, minutes=30), PlayerLine(2, minutes=10))
        assert team_rating(lines, {1: 1600, 2: 1400}, 1500) == pytest.approx(1550)

    def test_unknown_players_use_initial_rating(self):
        lines = (PlayerLine(1, minutes=24), PlayerLine(2, minutes=24))
        assert team_rating(lines, {1: 1700}, 1500) == pytest.approx(1600)


class TestRateGame:
    def test_winners_gain_losers_lose(self):
        new = rate_game(make_game(home_won=True), {}, PARAMS)
        assert all(new[pid] > 1500 for pid in (11, 12, 13, 14, 15))
        assert all(new[pid] < 1500 for pid in (21, 22, 23, 24, 25))

    def test_zero_sum_for_full_minutes(self):
        new = rate_game(make_game(), {}, PARAMS)
        assert sum(r - 1500 for r in new.values()) == pytest.approx(0.0, abs=1e-9)

    def test_home_win_worth_less_than_away_win(self):
        home_win = rate_game(make_game(home_won=True), {}, PARAMS)[11] - 1500
        away_win = rate_game(make_game(home_won=False), {}, PARAMS)[21] - 1500
        assert away_win > home_win > 0

    def test_does_not_mutate_input_ratings(self):
        ratings = {11: 1550.0}
        rate_game(make_game(), ratings, PARAMS)
        assert ratings == {11: 1550.0}

    def test_bench_player_moves_less_than_starter(self):
        game = make_game()
        lines = (PlayerLine(11, minutes=40), PlayerLine(12, minutes=8)) + game.home.lines[2:]
        game = Game(
            game_id=game.game_id,
            game_date=game.game_date,
            season=game.season,
            home=TeamSide(1, True, True, game.home.points, lines),
            away=game.away,
        )
        new = rate_game(game, {}, PARAMS)
        assert (new[11] - 1500) > (new[12] - 1500) > 0

    def test_zero_minute_players_are_not_rated(self):
        game = make_game()
        lines = game.home.lines + (PlayerLine(99, minutes=0),)
        game = Game(
            game_id="g",
            game_date="2020-12-23",
            season=2020,
            home=TeamSide(1, True, True, game.home.points, lines),
            away=game.away,
        )
        assert 99 not in rate_game(game, {}, PARAMS)

    def test_known_delta(self):
        # Equal teams, home wins by 10: E_home = 1/(1+10^(-100/400)).
        new = rate_game(make_game(margin=10), {}, PARAMS)
        e_home = 1 / (1 + math.pow(10, -100 / 400))
        mult = mov_multiplier(10, 100)
        assert new[11] - 1500 == pytest.approx(PARAMS.k_factor * mult * (1 - e_home))


class TestRunElo:
    def test_yields_one_update_per_player_per_game(self):
        updates = list(run_elo([make_game("a"), make_game("b", date="2020-12-25")], PARAMS))
        assert len(updates) == 20
        assert {u.game_id for u in updates} == {"a", "b"}

    def test_ratings_chain_between_games(self):
        updates = list(run_elo([make_game("a"), make_game("b", date="2020-12-25")], PARAMS))
        first, second = [u for u in updates if u.player_id == 11]
        assert second.rating_before == pytest.approx(first.rating_after)

    def test_new_season_regresses_toward_mean(self):
        games = [make_game("a", season=2020), make_game("b", season=2021, date="2021-10-20")]
        updates = [u for u in run_elo(games, PARAMS) if u.player_id == 11]
        after_first = updates[0].rating_after
        expected = after_first + (PARAMS.initial_rating - after_first) * PARAMS.season_reversion
        assert updates[1].rating_before == pytest.approx(expected)

    def test_records_opponent(self):
        update = next(u for u in run_elo([make_game()], PARAMS) if u.player_id == 21)
        assert (update.team_id, update.opponent_team_id, update.won) == (2, 1, False)
