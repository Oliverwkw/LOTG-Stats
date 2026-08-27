"""The picks frame ships as two sheets, and the non-rookie half is de-trended.

Covers the four things the split has to get right:

  1. the row split is exhaustive, disjoint, and keeps the original index (the
     `PH#N` refs on other sheets are that index, so losing it moves rows on
     sheets this change must not touch);
  2. overall draft position reads the pick NUMBER as draft ORDER — including the
     snake startup — and continues the vet draft after the startup's last pick;
  3. the de-trend is monotone, linear in lambda, bounded, and touches ONLY the
     non-rookie rows — and the starts term in Player addition value rewards the
     LENGTH of a run rather than adding a third rate;
  4. the half-season gate is one predicate, shared by the withheld rookie
     O-Score and the pick-adjustment reference pools;
  5. `PH#N` survives the split — the frame's own row order is written out as
     `raw/pick_ref_index.csv` and rebuilds exactly, and the retired `picks.csv`
     is named so the build deletes it instead of shipping it frozen.

Run: PYTHONPATH=src:lib python tests/test_pick_sheets_split.py
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

import pick_history as PH               # noqa: E402
from lotg_support import pick_index     # noqa: E402
import non_rookie_picks as NRP          # noqa: E402
import rookie_picks as RP               # noqa: E402

_spec = importlib.util.spec_from_file_location("lotg", _ROOT / "src" / "lotg.py")
lotg = importlib.util.module_from_spec(_spec)
sys.modules["lotg"] = lotg
_spec.loader.exec_module(lotg)


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _frame():
    """A startup snake, the vet draft, and two rookie classes."""
    rows = []
    for rnd in range(1, 4):                       # startup rounds 1-3
        for slot in range(1, 9):
            rows.append({"Year": "startup", "_is_startup": True,
                         "Number": f"{rnd}.0{slot}",
                         "Player Picked": f"SU{rnd}{slot}", "O-Score": 50.0})
    for slot in range(1, 9):                      # vet round 1
        rows.append({"Year": "2021 (vet)", "_is_startup": np.nan,
                     "Number": f"1.0{slot}",
                     "Player Picked": f"VET{slot}", "O-Score": 40.0})
    for yr in (2025, 2026):                       # two rookie classes
        for slot in range(1, 9):
            rows.append({"Year": str(yr), "_is_startup": np.nan,
                         "Number": f"1.0{slot}",
                         "Player Picked": f"R{yr}{slot}", "O-Score": 60.0})
    return pd.DataFrame(rows)


# --- 1. the split ----------------------------------------------------------

def check_split_is_exhaustive_disjoint_and_index_preserving():
    df = _frame()
    ctx = {PH.FRAME_KEY: df}
    nr, rk = NRP.build_output(ctx), RP.build_output(ctx)
    ok = _ok("every row lands on exactly one sheet",
             len(nr) + len(rk) == len(df), f"{len(nr)}+{len(rk)} vs {len(df)}")
    ok &= _ok("the two sheets are disjoint",
              not (set(nr.index) & set(rk.index)))
    ok &= _ok("together they are the whole frame",
              set(nr.index) | set(rk.index) == set(df.index))
    # The PH#N refs on trades / add_drops / player_additions are this index.
    ok &= _ok("each sheet keeps the ORIGINAL frame index (PH#N refs)",
              list(nr.index) == sorted(nr.index) and list(rk.index) == sorted(rk.index)
              and set(nr.index) <= set(df.index))
    ok &= _ok("non-rookie sheet is exactly startup + vet",
              set(nr["Year"]) == {"startup", "2021 (vet)"}, sorted(set(nr["Year"])))
    ok &= _ok("rookie sheet holds no startup or vet row",
              not nr.empty and set(rk["Year"]) == {"2025", "2026"}, sorted(set(rk["Year"])))
    return ok


def check_mask_survives_both_naming_stages():
    """The startup's Year is 2020 for most of the build and "startup" only at
    the end, while `_is_startup` is dropped on write — so the mask has to work
    off whichever of the two is present."""
    early = _frame()
    early.loc[early["Year"] == "startup", "Year"] = "2020"   # pre-relabel state
    late = _frame().drop(columns=["_is_startup"])            # post-write state
    ok = _ok("pre-relabel (Year=2020 + _is_startup) -> 32 non-rookie",
             int(PH.non_rookie_mask(early).sum()) == 32, int(PH.non_rookie_mask(early).sum()))
    ok &= _ok("post-relabel (Year='startup', no flag) -> 32 non-rookie",
              int(PH.non_rookie_mask(late).sum()) == 32, int(PH.non_rookie_mask(late).sum()))
    return ok


# --- 2. draft position -----------------------------------------------------

def check_positions_read_number_as_draft_order_and_append_the_vet():
    df = _frame()
    nr = PH.non_rookie_mask(df)
    pos = PH.overall_positions(df, nr)
    su, vet = PH.startup_mask(df), PH.vet_mask(df)
    ok = _ok("startup runs 1..24 with no gaps",
             sorted(pos[su].tolist()) == list(range(1, 25)), sorted(pos[su].tolist())[:5])
    # 2.01 is the 9th pick of a snake only because the NUMBER is draft order.
    _p201 = pos[su & (df["Number"] == "2.01")].iloc[0]
    ok &= _ok("2.01 is overall pick 9 (number is order, not slot)", _p201 == 9, _p201)
    ok &= _ok("the vet draft continues AFTER the startup",
              float(pos[vet].min()) == float(pos[su].max()) + 1,
              f"vet starts {pos[vet].min()}, startup ends {pos[su].max()}")
    ok &= _ok("rookie rows get no position", bool(pos[~nr].isna().all()))
    return ok


# --- 3. the de-trend -------------------------------------------------------

def _sloped_frame():
    """Non-rookie scores that fall with draft position, so there is a real
    trend to remove."""
    df = _frame()
    nr = PH.non_rookie_mask(df)
    pos = PH.overall_positions(df, nr)
    df.loc[nr, "O-Score"] = (90.0 - 1.5 * pos[nr]).clip(lower=1.0)
    return df, nr


def check_detrend_only_touches_non_rookie_rows():
    df, nr = _sloped_frame()
    before = pd.to_numeric(df["O-Score"], errors="coerce").copy()
    PH.detrend_non_rookie_oscore(df, nr)
    after = pd.to_numeric(df["O-Score"], errors="coerce")
    ok = _ok("every rookie O-Score is untouched",
             before[~nr].equals(after[~nr]))
    ok &= _ok("non-rookie scores did move", not before[nr].equals(after[nr]))
    ok &= _ok("result stays inside the O-Score's own 0-100 range",
              bool(((after >= 0) & (after <= 100)).all()))
    return ok


def check_detrend_lifts_late_picks_and_lowers_early_ones():
    df, nr = _sloped_frame()
    pos = PH.overall_positions(df, nr)
    before = pd.to_numeric(df["O-Score"], errors="coerce").copy()
    PH.detrend_non_rookie_oscore(df, nr)
    shift = (pd.to_numeric(df["O-Score"], errors="coerce") - before)[nr]
    first, last = pos[nr].idxmin(), pos[nr].idxmax()
    ok = _ok("the very first pick is marked DOWN", shift[first] < 0, round(shift[first], 2))
    ok &= _ok("the very last pick is marked UP", shift[last] > 0, round(shift[last], 2))
    # A function of position alone cannot reorder two picks at the same slot.
    ok &= _ok("picks at one position all shift by the same amount",
              all(shift[pos[nr] == p].round(6).nunique() <= 1 for p in pos[nr].unique()))
    return ok


def check_lambda_scales_the_shift_and_zero_is_a_no_op():
    """lambda is a dial, not a switch: the shift must be linear in it, and the
    shipped setting must be strictly between "do nothing" and "remove it all"."""
    df0, nr = _sloped_frame()
    base = pd.to_numeric(df0["O-Score"], errors="coerce").copy()

    noop = df0.copy()
    PH.detrend_non_rookie_oscore(noop, nr, lam=0.0)
    ok = _ok("lambda=0 leaves the O-Score exactly as computed",
             base.equals(pd.to_numeric(noop["O-Score"], errors="coerce")))

    def shift(lam):
        d = df0.copy()
        PH.detrend_non_rookie_oscore(d, nr, lam=lam)
        return (pd.to_numeric(d["O-Score"], errors="coerce") - base)[nr]

    full = shift(1.0)
    ok &= _ok("the shipped lambda is 0.75", PH.NONROOKIE_OSCORE_LAMBDA == 0.75,
              PH.NONROOKIE_OSCORE_LAMBDA)
    ok &= _ok("and it is a partial de-trend, not a full one",
              0.0 < PH.NONROOKIE_OSCORE_LAMBDA < 1.0)
    for lam in (0.25, 0.5, 0.75):
        got = shift(lam)
        ok &= _ok(f"lambda={lam} moves each pick {lam:g}x as far as lambda=1",
                  bool(np.allclose(got.to_numpy(), full.to_numpy() * lam, atol=0.06)),
                  f"max gap {float(np.abs(got - full * lam).max()):.3f}")
    ok &= _ok("0.75 moves further than the 0.5 this used to ship at",
              float(shift(0.75).abs().max()) > float(shift(0.5).abs().max()))
    return ok


def check_the_starts_term_rewards_length_not_rate():
    """Player addition value's two % terms are RATES. The starts term is what
    separates a six-year starter from a one-year one at the same clip."""
    d = PH.STARTS_TENURE_DIVISOR
    ok = _ok("the divisor is 170 (about a decade of starts)", d == 170.0, d)

    def value(ppg, starts, pct=0.5, ipct=0.5, cuff=0.0):
        return ppg * (1.0 + starts / d) * (1.0 + pct) * (1.0 + ipct) + cuff

    ok &= _ok("no starts -> the term is exactly 1, so nothing changes",
              value(10.0, 0) == 10.0 * 1.5 * 1.5)
    ok &= _ok("same rate, longer run -> a higher grade",
              value(10.0, 100) > value(10.0, 20))
    ok &= _ok("and the factor stays gentle across a real career",
              1.0 < (1.0 + 100 / d) < 1.6, f"{1.0 + 100 / d:.3f}")
    # It scales the MAIN variable only: the handcuff bonus must not inflate.
    plain, cuffed = value(10.0, 100), value(10.0, 100, cuff=5.0)
    ok &= _ok("the handcuff bonus is added after, unscaled",
              abs((cuffed - plain) - 5.0) < 1e-9, cuffed - plain)
    # A negative on-team PPG must get MORE negative, not less: the term is a
    # magnitude scaler, and a long bad run is worse than a short one.
    ok &= _ok("a longer bad run grades worse, not better",
              value(-4.0, 100) < value(-4.0, 0))
    return ok


def check_the_fitted_curve_is_never_upward_sloping():
    """A positive slope would say a LATER pick is expected to return more, which
    is not a draft-slot trend. Feed it exactly that and the fit must flatten."""
    df = _frame()
    nr = PH.non_rookie_mask(df)
    pos = PH.overall_positions(df, nr)
    df.loc[nr, "O-Score"] = (10.0 + 1.5 * pos[nr]).clip(upper=99.0)   # rises with position
    before = pd.to_numeric(df["O-Score"], errors="coerce").copy()
    diag = PH.detrend_non_rookie_oscore(df, nr)
    after = pd.to_numeric(df["O-Score"], errors="coerce")
    ok = _ok("slope is clamped at 0", diag is not None and diag["slope"] <= 0.0,
             None if diag is None else diag["slope"])
    ok &= _ok("so an upward trend is left alone, not inverted",
              bool(np.allclose(before[nr].to_numpy(), after[nr].to_numpy())))
    return ok


def check_detrend_never_fails_a_build():
    ok = _ok("no frame -> no-op", PH.detrend_non_rookie_oscore(None) is None)
    ok &= _ok("empty frame -> no-op",
              PH.detrend_non_rookie_oscore(pd.DataFrame()) is None)
    ok &= _ok("no O-Score column -> no-op",
              PH.detrend_non_rookie_oscore(pd.DataFrame({"Year": ["startup"],
                                                         "Number": ["1.01"]})) is None)
    ok &= _ok("no non-rookie rows -> no-op",
              PH.detrend_non_rookie_oscore(
                  pd.DataFrame({"Year": ["2025"], "Number": ["1.01"],
                                "O-Score": [50.0]})) is None)
    ok &= _ok("too few scored rows -> no-op",
              PH.detrend_non_rookie_oscore(
                  pd.DataFrame({"Year": ["startup", "startup"],
                                "Number": ["1.01", "1.02"],
                                "O-Score": [50.0, 60.0]})) is None)
    unparseable = pd.DataFrame({"Year": ["startup"] * 4, "Number": ["x"] * 4,
                                "O-Score": [10.0, 20.0, 30.0, 40.0]})
    ok &= _ok("unparseable pick numbers -> no-op",
              PH.detrend_non_rookie_oscore(unparseable) is None)
    return ok


# --- 4. the shared half-season gate ---------------------------------------

def check_the_week_8_gate_is_one_predicate():
    df = _frame()
    nr = PH.non_rookie_mask(df)
    early = lotg._early_rookie_class_mask(df, nr, current_season=2026,
                                          season_weeks_completed=5)
    ok = _ok("before week 8 the CURRENT class is flagged",
             set(df.loc[early.astype(bool), "Year"]) == {"2026"},
             sorted(set(df.loc[early.astype(bool), "Year"])))
    ok &= _ok("a past class is not flagged",
              not bool((early & (df["Year"] == "2025")).any()))
    ok &= _ok("a non-rookie pick is never flagged", not bool((early & nr).any()))

    at8 = lotg._early_rookie_class_mask(df, nr, 2026, 8)
    ok &= _ok("from week 8 nothing is held back", not bool(at8.any()))

    # The same predicate drives the withheld O-Score.
    withheld = df.copy()
    lotg._withhold_early_rookie_oscore(withheld, nr, 2026, 5)
    o = pd.to_numeric(withheld["O-Score"], errors="coerce")
    ok &= _ok("the withheld O-Score uses it — 2026 blank",
              bool(o[withheld["Year"] == "2026"].isna().all()))
    ok &= _ok("and only 2026 is blank",
              not bool(o[withheld["Year"] != "2026"].isna().any()))

    for label, bad in (("no mask", (None, 2026, 5)),
                       ("no season", (nr, None, 5)),
                       ("no week count", (nr, 2026, None))):
        m = lotg._early_rookie_class_mask(df, *bad)
        ok &= _ok(f"missing input ({label}) -> nothing flagged, no raise",
                  m is not None and not bool(m.any()))
    return ok


def check_drafting_skill_weight_is_a_half():
    ok = _ok("non-rookie picks weigh half a rookie pick in Drafting skill",
             lotg._NONROOKIE_SKILL_WEIGHT == 0.5, lotg._NONROOKIE_SKILL_WEIGHT)
    return ok


# --- 5. against the real build, when it is there --------------------------

def check_against_the_committed_build():
    """The de-trend on the real non-rookie picks: bounded, rookie-safe, gentle."""
    import lotg_support.inquiry as Q
    try:
        nr_sheet = Q.load_sheet("non_rookie_picks")
        rk_sheet = Q.load_sheet("rookie_picks")
    except FileNotFoundError:
        print("  [SKIP] no exports/ — data check skipped")
        return True
    if nr_sheet.empty or rk_sheet.empty:
        print("  [SKIP] empty pick sheets — data check skipped")
        return True
    ok = _ok("non-rookie sheet is only startup + vet",
             set(nr_sheet["Year"]) <= {"startup", "2021 (vet)"},
             sorted(set(nr_sheet["Year"])))
    ok &= _ok("rookie sheet has neither",
              not ({"startup"} & set(rk_sheet["Year"]))
              and not any("vet" in str(y) for y in rk_sheet["Year"]))
    o = pd.to_numeric(nr_sheet["O-Score"], errors="coerce").dropna()
    ok &= _ok("every non-rookie O-Score is inside 0-100",
              bool(((o >= 0) & (o <= 100)).all()) if len(o) else True,
              f"min {o.min():.1f} max {o.max():.1f}" if len(o) else "none scored")
    ok &= _ok("the virtual 'picks' sheet is still the two of them",
              len(Q.load_sheet("picks")) == len(nr_sheet) + len(rk_sheet))
    return ok


def check_the_ref_index_rebuilds_the_frame_in_build_order():
    """PH#N counts through the FRAME, and the frame interleaves the two sheets.

    Concatenating the sheets is a different order, so the map is the only thing
    that can put row N back. Round-trip it on a frame shaped like the real one:
    a vet block, a rookie block, then the startup — the interleaving that broke
    naive concatenation in the first place."""
    import tempfile

    frame = pd.DataFrame({
        "Year": ["2021 (vet)"] * 2 + ["2022"] * 3 + ["startup"] * 2 + ["2023"],
        "Number": ["1.01", "1.02", "1.01", "1.02", "1.03", "1.01", "1.02", "1.01"],
    })
    nr = frame[PH.non_rookie_mask(frame)]
    rk = frame[~PH.non_rookie_mask(frame)]
    # What the writer hands over: ref -> (sheet, XLSX row) = csv row + 2.
    ref_target = {}
    for sheet, part in (("non_rookie_picks", nr), ("rookie_picks", rk)):
        for row_i, orig in enumerate(part.index):
            ref_target[int(orig) + 1] = (sheet, row_i + 2)

    with tempfile.TemporaryDirectory() as d:
        ok = _ok("write_index returns a path under raw/",
                 str(pick_index.write_index(d, ref_target)).endswith(
                     f"{pick_index.RAW_SUBDIR}/{pick_index.FILE_NAME}"))
        sheets = {"non_rookie_picks": nr.reset_index(drop=True),
                  "rookie_picks": rk.reset_index(drop=True)}
        rebuilt = pick_index.order_frame(d, sheets)
        ok &= _ok("rebuilt frame is the original, row for row",
                  rebuilt is not None
                  and list(rebuilt["Year"]) == list(frame["Year"])
                  and list(rebuilt["Number"]) == list(frame["Number"]),
                  None if rebuilt is None else list(rebuilt["Year"]))
        ok &= _ok("and it is NOT plain concatenation",
                  list(pd.concat(sheets.values(), ignore_index=True)["Year"])
                  != list(frame["Year"]))
        ok &= _ok("_sheet says which half each row came from",
                  rebuilt is not None
                  and set(rebuilt.loc[PH.non_rookie_mask(rebuilt), "_sheet"]) == {"non_rookie_picks"})
        # dict-of-lists variant, which is what the pick-chain guard reads
        as_rows = {k: v.to_dict("records") for k, v in sheets.items()}
        ordered = pick_index.order_rows(d, as_rows)
        ok &= _ok("order_rows agrees with order_frame",
                  ordered is not None
                  and [r["Year"] for r in ordered] == list(frame["Year"]))
        # A gapped map cannot be indexed positionally: say so, do not guess.
        gapped = dict(ref_target)
        gapped.pop(max(gapped))
        gapped[max(gapped) + 5] = ("rookie_picks", 2)
        pick_index.write_index(d, gapped)
        ok &= _ok("a gapped map reads as unusable, not as a guess",
                  pick_index.load_index(d) is None)
    with tempfile.TemporaryDirectory() as d:
        ok &= _ok("a pre-split exports/ reads as absent, not as an error",
                  pick_index.load_index(d) is None
                  and pick_index.order_rows(d, {}) is None
                  and pick_index.order_frame(d, {}) is None)
    return ok


def check_the_retired_picks_csv_is_deleted_not_left_behind():
    """A rename does not retire the old CSV — the build has to say so.

    Left alone it survives the checkout untouched, so `git add exports` never
    stages it, the zip globs it in, and every test gating on the old filename
    keeps passing against a frozen table."""
    ok = _ok("picks.csv is on the build's retired list",
             "picks.csv" in getattr(lotg, "_RETIRED_EXPORTS", ()))
    # The build deletes it and the export-refresh commit stages that deletion,
    # so the file goes away at exactly the moment the two sheets replacing it
    # arrive. Only assert it against a tree that HAS been rebuilt: the committed
    # exports/ is a replay cache that lags main, and hand-deleting the old CSV
    # there just leaves the tree half-split until the next refresh.
    exports = _ROOT / "exports"
    if (exports / "non_rookie_picks.csv").exists():
        ok &= _ok("a post-split exports/ has no picks.csv left",
                  not (exports / "picks.csv").exists())
    else:
        print("  [SKIP] exports/ predates the split — nothing to retire yet")
    # Nothing may read the retired name back into existence.
    readers = []
    # lotg.py is where the name is RETIRED, and this file is where that is
    # asserted; everyone else naming it would be reading the frozen table.
    exempt = {"lotg.py", Path(__file__).name}
    for folder in ("tests", "scripts", "lib", "src"):
        for f in sorted((_ROOT / folder).rglob("*.py")):
            if f.name in exempt:
                continue
            if '"picks.csv"' in f.read_text(errors="ignore"):
                readers.append(str(f.relative_to(_ROOT)))
    ok &= _ok("nothing loads exports/picks.csv any more", not readers, readers)
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_split_is_exhaustive_disjoint_and_index_preserving,
              check_mask_survives_both_naming_stages,
              check_positions_read_number_as_draft_order_and_append_the_vet,
              check_detrend_only_touches_non_rookie_rows,
              check_detrend_lifts_late_picks_and_lowers_early_ones,
              check_lambda_scales_the_shift_and_zero_is_a_no_op,
              check_the_starts_term_rewards_length_not_rate,
              check_the_fitted_curve_is_never_upward_sloping,
              check_detrend_never_fails_a_build,
              check_the_week_8_gate_is_one_predicate,
              check_drafting_skill_weight_is_a_half,
              check_the_ref_index_rebuilds_the_frame_in_build_order,
              check_the_retired_picks_csv_is_deleted_not_left_behind,
              check_against_the_committed_build):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_pick_sheets_split():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
