"""Shared logic for the two pick sheets.

The picks frame is built as ONE table (`context["pick_history"]`) and split into
two OUTPUT sheets at write time:

  * ``non_rookie_picks`` — the 2020 ESPN startup draft + the 2021 supplemental
    veteran draft, and
  * ``rookie_picks`` — every rookie draft.

Splitting at OUTPUT rather than at build time is deliberate. Every ``PH#N``
cross-sheet reference (trades' per-asset links, add/drops, player_additions) is
``ph``'s positional index + 1, and the pick chains are keyed the same way, so
re-partitioning the frame mid-build would renumber all of them and move rows on
sheets this change is not meant to touch. Built as one, written as two, the refs
and every other sheet stay byte-identical.

The two drafts are not comparable, which is why they are no longer one sheet: a
19-round startup snake and a 4-round rookie draft have different slot economics,
so the same O-Score means different things in each. The startup + vet pool is
already ranked in its own percentile universe upstream; this module adds the
draft-slot de-trend that universe still needs.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

FRAME_KEY = "pick_history"  # internal context key shared by both output sheets

# --- Non-rookie O-Score de-trend -------------------------------------------
# The startup's O-Score still carries a draft-slot trend: an early pick is
# expected to return more than a 19th-round flier, so an early bust and a late
# bust with the same on-field return do not deserve the same grade. `LAMBDA`
# says how much of that trend to remove — 0.0 leaves the O-Score exactly as
# computed, 1.0 removes the fitted trend entirely. HALF (0.5) is deliberate:
# fully neutralising the slot would say a late-round dart that missed is
# blameless, which the data contradicts (deep startup rounds returned real
# value), while leaving it in blames the 1.07 bust no more than the 19.07 one.
NONROOKIE_OSCORE_LAMBDA = 0.5

# Slots per round. The startup and the vet draft are both 8-team drafts, and
# this mirrors the `_rsize` the build's own pick-adjustment window uses.
ROUND_SIZE = 8

_OSCORE_MIN, _OSCORE_MAX = 0.0, 100.0


def _su_flag(v: Any) -> bool:
    """`_is_startup` is set only on the 152 startup rows, so every other row
    holds NaN — and NaN is TRUTHY. Always ask through this (mirrors `_su_row`
    in lotg.py)."""
    return v is True or str(v).strip().lower() == "true"


def _empty_mask(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index if df is not None else [])


def startup_mask(df: pd.DataFrame) -> pd.Series:
    """The 2020 ESPN startup picks.

    Reads `_is_startup` when present and falls back to the displayed
    `Year == "startup"`. Both are needed: the startup's Year is still 2020 for
    most of the build and is relabeled to "startup" only near the end, while
    `_is_startup` is internal and dropped on write — so exactly one of the two
    is available depending on when the caller runs.
    """
    if df is None or getattr(df, "empty", True):
        return _empty_mask(df)
    if "_is_startup" in df.columns:
        m = df["_is_startup"].map(_su_flag)
        if bool(m.any()):
            return m.astype(bool)
    if "Year" in df.columns:
        return df["Year"].astype(str).str.strip().str.lower().eq("startup")
    return _empty_mask(df)


def vet_mask(df: pd.DataFrame) -> pd.Series:
    """The 2021 supplemental VETERAN draft (Year tagged `2021 (vet)`)."""
    if df is None or getattr(df, "empty", True) or "Year" not in df.columns:
        return _empty_mask(df)
    return df["Year"].astype(str).str.contains("vet", case=False, na=False)


def non_rookie_mask(df: pd.DataFrame) -> pd.Series:
    """Startup + 2021 vet — the rows that become `non_rookie_picks`."""
    if df is None or getattr(df, "empty", True):
        return _empty_mask(df)
    return (startup_mask(df) | vet_mask(df)).astype(bool)


def _round_slot(number: Any) -> Optional[tuple]:
    """`"12.08"` -> (12, 8). None when the cell is not a pick number."""
    m = pd.Series([str(number)]).str.extract(r"\s*(\d+)\.(\d+)")
    if m.isna().any(axis=None):
        return None
    return int(m.iloc[0, 0]), int(m.iloc[0, 1])


def overall_positions(df: pd.DataFrame, mask: Optional[pd.Series] = None,
                      round_size: int = ROUND_SIZE) -> pd.Series:
    """Overall draft position for the non-rookie picks, as ONE sequence.

    The pick NUMBER is the position picked FROM at every draft — including the
    snake startup, where it is not the owner's constant slot — so overall
    position reads straight back out of it as `(round - 1) * round_size + slot`.

    The 2021 vet draft is positioned as a CONTINUATION of the startup (vet 1.01
    follows the startup's last pick), which is exactly how the build's own
    pick-adjustment sequences the two. NaN for any row outside `mask` or whose
    Number does not parse.
    """
    if df is None or getattr(df, "empty", True) or "Number" not in df.columns:
        return pd.Series(np.nan, index=df.index if df is not None else [], dtype=float)
    if mask is None:
        mask = non_rookie_mask(df)
    mask = mask.astype(bool)
    su, vet = startup_mask(df), vet_mask(df)

    pos = pd.Series(np.nan, index=df.index, dtype=float)
    for i in df.index[mask]:
        rs = _round_slot(df.at[i, "Number"])
        if rs is None:
            continue
        pos.at[i] = (rs[0] - 1) * int(round_size) + rs[1]

    # Append the vet draft after the startup so the two share one sequence.
    su_positions = pos.where(su & mask).dropna()
    su_max = float(su_positions.max()) if not su_positions.empty else 0.0
    vet_rows = (vet & mask) & pos.notna()
    pos.loc[vet_rows] = pos.loc[vet_rows] + su_max
    return pos


def detrend_non_rookie_oscore(df: pd.DataFrame,
                              mask: Optional[pd.Series] = None,
                              lam: float = NONROOKIE_OSCORE_LAMBDA,
                              round_size: int = ROUND_SIZE) -> Optional[dict]:
    """Partially remove the draft-slot trend from the non-rookie O-Score.

    Fits expected O-Score as a smooth, monotone-decreasing curve in overall
    draft position — `expected = a + b·ln(position)`, with `b` clamped at 0 so
    the curve can never reward a later pick's *expectation* — then moves each
    score `lam` of the way off that expectation:

        adjusted = O − lam · (expected(position) − mean expected)

    Being a function of position only, it shifts whole draft regions and never
    reorders picks *within* one slot, and it leaves the pool's mean O-Score
    where it was. `lam=0` is a no-op; `lam=1` removes the fitted trend
    entirely. The result is clamped to the O-Score's own 0-100 range and
    rounded like it (1 decimal).

    Mutates `df` in place and returns a small dict of fit diagnostics for the
    build log (None when it could not run). Safe on any frame: a missing
    column, too few scored rows, or a degenerate fit all leave the O-Score
    untouched rather than failing a build.
    """
    if (df is None or getattr(df, "empty", True)
            or "O-Score" not in df.columns or "Number" not in df.columns):
        return None
    try:
        lam = float(lam)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(lam) or lam == 0.0:
        return None
    if mask is None:
        mask = non_rookie_mask(df)
    mask = mask.reindex(df.index).fillna(False).astype(bool)
    if not bool(mask.any()):
        return None

    pos = overall_positions(df, mask=mask, round_size=round_size)
    osc = pd.to_numeric(df["O-Score"], errors="coerce")
    fit_rows = mask & pos.notna() & osc.notna() & (pos > 0)
    n = int(fit_rows.sum())
    if n < 3:
        return None

    x = np.log(pos[fit_rows].to_numpy(dtype=float))
    y = osc[fit_rows].to_numpy(dtype=float)
    if not (np.isfinite(x).all() and np.isfinite(y).all()) or float(np.ptp(x)) == 0.0:
        return None
    try:
        b, a = np.polyfit(x, y, 1)
    except Exception:
        return None
    if not (np.isfinite(a) and np.isfinite(b)):
        return None
    # Monotone NON-INCREASING by construction: a positive slope would say a
    # later pick is expected to return more, which is not a draft-slot trend.
    b = min(float(b), 0.0)

    expected = a + b * np.log(pos[fit_rows].to_numpy(dtype=float))
    # Centre on the fitted curve's OWN mean, not the observed one. For an
    # ordinary least-squares fit the two are equal (the residuals sum to zero),
    # so this changes nothing in the normal case — but when the slope has been
    # clamped to 0 the curve is a constant, and only this makes the whole
    # transform the no-op it should be. It also keeps the pool's mean O-Score
    # fixed: the de-trend redistributes, it does not inflate.
    adjusted = y - lam * (expected - float(expected.mean()))
    adjusted = np.clip(adjusted, _OSCORE_MIN, _OSCORE_MAX).round(1)

    df.loc[fit_rows, "O-Score"] = adjusted
    return {
        "rows": n,
        "lambda": lam,
        "intercept": round(float(a), 4),
        "slope": round(float(b), 4),
        "mean_expected": round(float(expected.mean()), 4),
        "max_abs_shift": round(float(np.abs(adjusted - y).max()), 4),
    }
