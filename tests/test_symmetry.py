import pandas as pd

from lotg_stats.compute import build_team_game_table


def test_wins_losses_symmetry():
    games = pd.DataFrame(
        {
            "season": ["2025"] * 2,
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "home_team": ["A", "B"],
            "away_team": ["B", "A"],
            "home_score": [80, 70],
            "away_score": [70, 90],
        }
    )
    team_games = build_team_game_table(games)
    assert int(team_games["is_win"].sum()) == int((~team_games["is_win"]).sum())
