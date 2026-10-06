"""Write data/struck_game_stats.csv: the real stat lines of the games nflverse
struck (see lotg_support.struck_games), in nflverse's stats_player_week schema.

Source: Sleeper's stats API for that week (the stats the league scored), joined
to nflverse's weekly rosters for team / position / names and to the
DynastyProcess id map for gsis ids. One row per player with a countable stat —
nflverse's own event-list rule. `fantasy_points_ppr` is computed the nflverse
way from the stat line and checked against Sleeper's `pts_ppr`.

Run once (the output is committed): python scripts/struck_game_stats.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support.struck_games import STATS_CSV, STRUCK_GAMES  # noqa: E402

# Sleeper stat key -> nflverse stats_player_week column
MAP = {
    "pass_cmp": "completions", "pass_att": "attempts", "pass_yd": "passing_yards",
    "pass_td": "passing_tds", "pass_int": "passing_interceptions", "pass_sack": "sacks_suffered",
    "pass_sack_yds": "sack_yards_lost", "pass_air_yd": "passing_air_yards",
    "pass_fd": "passing_first_downs", "pass_2pt": "passing_2pt_conversions",
    "rush_att": "carries", "rush_yd": "rushing_yards", "rush_td": "rushing_tds",
    "rush_fd": "rushing_first_downs", "rush_2pt": "rushing_2pt_conversions",
    "rec": "receptions", "rec_tgt": "targets", "rec_yd": "receiving_yards", "rec_td": "receiving_tds",
    "rec_air_yd": "receiving_air_yards", "rec_yar": "receiving_yards_after_catch",
    "rec_fd": "receiving_first_downs", "rec_2pt": "receiving_2pt_conversions",
    "fum": "rushing_fumbles", "fum_lost": "rushing_fumbles_lost",
    "kr": "kickoff_returns", "kr_yd": "kickoff_return_yards",
    "pr": "punt_returns", "pr_yd": "punt_return_yards",
    "fgm": "fg_made", "fga": "fg_att", "fgm_20_29": "fg_made_20_29", "fgm_lng": "fg_long",
    "xpm": "pat_made", "xpa": "pat_att",
    "idp_tkl_solo": "def_tackles_solo", "idp_tkl_ast": "def_tackle_assists",
    "idp_sack": "def_sacks", "idp_int": "def_interceptions", "idp_pass_def": "def_pass_defended",
    "idp_ff": "def_fumbles_forced", "idp_tkl_loss": "def_tackles_for_loss",
    "penalty": "penalties", "penalty_yd": "penalty_yards",
}


def ppr(r: dict) -> float:
    g = lambda k: float(r.get(k) or 0)  # noqa: E731
    return round(0.04 * g("passing_yards") + 4 * g("passing_tds") - 2 * g("passing_interceptions")
                 + 0.1 * (g("rushing_yards") + g("receiving_yards")) + 6 * (g("rushing_tds") + g("receiving_tds"))
                 + g("receptions") - 2 * g("rushing_fumbles_lost")
                 + 2 * (g("passing_2pt_conversions") + g("rushing_2pt_conversions") + g("receiving_2pt_conversions")), 2)


def main() -> None:
    dp = pd.read_csv(_ROOT / ".cache" / "dynastyprocess_playerids.csv", low_memory=False)
    s2g = dict(zip(dp["sleeper_id"].astype(str).str.replace(r"\.0$", "", regex=True), dp["gsis_id"]))
    out, problems = [], []
    for game in STRUCK_GAMES:
        season, week = game["season"], game["week"]
        url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
        stats = json.load(urllib.request.urlopen(url, timeout=60))
        ros = pd.read_csv(_ROOT / ".cache" / f"nflverse_weekly_rosters_{season}.csv", low_memory=False)
        teams = (game["away_team"], game["home_team"])
        ros = ros[(ros["week"] == week) & ros["team"].isin(teams)].set_index("gsis_id")
        for sid, s in stats.items():
            gsis = s2g.get(sid)
            if gsis not in ros.index or not s.get("gp"):
                continue
            line = {MAP[k]: v for k, v in s.items() if k in MAP and v}
            if not line:
                continue          # dressed, recorded nothing: not in an event list
            p = ros.loc[gsis]
            team = p["team"]
            row = {"player_id": gsis, "player_name": f"{str(p['first_name'])[:1]}.{p['last_name']}",
                   "player_display_name": p["full_name"], "position": p["position"],
                   "position_group": p.get("depth_chart_position", p["position"]),
                   "season": season, "week": week, "season_type": "REG", "game_id": game["game_id"],
                   "team": team, "opponent_team": teams[1] if team == teams[0] else teams[0], **line}
            row["fantasy_points_ppr"] = ppr(row)
            row["fantasy_points"] = round(row["fantasy_points_ppr"] - float(row.get("receptions") or 0), 2)
            # Sleeper's pts_ppr scores kicking; nflverse's PPR does not.
            if p["position"] != "K" and s.get("pts_ppr") is not None and abs(row["fantasy_points_ppr"] - float(s["pts_ppr"])) > 0.005:
                problems.append((row["player_display_name"], row["fantasy_points_ppr"], s["pts_ppr"]))
            out.append(row)
    df = pd.DataFrame(out)
    # nflverse's team shares, from the team's totals in the game.
    for c in ("targets", "receiving_air_yards"):
        if c not in df.columns:
            df[c] = 0.0
        df[c] = df[c].fillna(0.0)
    tot = df.groupby(["game_id", "team"])[["targets", "receiving_air_yards"]].transform("sum")
    df["target_share"] = (df["targets"] / tot["targets"]).where(tot["targets"] > 0, 0.0).round(4)
    df["air_yards_share"] = (df["receiving_air_yards"] / tot["receiving_air_yards"]) \
        .where(tot["receiving_air_yards"] > 0, 0.0).round(4)
    df["wopr"] = (1.5 * df["target_share"] + 0.7 * df["air_yards_share"]).round(4)
    df = df.sort_values(["game_id", "team", "position", "player_display_name"])
    df.to_csv(STATS_CSV, index=False)
    print(f"{len(df)} rows -> {STATS_CSV.relative_to(_ROOT)}")
    if problems:
        raise SystemExit(f"PPR disagrees with Sleeper: {problems}")


if __name__ == "__main__":
    main()
