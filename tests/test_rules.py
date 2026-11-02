"""Rule-change simulator (`lotg_support.rules`): spec, engine, guards.

The load-bearing tests are `test_empty_spec_reproduces_every_completed_season`
(the real rules replayed reproduce every record, PF, bracket and champion, and
the optimal routine reproduces `Max PF`) and
`test_scoring_delta_equals_the_build_scorer` (moving a player-week by the
changed keys is exactly what the build's `_league_score` says the new table is
worth). Everything else is the spec algebra, the bracket and the lineup rules.

Data tests SKIP cleanly without the committed exports/snapshot/.cache.

Run: python tests/test_rules.py
"""
from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import rules as RC  # noqa: E402

_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())
_HAVE_STATS = (_ROOT / ".cache" / "nflverse_stats_player_week_2025.csv").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------
def test_spec_round_trips_and_refuses_typos():
    blob = {"name": "x", "seasons": "2021-2023",
            "scoring": {"set": {"rec": 0.5}, "add": {"bonus_rec_te": 0.5}, "scale": {"pass_yd": 2}},
            "lineup": {"add": ["FLEX"], "remove": ["SUPER_FLEX"]},
            "playoffs": {"teams": 6, "byes": 2, "median_game": True, "home_bonus": 0}}
    spec = RC.spec_from_dict(blob)
    assert spec.seasons == (2021, 2022, 2023)
    assert spec.scoring == {"rec": (0.0, 0.5), "bonus_rec_te": (1.0, 0.5), "pass_yd": (2.0, 0.0)}
    again = RC.spec_from_dict(RC.spec_to_dict(spec))
    assert RC.spec_to_dict(again) == RC.spec_to_dict(spec)
    for bad in ({"scoring": {"set": {"recs": 1}}}, {"lineups": {}}, {"lineup": {"add": ["FLX"]}},
                {"playoffs": {"teams": 9}}, {"playoffs": {"seeding": "coin"}}):
        try:
            RC.spec_from_dict(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_compose_is_affine_per_key_and_later_wins_elsewhere():
    a = RC.spec_from_dict({"name": "a", "scoring": {"add": {"rec": 0.5}}, "lineup": {"add": ["FLEX"]},
                           "playoffs": {"teams": 6}})
    b = RC.spec_from_dict({"name": "b", "scoring": {"scale": {"rec": 2}}, "lineup": {"remove": ["SUPER_FLEX"]},
                           "playoffs": {"teams": 4, "median_game": True}})
    c = RC.compose(a, b)
    assert c.name == "a + b"
    a1, b1 = c.scoring["rec"]
    assert (a1 * 1.0 + b1) == (1.0 + 0.5) * 2          # (old + 0.5) * 2 on a PPR table
    assert c.slots_add == ("FLEX",) and c.slots_remove == ("SUPER_FLEX",)
    assert c.playoff_teams == 4 and c.median_game is True
    # a later set wins over an earlier add; an add cancelled by its opposite drops out
    s = RC.compose(a, RC.spec_from_dict({"scoring": {"set": {"rec": 0.25}}}))
    assert s.scoring["rec"] == (0.0, 0.25)
    z = RC.compose(a, RC.spec_from_dict({"scoring": {"add": {"rec": -0.5}}}))
    assert "rec" not in z.scoring
    # a later full template restarts the slot edits
    t = RC.compose(a, RC.spec_from_dict({"lineup": {"slots": ["QB", "RB", "WR"]}}))
    assert t.slots == ("QB", "RB", "WR") and not t.slots_add


def test_example_specs_load():
    specs = sorted((_ROOT / "plan" / "rule_specs").glob("*.json"))
    assert specs, "plan/rule_specs/ should carry the example specs"
    for path in specs:
        spec = RC.load_spec(path)
        assert not spec.is_empty, path.name


# ---------------------------------------------------------------------------
# Standings and bracket
# ---------------------------------------------------------------------------
def _fmt(**kw):
    base = dict(playoff_teams=4, regular_season_weeks=2, playoff_weeks=((3,), (4,)))
    base.update(kw)
    return RC.Format(**base)


def test_bracket_order_puts_top_seeds_apart():
    assert RC._bracket_order(4) == [1, 4, 2, 3]
    assert RC._bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]


def test_median_game_adds_a_result_every_week():
    names = {t: t for t in "abcd"}
    scores = {1: {"a": 100, "b": 90, "c": 80, "d": 70}, 2: {"a": 100, "b": 90, "c": 80, "d": 70}}
    pairs = {1: [("a", "b"), ("c", "d")], 2: [("a", "c"), ("b", "d")]}
    plain = {s.team: s.record for s in RC.standings(scores, pairs, names, _fmt())}
    med = {s.team: s.record for s in RC.standings(scores, pairs, names, _fmt(median_game=True))}
    assert plain == {"a": "2-0", "b": "1-1", "c": "1-1", "d": "0-2"}
    assert med == {"a": "4-0", "b": "3-1", "c": "1-3", "d": "0-4"}
    pts = RC.standings(scores, pairs, names, _fmt(seeding="points"))
    assert [s.team for s in pts] == ["a", "b", "c", "d"]


def test_six_team_bracket_gives_the_top_two_byes_and_the_bonus_in_the_semis():
    names = {t: t for t in "abcdefgh"}
    fmt = _fmt(playoff_teams=6, playoff_weeks=((3,), (4,), (5,)))
    assert fmt.byes == 2 and fmt.bracket_size == 8
    table = [Q_standing(t, 10 - i) for i, t in enumerate("abcdefgh")]
    # week 3: 6 beats 3, 4 beats 5; week 4: 1 v 4 decided by the +5, 2 v 6; week 5: final
    scores = {3: {"c": 90, "f": 95, "d": 100, "e": 80},
              4: {"a": 100, "d": 104, "b": 110, "f": 120},
              5: {"a": 130, "f": 120}}
    br = RC.bracket(scores, table, names, fmt)
    assert br.seeds == list("abcdef")
    assert [(g.round, g.high, g.low, g.winner) for g in br.games] == [
        (1, "d", "e", "d"), (1, "c", "f", "f"),
        (2, "a", "d", "a"), (2, "b", "f", "f"),
        (3, "a", "f", "a")]
    semi = [g for g in br.games if g.round == 2]
    assert semi[0].high_pts == 105.0 and semi[0].low_pts == 104.0   # +5 to the higher seed only
    assert br.champion == "a" and br.runner_up == "f" and br.complete
    none = RC.bracket(scores, table, names, _fmt(playoff_teams=6, playoff_weeks=((3,), (4,), (5,)),
                                                  home_bonus_round="none"))
    assert [g.winner for g in none.games if g.round == 2][0] == "d"


def Q_standing(team, wins):
    from lotg_support.replay import Standing
    return Standing(team, team, wins, 0, 0, 0.0)


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------
_TEMPLATE = (("QB",), ("RB",), ("RB",), ("WR",), ("WR",), ("WR",), ("TE",), ("RB", "WR", "TE"),
             ("QB", "RB", "WR", "TE"))


def _brute(points, pos, slots):
    best = 0.0
    players = list(points)
    for k in range(min(len(players), len(slots)), 0, -1):
        found = False
        for combo in itertools.combinations(players, k):
            for perm in itertools.permutations(range(len(slots)), k):
                if all(pos[p] in slots[i] for p, i in zip(combo, perm)):
                    best = max(best, sum(points[p] for p in combo)) if found else sum(points[p] for p in combo)
                    found = True
                    break
        if found:
            return best
    return best


def test_best_lineup_is_exact_against_brute_force():
    rng = random.Random(7)
    slots = (("QB",), ("RB",), ("WR",), ("RB", "WR", "TE"), ("QB", "RB", "WR", "TE"))
    for _ in range(40):
        pos = {f"p{i}": rng.choice("QB RB WR TE".split()) for i in range(8)}
        pts = {p: round(rng.uniform(-2, 30), 2) for p in pos}
        got, chosen = RC.best_lineup(pts, lambda p: frozenset({pos[p]}), slots)
        assert abs(got - _brute(pts, pos, slots)) < 1e-6, (pos, pts)


def test_best_lineup_matches_the_max_pf_routine_on_the_real_template():
    from lotg_support.lineup import compute_optimal_lineup
    rng = random.Random(11)
    slots = _TEMPLATE + (("RB", "WR", "TE"),)
    for _ in range(40):
        pos = {f"p{i}": rng.choice("QB QB RB RB RB WR WR WR WR TE TE".split()) for i in range(18)}
        pts = {p: round(rng.uniform(0, 35), 2) for p in pos}
        got, _ = RC.best_lineup(pts, lambda p: frozenset({pos[p]}), slots)
        assert abs(got - compute_optimal_lineup(pts, pos, 2024)) < 1e-6


def test_an_added_slot_is_filled_by_the_plausible_rule_and_never_by_a_rookie():
    pos = {"qb": "QB", "rb1": "RB", "rb2": "RB", "wr1": "WR", "wr2": "WR", "wr3": "WR", "te": "TE",
           "fx": "WR", "sf": "RB", "hot": "WR", "steady": "RB", "rookie": "WR", "cold": "TE"}
    elig = lambda p: frozenset({pos[p]})  # noqa: E731
    starters = ["qb", "rb1", "rb2", "wr1", "wr2", "wr3", "te", "fx", "sf"]
    roster = starters + ["hot", "steady", "rookie", "cold"]
    points = {p: 10.0 for p in starters}
    points.update(hot=40.0, steady=12.0, rookie=50.0, cold=30.0)
    form = {p: 10.0 for p in starters}
    form.update(hot=4.0, steady=11.0, rookie=None, cold=11.5)
    slots = _TEMPLATE + (("RB", "WR", "TE"),)
    total, lineup, benched, fillers = RC.adapt_lineup(
        starters, 0, roster, points, elig, slots, form.get, set())
    # options by form: cold 11.5, steady 11.0, hot 4.0 (rookie unproven, never moved in);
    # the bar is 11.5 - 5 = 6.5, so hot is not plausible; cold scored more than steady
    assert fillers == ["cold"] and not benched
    assert total == 90.0 + min(30.0, 1.5 * 11.5)
    # flagged out -> the next plausible option
    _, _, _, fillers = RC.adapt_lineup(starters, 0, roster, points, elig, slots, form.get, {"cold"})
    assert fillers == ["steady"]


def test_a_removed_slot_benches_a_plausible_starter_and_absorbs_empties_first():
    pos = {"qb": "QB", "rb1": "RB", "rb2": "RB", "wr1": "WR", "wr2": "WR", "wr3": "WR", "te": "TE",
           "fx": "WR", "sf": "QB"}
    elig = lambda p: frozenset({pos[p]})  # noqa: E731
    starters = list(pos)
    points = {p: 10.0 for p in pos}
    points.update(sf=25.0, fx=3.0)
    form = {p: 10.0 for p in pos}
    no_sf = _TEMPLATE[:-1]
    total, lineup, benched, _ = RC.adapt_lineup(starters, 0, starters, points, elig, no_sf, form.get, set())
    # one QB slot for two QBs: only qb or sf can sit; equal form, so the one who scored less
    assert benched == ["qb"]
    assert total == 88.0
    no_flex = _TEMPLATE[:7] + (_TEMPLATE[8],)
    _, _, benched, _ = RC.adapt_lineup(starters, 0, starters, points, elig, no_flex, form.get, set())
    assert benched == ["fx"]           # all equal form: the one who scored least
    _, lineup, benched, _ = RC.adapt_lineup(starters[:-1], 1, starters[:-1], points, elig, no_sf,
                                            form.get, set())
    assert not benched and len(lineup) == 8


# ---------------------------------------------------------------------------
# Against the data
# ---------------------------------------------------------------------------
def test_empty_spec_reproduces_every_completed_season():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    seasons = RC.history_seasons()
    assert 2020 in seasons and 2025 in seasons, seasons
    problems = RC.validate(seasons)
    assert not problems, "\n".join(problems[:20])


def test_real_formats_match_the_league_calendar():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    assert RC.real_format(2020).playoff_weeks == ((15,), (16,))
    assert RC.real_format(2020).regular_season_weeks == 14
    assert RC.real_format(2024).playoff_weeks == ((16,), (17,))
    assert RC.real_format(2026).playoff_weeks == ((15,), (16, 17))
    six = RC.scenario_format(2024, RC.spec_from_dict({"playoffs": {"teams": 6}}))
    assert six.regular_season_weeks == 14 and six.playoff_weeks == ((15,), (16,), (17,))
    one = RC.scenario_format(2026, RC.spec_from_dict({"playoffs": {"two_week_final": False}}))
    assert one.playoff_weeks == ((15,), (16,)) and one.regular_season_weeks == 14
    try:
        RC.scenario_format(2024, RC.spec_from_dict({"playoffs": {"teams": 6, "byes": 0}}))
    except ValueError:
        pass
    else:
        raise AssertionError("6 teams with 0 byes accepted")
    assert RC.real_slot_names(2023).count("FLEX") == 1 and RC.real_slot_names(2024).count("FLEX") == 2


def test_scoring_delta_equals_the_build_scorer():
    if not (_HAVE_DATA and _HAVE_STATS):
        return _skip("no exports or nflverse cache")
    spec = RC.spec_from_dict({"scoring": {"set": {"pass_td": 6, "rec": 0.5},
                                          "add": {"bonus_rec_te": 0.5, "bonus_rush_yd_100": 2}}})
    season = 2025
    score_map, bonus = RC._build_scoring()
    from lotg_support import wins_added as W
    W._src_on_path()
    import lotg
    old, new = RC.scoring_table(season), RC.scenario_table(season, spec)
    deltas = RC.score_deltas(season, spec)
    cols = tuple(sorted({c for cs in score_map.values() for c in cs} | {b[1] for b in bonus}))
    frame = RC._stat_frame(season, cols)
    bridge = RC._bridge()
    by_gsis = {}
    for sid, g in bridge.items():
        by_gsis.setdefault(g, []).append(sid)
    positions = Q.players().positions()
    checked = 0
    for row in frame.sample(n=min(4000, len(frame)), random_state=3).itertuples(index=False):
        rec = row._asdict()
        sids = by_gsis.get(rec["player_id"], [])
        if len(sids) != 1:
            continue
        stats = {c: rec[c] for c in cols}
        want = (lotg._league_score(stats, new, positions.get(sids[0]))
                - lotg._league_score(stats, old, positions.get(sids[0])))
        got = deltas.get((sids[0], int(rec["week"])), 0.0)
        assert abs(want - got) < 0.0151, (sids[0], rec["week"], want, got)
        checked += 1
    assert checked > 1000, checked


def test_a_no_op_scoring_change_moves_nothing():
    if not (_HAVE_DATA and _HAVE_STATS):
        return _skip("no exports or nflverse cache")
    current = RC.scoring_table(2024).get("rec", 0.0)
    run = RC.run_season(2024, RC.spec_from_dict({"scoring": {"set": {"rec": current}}}))
    base, scen = run.outcomes["actual"]
    assert base.scores == scen.scores


def test_an_added_flex_keeps_every_real_starter_and_lineups_stay_legal():
    if not (_HAVE_DATA and _HAVE_STATS):
        return _skip("no exports or nflverse cache")
    spec = RC.spec_from_dict({"lineup": {"add": ["FLEX"]}})
    run = RC.run_season(2023, spec)
    lg = RC.load_league()
    elig = RC._lineup_elig(lg, 2023)
    slots = RC.pools(run.slots)
    assert len(slots) == 10
    for (wk, team), (real, lineup) in run.lineups.items():
        assert set(real) <= set(lineup), (wk, team)
        m = RC._Matcher(slots, elig)
        assert all(m.add(p) for p in lineup), (wk, team, lineup)
    for wk, s in run.outcomes["optimal"][1].scores.items():
        for team, v in s.items():
            assert v >= run.outcomes["optimal"][0].scores[wk][team] - 1e-6
    assert run.filled > 0


def test_dropping_the_superflex_benches_one_starter_a_week():
    if not (_HAVE_DATA and _HAVE_STATS):
        return _skip("no exports or nflverse cache")
    run = RC.run_season(2024, RC.spec_from_dict({"lineup": {"remove": ["SUPER_FLEX"]}}))
    assert run.slots.count("SUPER_FLEX") == 0 and len(run.slots) == 9
    for (wk, team), (real, lineup) in run.lineups.items():
        assert len(lineup) <= 9 and set(lineup) <= set(real)
    # the optimal side can only lose a slot's worth
    for wk, s in run.outcomes["optimal"][1].scores.items():
        for team, v in s.items():
            assert v <= run.outcomes["optimal"][0].scores[wk][team] + 1e-6


def test_six_team_playoffs_on_a_real_season():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    sim = RC.simulate(RC.spec_from_dict({"playoffs": {"teams": 6}}), [2025])
    base, scen = sim.run(2025).outcomes["actual"]
    assert len(scen.bracket.seeds) == 6 and scen.bracket.complete
    first = [g for g in scen.bracket.games if g.round == 1]
    assert len(first) == 2 and not {g.high for g in first} & set(scen.bracket.seeds[:2])
    assert scen.fmt.regular_season_weeks == 14
    assert "RULE CHANGE" in RC.render(sim)


def test_forecast_hook_with_the_real_rules_changes_nothing():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    from lotg_support import forecast as F
    year = max(Q.snapshot_seasons())
    if not Q.played_weeks(year):
        return _skip(f"{year} has no played weeks")
    plain = F.forecast(year, sims=150, seed=5)
    hooked = F.forecast(year, sims=150, seed=5, rules=RC.ForecastRules(year, RC.RuleSpec()))
    assert [(o.team, o.champion, o.playoffs, o.expected_wins) for o in plain.odds] == \
        [(o.team, o.champion, o.playoffs, o.expected_wins) for o in hooked.odds]


TESTS = [
    test_spec_round_trips_and_refuses_typos,
    test_compose_is_affine_per_key_and_later_wins_elsewhere,
    test_example_specs_load,
    test_bracket_order_puts_top_seeds_apart,
    test_median_game_adds_a_result_every_week,
    test_six_team_bracket_gives_the_top_two_byes_and_the_bonus_in_the_semis,
    test_best_lineup_is_exact_against_brute_force,
    test_best_lineup_matches_the_max_pf_routine_on_the_real_template,
    test_an_added_slot_is_filled_by_the_plausible_rule_and_never_by_a_rookie,
    test_a_removed_slot_benches_a_plausible_starter_and_absorbs_empties_first,
    test_empty_spec_reproduces_every_completed_season,
    test_real_formats_match_the_league_calendar,
    test_scoring_delta_equals_the_build_scorer,
    test_a_no_op_scoring_change_moves_nothing,
    test_an_added_flex_keeps_every_real_starter_and_lineups_stay_legal,
    test_dropping_the_superflex_benches_one_starter_a_week,
    test_six_team_playoffs_on_a_real_season,
    test_forecast_hook_with_the_real_rules_changes_nothing,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall rule-change checks passed")
