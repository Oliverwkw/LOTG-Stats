"""Pick-label -> dynasty-daddy candidate translation (lib/lotg_support/ktc.py).

`pick_label_candidates` maps a LOTG pick label onto KTC's 12-team Early/Mid/Late
quarters by OVERALL draft position in this 8-team league. The live build feeds it
labels normalised by `_pick_val_label`, but display strings carry a parenthetical
rider ('2026 3.05(T. Hurst)') and picks can arrive as a bare round ('2027 4').
Both used to fall through to [] — an unvalued asset that reads as N/A rather than
raising, so the gap was invisible in the exports.

These guard the parsing contract:
  * a rider never changes the answer (paren form == clean form)
  * a bare round == the explicit-unknown '??' form
  * the 2.09 toilet-pick convention still normalises to Early 2nd
  * genuine garbage still returns [] rather than a bogus quarter

Run: python tests/test_ktc_pick_labels.py
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.ktc import (  # noqa: E402
    ValueIndex,
    asset_value_at,
    pick_label_candidates as plc,
)


def test_clean_slot_labels():
    assert plc("2026 1.01") == ["2026 Early 1st"]
    assert plc("2026 3.05") == ["2026 Late 2nd"]
    assert plc("2026 4.06") == ["2026 Mid 3rd"]


def test_parenthetical_rider_matches_clean_form():
    # The rider names the drafted player or the original owner; it must not
    # change the valuation.
    for dirty, clean in (
        ("2026 3.05(T. Hurst)", "2026 3.05"),
        ("2026 3.02(C. Okonkwo)", "2026 3.02"),
        ("2026 4.06(S. Bell)", "2026 4.06"),
        ("2027 4(LWebs53)", "2027 4"),
        ("2028 3(plehv79)", "2028 3"),
    ):
        assert plc(dirty) == plc(clean), dirty
        assert plc(dirty), f"{dirty} resolved to nothing"


def test_bare_round_equals_unknown_slot():
    # A round with no slot spans the whole round, same as the explicit '??'.
    assert plc("2027 4") == plc("2027 4.??")
    assert plc("2027 3") == plc("2027 3.??")
    assert plc("2027 4") == ["2027 Early 3rd", "2027 Mid 3rd"]


def test_unknown_slot_spans_round():
    # Round 3 in an 8-team draft = overall 17-24 = Mid 2nd + Late 2nd.
    assert plc("2027 3.??") == ["2027 Mid 2nd", "2027 Late 2nd"]


def test_toilet_pick_209_normalises():
    # League convention: the 2.09 reward pick is valued as a 2.08 (Early 2nd),
    # not the Mid 2nd its raw overall position (17) would imply.
    assert plc("2025 2.09") == ["2025 Early 2nd"]
    assert plc("2025 2.09(X)") == ["2025 Early 2nd"]
    assert plc("2025 2.9") == ["2025 Early 2nd"]


def test_garbage_returns_empty():
    for bad in ("", "   ", "garbage", "2026", "2026 x.y", "(2026 1.01)", "abc def"):
        assert plc(bad) == [], bad


def test_whitespace_tolerated():
    assert plc("  2026   1.01  ") == ["2026 Early 1st"]


# --------------------------------------------------------------------------
# Far-future picks: classes KTC doesn't list yet fall back to the furthest
# class it DOES list, rather than going unvalued.
# --------------------------------------------------------------------------

def _index_listing_through(last_year: int) -> ValueIndex:
    """A ValueIndex quoting round-3 quarters for every class up to last_year."""
    idx = ValueIndex()
    for yr in range(2027, last_year + 1):
        base = 900 - (yr - 2027) * 100
        idx.add_pick(f"{yr} Mid 2nd", [{"date": "2026-01-01", "trade_value": base}], "trade_value")
        idx.add_pick(f"{yr} Late 2nd", [{"date": "2026-01-01", "trade_value": base - 100}], "trade_value")
    return idx


def test_listed_class_uses_own_value():
    idx = _index_listing_through(2029)
    t = date(2026, 7, 21)
    # Round 3 spans Mid+Late 2nd, so the '??' value is the mean of the two.
    assert asset_value_at("2027 3.??", None, t, idx) == 850.0
    assert asset_value_at("2029 3.??", None, t, idx) == 650.0


def test_unlisted_class_clamps_to_furthest_listed():
    idx = _index_listing_through(2029)
    t = date(2026, 7, 21)
    furthest = asset_value_at("2029 3.??", None, t, idx)
    for far in ("2030 3.??", "2031 3.??", "2035 3.??"):
        assert asset_value_at(far, None, t, idx) == furthest, far


def test_clamp_follows_the_listing_horizon():
    # As KTC extends its horizon, the substitute moves with it.
    t = date(2026, 7, 21)
    near = asset_value_at("2031 3.??", None, t, _index_listing_through(2028))
    far = asset_value_at("2031 3.??", None, t, _index_listing_through(2030))
    assert near == 750.0      # clamped to 2028
    assert far == 550.0       # clamped to 2030
    assert near != far


def test_no_listing_at_all_stays_none():
    idx = ValueIndex()
    assert asset_value_at("2031 3.??", None, date(2026, 7, 21), idx) is None


def test_never_substitutes_an_already_drafted_class():
    # A 2025 pick valued in 2026 must not borrow a 2024 (long-drafted) quote.
    idx = _index_listing_through(2029)
    assert asset_value_at("2025 3.??", None, date(2026, 7, 21), idx) is None


# --------------------------------------------------------------------------
# The draft anchor must come from _draft_anchor everywhere, not a hardcode.
# --------------------------------------------------------------------------

def test_no_stray_aug28_draft_anchors():
    """Only the _draft_anchor fallback may hardcode Aug 28.

    The anchor was originally written as a literal `date(_yr, 8, 28)` in five
    separate places (tenure, post-draft PPG, age when drafted, the KTC
    checkpoints, the tz-aware tenure event). When it became dynamic, a
    search-and-replace caught the ones assigning `_draft_iso` and MISSED the
    rest — so `Age when drafted` silently kept computing at Aug 28 while every
    neighbouring stat moved. Nothing failed; the column just stayed wrong.

    Any new hardcode is almost certainly the same mistake, so pin the count.
    """
    src = (_ROOT / "src" / "lotg.py").read_text().splitlines()
    hits = [
        (i + 1, ln.strip())
        for i, ln in enumerate(src)
        if re.search(r"\b8,\s*28\b", ln) or "-08-28" in ln
    ]
    # Exactly one survivor: the fallback inside _draft_anchor, for a season with
    # no draft on record.
    assert len(hits) == 1, (
        "unexpected hardcoded Aug-28 draft anchor(s) — use _draft_anchor/"
        f"_draft_anchor_iso instead:\n" + "\n".join(f"  lotg.py:{n}: {t}" for n, t in hits)
    )
    line_no, text = hits[0]
    assert "_days[0] if _days else" in text, (
        f"the one permitted Aug-28 literal should be the _draft_anchor fallback, "
        f"got lotg.py:{line_no}: {text}"
    )


# --------------------------------------------------------------------------
# Worth-zero must stay distinct from could-not-value.
# --------------------------------------------------------------------------

def test_zero_and_none_are_distinct_outcomes():
    """A retired player resolves to 0.0; an unknown one resolves to None.

    The trade KTC columns lean on this: a side whose assets are all 0 is
    genuinely worthless (computable), a side nothing resolved on is unknown
    (N/A). If asset_value_at ever collapsed the two, that distinction dies.
    """
    idx = ValueIndex()
    idx.add_player("known", [{"date": "2021-06-01", "trade_value": 900}], "trade_value")
    # On the rolls today, so a post-floor absence is not zeroed by the off-rolls rule.
    idx.active_sids = {"known", "ranked_but_late"}
    # A player KTC never ranked, queried after the floor -> confirmed worthless.
    assert asset_value_at(None, "never_ranked", date(2024, 1, 1), idx) == 0.0
    # A real value resolves as itself.
    assert asset_value_at(None, "known", date(2024, 1, 1), idx) == 900.0
    # An unknown asset with no id at all -> None, not 0.
    assert asset_value_at(None, None, date(2024, 1, 1), idx) is None


def test_side_values_does_not_drop_zeros():
    """`_side_values` must not filter on `v > 0`.

    It used to, which made a side of all-worthless assets look identical to a
    side nothing could be priced on — so `_diff_at` blanked the row. A trade of
    Kerryon Johnson (0 by 2022) for Alexander Mattison (2546) read N/A rather
    than +2546. 20 cells across 8 mirrored trade rows were lost to it.

    Source-level because `_side_values` is a closure inside build_all.
    """
    src = (_ROOT / "src" / "lotg.py").read_text()
    start = src.index("def _side_values(")
    body = src[start:start + 2000]
    assert "and v > 0" not in body, (
        "_side_values is dropping zero-valued assets again — that conflates "
        "'worth nothing' with 'could not be valued' and blanks real trades"
    )


if __name__ == "__main__":
    for fn in (
        test_no_stray_aug28_draft_anchors,
        test_zero_and_none_are_distinct_outcomes,
        test_side_values_does_not_drop_zeros,
        test_clean_slot_labels,
        test_parenthetical_rider_matches_clean_form,
        test_bare_round_equals_unknown_slot,
        test_unknown_slot_spans_round,
        test_toilet_pick_209_normalises,
        test_garbage_returns_empty,
        test_whitespace_tolerated,
        test_listed_class_uses_own_value,
        test_unlisted_class_clamps_to_furthest_listed,
        test_clamp_follows_the_listing_horizon,
        test_no_listing_at_all_stays_none,
        test_never_substitutes_an_already_drafted_class,
    ):
        fn()
        print(f"ok: {fn.__name__}")
    print("all pick-label checks passed")
