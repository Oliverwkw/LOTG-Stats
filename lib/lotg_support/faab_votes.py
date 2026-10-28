"""League rating-page votes: the question queue the page asks, and the votes as a capped signal for the fit.

Votes are signals about which characteristics the league weighs, NOT edits. They never move a player's value
directly: they enter `faab_value`'s fit only as one more term the GENERAL rules are scored on, beside the
trades, cuts and calls, and that term

  - grows only as answers accumulate (n_eff / (n_eff + VOTE_HALF)), and with how many teams answered
    (full weight needs 4 of the 8), so a few keen voters cannot steer it;
  - is capped at VOTE_MAX, half the weight of trades (and of cuts) — never the largest term;
  - counts each team's answer to a question once (its latest), halves an answer about the voter's own player
    (the endowment effect), quarters a non-member's, and caps any one team's share of the vote weight.

Where the board and the votes disagree, `report` names the rule terms behind the board's side: those are the
leads for a characteristic the system is missing, to be added as a general rule and refit — not a pin.

Every answer carries the board date and the value(s) it was shown, so it is judged against what was known
then (point in time). A vote on a board date the inputs have no rows for is reported and left out of the fit.

The page (docs/rate/) posts each answer to a Google Form; `.github/workflows/faab_votes.yml` pulls the form's
published response sheet into data/votes/responses.csv.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESPONSES = ROOT / "data" / "votes" / "responses.csv"
TEAMS = ["AceMatthew", "BROsenzweig", "JacobRosenzweig", "LWebs53", "Oliverwkw", "plehv79", "Shmuel256", "stevenb123"]
GUEST = "Not in the league"
FIELDS = ["timestamp", "team", "question_id", "kind", "board_date", "player_a", "player_b", "shown_a", "shown_b",
          "answer", "verdict_a", "verdict_b", "amount_a", "amount_b", "why", "own", "client_time", "page_version"]
VOTE_MAX, VOTE_HALF, FULL_TEAMS = 1.5, 100.0, 4
OWN_W, GUEST_W, TEAM_CAP = 0.5, 0.25, 0.35
PRICE_RATIO = {"lower": 0.75, "right": 1.0, "higher": 4 / 3}   # display only (the vote report's "votes $" column)
BAND = 0.15                                                   # +-15%: "about right", and the slack around a typed amount


# ------------------------------------------------------------------ question queue
def _qid(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def questions(T, stages, as_of, n_close=60, n_moved=40, n_rules=30, n_random=30, seed=0):
    """T: the board (sid, name, pos, V, rank); stages: apply_rules(explain=True) stage values, aligned with T.
    Every question is a pair of players near in value (each answer also prices both, so every pair is two price
    checks too): close calls across positions, each of the players the rules moved most against his nearest
    neighbour, pairs the rules pulled in opposite directions, and random near pairs. Deterministic for a date."""
    rng = np.random.default_rng(seed + int(pd.Timestamp(as_of).strftime("%Y%m%d")))
    T = T.reset_index(drop=True).copy()
    T["moved"] = np.log(np.maximum(stages["final"], 1) / np.maximum(stages["vet"], 1))
    top = T[T.V >= 50].head(300).reset_index(drop=True)
    lv = np.log(top.V.values); sid = top.sid.values; pos = top.pos.values; mv = top.moved.values
    out, seen = [], set()

    def add_pair(i, j, why):
        a, b = (i, j) if rng.random() < 0.5 else (j, i)
        k = tuple(sorted((sid[a], sid[b])))
        if k in seen or a == b: return False
        seen.add(k)
        out.append(dict(id=_qid("pair", *k, as_of), kind="pair", why=why, a=str(sid[a]), b=str(sid[b])))
        return True

    near = [(i, j) for i in range(len(top)) for j in range(i + 1, min(i + 9, len(top))) if lv[i] - lv[j] < 0.15]
    cross = [p for p in near if pos[p[0]] != pos[p[1]]]
    for idx in rng.permutation(len(cross))[:n_close]: add_pair(*cross[idx], "close")
    for i in np.argsort(-np.abs(mv))[:n_moved]:
        for j in np.argsort(np.abs(lv - lv[i]))[1:6]:
            if add_pair(i, j, "moved"): break
    wide = [(i, j) for i in range(len(top)) for j in range(i + 1, len(top)) if lv[i] - lv[j] < 0.2]
    for i, j in sorted(wide, key=lambda p: -abs(mv[p[0]] - mv[p[1]]))[:n_rules * 3][::3]: add_pair(i, j, "rules")
    pool = [(i, j) for i in range(len(top)) for j in range(i + 1, len(top)) if lv[i] - lv[j] < 0.4]
    for idx in rng.permutation(len(pool))[:n_random]: add_pair(*pool[idx], "random")
    order = rng.permutation(len(out))
    return [out[i] for i in order]


# ------------------------------------------------------------------ responses
def _norm_header(h):
    return h.strip().lower().replace(" ", "_")


def read_responses(text_or_path=RESPONSES):
    """the responses sheet as a frame with FIELDS (header names are matched loosely; unknown columns dropped)"""
    is_path = isinstance(text_or_path, Path) or (str(text_or_path).endswith(".csv") and "\n" not in str(text_or_path))
    text = Path(text_or_path).read_text() if is_path and Path(text_or_path).is_file() else ("" if is_path else str(text_or_path))
    rows = list(csv.reader(io.StringIO(text)))
    if not rows: return pd.DataFrame(columns=FIELDS)
    head = [_norm_header(h) for h in rows[0]]
    df = pd.DataFrame(rows[1:], columns=head) if len(rows) > 1 else pd.DataFrame(columns=head)
    for f in FIELDS:
        if f not in df: df[f] = ""
    df = df[FIELDS].astype(str).apply(lambda s: s.str.strip())
    return df[df.question_id != ""].reset_index(drop=True)


def normalise(text):
    """the published sheet -> data/votes/responses.csv text (FIELDS order, rows sorted, stable)"""
    df = read_responses(text)
    df = df.sort_values(["timestamp", "team", "question_id"], kind="stable")
    buf = io.StringIO(); df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def signals(df):
    """one submission -> up to three signals: which player is higher (question_id, kind pair) and a price check
    for each player that got a verdict or an amount (question_id:a / :b, kind price, as player_a)"""
    rows = []
    for r in df.to_dict("records"):
        own = (r.get("own") or "").upper()
        if r.get("answer"):
            rows.append(dict(r, kind="pair", amount=""))
        for x in ("a", "b"):
            v, amt = (r.get(f"verdict_{x}") or "").lower(), r.get(f"amount_{x}") or ""
            if v or amt:
                rows.append(dict(r, question_id=f"{r['question_id']}:{x}", kind="price", player_a=r[f"player_{x}"], player_b="",
                                 shown_a=r[f"shown_{x}"], answer=v, amount=amt, own=x.upper() if x.upper() in own else ""))
    cols = list(df.columns) + ["amount"]
    return pd.DataFrame(rows, columns=cols).fillna({"amount": ""}) if rows else df.iloc[:0].assign(amount=[])


def weighted(df):
    """one row per (team, question): the latest answer, with its weight after own-player / guest / team-cap rules"""
    if df.empty: return df.assign(w=[])
    df = df[df.team.isin(TEAMS + [GUEST])].copy()
    df["t"] = pd.to_datetime(df.timestamp, errors="coerce").fillna(pd.to_datetime(df.client_time, errors="coerce", utc=True).dt.tz_localize(None))
    df = df.sort_values("t", kind="stable").drop_duplicates(["team", "question_id"], keep="last")
    own = df.own.str.upper()
    df["w"] = np.where(df.team == GUEST, GUEST_W, 1.0) * np.where(own.isin(["A", "B", "AB"]), OWN_W, 1.0)
    members = df[df.team != GUEST]
    n_teams = members.team.nunique()
    cap = max(TEAM_CAP, 1.0 / max(n_teams, 1))
    for _ in range(60):                          # scale any team above cap x total down until none is (converges by cap^k)
        tot = df.w.sum(); by = df.groupby("team").w.transform("sum")
        f = np.minimum(1.0, cap * tot / by)
        if f.min() > 1 - 1e-6: break
        df["w"] = df.w * f
    return df.reset_index(drop=True)


def strength(df):
    """the vote term's weight in the fit: grows with answers and with how many league teams answered, capped"""
    if df.empty: return 0.0
    n_eff = float(df.w.sum()); n_teams = df[df.team != GUEST].team.nunique()
    return VOTE_MAX * min(1.0, n_teams / FULL_TEAMS) * n_eff / (n_eff + VOTE_HALF)


def consensus(df):
    """per question: the weighted answer. pair -> s in [-1, 1] (A minus B) and the 'even' share;
    price -> the weighted median ratio to the value shown"""
    out = []
    for q, g in df.groupby("question_id", sort=False):
        w = g.w.values; r = g.iloc[-1]
        if r.kind == "pair":
            a = g.answer.str.upper().values
            s = float(np.sum(w * ((a == "A") * 1.0 - (a == "B") * 1.0)) / w.sum())
            out.append(dict(question_id=q, kind="pair", board_date=r.board_date, a=r.player_a, b=r.player_b, n=len(g), w=float(w.sum()),
                            s=s, even=float(np.sum(w * (a == "EVEN")) / w.sum())))
        elif r.kind == "price":
            shown = pd.to_numeric(g.shown_a, errors="coerce").values
            amt = pd.to_numeric(g.amount.str.replace(r"[$,]", "", regex=True), errors="coerce").values
            ratio = np.where((amt > 0) & (shown > 0), amt / np.where(shown > 0, shown, 1), g.answer.str.lower().map(PRICE_RATIO).values.astype(float))
            ok = ~np.isnan(ratio)
            if not ok.any(): continue
            lr, ww = np.log(ratio[ok]), w[ok]; o = np.argsort(lr); c = np.cumsum(ww[o])
            med = float(lr[o][np.searchsorted(c, c[-1] / 2)])
            # each answer is a range on the value's ratio to the one shown: an amount is a point (+-15%); "too low" /
            # "too high" only say the shown value is not right in that direction (any amount above / below, no cap, no minimum)
            verd = g.answer.str.lower().values; iv = []
            for i in np.flatnonzero(ok):
                if amt[i] > 0 and shown[i] > 0: c_ = np.log(amt[i] / shown[i]); lo, hi = c_ - BAND, c_ + BAND
                elif verd[i] == "higher": lo, hi = 0.0, np.inf
                elif verd[i] == "lower": lo, hi = -np.inf, 0.0
                else: lo, hi = -BAND, BAND
                iv.append((float(np.log(shown[i])) if shown[i] > 0 else 0.0, lo, hi, float(w[i])))
            out.append(dict(question_id=q, kind="price", board_date=r.board_date, a=r.player_a, b="", n=int(ok.sum()), w=float(ww.sum()),
                            target=float(np.nanmedian(shown[ok]) * np.exp(med)), ratio=float(np.exp(med)), iv=iv,
                            said="; ".join(f"{k} {v}" for k, v in (("too low", int(((verd == "higher") & ~(amt > 0))[ok].sum())), ("about right", int(((verd == "right") & ~(amt > 0))[ok].sum())),
                                                                     ("too high", int(((verd == "lower") & ~(amt > 0))[ok].sum()))) if v)
                                 + "".join(f"; typed ${a:,.0f}" for a in amt[ok & (amt > 0)])))
    return pd.DataFrame(out)


def _look(V, c):
    """V: a Series by sid (one board), or a dict keyed (board date, sid) holding each vote's own board"""
    if isinstance(V, pd.Series): return lambda s_: float(V.get(s_, np.nan))
    return lambda s_: float(V.get((c["board_date"], s_), np.nan))


def q_loss(c, V):
    """hinge loss of one question's consensus against the board it was asked on; NaN if a player is missing"""
    g = _look(V, c); va = g(c["a"])
    if c["kind"] == "pair":
        vb = g(c["b"])
        if np.isnan(va) or np.isnan(vb): return np.nan
        r = np.log(max(va, 1) / max(vb, 1))
        if c["even"] >= 0.5: return max(0.0, abs(r) - 0.25)
        return abs(c["s"]) * max(0.0, 0.05 - np.sign(c["s"]) * r)
    if np.isnan(va): return np.nan
    iv = c.get("iv")
    if not isinstance(iv, list) or not iv:
        return max(0.0, abs(np.log(max(va, 1) / max(c["target"], 1))) - BAND)
    lv = np.log(max(va, 1)); W = sum(x[3] for x in iv)
    return float(sum(wi * max(0.0, (ls + lo) - lv, lv - (ls + hi)) for ls, lo, hi, wi in iv) / max(W, 1e-9))


class VoteTerm:
    """the votes, each judged against the board on the date it was shown, ready for the fit: loss(V) is the
    weighted mean hinge, times strength. `dates`: the board dates the inputs hold rows for (the as-of date
    always); votes on other dates are reported as not used."""

    def __init__(self, df, as_of, dates=()):
        self.raw = df
        self.all = weighted(signals(df))
        self.as_of = str(pd.Timestamp(as_of).date())
        self.dates = {self.as_of} | {str(pd.Timestamp(d).date()) for d in dates}
        self.used = self.all[self.all.board_date.isin(self.dates)] if len(self.all) else self.all
        self.C = consensus(self.used) if len(self.used) else pd.DataFrame()
        self.weight = strength(self.used)
        self.stale = sorted(set(self.all.board_date) - self.dates) if len(self.all) else []

    def loss(self, V):
        if self.C.empty or self.weight <= 0: return 0.0
        l = np.array([q_loss(c, V) for c in self.C.to_dict("records")]); qw = self.C.w.values / (self.C.w.values + 1.0)
        ok = ~np.isnan(l)
        return float(self.weight * np.sum(qw[ok] * l[ok]) / max(np.sum(qw[ok]), 1e-9)) if ok.any() else 0.0


def report(term, V, names, terms=None):
    """where the boards disagree with the votes, and which rule terms put each side where it is (markdown lines).
    V: dict (board date, sid) -> value; names: sid -> name; terms: dict (board date, sid) -> {rule: log multiplier}."""
    terms = terms or {}
    L = [f"# Rating-page votes vs the board (inputs as of {term.as_of})", "",
         f"{len(term.raw)} answers ({len(term.all)} signals: picks and price checks) from {term.all.team.nunique() if len(term.all) else 0} teams; "
         f"{len(term.used)} signals on board dates the inputs hold, "
         f"vote term weight {term.weight:.2f} of max {VOTE_MAX} (trades and cuts weigh {3.0} each).", ""]
    if term.stale: L += [f"Not used (no inputs for that board date): {', '.join(term.stale)}", ""]
    if term.C.empty: return L + ["No votes on the board dates the inputs hold."]

    def why(bd, s, k=4):
        t = sorted(((n, v) for n, v in terms.get((bd, s), {}).items() if abs(v) > 0.02), key=lambda x: -abs(x[1]))[:k]
        return ", ".join(f"{n} x{np.exp(v):.2f}" for n, v in t) or "no rule moved him"

    rows = []
    for c in term.C.to_dict("records"):
        l = q_loss(c, V)
        if np.isnan(l): continue
        bd = c["board_date"]; g = _look(V, c)
        if c["kind"] == "pair":
            say = ("even" if c["even"] >= 0.5 else (names.get(c["a"]) if c["s"] > 0 else names.get(c["b"])))
            rows.append((l, f"- {bd}: **{names.get(c['a'])}** ${g(c['a']):,.0f} vs **{names.get(c['b'])}** ${g(c['b']):,.0f}: votes say {say} "
                            f"(s {c['s']:+.2f}, {c['n']} answers){' — DISAGREES' if l > 0 else ''}"
                            + (f"\n  - {names.get(c['a'])}: {why(bd, c['a'])}\n  - {names.get(c['b'])}: {why(bd, c['b'])}" if l > 0 else "")))
        else:
            said = c.get("said") or f"${c['target']:,.0f}"
            rows.append((l, f"- {bd}: **{names.get(c['a'])}** board ${g(c['a']):,.0f}, votes: {said} ({c['n']} answers)"
                            f"{' — DISAGREES' if l > 0 else ''}" + (f"\n  - {why(bd, c['a'])}" if l > 0 else "")))
    rows.sort(key=lambda r: -r[0])
    n_bad = sum(r[0] > 0 for r in rows)
    ok_team = term.raw.team.isin(TEAMS + [GUEST]) if len(term.raw) else []
    notes = [f"- {r.board_date}: {names.get(r.player_a, r.player_a)} vs {names.get(r.player_b, r.player_b)} — {r.team}: {r.why}"
             for r in term.raw[ok_team & (term.raw.why.str.len() > 0)].itertuples()] if len(term.raw) else []
    return (L + [f"{len(rows) - n_bad} of {len(rows)} checks agree with the board.", ""] + [r[1] for r in rows]
            + (["", "## Why notes", ""] + notes if notes else []))


def vote_keys(df):
    """(board date, sid) of every player a vote was about"""
    if df.empty: return set()
    return {(r.board_date, s) for r in df.itertuples() for s in (r.player_a, r.player_b) if s}


def page_board(T, owners, as_of, info, picks=None):
    """docs/rate/board.json: what the page shows (picks: slot -> league price, for the draft-pick comparison)"""
    pl = [dict(sid=str(r.sid), name=r["name"], pos=r.pos, age=None if pd.isna(r.age) else round(float(r.age), 1),
               team=info.get(str(r.sid), {}).get("team") or "", injury=r.injury or "", owner=owners.get(str(r.sid), ""),
               value=int(round(r.V)), rank=int(r["rank"])) for _, r in T.iterrows()]
    return dict(as_of=str(pd.Timestamp(as_of).date()), teams=TEAMS, guest=GUEST, players=pl,
                picks=[dict(slot=k, value=int(round(v))) for k, v in (picks or {}).items()])


def slot_values(exports, as_of, rounds=4):
    """rookie-draft slot -> the league's median price for it, over drafts held before as_of (exports/rookie_picks
    joined to the Draft rows of exports/player_additions); made non-increasing down the draft so a later slot
    never reads dearer than an earlier one"""
    exports = Path(exports)
    rp = pd.read_csv(exports / "rookie_picks.csv", usecols=["Year", "Number", "Player Picked"], dtype=str)
    pa = pd.read_csv(exports / "player_additions.csv", usecols=["Player", "Season", "Addition type", "Price paid (FAAB)", "Date"], dtype=str)
    rp = rp[rp.Number.str.fullmatch(r"\d\.\d\d", na=False)]
    m = rp.merge(pa[pa["Addition type"] == "Draft"], left_on=["Player Picked", "Year"], right_on=["Player", "Season"])
    held = m.groupby("Year").Date.transform("min").str[:10]
    m = m[held < str(pd.Timestamp(as_of).date())]
    v = pd.to_numeric(m["Price paid (FAAB)"], errors="coerce")
    med = v.groupby(m.Number).median().dropna()
    med = med[med.index.str[0].astype(int) <= rounds].sort_index()
    return med.cummin().to_dict()


def owners_from_snapshot(season_dir):
    """sid -> owning team's display name, from a committed Sleeper snapshot season folder"""
    season_dir = Path(season_dir)
    users = {u["user_id"]: u["display_name"] for u in json.load(open(season_dir / "users.json"))}
    out = {}
    for r in json.load(open(season_dir / "rosters.json")):
        for s in (r.get("players") or []): out[str(s)] = users.get(r.get("owner_id"), "")
    return out
