"""Shared classifier for build-volatile / recompute-sensitive stat columns.

A "volatile" column is one whose value legitimately moves between two builds even
for a COMPLETED season — because it is a league-relative percentile, a
present-day rolling window, a chain of custody answered as of today, or a
row-index reference — rather than a fixed historical fact. Two Phase-14 consumers
need the same list:

  * `scripts/audit_weekly.py` — so recompute drift on a past-season row isn't
    mis-read as a historical-immutability break.
  * `lib/lotg_support/digest.py` — so the same drift doesn't manufacture a fake
    "all-time leaderboard move" in the weekly email. In the offseason (no games)
    an all-time board should only move on a real roster / pick / trade event; a
    percentile like Luck that wobbles a hair on every recompute would otherwise
    flip a rank-boundary tie and email the league about nothing.

Empirical basis (see plan/AUDIT_PHASE14_3PART.md finding F1, and the run
451↔452 same-day rebuild check): across identical-day rebuilds the ONLY all-time
column that churns is the `skill` family; the league-relative `Luck` family
drifts as soon as any historical input is revised. Everything else stays under
the immutability check / eligible for crossings, which is where a genuine
regression shows up.
"""
from __future__ import annotations

_VOLATILE_SUBSTRINGS = (
    "link to",
    "o-score",
    "skill",                # Drafting / Trading / Transaction skill
    "luck",                 # Luck / Avg yearly luck — league-relative each season
    "length of tenure",
    "trade impact score",
    "date dropped/traded",
    "year later", "years later",    # rolling: KTC value difference N year(s) later
    "year after", "years after",    # rolling: KTC N year(s) after draft day
)
_VOLATILE_EXACT = {
    "Luck", "Hardship", "Starter-adjusted Hardship", "Number of teams",
    "Tanking", "Future draft capital", "Startup draft players remaining",
    # Trade chain-of-custody: "where did the assets from this deal end up",
    # answered as of TODAY. Any new trade rewrites them on every historical deal
    # the assets descend from — which is the column set doing exactly what it
    # says, not a completed season coming unfrozen. One 2026-08 trade of Tee
    # Higgins rewrote three trade rows from 2024-25 in the 2026-08-05 audit.
    # Matched exactly, not by substring: the sibling counts ("Number of assets
    # traded away") and the deal's own contents ("Assets received" / "sent") are
    # fixed historical facts and must stay under the immutability check.
    "Assets retained now", "Assets traded away", "Assets dropped to FA",
    "Return from trades", "Additional assets traded away in those deals",
    "Return from trades of trades...of trades. Keep going until present day",
}


def is_volatile_column(column: str) -> bool:
    """True if a completed-season value in this column is expected to drift
    between builds (so it must not count as a historical-immutability break, nor
    as an all-time leaderboard move in the digest)."""
    if column in _VOLATILE_EXACT:
        return True
    c = str(column).lower()
    return any(s in c for s in _VOLATILE_SUBSTRINGS)
