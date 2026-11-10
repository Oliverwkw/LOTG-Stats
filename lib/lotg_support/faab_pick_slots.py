"""A traded pick's slot as it was knowable on the trade date, for the FAAB system's pick prices (Oliver, 2026-11-10).

A pick's number is not known until its deciding season ends. Before then it is estimable from that day's standings,
and the estimate firms up as the season is played. This mirrors what the KTC "Price paid" already does
(`acquisition.project_slot_odds` / `post_season_slot_odds`, src/lotg.py's `_pae_traded_pick_faab`), on the FAAB
system's own inputs:

  - two or more drafts out (its deciding season not next up or under way): the round's average slot price;
  - its deciding season next up, not started: odds over the slots from the original team's roster strength that day
    (the sum of its best ROSTER_TOP players' FAAB values, `faab_history.FaabIndex`), spread SLOT_SIGMA[0] = 2.75
    slots, so it is still close to the round average;
  - during the regular season: roster strength blended toward the stat that sets the order (record; under the Max PF
    rule, 2026 draft on, record for the playoff / bottom split and Max PF within the bottom four), the blend and the
    spread narrowing by week (`acquisition.roster_weight`, `SLOT_SIGMA`, fitted on 2021-25);
  - regular season over: the bottom four by the draft's rule, the playoff four over 5-8, then losers / winners of
    the semifinals over 5-6 / 7-8;
  - after the season's last week: the exact slot (the label's number).

The price is the odds-weighted mean of the slot prices (`faab_inputs.Picks.slot_values`). Nothing reads the slot the
pick eventually landed in before its order is set; the label's number is used only once it is.

Inputs are the committed exports (team_week, rookie_picks, player_additions) and the FAAB history; any piece
missing falls back to the round average (the price before 2026-11-10).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import acquisition as A
from . import faab_frame as kp

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
LABEL = re.compile(r"^\s*(\d{4}) (\d)(?:\.(\d\d))?\s*(?:\(([^)]*)\))?")
ROSTER_TOP = A.ROSTER_TOP
WEEK_END_DAYS = 4          # a fantasy week is played by the Monday after its Thursday (kickoff + 7 (w - 1) + 4)

# Off switch: False prices every pick as before 2026-11-10 (exact slot from January of its draft year, else the
# round's average) — for comparisons only.
FADE_IN = True


def _week_end(season: int, week: int) -> Optional[pd.Timestamp]:
    ko = kp.KO.get(int(season))
    if ko is None:
        return None
    return pd.Timestamp(ko) + pd.Timedelta(days=7 * (int(week) - 1) + WEEK_END_DAYS)


class SlotOdds:
    """{original team: [P(slot 1..n)]} for a draft on a date, from what was knowable that day.

    value(sid, date) -> FAAB value (or None) gives roster strength; without it the pre-season / early-season odds are
    skipped (round average) and the in-season stat alone is used from week 8."""

    def __init__(self, exports: Path = EXPORTS, value: Optional[Callable] = None, tw: Optional[pd.DataFrame] = None,
                 rp: Optional[pd.DataFrame] = None, pa: Optional[pd.DataFrame] = None):
        exports = Path(exports)
        tw = tw if tw is not None else pd.read_csv(exports / "team_week.csv", low_memory=False,
                                                   usecols=["Team", "Year", "Week", "Week Name", "Win?", "PF", "Max PF"])
        tw = tw.copy()
        tw["Year"] = pd.to_numeric(tw.Year, errors="coerce"); tw["Week"] = pd.to_numeric(tw.Week, errors="coerce")
        tw = tw.dropna(subset=["Year", "Week"]); tw["Year"] = tw.Year.astype(int); tw["Week"] = tw.Week.astype(int)
        tw["win"] = tw["Win?"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        tw["PF"] = pd.to_numeric(tw.PF, errors="coerce").fillna(0.0)
        tw["Max PF"] = pd.to_numeric(tw["Max PF"], errors="coerce").fillna(0.0)
        self.teams = sorted(tw.Team.astype(str).unique())
        self.tw = tw
        self.seasons: Dict[int, dict] = {}
        for y, g in tw.groupby("Year"):
            nm = g["Week Name"].astype(str)
            reg = g[nm.str.fullmatch(r"Week \d+")]
            semi = g[nm == "Semifinal"]
            self.seasons[int(y)] = dict(
                last_reg=int(reg.Week.max()) if len(reg) else None,
                semi=int(semi.Week.iloc[0]) if len(semi) else None,
                final=int(g.loc[nm == "Final", "Week"].max()) if (nm == "Final").any() else None,
                reg=reg)
        rp = rp if rp is not None else pd.read_csv(exports / "rookie_picks.csv", usecols=["Year", "Number", "Original Team",
                                                                                          "Player Picked ID"], dtype={"Player Picked ID": str})
        self.orig = {(str(y)[:4], str(n).strip()): str(t) for y, n, t in zip(rp.Year, rp.Number, rp["Original Team"])
                     if isinstance(t, str) and t}
        self.orig_pid = ({(str(y)[:4], str(i).replace(".0", "")): str(t) for y, i, t in zip(rp.Year, rp["Player Picked ID"], rp["Original Team"])
                          if isinstance(t, str) and t and pd.notna(i)} if "Player Picked ID" in rp else {})
        self.value = value
        self.tenures: Dict[str, List[Tuple[pd.Timestamp, pd.Timestamp, str]]] = {}
        if pa is None and value is not None and (exports / "player_additions.csv").exists():
            pa = pd.read_csv(exports / "player_additions.csv", usecols=["Team", "Date", "Date dropped/traded", "Player ID"],
                             dtype={"Player ID": str}).rename(columns={"Player ID": "sid"})
        if pa is not None and value is not None:
            p = pa.dropna(subset=["sid"])
            st = pd.to_datetime(p.Date.astype(str).str[:10], errors="coerce")
            en = pd.to_datetime(p["Date dropped/traded"].astype(str).str[:10], errors="coerce")
            for tm, s, e, sid in zip(p.Team.astype(str), st, en, p.sid.astype(str).str.replace(r"\.0$", "", regex=True)):
                if pd.notna(s): self.tenures.setdefault(tm, []).append((s, e, sid))
        self._cache: Dict[tuple, dict] = {}

    # ---------------------------------------------------------------- the pick
    def original_team(self, label, pid=None) -> Optional[str]:
        """the team whose finish sets the pick's slot: named in a future pick's label, else the original team of the
        slot it was drafted at (the label's number, or the player later taken with it: the build's labels read
        "2026 3.??" before the deciding season)"""
        m = LABEL.match(str(label))
        if m is None: return None
        y, rn, sl, par = m.group(1), m.group(2), m.group(3), (m.group(4) or "").strip()
        if par in self.teams: return par                       # "2027 4(plehv79)": a future pick names its team
        if sl and (y, f"{rn}.{sl}") in self.orig: return self.orig[(y, f"{rn}.{sl}")]   # "2026 3.08(M. Fields)"
        if pid is not None: return self.orig_pid.get((y, str(pid).replace(".0", "")))
        return None

    # ---------------------------------------------------------------- the season on a date
    def state(self, draft_year: int, d) -> Tuple[str, int]:
        """('set' | 'post' | 'season' | 'pre' | 'far', regular-season weeks played) for draft `draft_year` on d"""
        d = pd.Timestamp(d); det = int(draft_year) - 1
        if det > d.year: return "far", 0
        s = self.seasons.get(det)
        if s is None or s["last_reg"] is None:
            # no league weeks for its deciding season yet: next up (it starts this year) or past with no data
            return ("pre", 0) if det >= d.year else ("set", 0)
        if s["final"] is not None:
            fe = _week_end(det, s["final"])
            if fe is not None and d >= fe: return "set", s["last_reg"]
        elif det < d.year and d >= pd.Timestamp(f"{det + 1}-01-15"):
            return "set", s["last_reg"]
        k = sum(1 for w in range(1, s["last_reg"] + 1) if (_week_end(det, w) or d + pd.Timedelta(days=1)) <= d)
        if k >= s["last_reg"]: return "post", k
        return ("season", k) if k > 0 else ("pre", 0)

    def _record(self, det: int, k: int):
        g = self.seasons[det]["reg"]; g = g[g.Week <= k]
        rec = {str(t): float(x.win.sum()) + float(x.PF.sum()) / 1e5 for t, x in g.groupby("Team")}
        mpf = {str(t): float(x["Max PF"].sum()) for t, x in g.groupby("Team")}
        return rec, mpf

    def roster_strength(self, d) -> Dict[str, float]:
        d = pd.Timestamp(d); out = {}
        if self.value is None: return out
        for tm, ten in self.tenures.items():
            ids = {sid for s, e, sid in ten if s <= d and (pd.isna(e) or e > d)}
            v = sorted((float(self.value(sid, d) or 0.0) for sid in ids), reverse=True)[:ROSTER_TOP]
            out[tm] = sum(v)
        return out

    def odds(self, draft_year: int, d) -> Dict[str, List[float]]:
        """{original team: [P(slot)]}; {} when the order is set, the pick is two drafts out, or nothing is known"""
        st, k = self.state(draft_year, d)
        key = (int(draft_year), pd.Timestamp(d).normalize(), st, k)
        if key in self._cache: return self._cache[key]
        det = int(draft_year) - 1; out: Dict[str, List[float]] = {}
        try:
            from .draft_capital import order_rule
            rule = order_rule(int(draft_year))
        except Exception:      # noqa: BLE001
            rule = "placement"
        if st == "post":
            rec, mpf = self._record(det, k)
            s = self.seasons[det]; sw = None
            if s["semi"] is not None and (_week_end(det, s["semi"]) or pd.Timestamp(d) + pd.Timedelta(days=1)) <= pd.Timestamp(d):
                g = self.tw[(self.tw.Year == det) & (self.tw.Week == s["semi"]) & (self.tw["Week Name"] == "Semifinal")]
                sw = [str(t) for t, w in zip(g.Team, g.win) if w]
            out = A.post_season_slot_odds(rec, mpf, int(draft_year), rule, semifinal_winners=sw)
        elif st in ("pre", "season"):
            rs = self.roster_strength(d)
            have = len([v for v in rs.values() if v > 0]) >= 2
            rec, mpf = self._record(det, k) if st == "season" else ({}, {})
            if have:
                rs = {t: rs.get(t, 0.0) for t in (self.teams if not rec else sorted(set(self.teams) | set(rec)))}
                out = A.project_slot_odds(rs, k, rec or None, mpf or None, rule)
            elif rec and A.roster_weight(k) == 0.0:
                out = A.project_slot_odds({t: 0.0 for t in rec}, k, rec, mpf, rule)
        self._cache[key] = out
        return out

    def price(self, label, d, slot_price: Dict[str, float], round_avg: Dict[int, float], pid=None) -> Optional[float]:
        """the odds-weighted slot price of a rounds 1-4 pick on d (before any future-draft discount), or None when the
        caller should keep its own rule (order set: the exact slot; far out / nothing known: the round average)"""
        if not FADE_IN: return None
        m = LABEL.match(str(label))
        if m is None: return None
        y, rn = int(m.group(1)), int(m.group(2))
        st, _ = self.state(y, d)
        if st in ("set", "far"): return None
        t = self.original_team(label, pid)
        if t is None: return None
        p = self.odds(y, d).get(t)
        if not p: return None
        ra = round_avg.get(rn)
        each = [slot_price.get(f"{rn}.{s:02d}", ra) for s in range(1, len(p) + 1)]
        if any(x is None or (isinstance(x, float) and np.isnan(x)) for x in each): return None
        return float(sum(a * b for a, b in zip(p, each)))


def load(exports: Path = EXPORTS, value: Optional[Callable] = None, pa: Optional[pd.DataFrame] = None) -> Optional[SlotOdds]:
    """SlotOdds on the committed exports (None when they are missing: every pick keeps the round-average rule)"""
    try:
        return SlotOdds(exports, value=value, pa=pa)
    except Exception:          # noqa: BLE001 - a missing export means the old rule, never a failed build
        return None
