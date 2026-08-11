"""Draft capital: slot returns, the two ordering rules, and the cost of moving up.

Three guards tie this layer to numbers the build computed independently, which
is what makes it safe to answer "is tanking worth it" from:

  * season `Max PF` recomputed from the snapshot must equal the built
    `team_week."Max PF"` for every team in every completed season — this is the
    baseline every stripping cost is measured from, and since the 2026 draft it
    is also the number the league's draft order is set by;
  * the bottom-four ordering rule must reproduce `picks."Original Team"` for
    slots 1.01-1.04 in every draft on record, which is what licenses the claim
    that the rule changed rather than that one draft was odd;
  * the slot tables must add back up to the pick sheet's own total, which
    catches a filter quietly dropping picks.

The rest pin behaviour a wrong answer would depend on: the startup/vet drafts
and unmade picks staying out and being counted, a rate column never being
summed across rounds, and the two cohort comparisons keeping the units the
question needs.

Run: python tests/test_draft_capital.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import draft_capital as D  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "picks.csv").exists()
_HAVE_SNAPSHOT = (_ROOT / "exports" / "snapshot").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Guards against the build
# ---------------------------------------------------------------------------
def test_max_pf_matches_build():
    """The recomputed ceiling must equal the built column, every team-season."""
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    checked = 0
    for season in Q.completed_seasons():
        if not Q.season_meta(season).has_snapshot:
            continue
        problems = D.check_max_pf_matches_build(season)
        assert not problems, f"{season}: {problems[:3]}"
        checked += 1
    assert checked >= 1, "no completed season with a snapshot to check"
    print(f"  ok — Max PF reproduced for {checked} season(s)")


def test_bottom_four_order_matches_picks():
    """Each era's rule must reproduce who actually owned slots 1.01-1.04."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    drafts = D.checkable_drafts()
    assert drafts, "no checkable drafts"
    for draft_year in drafts:
        problems = D.check_bottom_four_order_matches_picks(draft_year)
        assert not problems, problems
    print(f"  ok — bottom-four order reproduced for {len(drafts)} draft(s): {drafts}")


def test_rule_actually_changed():
    """The two rules must disagree somewhere, or the module is claiming nothing.

    If `placement` and `max_pf` produced the same order in every draft, the
    2026 change would be cosmetic and every conclusion about its effect would
    be unfounded. Pin that they genuinely differ.
    """
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    disagreements = [d for d in D.checkable_drafts()
                     if D.bottom_four_order(d, rule="placement")
                     != D.bottom_four_order(d, rule="max_pf")]
    assert disagreements, "the two ordering rules never disagree"
    assert 2026 in disagreements, "the 2026 draft should be a disagreement"
    print(f"  ok — rules disagree in {len(disagreements)} draft(s): {disagreements}")


def test_haul_table_reconciles():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    assert not D.check_haul_table_reconciles()
    print("  ok — slot totals reconcile with the pick sheet")


def test_validate_runs_clean():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    results = D.validate()
    failed = {k: v for k, v in results.items() if v}
    assert not failed, failed
    print(f"  ok — {len(results)} guards clean")


# ---------------------------------------------------------------------------
# The pick frame: what is excluded, and that it is counted
# ---------------------------------------------------------------------------
def test_startup_and_unmade_picks_are_excluded_and_counted():
    """The startup draft is not a rookie draft and `1.??` is not a pick."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    frame = D.rookie_picks()
    years = set(frame.rows["Year"].astype(str))
    assert all(y.isdigit() for y in years), f"non-rookie drafts leaked in: {years}"
    assert not frame.rows["Number"].astype(str).str.contains(r"\?").any()
    excluded = frame.excluded
    assert sum(excluded.values()) > 0, "nothing was excluded — the filter is not running"
    assert any("startup" in k for k in excluded), excluded
    assert any("unmade" in k for k in excluded), excluded
    print(f"  ok — excluded: {frame.describe_exclusions()}")


def test_unplayed_draft_is_excluded_by_default():
    """A class with no completed season reads 0.0 everywhere and must not average in."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    completed = set(Q.completed_seasons())
    played = set(D.rookie_picks().rows["draft_year"])
    assert played <= completed, f"unplayed drafts leaked in: {sorted(played - completed)}"
    everything = set(D.rookie_picks(played_only=False).rows["draft_year"])
    assert everything >= played
    print(f"  ok — averaging over {sorted(played)}, holding back {sorted(everything - played)}")


def test_reward_picks_are_flagged_not_silently_dropped():
    """Slot 9 (toilet-bowl reward) exists; it must be reported either way."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    frame = D.rookie_picks(played_only=False)
    wide = frame.rows[frame.rows["slot"] > D.TEAMS]
    if not len(wide):
        return _skip("no above-league-size slots in this build")
    assert frame.warnings, "reward picks present but no warning raised"
    _, warnings = D.hauls()
    assert warnings, "cohorts dropped reward picks without saying so"
    print(f"  ok — {len(wide)} reward pick(s) flagged in both paths")


# ---------------------------------------------------------------------------
# Slot returns
# ---------------------------------------------------------------------------
def test_haul_total_is_the_sum_of_its_rounds():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    table = D.haul_table()
    rounds = [c for c in table.columns if c != "TOTAL"]
    for slot, row in table.iterrows():
        want = float(row[rounds].sum())
        assert abs(float(row["TOTAL"]) - want) < 0.01, f"slot {slot}: {row['TOTAL']} != {want}"
    print(f"  ok — {len(table)} slot totals equal their round parts")


def test_bust_rate_is_a_share():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    table = D.slot_table(statistic="bust_rate")
    values = table.stack().dropna()
    assert ((values >= 0) & (values <= 1)).all(), "bust rate outside [0, 1]"
    assert values.max() > 0, "no busts at all — the statistic is not being computed"
    print(f"  ok — bust rate in [0, 1], max {values.max():.2f}")


def test_rate_metric_is_never_summed_across_rounds():
    """Points-per-start does not add up across four picks; 'auto' must not sum it."""
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    per_pick = D.slot_cohorts(metric=D.RATE_METRIC, permutations=200)
    per_haul = D.slot_cohorts(metric=D.TOTAL_METRIC, permutations=200)
    a = per_pick.comparisons["bottom_four_vs_playoff"]
    b = per_haul.comparisons["bottom_four_vs_playoff"]
    assert a.n_with > b.n_with, (
        f"rate metric aggregated like a total (n={a.n_with} vs {b.n_with})")
    print(f"  ok — rate compared per pick (n={a.n_with}), total per haul (n={b.n_with})")


def test_cohorts_report_both_sides_and_a_breakdown():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    result = D.slot_cohorts(permutations=500)
    for label, cmp in result.comparisons.items():
        assert cmp.n_with > 0 and cmp.n_without > 0, label
        assert cmp.by_group, f"{label}: no per-draft breakdown"
        assert 0.0 <= cmp.p_value <= 1.0
    print(f"  ok — {len(result.comparisons)} comparisons, both cohorts and a breakdown each")


# ---------------------------------------------------------------------------
# The cost of moving up
# ---------------------------------------------------------------------------
def test_stripping_nobody_reproduces_the_baseline():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    season = max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)
    built = D.built_max_pf(season)
    mine = D.season_max_pf(season, drop=())
    for team, want in built.items():
        assert abs(mine[team] - want) < 0.01, f"{team}: {mine[team]} != {want}"
    print(f"  ok — {season}: empty drop reproduces every built Max PF")


def test_stripping_lowers_the_ceiling_monotonically():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    season = max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)
    team = min(D.built_max_pf(season), key=lambda t: D.built_max_pf(season)[t])
    cost = D.ceiling_cost(season, team, target=0.0, max_steps=3)
    ceilings = [cost.baseline] + [s.max_pf_after for s in cost.steps]
    assert ceilings == sorted(ceilings, reverse=True), ceilings
    assert all(s.ceiling_given_up > 0 for s in cost.steps)
    print(f"  ok — {team} {season}: ceiling falls monotonically {ceilings}")


def test_exchange_rate_exceeds_one():
    """Removing a starter costs more production than ceiling — the bench refills.

    This is the load-bearing asymmetry in the whole ceiling-rule argument: you
    cannot buy draft position by shedding one star, because the optimal lineup
    only loses his margin over the next-best legal option. If this ever came
    back at or below 1.0 the cost model would be wrong.
    """
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    season = max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)
    order = D.bottom_four_order(season + 1, rule="max_pf")
    cost = D.cost_to_pick_first(season + 1, order[-1])
    assert cost.steps, "nothing had to be shed to reach the top of the order"
    assert cost.exchange_rate > 1.0, cost.exchange_rate
    assert cost.production_lost > cost.ceiling_shed > 0
    print(f"  ok — {order[-1]}: {cost.exchange_rate:.2f} points produced per 1 of ceiling shed")


def test_cost_target_and_baseline_share_a_weeks_basis():
    """A regular-season baseline must be measured against a regular-season target."""
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    season = max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)
    weeks = list(range(1, Q.season_meta(season).regular_season_weeks + 1))
    team = D.bottom_four_order(season + 1, rule="max_pf")[-1]
    full = D.cost_to_pick_first(season + 1, team)
    reg = D.cost_to_pick_first(season + 1, team, weeks=weeks)
    assert reg.baseline < full.baseline and reg.target < full.target
    assert len(reg.steps) == len(full.steps), (
        f"the two weeks bases disagree on the cost: {len(reg.steps)} vs {len(full.steps)}")
    print(f"  ok — both weeks bases cost {len(full.steps)} players")


def test_cost_warns_that_it_is_a_floor():
    if not (_HAVE_EXPORTS and _HAVE_SNAPSHOT):
        return _skip("no exports/snapshot")
    season = max(s for s in Q.completed_seasons() if Q.season_meta(s).has_snapshot)
    cost = D.ceiling_cost(season, D.bottom_four_order(season + 1)[0], target=0.0, max_steps=1)
    assert any("floor" in w for w in cost.warnings), cost.warnings
    print("  ok — the stripping cost declares itself a floor")


# ---------------------------------------------------------------------------
# Ordering rules
# ---------------------------------------------------------------------------
def test_order_rule_switches_at_the_documented_draft():
    assert D.order_rule(D.MAX_PF_RULE_FROM_DRAFT - 1) == "placement"
    assert D.order_rule(D.MAX_PF_RULE_FROM_DRAFT) == "max_pf"
    print(f"  ok — rule switches at the {D.MAX_PF_RULE_FROM_DRAFT} draft")


def test_order_comparison_prices_both_rules():
    if not _HAVE_EXPORTS:
        return _skip("no exports")
    table = D.order_comparison(max(D.checkable_drafts()))
    assert len(table) == D.BOTTOM
    assert set(table["slots_moved"]) != {0}, "no team moved — the table shows nothing"
    assert table["slots_moved"].sum() == 0, "slot moves must net to zero"
    print(f"  ok — {len(table)} teams priced under both rules, moves net to zero")


def test_unknown_rule_raises():
    try:
        D.bottom_four_order(2026, rule="vibes")
    except ValueError:
        print("  ok — an unknown rule raises rather than guessing")
        return
    raise AssertionError("expected ValueError for an unknown rule")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            try:
                fn()
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL — {exc}")
    print("\nall good" if not failures else f"\n{failures} failure(s)")
    raise SystemExit(1 if failures else 0)
