"""Championship odds: the guards, and the behaviour an answer would depend on.

Two guards tie this layer to numbers the build computed independently, which is
what makes it safe to quote a forecast from:

  * the scores -> standings -> champion path must reproduce every completed
    season's real playoff field and champion (`check_bracket_pipeline`);
  * forecasting a season that is already over — every week observed, nothing
    left to simulate — must return 100% for the team `team_year` calls Champion
    (`check_completed_season_certainty`).

The rest pin the parts a wrong answer would turn on. Most of them exist because
the first version of this module got them wrong:

  * taxi-squad players are in the roster's player list and cannot be started,
    and neither can a rostered player with no NFL team;
  * **a preseason injury flag is stale**: most of them trace to injuries in the
    closing weeks of the previous season, because managers park players in the
    IR slot in December and never move them. The test proves that from the data
    rather than asserting it. What replaces them is a dated, sourced research
    file, which gets the strictest check in here — every row must name a real
    rostered player and cite a URL;
  * the backtest may not see the present: today's designations, today's free
    agents and a research file written today are all future information to a
    projection of 2022, and letting any of them in inflates out-of-sample r;
  * depth has to cost something: fielding a lineup under injury draws must come
    out below the healthy lineup, and further below for a thin roster;
  * the age curve and the rookie price are fits, so they must be signed and
    scaled the way the league's own history says;
  * the schedule is only a balanced round-robin in some seasons, so that is
    reported, never assumed.

Everything SKIPs cleanly without the committed snapshot/exports.

Run: python tests/test_forecast.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import forecast as F  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _seasons():
    """Completed seasons that have a season before them to project from.

    Never an in-progress season: its weeks are in the snapshot but not yet in
    `exports/`, so any comparison against the built sheets would be partial.
    """
    exported = set(Q.export_seasons())
    return [y for y in Q.completed_seasons() if y - 1 in exported]


def _live_season():
    """The season a forecast is actually for: the newest one not yet finished."""
    live = [y for y in Q.snapshot_seasons() if not Q.season_meta(y).is_complete]
    return max(live) if live else None


# ---------------------------------------------------------------------------
# Pure logic — no data needed
# ---------------------------------------------------------------------------
def test_rookie_price_prefers_the_market_and_falls_back_to_the_slot():
    price = F.RookiePrice(ktc_slope=0.002, ktc_intercept=0.9, ktc_r=0.55, ktc_n=169,
                          slot_bins=((4, 14.0), (8, 10.0), (10 ** 6, 5.3)), undrafted=3.0)
    assert abs(price.price(7573, 1, "ktc") - (0.002 * 7573 + 0.9)) < 1e-9
    # a weaker market price at the same slot must project lower — this is the
    # whole mechanism by which a weak rookie class reads as weak
    assert price.price(3000, 1, "ktc") < price.price(7573, 1, "ktc")
    # slot pricing ignores the market, and no KTC falls back to the slot
    assert price.price(7573, 1, "slot") == 14.0
    assert price.price(None, 5, "ktc") == 10.0
    assert price.price(float("nan"), 30, "ktc") == 5.3
    # neither history nor a draft slot
    assert price.price(None, None, "ktc") == 3.0


def test_age_curve_only_adjusts_positions_it_fitted():
    curve = F.AgeCurve(slope={"WR": -0.25}, reference={"WR": 26.0}, pooled=-0.1, n={"WR": 300})
    assert curve.adjust("WR", 30.0) == -1.0          # four years past the reference
    assert curve.adjust("WR", 26.0) == 0.0
    assert curve.adjust("WR", 22.0) == 1.0
    assert curve.adjust("QB", 34.0) == 0.0           # not fitted -> no opinion
    assert curve.adjust("WR", float("nan")) == 0.0


def test_strength_split_never_goes_imaginary():
    assert F._strength_sd(1.0, 25.0, 15.0, 8) == 0.0
    big = F._strength_sd(20.0, 25.0, 15.0, 8)
    assert 0.0 < big < 20.0, big
    assert F._strength_sd(12.0, 25.0, 30.0, 8) > F._strength_sd(12.0, 25.0, 15.0, 8)


def test_models_label_every_assumption():
    for token in ("weights=", "halflife=", "shrink=", "prior_games=", "age=", "rookies="):
        assert token in F.RateModel().label()
    for token in ("taxi=", "reserve=", "designations=", "research=", "unsigned="):
        assert token in F.AvailabilityModel().label()


# ---------------------------------------------------------------------------
# The two guards
# ---------------------------------------------------------------------------
def test_bracket_pipeline_reproduces_every_built_season():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    seasons = _seasons()
    assert seasons, "expected at least one completed season"
    for year in seasons:
        problems = F.check_bracket_pipeline(year)
        assert not problems, f"{year}: {problems}"
        print(f"  {year}: playoff field and champion match the build")


def test_a_finished_season_forecasts_at_one_hundred_percent():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    for year in _seasons():
        problems = F.check_completed_season_certainty(year, sims=40)
        assert not problems, f"{year}: {problems}"
        print(f"  {year}: forecast collapses to the built champion")


def test_validate_runs_every_guard_over_every_completed_season():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    assert F.validate(_seasons()[-1]) == []


# ---------------------------------------------------------------------------
# Who plays whom
# ---------------------------------------------------------------------------
def test_schedule_balance_is_reported_not_assumed():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    seen = {}
    for year in Q.snapshot_seasons():
        sched = F.schedule(year)
        seen[year] = sched.balanced
        # every pairing count must be positive and the description must say which
        assert sched.meetings and min(sched.meetings) >= 1, sched
        assert ("balanced" in sched.describe()), sched.describe()
    print(f"  balanced by season: {seen}")
    # the point of the check: this league is not always a clean round-robin, so
    # an answer may not assume the tidy case
    assert set(seen.values()) >= {True} or set(seen.values()) >= {False}
    for year, balanced in seen.items():
        assert bool(F.check_schedule_is_balanced(year)) != balanced, year


def test_strength_of_schedule_is_zero_when_the_schedule_is_balanced():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    balanced = [y for y in Q.snapshot_seasons() if F.schedule(y).balanced]
    if not balanced:
        return _skip("no balanced season in the snapshot")
    year = balanced[-1]
    strength = {rid: 100.0 + 10 * rid for rid in Q.teams(year)}   # deliberately lopsided
    sos = F.schedule(year, strength).sos
    # every team plays every other team the same number of times, so each one's
    # mean opponent is the league mean regardless of how unequal the teams are
    assert max(abs(v) for v in sos.values()) < 1e-9, sos


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------
def test_rates_only_ever_look_backwards():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _seasons()[-1]
    rates = F.player_rates(year)
    pw = Q.load_sheet("player_week")
    years = Q.numeric(pw, "Year")
    before = set(pw.loc[years < year, "Player"])
    debut = set(pw.loc[years == year, "Player"]) - before
    assert debut, f"expected someone to debut in {year}"
    leaked = debut & set(rates)
    assert not leaked, f"{year} projection sees players who only exist in {year}: {sorted(leaked)[:5]}"


def test_the_age_curve_says_players_decline():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    curve = F.age_curve()
    assert curve.slope, "expected an age curve to be fitted"
    assert curve.pooled < 0, f"pooled age slope should be negative, got {curve.pooled}"
    for pos, slope in curve.slope.items():
        assert -1.0 < slope < 0.25, f"{pos} age slope {slope} is not a plausible per-year effect"
    print("  " + "  ".join(f"{p} {v:+.2f}" for p, v in sorted(curve.slope.items())))


def test_rookies_are_priced_by_the_market_and_the_fit_is_real():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    price = F.rookie_price()
    assert price.ktc_n > 50, price.ktc_n
    assert price.ktc_slope > 0, "a higher draft-day price must project more points"
    assert price.ktc_r > 0.3, price.ktc_r
    # the slot fallback must still fall off with the pick
    values = [v for _, v in price.slot_bins]
    assert values[0] == max(values), price.slot_bins
    print(f"  ppg = {price.ktc_slope:.5f} x KTC + {price.ktc_intercept:.2f} "
          f"(r={price.ktc_r:.2f}, n={price.ktc_n})")


def test_rookie_class_strength_compares_like_for_like():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    strength = F.rookie_class_strength(year)
    if not strength:
        return _skip(f"no priced rookie class for {year}")
    assert strength["picks"] > 0 and strength["mean_ktc"] > 0
    assert 1 <= strength["rank_of_classes"] <= strength["classes"]
    print(f"  {year}: mean KTC {strength['mean_ktc']:.0f} vs {strength['past_mean_ktc']:.0f} "
          f"({strength['ratio']:.0%}), rank {int(strength['rank_of_classes'])} "
          f"of {int(strength['classes'])}")


def test_taxi_players_are_not_startable():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    state = F._roster_state(year, str(Q.repo_root()))
    taxi = {rid: s["taxi"] for rid, s in state.items() if s["taxi"]}
    if not taxi:
        return _skip(f"no taxi squads in {year}")
    pool = F.startable_pool(year)
    for rid, squad in taxi.items():
        assert not (set(pool[rid]) & squad), f"roster {rid} can start taxi players {squad}"
    # and they really were in the raw week list — i.e. this is doing work
    raw = {rid: set(row.players) for rid, row in Q.week(year, 1).items()}
    assert any(raw[rid] & squad for rid, squad in taxi.items()), \
        "taxi players were never in the week list, so the filter proves nothing"
    kept = F.startable_pool(year, model=F.AvailabilityModel(exclude_taxi=False))
    assert sum(map(len, kept.values())) > sum(map(len, pool.values()))


def test_injuries_cost_points_and_depth_decides_how_many():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    dist = F.fielded_distribution(year, availability=dataclasses.replace(
        F.AvailabilityModel(), draws=400))
    for rid in dist.mean:
        cost = dist.depth_cost(rid)
        assert cost > 0, f"{dist.teams[rid]} loses nothing to injuries, which cannot be right"
        assert cost < 30, f"{dist.teams[rid]} loses {cost:.1f} pts/wk, which is not plausible"
        assert dist.sd[rid] > 0
    costs = {dist.teams[r]: round(dist.depth_cost(r), 1) for r in dist.mean}
    print(f"  depth cost by team: {costs}")
    # the cost is not the same for everyone — that is the whole point
    assert max(costs.values()) - min(costs.values()) > 0.5, costs
    # and a team that loses more to injuries also swings more week to week
    order = sorted(dist.mean, key=lambda r: dist.depth_cost(r))
    rank = lambda a: np.argsort(np.argsort(a))  # noqa: E731
    rho = float(np.corrcoef(rank([dist.depth_cost(r) for r in order]),
                            rank([dist.sd[r] for r in order]))[0, 1])
    assert rho > 0.5, f"depth cost and weekly spread should move together (rho={rho:.2f})"


def test_preseason_injury_flags_are_stale_and_are_not_believed():
    """The finding this whole layer rests on: in August, Sleeper's flags are last December's.

    A manager parks a player in the IR slot in week 15 and never moves him, so a
    preseason snapshot records how the *previous* season ended. The test proves
    it from the data rather than asserting it, then checks the model acts on it.
    """
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season()
    if year is None or Q.played_weeks(year):
        return _skip("no un-started live season to check")
    model = F.AvailabilityModel()
    assert model.uses_designations(year) is False, \
        "preseason designations must not be believed"
    # ...and they must be believed once games are played
    played = [y for y in Q.completed_seasons() if Q.played_weeks(y)]
    if played:
        assert model.uses_designations(played[-1]) is True

    # the evidence: most flagged players were hurt at the end of the prior season
    root = str(Q.repo_root())
    players, state = Q.players(), F._roster_state(year, root)
    designations = F._designations(root)
    pw = Q.load_sheet("player_week")
    years, weeks = Q.numeric(pw, "Year"), Q.numeric(pw, "Week")
    hurt = pw["Injury?"].astype(str).str.lower().isin(("true", "1", "yes"))
    late = set(pw.loc[(years == year - 1) & (weeks >= 14) & hurt, "Player"])
    flagged = [players.name(pid)
               for rid, pids in F.startable_pool(year).items()
               for pid in pids
               if pid in state.get(rid, {}).get("reserve", frozenset())
               or designations.get(pid, "") in F.OUT_DESIGNATIONS]
    assert flagged, "no flagged players, so this proves nothing"
    carryover = [n for n in flagged if n in late]
    share = len(carryover) / len(flagged)
    assert share > 0.5, (f"only {share:.0%} of {year} flags trace to late {year - 1} "
                         "injuries — the staleness argument may no longer hold")
    print(f"  {len(carryover)}/{len(flagged)} preseason flags are {year - 1} carry-over")


def test_the_backtest_may_not_see_the_present():
    """Designations, research and free agency are all *today's* facts."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    back = F._backtest_availability(F.AvailabilityModel())
    assert back.designations == "never"
    assert back.research is False
    assert back.unsigned_availability == 1.0, \
        "who is unsigned today cannot be told to a projection of 2022"
    assert back.exclude_taxi is True, "taxi membership is preseason, so it stays"


def test_the_research_file_is_sourced_dated_and_lands_on_real_players():
    """The one hand-written input gets the strictest check."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    problems = F.check_research_file(year)
    assert not problems, problems
    notes = F.research_overrides(year)
    if not notes:
        return _skip(f"no research file for {year}")
    for name, note in notes.items():
        assert note.source.startswith("http"), name
        assert len(note.note) > 20, f"{name}: a bare number is not research"
    print(f"  {len(notes)} researched players, all sourced and dated")


def test_research_moves_the_players_it_names():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season()
    notes = F.research_overrides(year) if year else {}
    if not notes:
        return _skip("no live season with a research file")
    avail = dataclasses.replace(F.AvailabilityModel(), draws=400)
    on = F.fielded_distribution(year, availability=avail)
    off = F.fielded_distribution(year, availability=dataclasses.replace(avail, research=False))
    assert any(on.researched.values()), "research file applied to nobody"
    # research cuts both ways — some players are healthier than their flag, some
    # worse — so the requirement is that it *moves* rosters, not that it lowers them
    moved = [rid for rid in on.mean if abs(on.mean[rid] - off.mean[rid]) > 0.2]
    assert moved, "research changed no roster's projection at all"
    print("  " + ", ".join(f"{on.teams[r]} {off.mean[r]:.1f}->{on.mean[r]:.1f}" for r in moved))


def test_an_unsigned_player_cannot_score():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season()
    if year is None:
        return _skip("no live season")
    avail = dataclasses.replace(F.AvailabilityModel(), draws=400, research=False)
    capped = F.fielded_distribution(year, availability=avail)
    free = F.fielded_distribution(year, availability=dataclasses.replace(
        avail, unsigned_availability=1.0))
    assert any(capped.unsigned.values()), "no unsigned players found on any roster"
    for rid, n in capped.unsigned.items():
        if n:
            assert capped.mean[rid] <= free.mean[rid] + 1e-9, \
                f"{capped.teams[rid]} gains from having unsigned players"


def test_every_roster_gets_a_projection_and_unplaced_players_are_counted():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    proj = F.roster_projection(year, availability=dataclasses.replace(
        F.AvailabilityModel(), draws=200))
    assert set(proj.mean) == set(Q.teams(year))
    assert all(v > 0 for v in proj.mean.values()), proj.mean
    for rid, count in proj.unplaced.items():
        if count:
            assert any(proj.teams[rid] in w for w in proj.warnings), proj.warnings


def test_calibration_says_the_projection_beats_a_coin_flip():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    calib = F.calibrate()
    assert calib.n == len(calib.seasons) * len(Q.teams(calib.seasons[-1])), calib.n
    assert calib.slope > 0, calib.slope
    assert calib.corr_oos > 0.3, calib.corr_oos          # out-of-sample, not in-sample
    assert 0 < calib.sd_true < calib.sd_resid, (calib.sd_true, calib.sd_resid)
    assert calib.sd_week > calib.sd_league_week > 0, (calib.sd_week, calib.sd_league_week)
    print(f"  out-of-sample r={calib.corr_oos:.3f}, RMSE={calib.rmse_oos:.2f}")


# ---------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------
def test_a_league_of_identical_teams_comes_out_uniform():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season()
    if year is None:
        return _skip("no live season to simulate")
    fc = F.forecast(year, sims=6000, strength_model="uniform")
    n = len(fc.odds)
    for o in fc.odds:
        assert abs(o.champion - 100.0 / n) < 2.0, f"{o.team} {o.champion:.2f}% in a uniform league"
        assert abs(o.playoffs - 100.0 * Q.season_meta(year).playoff_teams / n) < 4.0, o
    print(f"  every team within 2 points of {100.0 / n:.1f}%")


def test_probabilities_close():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    fc = F.forecast(year, sims=3000)
    meta = Q.season_meta(year)
    assert abs(sum(o.champion for o in fc.odds) - 100.0) < 1e-6
    assert abs(sum(o.finals for o in fc.odds) - 200.0) < 1e-6
    assert abs(sum(o.playoffs for o in fc.odds) - 100.0 * meta.playoff_teams) < 1e-6
    for o in fc.odds:
        assert abs(sum(o.seed_pct) - 100.0) < 1e-6, o.team
        assert o.champion <= o.finals <= o.playoffs + 1e-9, o


def test_odds_track_strength():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season()
    if year is None:
        return _skip("a finished season has no spread to rank")
    fc = F.forecast(year, sims=6000)
    strength = np.array([o.strength for o in fc.odds])
    champ = np.array([o.champion for o in fc.odds])
    rank = lambda a: np.argsort(np.argsort(a))  # noqa: E731
    spearman = float(np.corrcoef(rank(strength), rank(champ))[0, 1])
    assert spearman > 0.9, f"championship odds do not follow strength (rho={spearman:.2f})"


def test_simulated_weekly_spread_matches_history():
    """Availability spread is taken *out* of the residual noise, not added on top."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    fc = F.forecast(year, sims=4000)
    calib = fc.calibration
    for o in fc.odds:
        assert o.availability_sd < calib.sd_week, (o.team, o.availability_sd)
    # the combined per-week sd a team is simulated with must land on the
    # historical figure, not above it
    for o in fc.odds:
        combined = float(np.hypot(o.availability_sd,
                                  np.sqrt(max(calib.sd_week ** 2 - o.availability_sd ** 2, 1.0))))
        assert abs(combined - calib.sd_week) < 0.05, (o.team, combined, calib.sd_week)


def test_the_same_seed_gives_the_same_answer():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    a = F.forecast(year, sims=1500, seed=7)
    b = F.forecast(year, sims=1500, seed=7)
    c = F.forecast(year, sims=1500, seed=8)
    assert a.champion_pct() == b.champion_pct()
    for team, pct in a.champion_pct().items():
        assert abs(pct - c.champion_pct()[team]) < 7.0, (team, pct, c.champion_pct()[team])


def test_an_unknown_strength_model_is_refused():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _live_season() or _seasons()[-1]
    try:
        F.forecast(year, sims=10, strength_model="vibes")
    except ValueError as exc:
        assert "vibes" in str(exc)
    else:
        raise AssertionError("expected an unknown strength model to raise")


def test_as_of_week_rewinds_the_clock():
    """A finished season must be answerable as though it had not happened yet."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    year = _seasons()[-1]
    full = F.forecast(year, sims=200)
    assert full.by_champion()[0].champion == 100.0, "a played-out season should be certain"
    pre = F.forecast(year, sims=2000, as_of_week=0,
                     availability=F._backtest_availability(F.AvailabilityModel()))
    assert pre.played_weeks == (), "as_of_week=0 must treat no week as known"
    assert max(o.champion for o in pre.odds) < 100.0, "a rewound season cannot be certain"
    assert abs(sum(o.champion for o in pre.odds) - 100.0) < 1e-6
    mid = F.forecast(year, sims=2000, as_of_week=8,
                     availability=F._backtest_availability(F.AvailabilityModel()))
    assert mid.played_weeks == tuple(range(1, 9)), mid.played_weeks
    # more information must not make the forecast less certain about the winner
    assert max(o.champion for o in mid.odds) >= max(o.champion for o in pre.odds) - 5.0


def test_the_forecast_beats_guessing_on_seasons_that_happened():
    """The only test of the probabilities rather than the machinery."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    problems = F.check_beats_uniform(sims=2000)
    assert not problems, problems
    bt = F.backtest(as_of_weeks=(0,), sims=2000, models=("roster", "uniform"))
    roster, uniform = bt.summary("roster"), bt.summary("uniform")
    print(f"  champion log-loss {roster['champion_logloss']:.3f} vs {uniform['champion_logloss']:.3f} "
          f"guessing; playoff Brier {roster['playoff_brier']:.3f} vs "
          f"{uniform['playoff_brier']:.3f}; seed rho {roster['seed_rho']:.2f}")


def test_the_backtest_is_actually_out_of_sample():
    """It must refit leaving the scored season out, and see none of today's facts."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    seasons = _seasons()
    if len(seasons) < 3:
        return _skip("not enough seasons")
    # the calibration a backtest uses for season Y must not contain Y
    for year in seasons:
        others = [y for y in seasons if y != year]
        assert year not in F.calibrate(others).seasons
    # and the availability model it runs under must be blind to the present
    back = F._backtest_availability(F.AvailabilityModel())
    assert back.designations == "never" and back.research is False
    assert back.unsigned_availability == 1.0


def test_a_uniform_forecast_is_exactly_as_confident_as_it_should_be():
    """Sanity check on the confidence ratio: a 1/n forecast can only score 1.0."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    bt = F.backtest(as_of_weeks=(0,), sims=2000, models=("uniform",))
    s = bt.summary("uniform")
    assert abs(s["confidence_ratio_champion"] - 1.0) < 0.08, s["confidence_ratio_champion"]
    assert abs(s["champion_logloss"] - s["champion_logloss_uniform"]) < 0.08, s


def test_reads_are_pure():
    """An inquiry must not write. Nothing under exports/ may change."""
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    targets = [_ROOT / "exports" / "team_week.csv", _ROOT / "exports" / "picks.csv"]
    before = [(p.stat().st_mtime, p.stat().st_size) for p in targets]
    year = _live_season() or _seasons()[-1]
    F.forecast(year, sims=200)
    F.calibrate()
    after = [(p.stat().st_mtime, p.stat().st_size) for p in targets]
    assert before == after, "forecast touched an export"


def test_the_build_does_not_import_the_forecast():
    """Playbook rule 2: nothing the build runs may depend on an inquiry module."""
    hits = []
    for folder in ("src", ".github/workflows"):
        base = _ROOT / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and "forecast" in path.read_text(errors="ignore"):
                hits.append(str(path.relative_to(_ROOT)))
    assert not hits, f"build code references the forecast module: {hits}"


TESTS = [
    test_rookie_price_prefers_the_market_and_falls_back_to_the_slot,
    test_age_curve_only_adjusts_positions_it_fitted,
    test_strength_split_never_goes_imaginary,
    test_models_label_every_assumption,
    test_bracket_pipeline_reproduces_every_built_season,
    test_a_finished_season_forecasts_at_one_hundred_percent,
    test_validate_runs_every_guard_over_every_completed_season,
    test_schedule_balance_is_reported_not_assumed,
    test_strength_of_schedule_is_zero_when_the_schedule_is_balanced,
    test_rates_only_ever_look_backwards,
    test_the_age_curve_says_players_decline,
    test_rookies_are_priced_by_the_market_and_the_fit_is_real,
    test_rookie_class_strength_compares_like_for_like,
    test_taxi_players_are_not_startable,
    test_injuries_cost_points_and_depth_decides_how_many,
    test_preseason_injury_flags_are_stale_and_are_not_believed,
    test_the_backtest_may_not_see_the_present,
    test_the_research_file_is_sourced_dated_and_lands_on_real_players,
    test_research_moves_the_players_it_names,
    test_an_unsigned_player_cannot_score,
    test_every_roster_gets_a_projection_and_unplaced_players_are_counted,
    test_calibration_says_the_projection_beats_a_coin_flip,
    test_a_league_of_identical_teams_comes_out_uniform,
    test_probabilities_close,
    test_odds_track_strength,
    test_simulated_weekly_spread_matches_history,
    test_the_same_seed_gives_the_same_answer,
    test_an_unknown_strength_model_is_refused,
    test_as_of_week_rewinds_the_clock,
    test_the_forecast_beats_guessing_on_seasons_that_happened,
    test_the_backtest_is_actually_out_of_sample,
    test_a_uniform_forecast_is_exactly_as_confident_as_it_should_be,
    test_reads_are_pure,
    test_the_build_does_not_import_the_forecast,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall forecast checks passed")
