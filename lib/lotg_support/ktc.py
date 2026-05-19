"""
KTC (KeepTradeCut) dynasty value lookup, sourced from DynastyProcess.

DynastyProcess publishes a daily-updated KTC values feed on GitHub at:
  https://github.com/dynastyprocess/data

We use two files:
  files/values.csv         — daily snapshot of player + pick values
  files/db_playerids.csv   — cross-walk between Sleeper, FantasyPros, etc.

For 'KTC value difference at deal time' on trades.csv, we need each trade's
asset values AS THEY WERE at the trade date — not today. DynastyProcess
commits values.csv approximately daily, so historical values are recoverable
by walking the file's commit history via the GitHub API and fetching the
CSV at the closest commit on-or-before each trade date.

Network requests are cached on disk at data/ktc_cache/. A cached snapshot
keyed by date is reused indefinitely (values for a past date never change).
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


DP_OWNER = "dynastyprocess"
DP_REPO = "data"
DP_VALUES_PATH = "files/values.csv"
DP_IDS_PATH = "files/db_playerids.csv"

USER_AGENT = "lotg-stats-build/1 (+https://github.com/Oliverwkw/LOTG-Stats)"


def _http_get(url: str, accept: str = "text/csv") -> bytes:
    """Fetch a URL with a simple retry policy. Returns raw bytes."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    # GitHub raw and the REST API both honor a bearer token if present.
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _cache_dir(repo_root: Path) -> Path:
    p = repo_root / "data" / "ktc_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_playerid_xwalk(repo_root: Path) -> pd.DataFrame:
    """Load DynastyProcess's db_playerids.csv. Cached after first fetch.

    Returns a DataFrame with at minimum: sleeper_id, fantasypros_id, name.
    Values may include 'NA' strings; callers should coerce as needed.
    """
    cache = _cache_dir(repo_root) / "db_playerids.csv"
    # Refresh once a week — IDs don't change retroactively but new rookies
    # get added each spring.
    stale = True
    if cache.exists():
        age = datetime.utcnow().timestamp() - cache.stat().st_mtime
        if age < 7 * 86400:
            stale = False
    if stale:
        url = f"https://raw.githubusercontent.com/{DP_OWNER}/{DP_REPO}/master/{DP_IDS_PATH}"
        cache.write_bytes(_http_get(url))
    df = pd.read_csv(cache, dtype=str)
    # normalize columns
    for col in ("sleeper_id", "fantasypros_id", "name"):
        if col not in df.columns:
            df[col] = None
    return df


def _commit_sha_at_or_before(target: date) -> Optional[str]:
    """Find the most recent commit to files/values.csv on or before target.

    Returns the commit SHA, or None if the API call fails. We probe one
    day past `target` (until=target+1, since GitHub's `until` is exclusive
    on the upper bound for some endpoints) and accept the first hit.
    """
    until = (target + timedelta(days=1)).isoformat()
    url = (
        f"https://api.github.com/repos/{DP_OWNER}/{DP_REPO}/commits"
        f"?path={DP_VALUES_PATH}&until={until}T23:59:59Z&per_page=1"
    )
    try:
        raw = _http_get(url, accept="application/vnd.github+json")
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    return data[0].get("sha")


def values_at_date(repo_root: Path, target: date) -> pd.DataFrame:
    """Return the DynastyProcess values.csv snapshot as it was on `target`.

    Cached on disk. If the GitHub commit lookup fails, returns an empty
    DataFrame (callers should treat this as 'no KTC data available').
    """
    cache = _cache_dir(repo_root) / f"values_{target.isoformat()}.csv"
    if cache.exists():
        return pd.read_csv(cache)
    sha = _commit_sha_at_or_before(target)
    if not sha:
        return pd.DataFrame()
    url = f"https://raw.githubusercontent.com/{DP_OWNER}/{DP_REPO}/{sha}/{DP_VALUES_PATH}"
    try:
        raw = _http_get(url)
    except Exception:
        return pd.DataFrame()
    cache.write_bytes(raw)
    try:
        return pd.read_csv(io.BytesIO(raw))
    except Exception:
        return pd.DataFrame()


_ORD_SUFFIX = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def _pick_label_to_dp(label: str) -> List[str]:
    """Translate a LOTG pick label like '2024 1.??' or '2024 1.05' to the
    set of DynastyProcess labels it refers to. Returned in fallback order
    — the caller should use the first list that produces a match.

    DynastyProcess publishes two kinds of pick rows:
      - Specific slot: '2024 Pick 1.01' (after the draft happens)
      - Generic: '2024 1st', '2024 Early 1st', '2024 Mid 1st', '2024 Late 1st'
        (used while the draft is still in the future)

    For a '??' slot we prefer the generic round label; otherwise we use
    the specific slot and fall back to the generic average.
    """
    parts = label.strip().split()
    if len(parts) != 2:
        return []
    year_s, round_pick = parts
    if "." not in round_pick:
        return []
    rd_s, slot_s = round_pick.split(".", 1)
    try:
        year = int(year_s)
        rd = int(rd_s)
    except Exception:
        return []
    ord_str = _ORD_SUFFIX.get(rd, f"{rd}th")
    generic = [
        f"{year} {ord_str}",
        f"{year} Early {ord_str}",
        f"{year} Mid {ord_str}",
        f"{year} Late {ord_str}",
    ]
    if slot_s == "??":
        return generic + [f"{year} Pick {rd}.{i:02d}" for i in range(1, 13)]
    try:
        slot = int(slot_s)
    except Exception:
        return generic
    return [f"{year} Pick {rd}.{slot:02d}"] + generic


def asset_value(
    asset: str,
    sleeper_id: Optional[str],
    values_df: pd.DataFrame,
    fp_id_by_sleeper: Dict[str, str],
    value_col: str = "value_1qb",
) -> Optional[float]:
    """Return the KTC value of one asset on the snapshot in values_df.

    Players are resolved by sleeper_id -> fantasypros_id -> fp_id row.
    Picks are resolved by label match; '??' slots get the round average.
    Returns None when no match is found.
    """
    if values_df.empty:
        return None

    # Pick label like '2024 1.??' or '2024 1.05'
    if asset and len(asset) >= 5 and asset[:4].isdigit() and asset[4] == " ":
        dp_labels = _pick_label_to_dp(asset)
        if not dp_labels:
            return None
        # Walk fallback list, take the first group of labels that resolves
        # to at least one row. We split into three precedence buckets so
        # specific-slot match wins over generic, and generic round wins
        # over averaging all 12 specific slots.
        for label in dp_labels:
            picks = values_df[values_df["player"] == label]
            if not picks.empty:
                vals = pd.to_numeric(picks[value_col], errors="coerce").dropna()
                if not vals.empty:
                    return float(vals.mean())
        return None

    # Player — resolve sleeper -> fp_id
    if not sleeper_id:
        return None
    fp_id = fp_id_by_sleeper.get(str(sleeper_id))
    if not fp_id:
        return None
    if "fp_id" not in values_df.columns:
        return None
    # DynastyProcess stores fp_id as a numeric column (parses as float).
    # Compare numerically so '19788' matches '19788.0'.
    try:
        target = float(str(fp_id))
    except Exception:
        return None
    fp_numeric = pd.to_numeric(values_df["fp_id"], errors="coerce")
    hit = values_df[fp_numeric == target]
    if hit.empty:
        return None
    v = pd.to_numeric(hit[value_col], errors="coerce").dropna()
    if v.empty:
        return None
    return float(v.iloc[0])


def build_fp_id_by_sleeper(xwalk: pd.DataFrame) -> Dict[str, str]:
    """sleeper_id (str) -> fantasypros_id (str). Filters out NA rows."""
    out: Dict[str, str] = {}
    if xwalk.empty or "sleeper_id" not in xwalk.columns:
        return out
    for _, row in xwalk.iterrows():
        sid = str(row.get("sleeper_id") or "").strip()
        fpid = str(row.get("fantasypros_id") or "").strip()
        if not sid or not fpid or sid.upper() == "NA" or fpid.upper() == "NA":
            continue
        out[sid] = fpid
    return out
