// LOTG league site. Everything is precomputed JSON under data/ (built by
// scripts/build_site.py); this file only fetches and renders. Hash routes:
// #/  #/teams  #/team/<slug>  #/player/<key>  #/records[/<sheet>][?full=<col>]  #/h2h
// #/trades[/<id>]  #/draft  #/search/<q>  #/faab  #/data[/<sheet>]  #/game/<y>/<w>/<team>
// #/week/<y>/<w>  #/pick/<sheet>/<row>  #/nfl/<code>
"use strict";

const $app = document.getElementById("app");
const cache = {};
// every data file is asked for with this build's stamp (index.html sets it), so a
// browser's cached copy from an earlier build is never mixed with this code
const BUILD = window.SITE_BUILD || "";
const withBuild = (u) => BUILD ? u + (u.includes("?") ? "&" : "?") + "b=" + BUILD : u;
const load = (p) => cache[p] || (cache[p] = fetch(withBuild("data/" + p)).then((r) => {
  if (!r.ok) throw new Error(p + " " + r.status);
  return r.json();
}));

// ---------- formatting (workbook decimals: number_format.col_number_format)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function fmt(spec, v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "number") return esc(v);
  spec = spec || {};
  let x = spec.p === "x" ? v * 100 : v;
  let s;
  if (spec.d === undefined) s = String(+x.toFixed(2));
  else s = x.toLocaleString("en-US", { minimumFractionDigits: spec.d, maximumFractionDigits: spec.d });
  if (/^-[0.,]*$/.test(s)) s = s.slice(1);
  return s + (spec.p ? "%" : "");
}
const pct1 = (v) => (v === null || v === undefined ? "—" : v < 0.05 && v > 0 ? "<0.1%" : v.toFixed(1) + "%");
// Clinched / eliminated, conservatively (a PF tiebreak counts as still open):
// clinched = fewer than `spots` other teams can still reach its win total;
// eliminated = `spots` teams already have more wins than it can still reach.
function clinchStatus(wins, left, spots) {
  const ts = Object.keys(wins), sure = new Set(), out = new Set();
  for (const t of ts) {
    const threats = ts.filter((u) => u !== t && wins[u] + (left[u] || 0) >= wins[t]).length;
    if (threats < spots) sure.add(t);
    const ahead = ts.filter((u) => u !== t && wins[u] > wins[t] + (left[t] || 0)).length;
    if (ahead >= spots) out.add(t);
  }
  return { sure, out };
}
// odds as shown: 100% only when clinched, 0% only when eliminated; otherwise at
// most 99.9% and at least <0.1%. p is 0-1; whole percents unless `tenth`.
function oddsText(p, sure, out, tenth) {
  if (p === null || p === undefined) return "—";
  if (sure) return "100%";
  if (out) return "0%";
  const x = p * 100;
  if (x >= 99.95 || (!tenth && x >= 99.5)) return "99.9%";
  if (x < 0.05 || (!tenth && x < 0.5 && x === 0)) return "<0.1%";
  if (!tenth && x < 0.5) return "<1%";
  return tenth ? x.toFixed(1) + "%" : Math.round(x) + "%";
}
const signed = (spec, v) => (typeof v === "number" && v > 0 ? "+" : "") + fmt(spec, v);
const tslug = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const teamLink = (t) => t ? `<a href="#/team/${tslug(t)}">${esc(t)}</a>` : "—";
let NAMES = {}, NAMES_BY_ID = {};   // player name -> page key, from search.json
const playerLink = (n) => NAMES[n] ? `<a href="#/player/${NAMES[n]}">${esc(n)}</a>` : esc(n);
const assetLink = (a) => assetHtml(a);
// picks as links: a drafted one opens its pick page, a future one its owner's picks
let PICKROWS = null;   // "2025 1.05" -> ["rookie_picks", row]
const loadPickRows = () => PICKROWS ? Promise.resolve(PICKROWS) : load("draft.json").then((d) => {
  PICKROWS = {};
  for (const [key, sheet] of [["rookie", "rookie_picks"], ["startup", "non_rookie_picks"]]) {
    const t = d[key]; if (!t) continue;
    const yi = t.cols.indexOf("Year"), ni = t.cols.indexOf("Number"), ri = t.cols.indexOf("_row");
    for (const r of t.rows) { const y = String(r[yi]).match(/\d{4}/); if (y) PICKROWS[`${y[0]} ${r[ni]}`] = PICKROWS[`${y[0]} ${r[ni]}`] || [sheet, r[ri]]; }
  }
  return PICKROWS;
});
function assetHtml(a) {
  if (NAMES[a]) return playerLink(a);
  const m = /^(\d{4}) (\d+\.\d+)(?:\((.+)\))?$/.exec(a);
  if (m && PICKROWS && PICKROWS[`${m[1]} ${m[2]}`]) { const [sh, row] = PICKROWS[`${m[1]} ${m[2]}`]; return `<a href="#/pick/${sh}/${row}">${esc(a)}</a>`; }
  const f = /^(\d{4}) (\d)\((.+)\)$/.exec(a);
  if (f) return `<a href="#/team/${tslug(f[3])}" title="${esc(f[3])}'s ${esc(f[1])} round ${esc(f[2])} pick, not drafted yet">${esc(a)}</a>`;
  return esc(a);
}
const nflLink = (t) => t && t !== "NFL" && t !== "FA" ? `<a href="#/nfl/${esc(t)}">${esc(t)}</a>` : esc(t || "");

// ---------- definitions: tap or hover a stat's name for its formula (formulas.csv),
// on every table header, tile and record board. DEFS[sheet][column] = text.
let DEFS = {};
const defOf = (col, sheet) => (sheet && DEFS[sheet] && DEFS[sheet][col]) || DEFS._any?.[col] || "";
const defAttr = (col, sheet) => { const d = defOf(col, sheet); return d ? ` data-def="${esc(d)}" class="hasdef"` : ""; };
function showDef(el) {
  let pop = document.getElementById("defpop");
  if (!pop) { pop = document.createElement("div"); pop.id = "defpop"; pop.className = "defpop"; document.body.appendChild(pop); }
  pop.innerHTML = `<b>${esc(el.dataset.deflabel || el.textContent.replace(/[▾▴ⓘ]/g, "").trim())}</b><br>${esc(el.dataset.def)}`;
  const r = el.getBoundingClientRect();
  pop.style.display = "block";
  const w = Math.min(320, window.innerWidth - 24);
  pop.style.width = w + "px";
  pop.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left)) + "px";
  pop.style.top = (window.scrollY + r.bottom + 6) + "px";
}
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-def]");
  const pop = document.getElementById("defpop");
  if (el && e.target.closest(".defbtn")) { e.preventDefault(); e.stopPropagation(); showDef(el); return; }
  if (pop && !e.target.closest("#defpop")) pop.style.display = "none";
}, true);
document.addEventListener("mouseover", (e) => { const el = e.target.closest("[data-def]"); if (el && matchMedia("(hover: hover)").matches) showDef(el); });
document.addEventListener("mouseout", (e) => { const el = e.target.closest("[data-def]"); const pop = document.getElementById("defpop"); if (el && pop && matchMedia("(hover: hover)").matches) pop.style.display = "none"; });
const defMark = (col, sheet) => defOf(col, sheet) ? ' <span class="defbtn" title="What is this?">ⓘ</span>' : "";

// ---------- sortable table
let tableSeq = 0;
function table(cols, rows, opts = {}) {
  // cols: [{k: index or fn, label, spec, left, html(row) }]
  const id = "t" + (++tableSeq);
  const state = { by: opts.sort ?? null, asc: !!opts.asc };
  const val = (c, r) => (typeof c.k === "function" ? c.k(r) : r[c.k]);
  function render() {
    let rs = rows.slice();
    if (state.by !== null) {
      const c = cols[state.by];
      rs.sort((a, b) => {
        const x = val(c, a), y = val(c, b);
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
        return state.asc ? r : -r;
      });
    }
    const head = cols.map((c, i) => { const d = c.col ? defOf(c.col, opts.defs) : ""; return `<th data-i="${i}" class="${c.left ? "l" : ""}${state.by === i ? " sorted" + (state.asc ? " asc" : "") : ""}${i < (opts.pin || 1) ? " pin pin" + i : ""}"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(c.label)}"` : ""}>${esc(c.label)}${d ? ' <span class="defbtn">ⓘ</span>' : ""}</th>`; }).join("");
    const body = rs.map((r) => "<tr" + (opts.rowClass ? ` class="${opts.rowClass(r)}"` : "") + (opts.rowLink ? ` data-go="${esc(opts.rowLink(r) || "")}"` : "") + ">" + cols.map((c, i) =>
      `<td class="${c.left ? "l" : ""}${i < (opts.pin || 1) ? " pin pin" + i : ""}">${c.html ? c.html(r) : fmt(c.spec, val(c, r))}</td>`).join("") + "</tr>").join("");
    const el = document.getElementById(id);
    if (el) { el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`; pinColumns(el); }
  }
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("click", (e) => {
      if (e.target.closest(".defbtn")) return;
      const th = e.target.closest("th");
      if (!th) return;
      const i = +th.dataset.i;
      if (state.by === i) state.asc = !state.asc; else { state.by = i; state.asc = !!cols[i].left; }
      render();
    });
    render();
  });
  return `<div class="scroll" id="${id}"></div>`;
}
// keep the first N columns in view while a wide table scrolls sideways: each pinned
// column sticks at the summed width of the pinned columns before it
function pinColumns(el) {
  // a phone keeps at most two pinned columns, so the rest of the table has room to scroll
  const narrow = window.innerWidth < 600;
  if (narrow) for (let i = 2; i < 8; i++) el.querySelectorAll(".pin" + i).forEach((c) => c.classList.remove("pin", "pin" + i));
  el.classList.toggle("narrowpin", narrow);
  const ths = [...el.querySelectorAll("thead th.pin")];
  let left = 0;
  ths.forEach((th, i) => {
    el.querySelectorAll(".pin" + i).forEach((c) => { c.style.left = left + "px"; });
    left += th.offsetWidth;
  });
  if (ths.length) el.querySelectorAll(".pin" + (ths.length - 1)).forEach((c) => c.classList.add("pinlast"));
}
// a {cols, labels, fmt, rows} table from the generator
function dataTable(t, opts = {}) {
  if (!t || !t.rows || !t.rows.length) return `<p class="muted small">None.</p>`;
  const hide = new Set(opts.hide || []);
  const cols = [];
  t.cols.forEach((c, i) => {
    if (hide.has(c)) return;
    const col = { k: i, label: t.labels[i], spec: t.fmt[c], col: c };
    if (opts.links && opts.links[c]) col.html = (r) => opts.links[c](r[i], r, t.cols);
    if (typeof t.rows[0][i] === "string" || opts.left?.includes(c)) col.left = true;
    cols.push(col);
  });
  return table(cols, t.rows, opts);
}
const idx = (t, c) => t.cols.indexOf(c);

// ---------- pages
const routes = {
  "": home, teams, team, player, records, h2h, trades, draft, search, faab, data, game, week, pick, nfl, predict,
};

// ---------- live layer: rosters and traded picks straight from Sleeper on open.
// Stats come from the last main build (the site redeploys after each one); rosters
// and pick ownership come from Sleeper as of this page view, so a trade made since
// the build already shows. Three small requests (~40 KB, ~0.2 s); on any failure or
// after 4 s the page keeps the build's rosters and says so.
let liveP = null, nflP = null, liveStatus = "pending";
const loadNfl = () => nflP || (nflP = load("nfl_players.json").catch(() => ({})));
function loadLive() {
  if (liveP) return liveP;
  liveP = (async () => {
    const meta = await load("meta.json");
    if (!meta.league_id) return null;
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 4000);
    try {
      const base = `https://api.sleeper.app/v1/league/${meta.league_id}/`;
      const [rosters, users, traded] = await Promise.all(["rosters", "users", "traded_picks"].map((p) =>
        fetch(base + p, { signal: ctl.signal, cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(p); return r.json(); })));
      const uname = Object.fromEntries(users.map((u) => [u.user_id, u.display_name]));
      const canon = (n) => meta.teams.find((t) => t.toLowerCase() === String(n || "").toLowerCase()) || n;
      const byRid = {}, rosterOf = {}, owner = {};
      for (const r of rosters) {
        const t = canon(uname[r.owner_id]);
        byRid[r.roster_id] = t;
        rosterOf[t] = { players: r.players || [], starters: new Set(r.starters || []), taxi: new Set(r.taxi || []), ir: new Set(r.reserve || []) };
        for (const p of r.players || []) owner[p] = t;
      }
      const picks = traded.map((p) => [+p.season, +p.round, byRid[p.roster_id], byRid[p.owner_id]]);
      liveStatus = "ok";
      return { at: new Date(), rosterOf, owner, picks, byRid };
    } catch (e) {
      liveStatus = "failed";
      return null;
    } finally { clearTimeout(timer); }
  })();
  return liveP;
}
// future picks held, with every pick Sleeper shows moved SINCE the build applied
function livePicks(PK, live) {
  const own = {};
  for (const [t, ps] of Object.entries(PK.held)) for (const [y, r, o] of ps) own[`${y}|${r}|${o}`] = t;
  if (live) {
    const atBuild = {}, now = {};
    for (const [y, r, o, t] of PK.sleeper_at_build || []) atBuild[`${y}|${r}|${o}`] = t;
    for (const [y, r, o, t] of live.picks) if (PK.years.includes(y)) now[`${y}|${r}|${o}`] = t;
    for (const k of new Set([...Object.keys(atBuild), ...Object.keys(now)])) {
      const orig = k.split("|")[2], then = atBuild[k] || orig, cur = now[k] || orig;
      if (cur !== then && k in own) own[k] = cur;
    }
  }
  const held = {};
  for (const [k, t] of Object.entries(own)) { const [y, r, o] = k.split("|"); (held[t] = held[t] || []).push([+y, +r, o]); }
  return held;
}
const liveNote = (live) => live ? `<span class="chip live">live from Sleeper ${live.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>` : (liveStatus === "failed" ? '<span class="chip">Sleeper unreachable: as of the last build</span>' : '<span class="chip">as of the last build</span>');

// ---------- FAAB board (docs/rate/board.json, published with the rating page)
let boardP = null;
const loadBoard = () => boardP || (boardP = fetch(withBuild("rate/board.json")).then((r) => (r.ok ? r.json() : null)).catch(() => null));
const money = (v) => (typeof v === "number" ? "$" + Math.round(v).toLocaleString("en-US") : "—");
function ownerTeam(o, teams) {
  if (!o) return null;
  return teams.find((t) => t.toLowerCase() === String(o).toLowerCase()) || o;
}
// a future rookie pick on the board's scale — the FAAB system's own rule
// (lotg_support.faab_pick_schedule): its round's average slot price on the board's
// date, from the fixed weekly pick schedule (board.json future_picks); 5th round+ = $20.
// An older board without future_picks falls back to 5% off a year per draft.
// A held pick's value: the generator's per-pick price (picks.json values), which is the
// FAAB system's own rule (faab_history.FaabIndex.pick): the next draft's picks by the
// ORIGINAL team's projected slot odds, so a likely 1.01 is worth more than a likely
// 1.08; later drafts at the round average. Without it, the round rule below.
function pickValue(PK, B, year, round, orig) {
  const v = PK && PK.values && PK.values[`${year}|${round}|${orig}`];
  return typeof v === "number" ? v : (B ? futurePickValue(B, year, round) : null);
}
function futurePickValue(B, year, round) {
  if (round >= 5) return 20;
  const fp = B.future_picks && B.future_picks[String(year)];
  if (fp && typeof fp[String(round)] === "number") return fp[String(round)];
  const slots = (B.picks || []).filter((p) => +p.slot.split(".")[0] === round);
  if (!slots.length) return 0;
  const avg = slots.reduce((a, p) => a + p.value, 0) / slots.length;
  const d = new Date(B.as_of + "T12:00:00");
  const next = d.getMonth() + 1 <= 8 ? d.getFullYear() : d.getFullYear() + 1;
  return avg * Math.pow(0.95, Math.max(0, year - next));
}
const ORD = { 1: "1st", 2: "2nd", 3: "3rd", 4: "4th" };
// a year's picks as numbered squares: outlined = own pick, filled = acquired
function pickDots(picks, team) {
  if (!picks.length) return '<span class="muted">—</span>';
  return `<span class="dots">${picks.slice().sort((a, b) => a.r - b.r).map((p) => `<span class="dot${p.o === team ? "" : " acq"}" title="${esc(ORD[p.r] || p.r)} round${p.o === team ? "" : ", from " + esc(p.o)}${p.v != null ? " · " + money(p.v) : ""}">${p.r}</span>`).join("")}</span>`;
}
// the nearest rookie-pick comparison, as the rating page words it
function pickText(B, v) {
  const S = (B.picks || []).filter((p) => p.value > 0);
  if (!S.length || typeof v !== "number") return "";
  const low = S[S.length - 1];
  if (v < low.value * 0.75) return "less than a " + low.slot.split(".")[0] + "th-round rookie pick";
  const R = S.filter((p) => +p.slot.split(".")[0] <= 2);
  let best = null, bestE = 1e9;
  const consider = (set) => {
    const sum = set.reduce((a, p) => a + p.value, 0), e = Math.abs(Math.log(sum / v)) + 0.06 * (set.length - 1);
    if (e < bestE) { bestE = e; best = set; }
  };
  for (const p of S) consider([p]);
  for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++) {
    consider([R[i], R[j]]);
    for (let k = j + 1; k < R.length; k++) consider([R[i], R[j], R[k]]);
  }
  return "about the " + best.map((p) => p.slot).join(" + ") + " rookie pick" + (best.length > 1 ? "s" : "");
}

async function home() {
  const [meta, h, B, LWh] = await Promise.all([load("meta.json"), load("home.json"), loadBoard(), load("live_watch.json").catch(() => ({}))]);
  // who has clinched / is out, from the standings and the regular-season games left
  const regW = (LWh.playoff || {}).regular_weeks || 14, spots = (LWh.playoff || {}).teams || 4;
  const wins = Object.fromEntries(h.standings.map((r) => [r.team, r.w]));
  const leftG = Object.fromEntries(h.standings.map((r) => [r.team, Math.max(0, regW - r.w - r.l)]));
  const CL = clinchStatus(wins, leftG, spots);
  const oddsCell = (t, v, cap) => oddsText(v == null ? null : v / 100, !cap && CL.sure.has(t), CL.out.has(t), true);
  const odds = {};
  (h.forecast?.odds || []).forEach((o) => (odds[o.team] = o));
  const hasOdds = h.forecast && h.forecast.odds;
  const cols = [
    { k: "rank", label: "#" },
    { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
    { k: (r) => r.w - r.l, label: "W-L", html: (r) => `${r.w}-${r.l}` },
    { k: "pf", label: "PF", spec: { d: 2 } },
    { k: "pa", label: "PA", spec: { d: 2 } },
    { k: "max_pf", label: "Max PF", spec: { d: 2 } },
    { k: (r) => +r.ap.split("-")[0], label: "All-play", html: (r) => r.ap },
    { k: "form", label: "Last 5", left: true, html: (r) => r.form.split("").map((c) => `<span class="${c === "W" ? "w" : "lo"}">${c}</span>`).join("") },
  ];
  if (hasOdds) cols.push(
    { k: (r) => odds[r.team]?.playoffs, label: "Playoffs", html: (r) => oddsCell(r.team, odds[r.team]?.playoffs) },
    { k: (r) => odds[r.team]?.finals, label: "Final", html: (r) => oddsCell(r.team, odds[r.team]?.finals, true) },
    { k: (r) => odds[r.team]?.champion, label: "Title", html: (r) => `<b>${oddsCell(r.team, odds[r.team]?.champion, true)}</b>` },
    { k: (r) => odds[r.team]?.wins, label: "Proj. wins", html: (r) => fmt({ d: 2 }, odds[r.team]?.wins) },
  );
  const games = h.results.map((g) => `<div class="game" onclick="location.hash='#/game/${meta.season}/${meta.week}/${tslug(g.a)}'" style="cursor:pointer" title="Open the matchup">
      <div><span class="${g.win ? "w" : ""}">${teamLink(g.a)}</span><span>${fmt({ d: 2 }, g.pa)}</span></div>
      <div><span class="${g.win ? "" : "w"}">${teamLink(g.b)}</span><span>${fmt({ d: 2 }, g.pb)}</span></div></div>`).join("");
  const d = h.digest || { sections: [] };
  const groups = [];
  d.sections.forEach((s) => {
    let g = groups.find((x) => x.name === s.group);
    if (!g) groups.push((g = { name: s.group, edits: s.edits, secs: [] }));
    g.secs.push(s);
  });
  const item = (t) => {
    const parts = t.split(" · ");
    return parts.length > 1 ? `<li>${esc(parts[0])}<ul>${parts.slice(1).map((p) => `<li>${esc(p)}</li>`).join("")}</ul></li>` : `<li>${esc(t)}</li>`;
  };
  const digestHtml = groups.map((g, gi) => `<details ${gi < 2 && !g.edits ? "open" : ""}><summary>${esc(g.name)}</summary>
      ${g.secs.map((s) => `<h3>${s.title === g.name ? "" : esc(s.title)}</h3><ul>${s.items.slice(0, 8).map(item).join("")}</ul>
      ${s.items.length > 8 ? `<details><summary class="small muted">${s.items.length - 8} more</summary><ul>${s.items.slice(8).map(item).join("")}</ul></details>` : ""}`).join("")}
    </details>`).join("");
  const fcNote = h.forecast?.error ? `<p class="muted small">Forecast unavailable this build.</p>` :
    hasOdds ? `<p class="muted small">Odds: ${h.forecast.sims.toLocaleString()} simulations of the rest of ${h.forecast.year} from the league's roster projection (lotg_support.forecast). Reads no news.</p>` : "";
  $app.innerHTML = `
    <h1>${meta.season} season</h1>
    <p class="muted">Through ${esc(meta.week_name)} · rebuilt ${esc(meta.built)}</p>
    <div class="card"><h2>Standings${hasOdds ? " &amp; odds" : ""}</h2>${table(cols, h.standings, { sort: 0, asc: true })}${fcNote}</div>
    <div class="card" id="watch"><h2>Record watch</h2><p class="muted small">Checking this week's games on Sleeper…</p></div>
    <div class="card"><h2>${esc(meta.week_name)} results</h2><div class="games">${games}</div></div>
    ${B ? `<div class="card"><h2>FAAB values</h2><p class="muted small">Board of ${esc(B.as_of)} · stats-only values in league FAAB</p>
      <ol>${B.players.slice(0, 5).map((x) => `<li>${playerLink(x.name)} <span class="muted small">${esc(x.pos)}</span> <b>${money(x.value)}</b></li>`).join("")}</ol>
      <p><a href="#/faab">Full board →</a> · <a href="rate/">Rate the board</a></p></div>` : ""}
    <div class="card digest"><h2>This week in the digest</h2>
      ${d.lede ? `<p>${esc(d.lede)}</p>` : `<p class="muted">No digest yet.</p>`}${digestHtml}</div>`;
  recordWatch(meta).catch(() => { const el = document.getElementById("watch"); if (el) el.innerHTML = `<h2>Record watch</h2><p class="muted small">Sleeper is unreachable right now.</p>`; });
}

// ---------- record watch: this week's live scores against the all-time boards
// a seeded random stream (mulberry32) and a string hash to seed it
const mulberry = (s) => () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const hashStr = (str) => { let h = 2166136261; for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619); return h >>> 0; };
// Where a value lands on a board's top 5 (values best first). Digest tie rule:
// it places only if it and everything tied with it fit in the top 5.
function boardPlace(vals, v, hi) {
  let gt = 0, ge = 0;
  for (const x of vals) { if (hi ? x > v : x < v) gt++; if (hi ? x >= v : x <= v) ge++; }
  return ge >= 5 ? 0 : ge > gt && gt === 0 ? 0.5 : gt + 1;   // 0 = not on the top 5; 0.5 = ties the record
}
const WATCH_SCOPES = { all: "League", win: "Filtered", loss: "Filtered", rookie: "Filtered" };
// Every weekly stat a live week can set (data/live_watch.json: team-week, game and
// player stats, each on the league board and its filtered versions — in a win / a
// loss, rookies). The rest of the week is simulated from each
// player's projection (forecast rate blended with this season's PPG) scaled by how
// much of his game is left (kickoff + ~3.3 h; ET); each simulated week is placed on
// every board. The random stream is seeded from the live scores and a 10-minute
// clock, so the same scores give everyone the same odds on every reload.
async function recordWatch(meta) {
  const el = () => document.getElementById("watch");
  const [LW, live, nfl] = await Promise.all([load("live_watch.json"), loadLive(), loadNfl()]);
  if (!live || !meta.league_id || !LW.stats) throw new Error("offline");
  const state = await fetch("https://api.sleeper.app/v1/state/nfl", { cache: "no-store" }).then((r) => r.json());
  const wk = state.week;
  const mus = await fetch(`https://api.sleeper.app/v1/league/${meta.league_id}/matchups/${wk}`, { cache: "no-store" }).then((r) => r.json());
  const nowRaw = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const nowET = new Date(Math.floor(nowRaw / 6e5) * 6e5);       // 10-minute clock: same odds for everyone
  const ko = LW.kickoffs[String(wk)] || {};
  const left = (pid) => {                       // share of his game still to play
    const t = (nfl[pid] || [])[2], k = t && ko[t];
    if (!k) return 0;                            // bye or not on an NFL team this week
    const h = (nowET - new Date(k)) / 36e5;
    return h < 0 ? 1 : Math.max(0, 1 - h / 3.3);
  };
  const rookies = new Set(LW.rookies);
  const slots = LW.roster_positions;
  const fits = { QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"], FLEX: ["RB", "WR", "TE"], SUPER_FLEX: ["QB", "RB", "WR", "TE"] };
  const slotOrder = slots.slice().sort((a, b) => (fits[a] || []).length - (fits[b] || []).length);
  const maxPF = (ps) => {                        // best lineup from (pos, pts) pairs
    const pool = ps.slice().sort((a, b) => b.p - a.p), used = new Set();
    let sum = 0;
    for (const sl of slotOrder) {
      const i = pool.findIndex((x, j) => !used.has(j) && (fits[sl] || []).includes(x.pos));
      if (i >= 0) { used.add(i); sum += pool[i].p; }
    }
    return sum;
  };
  const games = {};
  for (const m of mus) if (m.matchup_id) (games[m.matchup_id] = games[m.matchup_id] || []).push(m);
  const pairs = Object.values(games).filter((g) => g.length === 2);
  const teams = pairs.flat().map((m) => {
    const team = live.byRid[m.roster_id], lr = live.rosterOf[team] || {};
    return { team, m, players: (m.players || []).filter((pid) => pid && pid !== "0").map((pid) => {
      const inj = (nfl[pid] || [])[4], st = (m.starters || []).includes(pid);
      // out, on IR / PUP / suspended, or in the reserve slot: he won't add points
      const out = (lr.ir && lr.ir.has(pid)) || ["IR", "Out", "PUP", "Sus", "NA", "DNR", "COV"].includes(inj);
      const f = out ? 0 : left(pid);
      // a bench player on a bye or out is absent: not in the roster donut / under-10 counts
      return { pid, pos: (nfl[pid] || [])[1], nfl: (nfl[pid] || [])[2], st, rk: rookies.has(pid),
        absent: !st && (out || !ko[(nfl[pid] || [])[2]]), cur: (m.players_points || {})[pid] || 0, f, rate: LW.rates[pid] ?? 3 }; }) };
  });
  teams.forEach((t) => (t.opp = teams.findIndex((o) => o !== t && o.m.matchup_id === t.m.matchup_id)));
  const anyLeft = teams.some((t) => t.players.some((p) => p.f > 0));
  const anyPlayed = teams.some((t) => t.m.points > 0);
  const POS = ["QB", "RB", "WR", "TE"];
  // a team's week from its players' points (each matches its team_week column)
  const teamStats = (t, pts) => {
    const S = {}, st = [], ro = [];
    t.players.forEach((p, i) => { const x = { p, v: pts[i] }; if (p.st) st.push(x); ro.push(x); });
    const sv = st.map((x) => x.v), cnt = (a, f) => a.reduce((n, x) => n + (f(x) ? 1 : 0), 0);
    S.pf = sv.reduce((a, v) => a + v, 0);
    S.bench = ro.reduce((a, x) => a + (x.p.st ? 0 : x.v), 0);
    S.maxpf = maxPF(t.players.map((p, i) => ({ pos: p.pos, p: pts[i] })));
    S.left = S.maxpf - S.pf; S.eff = S.maxpf ? S.pf / S.maxpf : null;
    S.hist = sv.length ? Math.max(...sv) : null; S.lost = sv.length ? Math.min(...sv) : null;
    S.spread = sv.length ? S.hist - S.lost : null;
    const pv = LW.prev && LW.prev[t.team];
    S.inc = pv && pv[0] === wk - 1 && pv[1] != null ? S.pf - pv[1] : null;
    for (const P of POS) {
      S["from_" + P] = st.reduce((a, x) => a + (x.p.pos === P ? x.v : 0), 0);
      S["pct_" + P] = S.pf ? S["from_" + P] / S.pf : null;
      S["nst_" + P] = cnt(st, (x) => x.p.pos === P); S["nro_" + P] = cnt(ro, (x) => x.p.pos === P);
    }
    const rc = ro.filter((x) => x.p.st || !x.p.absent);
    S.don_st = cnt(st, (x) => x.v === 0); S.don_ro = cnt(rc, (x) => x.v === 0);
    S.u10_st = cnt(st, (x) => x.v < 10); S.u10_ro = cnt(rc, (x) => x.v < 10);
    for (const n of [20, 30, 40, 50]) { S[`o${n}_st`] = cnt(st, (x) => x.v > n); S[`o${n}_ro`] = cnt(ro, (x) => x.v > n); }
    const byNfl = {};
    st.forEach((x) => { if (x.p.nfl) byNfl[x.p.nfl] = (byNfl[x.p.nfl] || 0) + 1; });
    S.same_nfl = Math.max(0, ...Object.values(byNfl)); S.nfl_teams = Object.keys(byNfl).length;
    S.rk_st = cnt(st, (x) => x.p.rk); S.rk_ro = cnt(ro, (x) => x.p.rk);
    return S;
  };
  const withOpp = (S, O) => { S.pa = O.pf; S.margin = S.pf - O.pf; return S; };
  const gameStats = (A, O) => {
    const G = { c_pf: A.pf + O.pf, c_maxpf: A.maxpf + O.maxpf, c_eff: A.eff != null && O.eff != null ? (A.eff + O.eff) / 2 : null,
      c_bench: A.bench + O.bench, c_left: A.left + O.left, c_don: A.don_st + O.don_st, c_u10: A.u10_st + O.u10_st, c_rk: A.rk_st + O.rk_st };
    for (const P of POS) G["c_from_" + P] = A["from_" + P] + O["from_" + P];
    for (const n of [20, 30, 40, 50]) G[`c_o${n}`] = A[`o${n}_st`] + O[`o${n}_st`];
    return G;
  };
  // every (board, who) this week can reach, built once: [stat, value getter, board, cond]
  const statById = Object.fromEntries(LW.stats.map((s) => [s.id, s]));
  const BD = LW.boards, targets = [];
  // ctx: whose numbers the mark waits on — i (team index), p (player, if a player mark)
  const reach = (stat, who, get, scopes, ctx) => {
    for (const d of statById[stat] ? statById[stat].dirs : "") for (const [sc, cond] of scopes) {
      const b = BD[`${stat}|${d}|${sc}`];
      if (b) targets.push({ stat, d, sc, who, get, b, cond, ...ctx, top5: 0, rec: 0, tie: 0 });
    }
  };
  const resultScopes = (extra) => [["all", 0], ["win", 1], ["loss", -1], ...extra];
  teams.forEach((t, i) => {
    for (const s of LW.stats.filter((s) => s.kind === "team")) reach(s.id, t.team, (R) => R.team[i][s.id], resultScopes([]).map(([sc, c]) => [sc, c === 0 ? 0 : { team: i, w: c }]), { i, both: s.id === "pa" || s.id === "margin" });
    if (t.team < teams[t.opp].team) for (const s of LW.stats.filter((s) => s.kind === "game"))
      reach(s.id, `${t.team} v ${teams[t.opp].team}`, (R) => R.game[i][s.id], [["all", 0]], { i, both: true });
    t.players.forEach((p, k) => {
      const role = p.st ? "st" : "bn";
      const sc = () => resultScopes(p.rk ? [["rookie", 0]] : [])
        .map(([s, c]) => [s, c === 0 ? 0 : { team: i, w: c }]);
      const get = (R) => R.pts[i][k], who = "pid:" + p.pid;
      const cx = { i, p };
      reach(`p_${role}_ALL`, who, get, sc(), cx); reach(`p_ro_ALL`, who, get, sc(), cx);
      if (POS.includes(p.pos)) { reach(`p_${role}_${p.pos}`, who, get, sc(), cx); reach(`p_ro_${p.pos}`, who, get, sc(), cx); }
      if (p.st) reach("p_share", who, (R) => R.team[i].pf ? R.pts[i][k] / R.team[i].pf : null, [["all", 0]], { i, p, own: true });
    });
  });
  const run = (pts) => {
    const team = teams.map((t, i) => teamStats(t, pts[i]));
    team.forEach((S, i) => withOpp(S, team[teams[i].opp]));
    const game = teams.map((t, i) => gameStats(team[i], team[t.opp]));
    return { pts, team, game };
  };
  const now = run(teams.map((t) => t.players.map((p) => p.cur)));
  // the seed: this week's live points (and the 10-minute clock)
  const rand = mulberry(hashStr(`${wk}|${+nowET}|` + teams.map((t) => t.team + ":" + t.players.map((p) => p.pid + "=" + p.cur).join(",")).join(";")));
  const gauss = () => { let u = 0, v = 0; while (!u) u = rand(); while (!v) v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const N = anyLeft ? 2000 : 1;
  const sums = targets.map(() => 0), seen = targets.map(() => 0);
  for (let n = 0; n < N; n++) {
    const R = run(teams.map((t) => t.players.map((p) => p.f > 0 ? p.cur + Math.max(0, p.rate * p.f + gauss() * Math.max(3, 0.65 * p.rate) * Math.sqrt(p.f)) : p.cur)));
    targets.forEach((x, j) => {
      if (x.cond && Math.sign(R.team[x.cond.team].margin) !== x.cond.w) return;
      const v = x.get(R); if (v === null || v === undefined || isNaN(v)) return;
      seen[j]++; sums[j] += v;
      const r = boardPlace(x.b[1], v, x.d === "h");
      if (r) { x.top5++; if (r === 1) x.rec++; else if (r === 0.5) x.tie++; }
    });
  }
  const nameOf = (pid) => (nfl[pid] || [])[0] || NAMES_BY_ID[pid] || pid;
  const whoHtml = (who) => {
    if (who.startsWith("pid:")) { const pid = who.slice(4), t = teams.find((x) => x.players.some((p) => p.pid === pid));
      return `${NAMES_BY_ID[pid] ? `<a href="#/player/${pid}">${esc(nameOf(pid))}</a>` : esc(nameOf(pid))} <span class="muted small">(${esc(t ? t.team : "")})</span>`; }
    return who.includes(" v ") ? who.split(" v ").map(teamLink).join(" v ") : teamLink(who);
  };
  const tidy = (l) => l.replace(/^Number of (QB|RB|WR|TE) (started|rostered)$/, "$1s $2").replace(/^Number of rookies/, "Rookies")
    .replace(/^Most number of players started from same NFL team$/, "Starters from one NFL team").replace(/^Number of NFL teams among starting players$/, "NFL teams among starters")
    .replace(/^Combined (QBs|RBs|WRs|TEs|rookies)/, "Combined $1");
  const boardLabel = (x) => {
    const s0 = statById[x.stat], s = { ...s0, label: tidy(s0.label) }, count = s.fmt && s.fmt.d === 0 && !s.fmt.p;
    const head = s.kind === "player" ? `${x.d === "h" ? "Most" : "Fewest"} ${s.label.charAt(0).toLowerCase() + s.label.slice(1)}`
      : `${x.d === "h" ? (count ? "Most" : "Highest") : (count ? "Fewest" : "Lowest")} ${s.label}`;
    const k = x.sc;
    const tail = { all: "", win: "in a win", loss: "in a loss", rookie: "by a rookie" }[k];
    return tail ? `${head} · ${tail}` : head;
  };
  const rowLabel = (s, ri) => {
    if (s.kind === "player") { const r = LW.rows_p[ri]; return r ? `${esc(r[1])} (${esc(r[2])}) ${r[3]} ${esc(r[4])}` : ""; }
    const r = LW.rows_t[ri]; return r ? `${esc(r[0])}${s.kind === "game" ? ` v ${esc(r[3] || "")}` : ""} ${r[1]} ${esc(r[2])}` : "";
  };
  const rows = targets.map((x, j) => ({ ...x, p5: x.top5 / N, p1: x.rec / N, pt: x.tie / N, med: seen[j] ? sums[j] / seen[j] : null, curV: x.get(now) }))
    .filter((x) => x.p5 >= 0.01).sort((a, b) => b.p5 - a.p5 || b.p1 + b.pt - a.p1 - a.pt || b.b[0] - a.b[0]);
  const pctTxt = (x) => x >= 0.995 ? "certain" : x < 0.01 ? "<1%" : Math.round(x * 100) + "%";
  const fmtS = (x, v) => fmt(statById[x.stat].fmt || { d: 2 }, v);
  if (!el()) return;
  const nBoards = Object.keys(BD).length;
  // where each mark stands: "pre" (its numbers not started), "live" (still counting),
  // "done" (counting has stopped: every game it waits on is over)
  const begun = (p) => p.f < 1 || p.cur !== 0;
  const tBegun = (i) => teams[i].players.some(begun), tDone = (i) => teams[i].players.every((p) => p.f === 0);
  const mBegun = (i) => tBegun(i) || tBegun(teams[i].opp), mDone = (i) => tDone(i) && tDone(teams[i].opp);
  const status = (x) => {
    if (!anyLeft) return "done";
    if (x.p) {                                   // a player mark (his team's result too if filtered by it)
      if (!begun(x.p)) return "pre";
      return x.p.f === 0 && (!x.cond || mDone(x.i)) && (!x.own || tDone(x.i)) ? "done" : "live";
    }
    const both = x.both || x.cond;
    if (!(both ? mBegun(x.i) : tBegun(x.i))) return "pre";
    return (both ? mDone(x.i) : tDone(x.i)) ? "done" : "live";
  };
  rows.forEach((x) => (x.st = status(x)));
  const VIEWS = { "Not started": (x) => x.st === "pre", Counting: (x) => x.st === "live", Finished: (x) => x.st === "done" };
  const tabs = ["All", "League", "Filtered"];
  let view = ["Counting", "Not started", "Finished"].find((v) => rows.some(VIEWS[v])) || "Not started", tab = "All";
  const item = (x) => `<li>
      <div class="wtop"><span><b>${esc(boardLabel(x))}</b> · ${whoHtml(x.who)}</span><span class="wp">${x.st === "done"
        ? `<b>${x.p1 >= 0.5 ? "record" : x.pt >= 0.5 ? "ties the record" : "top 5"}</b>` : `<b>${pctTxt(x.p5)}</b> top 5 · ${pctTxt(x.p1)} record${x.pt >= 0.01 ? ` · ${pctTxt(x.pt)} tie` : ""}`}</span></div>
      <div class="muted small">${x.st === "done" ? `final ${x.curV == null ? "—" : fmtS(x, x.curV)}` : `${x.st === "live" && x.curV != null ? `now ${fmtS(x, x.curV)} → ` : ""}projected ${x.med == null ? "—" : fmtS(x, x.med)}`} · record ${fmtS(x, x.b[1][0])} (${rowLabel(statById[x.stat], x.b[2][0])}) · 5th ${fmtS(x, x.b[1][4])} · ${x.b[0].toLocaleString()} on the board</div></li>`;
  const draw = () => {
    const inView = rows.filter(VIEWS[view]);
    const counts = Object.fromEntries(tabs.map((t) => [t, t === "All" ? inView.length : inView.filter((x) => WATCH_SCOPES[x.sc.split(":")[0]] === t).length]));
    const list = inView.filter((x) => tab === "All" || WATCH_SCOPES[x.sc.split(":")[0]] === tab);
    // the preview: the view's top 15 by chance of a top-5 place (marks all but certain
    // before a point is scored — lineup counts — are left to the list below)
    const fin = view === "Finished";
    const eligible = fin ? list : list.filter((x) => x.p5 < 0.995);
    const shown = (fin ? eligible.slice().sort((a, b) => b.p1 + b.pt - a.p1 - a.pt || b.b[0] - a.b[0]) : eligible).slice(0, 15);
    const rest = list.filter((x) => !shown.includes(x));
    el().innerHTML = `<h2>Record watch · week ${esc(wk)} ${liveNote(live)}</h2>
    <p class="muted small">${anyLeft ? (anyPlayed ? "Games under way: chances come from simulating the rest of the week." : "Before kickoff: chances come from simulating the whole week from projections.") : "Every game is over: these are where this week's numbers landed."} ${LW.stats.length} weekly stats on ${nBoards.toLocaleString()} boards (league; in a win, in a loss, by a rookie).</p>
    <div class="seg">${Object.keys(VIEWS).map((v) => { const n = rows.filter(VIEWS[v]).length; return `<button aria-pressed="${v === view}" data-wview="${v}"${n ? "" : " disabled"}>${v} ${n}</button>`; }).join("")}</div>
    <div class="seg">${tabs.map((t) => `<button aria-pressed="${t === tab}" data-wtab="${t}"${counts[t] ? "" : " disabled"}>${t} ${counts[t]}</button>`).join("")}</div>
    ${shown.length ? `<h3>${view} · top ${shown.length}</h3><ul class="wlist">${shown.map(item).join("")}</ul>`
      : `<p class="muted">${fin ? "No finished mark has made a top 5." : "Nothing here has even a 1% chance of a top-5 place."}</p>`}
    ${rest.length ? `<details${shown.length ? "" : " open"}><summary><b>Every other board (${rest.length})</b> <span class="muted small">— ${fin ? "the rest of the finished marks" : "beyond the top 15, or all but certain (mostly lineup counts already fixed by who is rostered or started)"}</span></summary><ul class="wlist">${rest.map(item).join("")}</ul></details>` : ""}
    <p class="muted small">Not started = no game the mark depends on has kicked off; Counting = under way; Finished = counting has stopped (every game it depends on — his, his team's, or both teams' for a result-filtered or game mark — is over). Top 5 follows the digest's tie rule: a mark ties its way in only if everything tied with it fits; "record" is an outright record, "tie" a share of it. Projected = the average simulated outcome. Each player's projection is his forecast rate blended with this season's points per game, scaled by how much of his NFL game is left; a player who is out, on IR or on a bye adds nothing. ${anyLeft ? `${N.toLocaleString()} simulations, run in your browser and seeded from the live scores and a 10-minute clock: the same scores give everyone the same odds, on every reload.` : ""} Boards count every finished week since 2020 (all week types unless filtered); team marks include the semifinal +5 bonus, live points do not. Rosters count every player (taxi and IR too). <a href="#/records/team_week">Record book →</a></p>`;
    el().querySelectorAll("[data-wtab]").forEach((b) => (b.onclick = () => { tab = b.dataset.wtab; draw(); }));
    el().querySelectorAll("[data-wview]").forEach((b) => (b.onclick = () => { view = b.dataset.wview; tab = "All"; draw(); }));
  };
  draw();
}

async function teams() {
  const [meta, h, AT] = await Promise.all([load("meta.json"), load("home.json"), load("all_time.json")]);
  const ts = await Promise.all(meta.teams.map((t) => load(`team/${tslug(t)}.json`)));
  // default order: titles, then all-time win %
  const rows = ts.map((t) => ({ t: t.team, ...t.summary, age: t.ages.avg }))
    .sort((a, b) => (b.Championships ?? 0) - (a.Championships ?? 0) || (b["All time win %"] ?? 0) - (a["All time win %"] ?? 0));
  const S = ts[0]?.summary_fmt || {};
  const order = rows.map((r) => r.t);
  const ti = AT.cols.indexOf("Team");
  const allRows = AT.rows.slice().sort((a, b) => order.indexOf(a[ti]) - order.indexOf(b[ti]));
  $app.innerHTML = `<h1>All-time standings</h1><div class="card">${table([
    { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
    { k: "Championships", label: "Titles" },
    { k: "All time record", label: "Record", left: true },
    { k: "All time win %", label: "Win %", spec: S["All time win %"] },
    { k: "Number of playoff appearances", label: "Playoffs" },
    { k: "Avg points", label: "Avg PF", spec: S["Avg points"] },
    { k: "Drafting skill", label: "Drafting", spec: S["Drafting skill"] },
    { k: "Trading skill", label: "Trading", spec: S["Trading skill"] },
    { k: "Add/Drop skill", label: "Add/Drop", spec: S["Add/Drop skill"] },
    { k: "age", label: "Current roster age", spec: { d: 2 } },
  ], rows)}<p class="muted small">Ordered by titles, then all-time win %; tap a header to re-sort. Current roster age = the average age of each team's roster as of the last build, using this season's ages.</p></div>
  <div class="card"><h2>Every all-time stat</h2>${dataTable({ ...AT, rows: allRows }, { links: { Team: (v) => teamLink(v) }, defs: "team_all_time" })}
    <p class="muted small">Every team_all_time column except the head-to-head ones (those are on <a href="#/h2h">Head to head</a>). Scroll sideways; the team stays pinned.</p></div>`;
}

function tiles(summary, labels, specs, keys, sheet) {
  return `<div class="tiles">${(keys || Object.keys(summary)).filter((k) => k in summary).map((k) => {
    const d = defOf(k, sheet);
    return `<div class="tile"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(labels[k] || k)}"` : ""}><b>${fmt(specs[k], summary[k])}</b><span>${esc(labels[k] || k)}${d ? ' <span class="defbtn">ⓘ</span>' : ""}</span></div>`; }).join("")}</div>`;
}

function tradeCard(t, meta, full) {
  const F = meta.fmt, L = meta.labels;
  const best = t.sides[0];
  const ktcNow = (s) => { for (let i = meta.ktc.length - 1; i >= 0; i--) { const v = s[meta.ktc[i][1]]; if (typeof v === "number") return [meta.ktc[i][0], v]; } return null; };
  const sides = t.sides.map((s) => {
    const k = ktcNow(s);
    return `<div class="side"><h4>${teamLink(s.team)} ${k ? `<span class="grade ${k[1] >= 0 ? "pos" : "neg"}" title="KTC value difference, latest available (${esc(k[0])})">${signed(F["KTC value difference at deal time"], k[1])} KTC</span>` : ""}</h4>
      <div class="small muted">Got</div><ul>${s.got.map((a) => `<li>${assetLink(a)}</li>`).join("") || '<li class="muted">nothing</li>'}</ul>
      ${t.sides.length > 2 || full ? `<div class="small muted">Sent</div><ul>${s.sent.map((a) => `<li>${assetLink(a)}</li>`).join("") || '<li class="muted">nothing</li>'}</ul>` : ""}
      <div class="ktc">${meta.ktc.map(([lab, c]) => `<span>${esc(lab)}: <b class="${(s[c] ?? 0) > 0 ? "pos" : (s[c] ?? 0) < 0 ? "neg" : ""}">${s[c] === null || s[c] === undefined ? "—" : signed(F[c], s[c])}</b></span>`).join("")}</div>
      ${meta.faab ? `<div class="ktc" title="FAAB Value difference: the same received − sent gap in the league's FAAB dollars (FAAB value system)"><span class="muted">FAAB $</span>${meta.faab.map(([lab, c]) => `<span>${esc(lab)}: <b class="${(s[c] ?? 0) > 0 ? "pos" : (s[c] ?? 0) < 0 ? "neg" : ""}">${s[c] === null || s[c] === undefined ? "—" : signed(F[c], s[c])}</b></span>`).join("")}</div>` : ""}
      <div class="ktc">${["Trade impact score", "Wins added", "Net points", "O-Score"].map((c) => `<span title="${esc(L[c])}">${esc(L[c])}: <b>${fmt(F[c], s[c])}</b></span>`).join("")}</div>
    </div>`;
  }).join("");
  return `<div class="trade${full ? "" : " go"}" id="trade-${t.id}"${full ? "" : ` data-go="trades/${t.id}"`}><div class="small muted"><a href="#/trades/${t.id}">Trade #${t.id}</a> · ${esc(t.date)}${t.sides.length > 1 && (best["Trade impact score"] ?? 0) > (t.sides[1]["Trade impact score"] ?? 0) ? ` · impact edge: ${esc(best.team)}` : ""}</div><div class="sides">${sides}</div></div>`;
}

async function team(slug, _q, live) {
  const [t, tr, PK, B, , AT] = await Promise.all([load(`team/${slug}.json`), load("trades.json"), load("picks.json"), loadBoard(), loadPickRows(), load("all_time.json")]);
  const atRow = AT.rows.find((r) => r[AT.cols.indexOf("Team")] === t.team) || [];
  const allStats = {}, allLabels = {};
  AT.cols.forEach((c, i) => { if (c !== "Team" && atRow[i] !== null && atRow[i] !== undefined) { allStats[c] = atRow[i]; allLabels[c] = AT.labels[i]; } });
  const mine = (livePicks(PK, live)[t.team] || []).map(([y, r, o]) => ({ y, r, o, v: pickValue(PK, B, y, r, o) }));
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const ages = t.ages || {};
  const leagueAvg = (k) => { const v = Object.values(t.league_ages).map((a) => k ? a.by_pos?.[k] : a.avg).filter((x) => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const ageRows = ["QB", "RB", "WR", "TE"].map((p) => [p, ages.by_pos?.[p], leagueAvg(p)]);
  const ri = idx(t.roster, "slug");
  let roster = dataTable(t.roster, { hide: ["slug"], defs: "player_week", links: { Player: (v, r) => ri >= 0 && r[ri] ? `<a href="#/player/${r[ri]}">${esc(v)}</a>` : esc(v), "NFL team": (v) => nflLink(v) } });
  let rosterNote = "Bench includes taxi and IR. Age is the player's age for this season. Lineup roles are the last built week's.";
  const lr = live && live.rosterOf[t.team];
  if (lr) {
    const nfl = await loadNfl();
    const built = new Map(t.roster.rows.map((r) => [String(r[ri]), r]));
    const age = idx(t.roster, "Age");
    const pos = { QB: 0, RB: 1, WR: 2, TE: 3 };
    const rows = lr.players.map((pid) => {
      const n = nfl[pid] || [];
      const b = built.get(String(pid));
      return { pid, name: n[0] || (b && b[0]) || pid, pos: n[1] || "", nfl: n[2] || "", age: (b && age >= 0 ? b[age] : null) ?? n[3] ?? null,
               role: lr.ir.has(pid) ? "IR" : lr.taxi.has(pid) ? "Taxi" : lr.starters.has(pid) ? "Starter" : "Bench", isNew: !b };
    }).sort((a, b) => (a.role === "Starter" ? 0 : a.role === "Bench" ? 1 : 2) - (b.role === "Starter" ? 0 : b.role === "Bench" ? 1 : 2) || (pos[a.pos] ?? 9) - (pos[b.pos] ?? 9));
    const gone = [...built.keys()].filter((pid) => !lr.players.includes(pid)).map((pid) => built.get(pid)[0]);
    roster = table([
      { k: "name", label: "Player", left: true, html: (r) => `${NAMES_BY_ID[r.pid] ? `<a href="#/player/${esc(r.pid)}">${esc(r.name)}</a>` : esc(r.name)}${r.isNew ? ' <span class="chip live">new since the build</span>' : ""}` },
      { k: "pos", label: "Pos", left: true }, { k: "nfl", label: "NFL", left: true, html: (r) => nflLink(r.nfl) },
      { k: "age", label: "Age", spec: { d: 2 } }, { k: "role", label: "Now", left: true },
    ], rows);
    rosterNote = `${rows.length} players on Sleeper now (Now = current lineup role).${gone.length ? ` Gone since the last build: ${gone.map(esc).join(", ")}.` : ""} Ages are this season's, for players the build has seen.`;
  }
  const HEAD = ["All time record", "All time win %", "Championships", "Number of playoff appearances", "Number of championship appearances", "Avg points", "All-play win %", "Trading skill"];
  const sec = (id, title, html) => `<section class="card" id="sec-${id}"><h2>${title}</h2>${html}</section>`;
  const nav = [["season", "This season"], ["roster", "Roster"], ["picks", "Picks"], ["h2h", "Head to head"], ["seasons", "Seasons"], ["style", "Style"], ["trades", "Trades"], ["draft", "Draft"]];
  $app.innerHTML = `
    <h1>${esc(t.team)}</h1>
    ${tiles(t.summary, t.summary_labels, t.summary_fmt, HEAD, "team_all_time")}
    <details class="more"><summary class="small">All ${Object.keys(allStats).length} all-time stats</summary>${tiles(allStats, allLabels, AT.fmt, Object.keys(allStats).filter((k) => !HEAD.includes(k)), "team_all_time")}</details>
    <nav class="secnav">${nav.map(([id, n]) => `<button data-sec="${id}">${n}</button>`).join("")}</nav>
    ${sec("season", "This season", dataTable(t.weeks, { hide: ["Week"], defs: "team_week", links: { "Week Name": (v, r, cols) => `<a href="#/game/${r[cols.indexOf("Year")]}/${r[cols.indexOf("Week")]}/${tslug(t.team)}">${esc(v)}</a>`, Opponent: (v) => teamLink(v) } }))}
    ${sec("roster", `Current roster ${liveNote(live)}`, `${roster}<p class="muted small">${rosterNote}</p>
      <h3>Roster age</h3><p>Whole roster <b>${fmt({ d: 2 }, ages.avg)}</b> · starters <b>${fmt({ d: 2 }, ages.starters)}</b> · league avg ${fmt({ d: 2 }, leagueAvg(null))} <span class="muted small">(current roster, this season's ages)</span></p>
      ${table([{ k: 0, label: "Pos", left: true }, { k: 1, label: "Age", spec: { d: 2 } }, { k: 2, label: "League avg", spec: { d: 2 } },
               { k: (r) => (r[1] ?? 0) - (r[2] ?? 0), label: "vs league", html: (r) => r[1] == null ? "—" : `<span class="${r[1] > r[2] ? "neg" : "pos"}">${signed({ d: 2 }, r[1] - r[2])}</span>` }], ageRows)}`)}
    ${sec("picks", `Future picks held (${mine.length}) ${liveNote(live)}`, `${table([{ k: "y", label: "Draft", left: true }, { k: (r) => r.ps.length, label: "Picks", left: true, html: (r) => pickDots(r.ps, t.team) },
        { k: (r) => r.ps.map((p) => p.o === t.team ? "" : `${ORD[p.r]} from ${p.o}`).filter(Boolean).join(", "), label: "Acquired", left: true },
        { k: (r) => r.ps.reduce((a, p) => a + (p.v || 0), 0), label: "Value", html: (r) => B ? money(r.ps.reduce((a, p) => a + (p.v || 0), 0)) : "—" }],
        PK.years.map((y) => ({ y, ps: mine.filter((p) => p.y === y) })))}
      ${B ? `<p class="small">Worth <b>${money(mine.reduce((a, p) => a + (p.v || 0), 0))}</b> on the FAAB board's pick scale. <a href="#/faab?owner=${encodeURIComponent(t.team)}">FAAB board →</a></p>` : ""}`)}
    ${sec("h2h", "Head to head", `${table([
        { k: "opp", label: "Opponent", left: true, html: (r) => teamLink(r.opp) },
        { k: (r) => r.w / Math.max(1, r.w + r.l), label: "W-L", html: (r) => `${r.w}-${r.l}` },
        ...[["reg", "Regular"], ["playoffs", "Playoffs"], ["final", "Final"], ["third", "3rd place"], ["toilet", "Toilet"], ["trash", "Toilet losers"]].map(([k, n]) =>
          ({ k: (r) => r[k + "w"] / Math.max(1, r[k + "w"] + r[k + "l"]), label: n, html: (r) => (r[k + "w"] || r[k + "l"]) ? `${r[k + "w"]}-${r[k + "l"]}` : '<span class="muted">—</span>' })),
        { k: "pf", label: "Avg PF", spec: { d: 2 } },
        { k: "pa", label: "Avg PA", spec: { d: 2 } },
      ], t.h2h, { sort: 1 })}<p class="small"><a href="#/h2h">Full matrix →</a></p>`)}
    ${sec("seasons", "Seasons", dataTable(t.seasons, { defs: "team_year" }))}
    ${t.swing && t.swing.rows && t.swing.rows.length && t.swing.cols.length > 1 ? sec("style", "Scoring style", `${dataTable(t.swing, { defs: "team_year" })}
      <p class="muted small">Swing = how far a typical week lands from the team's average (starters' points; the semifinal +5 left out). "To this point" compares every season over the weeks played so far this season. Boom / bust = a week at least 120% / at most 80% of the league's middle score.</p>
      <h3>Lineup risk and stacks</h3>${dataTable(t.risk, { defs: "team_year" })}
      <p class="muted small">Riskiness 1.00 = the usual swing for a lineup of that projected strength; above 1 = boom-or-bust picks. Underdog = pre-week win % under 50%; risky = riskiness 1.00 or more.</p>`) : ""}
    ${sec("trades", `Trades (${t.trades.length})`, `${t.trades.slice(0, 15).map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("")}
      ${t.trades.length > 15 ? `<p><a href="#/trades?team=${encodeURIComponent(t.team)}">All ${t.trades.length} trades →</a></p>` : ""}`)}
    ${sec("draft", "Rookie draft picks", dataTable(t.draft, { hide: ["Team", "_row"], pin: 2, defs: "rookie_picks", links: { Number: (v, r, cols) => `<a href="#/pick/rookie_picks/${r[cols.indexOf("_row")]}">${esc(v)}</a>`, "Player Picked": (v) => playerLink(v), "Original Team": (v) => teamLink(v) } }))}
    <p class="small">Every row in the data: ${[["team_week", "weeks"], ["team_year", "seasons"], ["team_all_time", "all-time"], ["trades", "trades"], ["add_drops", "add/drops"], ["player_additions", "pickups"], ["rookie_picks", "rookie picks"]].map(([s, n]) => `<a href="#/data/${s}?c=Team&v=${encodeURIComponent(t.team)}">${n}</a>`).join(" · ")}</p>`;
  $app.querySelector(".secnav").onclick = (e) => { const b = e.target.closest("[data-sec]"); if (!b) return; const el = document.getElementById("sec-" + b.dataset.sec); if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 110, behavior: "smooth" }); };
}

async function player(key, _q, live) {
  const [p, tr, B] = await Promise.all([load(`player/${key}.json`), load("trades.json"), loadBoard(), loadPickRows()]);
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const d = p.draft;
  const fv = B && B.players.find((x) => x.name === p.name);
  const enc = encodeURIComponent(p.name);
  $app.innerHTML = `
    <h1>${esc(p.name)}</h1>
    <p class="muted">${[p.pos, nflLink(p.nfl), ((t) => t ? "on " + teamLink(t) : "not on a roster now")(live && /^\d+$/.test(key) ? live.owner[key] : p.team)].filter(Boolean).join(" · ")} ${live ? liveNote(live) : ""}
      ${d ? ` · drafted ${esc(d.year)} pick ${esc(d.pick)} by ${teamLink(d.team)}${typeof d.faab === "number" ? ` (FAAB value on draft day ${money(d.faab)})` : ""}` : ""}</p>
    ${fv ? `<div class="card"><b>FAAB value ${money(fv.value)}</b> <span class="muted">· #${fv.rank} on the board of ${esc(B.as_of)} · ${esc(pickText(B, fv.value))}</span> · <a href="#/faab">board</a> · <a href="rate/">rate it</a></div>` : ""}
    ${tiles(p.summary, p.summary_labels, p.summary_fmt, null, "player_all_time")}
    <p class="small">Every row: <a href="#/data/player_week?c=Player&v=${enc}&y=all">weeks</a> · <a href="#/data/player_year?c=Player&v=${enc}">seasons</a> · <a href="#/data/player_all_time?c=Player&v=${enc}">career</a> · <a href="#/data/player_additions?c=Player&v=${enc}">acquisitions</a> · <a href="#/data/add_drops?q=${enc}">add/drops</a></p>
    <div class="card"><h2>Career by team</h2>${table([
      { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
      { k: "from", label: "From", left: true }, { k: "to", label: "To", left: true },
      { k: "weeks", label: "Weeks" }, { k: "starts", label: "Starts" },
      { k: "pts", label: "Pts as starter", spec: { d: 2 } }, { k: "ppg", label: "PPG starter", spec: { d: 2 } },
      { k: "best", label: "Best week", spec: { d: 2 } }], p.teams)}</div>
    <div class="card"><h2>Acquisitions</h2>${dataTable(p.stints, { pin: 2, defs: "player_additions", links: { Team: (v) => teamLink(v) } })}</div>
    <div class="card"><h2>Seasons</h2>${dataTable(p.seasons, { defs: "player_year", links: { "Top Team": (v) => teamLink(v), "Last team": (v) => teamLink(v) } })}</div>
    ${p.usage && p.usage.rows.length ? `<div class="card"><h2>Usage</h2><p class="muted small">Snaps, targets, carries and red-zone looks while rostered. xFP = the points his targets and carries usually produce in this league's scoring; points minus xFP above 0 = scoring beyond the opportunity (rarely sticky), rising xFP = a bigger role.</p>${dataTable(p.usage)}</div>` : ""}
    ${p.history ? `<div class="card"><h2>History</h2>${historyList(p.history)}<p class="muted small">Every draft, add, drop and trade, as the workbook's history note has it. Tap a trade to open it.</p></div>` : ""}
    ${p.trades.length ? `<div class="card"><h2>Trades</h2>${p.trades.map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("")}</div>` : ""}`;
}

const SHEETS = [
  ["team_week", "Team week"], ["team_year", "Team season"], ["team_all_time", "Team all-time"],
  ["player_week", "Player week"], ["player_year", "Player season"], ["player_all_time", "Player career"],
  ["league_week", "League week"], ["league_year", "League season"], ["trades", "Trades"],
  ["add_drops", "Add/drops"], ["player_additions", "Pickups"], ["rookie_picks", "Rookie picks"],
  ["non_rookie_picks", "Startup & vet picks"],
];
const FEATURED = {
  team_week: ["PF", "Margin", "Max PF", "Efficiency", "Points left on bench", "Bench points"],
  team_year: ["Points", "Win %", "All-play win %", "Efficiency", "Differential", "Lineup Boldness", "Starters' xFP", "Starters' points minus xFP", "Avg weekly score", "Weekly score swing %"],
  team_all_time: ["Championships", "All time win %", "Avg points", "Trading skill", "Drafting skill", "Add/Drop skill", "Avg weekly score", "Weekly score swing %"],
  player_week: ["Points", "xFP", "Points minus xFP"],
  player_year: ["Points", "PPG starter", "Starter PAR", "Times as Player of the week?", "xFP", "Points minus xFP"],
  player_all_time: ["Points", "Total points as starter", "Starter PAR", "Number of teams", "Number of trades"],
};

async function records(sheet, query) {
  sheet = sheet || "team_week";
  const params = new URLSearchParams(query || "");
  const r = await load(`records/${sheet}.json`);
  let q = params.get("q") || "", end = params.get("end") || "hi";
  let scope = r.scopes.includes(params.get("w")) ? params.get("w") : "all";
  const labelCols = r.labels;
  const pickSheet = sheet === "rookie_picks" || sheet === "non_rookie_picks";
  const lab = (row) => pickSheet ? pickLab(row) : row.map((x, i) => {
    const c = labelCols[i];
    if (x === null) return "";
    if (c === "Team" || c === "Top team" || c === "Top Team" || c === "Opponent" || c === "Team's traded with 1") return (c === "Opponent" ? "vs " : "") + teamLink(x);
    if (c === "Player" || c === "Player Picked" || c === "Player Added") return playerLink(x);
    if (c === "Player Dropped") return `<span class="muted">for</span> ${playerLink(x)}`;
    if (c === "Assets received") return `<span class="muted">got ${esc(String(x).slice(0, 60))}</span>`;
    if (c === "Date") return esc(String(x).slice(0, 10));
    return esc(x);
  }).filter(Boolean).join(" · ");
  // a pick board is about the pick: "2025 3.08 · AceMatthew → Jalen Milroe"
  function pickLab(row) {
    const v = (c) => row[labelCols.indexOf(c)];
    const player = v("Player Picked");
    const used = player && !/^unknown$/i.test(player);
    return `<b>${esc(v("Year"))} ${esc(v("Number"))}</b> · ${teamLink(v("Team"))}${used ? ` <span class="muted">→</span> ${playerLink(player)}` : ' <span class="muted">(not used yet)</span>'}`;
  }
  // ranks as the digest words them: "T2" for a shared place
  const place = (rows, i) => {
    const r0 = rows[i][3], tied = rows.filter((x) => x[3] === r0).length > 1;
    return (tied ? "T" : "") + r0;
  };
  function card(c) {
    const b = (c.scopes || {})[scope] || {};
    const useEnd = c.mirror ? "hi" : end;
    const rows = b[useEnd] || [];
    const body = rows.length
      ? `<table class="rk"><tbody>${rows.map((x, i) => `<tr${x[4] ? ` class="go" data-go="${esc(x[4])}"` : ""}><td class="muted">${place(rows, i)}</td><td class="v">${x[4] ? `<a href="#/${esc(x[4])}">${fmt(c.fmt, x[0])}</a>` : fmt(c.fmt, x[0])}</td><td class="l">${lab(x[1])}${x[2] ? ` <span class="chip live">${esc(r.flag || "")}</span>` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<p class="muted small">No board: ${b.hi || b.lo ? "a tie for the last places doesn't fit in the top " + r.depth : "no values"}.</p>`;
    const d = defOf(c.col, sheet);
    return `<div class="card rec"><a class="stat" href="#/records/${sheet}?full=${encodeURIComponent(c.col)}&end=${useEnd}&w=${scope}"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(c.label)}"` : ""}><b>${esc(c.label)}</b></a>${d ? ' <span class="defbtn" data-def="' + esc(d) + '" data-deflabel="' + esc(c.label) + '">ⓘ</span>' : ""} <span class="muted small">${useEnd === "hi" ? "highest" : "lowest"}${c.mirror ? " · each trade once" : ""}</span>
      ${body}${c.mirror && end === "lo" ? `<p class="muted small">Lowest is the same trades from the losing side, so only the highest is shown.</p>` : ""}</div>`;
  }
  function draw() {
    const ql = q.trim().toLowerCase();
    let cs = r.columns;
    if (ql) cs = cs.filter((c) => c.label.toLowerCase().includes(ql) || c.col.toLowerCase().includes(ql));
    else if (FEATURED[sheet]) { const f = FEATURED[sheet]; cs = f.map((n) => cs.find((c) => c.col === n)).filter(Boolean).concat(cs.filter((c) => !f.includes(c.col))); }
    document.getElementById("recs").innerHTML = cs.map(card).join("") || `<p class="muted">No column matches.</p>`;
    document.getElementById("reccount").textContent = `${cs.length} of ${r.columns.length} stats · tap a stat's name for its full all-time list`;
  }
  const full = params.get("full");
  if (full) return fullList(sheet, r, full, end, scope, lab);
  $app.innerHTML = `<h1>Record book</h1>
    <div class="seg">${SHEETS.map(([k, n]) => `<button aria-pressed="${k === sheet}" data-s="${k}">${n}</button>`).join("")}</div>
    <div class="controls"><input class="f" id="appq" type="search" placeholder="Find a player, team or week on any board (e.g. Josh Allen, 2025 Week 3)"><button class="b" id="appgo">Find</button></div>
    <div id="appres"></div>
    <div class="controls"><input class="f" id="rq" type="search" placeholder="Filter ${r.columns.length} stats (e.g. bench, boldness, KTC)" value="${esc(q)}">
      <span class="seg" style="margin:0"><button data-e="hi" aria-pressed="${end === "hi"}">Highest</button><button data-e="lo" aria-pressed="${end === "lo"}">Lowest</button></span></div>
    <p class="muted small" id="reccount"></p>
    ${r.scopes.length > 1 ? `<div class="seg">${r.scopes.map((k) => `<button data-w="${k}" aria-pressed="${k === scope}">${esc(r.scope_names[k])}</button>`).join("")}</div>` : ""}
    <div class="note">Top and bottom ${r.depth}, as the digest ranks them: a shared place reads "T2", and a tie that would not fit inside the ${r.depth} is left off. Team PF includes the semifinal +5 bonus; player points do not. Lineups were 9 starters 2020-23 and 10 from 2024.${r.flag ? ` "${esc(r.flag)}" marks a value that can still change, each stat on its own clock: fixed at the move (deal-time KTC, prices, ages, form before the move, a used pick's trade count: never tagged); while the player or received assets are still on the team (points added, on-team PPG, tenure); the sent side over that same span; until the traded picks are drafted; while he's active in the NFL (a pick's career PPG); until a KTC checkpoint's date; or always moving (wins added, impact score, O-Score and pick-adjusted figures, which are re-ranked as other rows change).` : ""}${sheet === "team_all_time" || sheet === "league_all_time" ? " All-time team and league totals move every week of a season." : ""}${sheet === "trades" ? " Each trade is listed once per board (the side that ranks), even though the trades sheet has a row for each side." : ""}</div>
    <div class="recgrid" id="recs"></div>`;
  $app.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => (location.hash = `#/records/${b.dataset.s}${q ? "?q=" + encodeURIComponent(q) : ""}`));
  $app.querySelectorAll("[data-e]").forEach((b) => b.onclick = () => { end = b.dataset.e; $app.querySelectorAll("[data-e]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  $app.querySelectorAll("[data-w]").forEach((b) => b.onclick = () => { scope = b.dataset.w; $app.querySelectorAll("[data-w]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("rq").oninput = (e) => { q = e.target.value; draw(); };
  const find = () => appearances(document.getElementById("appq").value.trim());
  document.getElementById("appgo").onclick = find;
  document.getElementById("appq").onkeydown = (e) => { if (e.key === "Enter") find(); };
  // tap anywhere on a board row (not on a link inside it) to open its details
  document.getElementById("recs").onclick = (e) => { if (e.target.closest("a")) return; const tr = e.target.closest("tr[data-go]"); if (tr) location.hash = "#/" + tr.dataset.go; };
  draw();
}

// every top/bottom-5 board place a player, team or week holds, across all sheets
async function appearances(q) {
  const out = document.getElementById("appres");
  if (!q) { out.innerHTML = ""; return; }
  out.innerHTML = `<p class="muted small">Searching every board…</p>`;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const all = await Promise.all(SHEETS.map(([k]) => load(`records/${k}.json`).then((r) => [k, r]).catch(() => [k, null])));
  const hits = [];
  for (const [sheet, r] of all) {
    if (!r) continue;
    for (const c of r.columns) for (const [scope, b] of Object.entries(c.scopes || {})) for (const [end, rows] of Object.entries(b)) {
      for (const x of rows) {
        const text = x[1].map((v) => String(v ?? "")).join(" ").toLowerCase();
        if (words.every((w) => text.includes(w))) hits.push({ sheet, c, scope, end, x, scopeName: r.scope_names?.[scope] });
      }
    }
  }
  hits.sort((a, b) => a.x[3] - b.x[3]);
  const name = Object.fromEntries(SHEETS);
  out.innerHTML = `<div class="card"><h2>${hits.length} board place${hits.length === 1 ? "" : "s"} for “${esc(q)}”</h2>
    ${hits.length ? `<table class="rk"><tbody>${hits.slice(0, 300).map((h) => `<tr class="go"${h.x[4] ? ` data-go="${esc(h.x[4])}"` : ""}><td class="muted">${h.x[3]}</td><td class="v">${fmt(h.c.fmt, h.x[0])}</td><td class="l"><a href="#/records/${h.sheet}?full=${encodeURIComponent(h.c.col)}&end=${h.end}&w=${h.scope}">${esc(h.c.label)}</a> <span class="muted small">${esc(name[h.sheet])} · ${h.end === "hi" ? "highest" : "lowest"}${h.scope !== "all" ? " · " + esc(h.scopeName || h.scope) : ""}</span><br><span class="small">${esc(h.x[1].filter((v) => v !== null).join(" · "))}</span></td></tr>`).join("")}</tbody></table>${hits.length > 300 ? `<p class="muted small">First 300 shown; add a word to narrow it.</p>` : ""}`
      : `<p class="muted">Not in any top or bottom 5. Open a stat's full list to see where it ranks.</p>`}</div>`;
  out.onclick = (e) => { if (e.target.closest("a")) return; const tr = e.target.closest("tr[data-go]"); if (tr && tr.dataset.go) location.hash = "#/" + tr.dataset.go; };
}

// a stat's full all-time list, ranked from the whole sheet (the Data page's rows)
const WEEK_KIND = (n) => { n = String(n); if (n.startsWith("Week ")) return "reg"; const l = n.toLowerCase(); if (l.includes("3rd") || l.includes("third")) return "third"; if (l.startsWith("toilet")) return (l.includes("trash") || l.includes("loser")) ? "trash" : "toilet"; return "playoffs"; };
async function fullList(sheet, r, col, end, scope, lab) {
  const c = r.columns.find((x) => x.col === col);
  if (!c) throw new Error("No stat " + col);
  $app.innerHTML = `<p class="small"><a href="#/records/${sheet}?w=${scope}&end=${end}">← ${esc(Object.fromEntries(SHEETS)[sheet])} records</a></p>
    <h1>${esc(c.label)}${defMark(c.col, sheet)}</h1><p class="muted" id="flmeta">Loading every row…</p><div id="fl"></div>`;
  const ix = await load("sheets/index.json");
  const m = ix.sheets.find((x) => x.sheet === sheet);
  const parts = await Promise.all(m.chunks.map(([, k]) => load(`sheets/${sheet}/${k}.json`)));
  let rows = [].concat(...parts.map((p) => p.rows));
  rows.forEach((x, i) => { x._i = i; });
  const ci = m.cols.indexOf(col), wn = m.cols.indexOf("Week Name");
  rows = rows.filter((x) => typeof x[ci] === "number" && (scope === "all" || wn < 0 || (scope === "final" ? x[wn] === "Final" : WEEK_KIND(x[wn]) === scope)));
  const tradeIds = sheet === "trades" ? tradeIndex(await load("trades.json")) : null;
  if (sheet === "trades") { const seen = new Set(); rows = rows.sort((a, b) => end === "hi" ? b[ci] - a[ci] : a[ci] - b[ci]).filter((x) => { const k = rowLink(sheet, m.cols, x, tradeIds); if (seen.has(k)) return false; seen.add(k); return true; }); }
  rows.sort((a, b) => end === "hi" ? b[ci] - a[ci] : a[ci] - b[ci]);
  const labIdx = r.labels.map((l) => m.cols.indexOf(l));
  let shown = 100;
  const placeOf = (i) => { let k = i; while (k > 0 && rows[k - 1][ci] === rows[i][ci]) k--; return k + 1; };
  const draw = () => {
    document.getElementById("flmeta").innerHTML = `${rows.length.toLocaleString()} rows · ${end === "hi" ? "highest first" : "lowest first"}${scope !== "all" ? " · " + esc(r.scope_names?.[scope] || scope) : ""} · <a href="#/records/${sheet}?full=${encodeURIComponent(col)}&end=${end === "hi" ? "lo" : "hi"}&w=${scope}">flip</a>`;
    document.getElementById("fl").innerHTML = `<div class="card"><table class="rk"><tbody>${rows.slice(0, shown).map((x, i) => { const link = rowLink(sheet, m.cols, x, tradeIds); return `<tr class="go"${link ? ` data-go="${esc(link)}"` : ""}><td class="muted">${placeOf(i)}</td><td class="v">${fmt(c.fmt, x[ci])}</td><td class="l">${lab(labIdx.map((j) => (j < 0 ? null : x[j])))}</td></tr>`; }).join("")}</tbody></table>
      ${rows.length > shown ? `<button class="b" id="flmore">Show ${Math.min(100, rows.length - shown)} more</button>` : ""}</div>`;
    const more = document.getElementById("flmore");
    if (more) more.onclick = () => { shown += 100; draw(); };
  };
  document.getElementById("fl").onclick = (e) => { if (e.target.closest("a") || e.target.closest("button")) return; const tr = e.target.closest("tr[data-go]"); if (tr && tr.dataset.go) location.hash = "#/" + tr.dataset.go; };
  draw();
}

async function h2h() {
  const m = await load("h2h.json");
  let mode = "all";
  function draw() {
    const key = mode === "all" ? ["w", "l"] : [mode + "w", mode + "l"];
    const head = `<tr><th class="l">Team ↓ vs →</th>${m.teams.map((t) => `<th>${esc(t.slice(0, 8))}</th>`).join("")}<th>Total</th></tr>`;
    const body = m.teams.map((a) => {
      let W = 0, L = 0;
      const cells = m.teams.map((b) => {
        if (a === b) return `<td class="self"></td>`;
        const c = m.cells[`${a}|${b}`];
        if (!c) return "<td>—</td>";
        const w = c[key[0]], l = c[key[1]];
        if (!w && !l) return `<td class="self" title="Never met here"></td>`;
        W += w; L += l;
        const p = w + l ? w / (w + l) : 0.5;
        const bg = w + l ? `background:color-mix(in srgb, ${p >= 0.5 ? "var(--good)" : "var(--bad)"} ${Math.round(Math.abs(p - 0.5) * 120)}%, transparent)` : "";
        return `<td style="${bg}" data-a="${esc(a)}" data-b="${esc(b)}">${w}-${l}</td>`;
      }).join("");
      return `<tr><td class="l">${teamLink(a)}</td>${cells}<td><b>${W}-${L}</b></td></tr>`;
    }).join("");
    document.getElementById("mx").innerHTML = `<table class="matrix"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }
  $app.innerHTML = `<h1>Head to head</h1>
    <div class="seg"><button data-m="all" aria-pressed="true">All games</button>${Object.entries(m.kinds).map(([k, n]) => `<button data-m="${k}" aria-pressed="false">${esc(n)}</button>`).join("")}</div>
    <div class="card"><div class="scroll" id="mx"></div><p class="muted small">Row team's record against the column team. Tap a cell for details. Playoffs = semifinals and final; the 3rd-place game, the toilet bowl (toilet semis and final) and the toilet losers game are each their own record, as on the team sheets. ${esc(m.note)}</p></div>
    <div class="card" id="cell"><p class="muted">Tap a cell.</p></div>`;
  $app.querySelectorAll("[data-m]").forEach((b) => b.onclick = () => { mode = b.dataset.m; $app.querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("mx").onclick = (e) => {
    const td = e.target.closest("td[data-a]");
    if (!td) return;
    const c = m.cells[`${td.dataset.a}|${td.dataset.b}`];
    document.getElementById("cell").innerHTML = `<h2>${teamLink(td.dataset.a)} vs ${teamLink(td.dataset.b)}</h2>
      <p>All games <b>${c.w}-${c.l}</b> · ${Object.entries(m.kinds).map(([k, n]) => `${esc(n.toLowerCase())} ${c[k + "w"]}-${c[k + "l"]}`).join(" · ")}</p>
      <p>Points ${fmt({ d: 2 }, c.pf)} – ${fmt({ d: 2 }, c.pa)}</p>
      <table class="rk"><tbody>${(c.games || []).map(([y, w, n, pf, pa, won]) => `<tr class="go" data-go="game/${y}/${w}/${tslug(td.dataset.a)}"><td class="l"><a href="#/game/${y}/${w}/${tslug(td.dataset.a)}">${y} ${esc(n)}</a></td><td class="${won ? "w" : "lo"}">${won ? "W" : "L"}</td><td>${fmt({ d: 2 }, pf)}–${fmt({ d: 2 }, pa)}</td></tr>`).join("")}</tbody></table>`;
  };
  draw();
}

async function trades(id, query) {
  const [tr, meta, FULL] = await Promise.all([load("trades.json"), load("meta.json"), load("trades_full.json"), loadPickRows()]);
  for (const t of tr.trades) (FULL[t.id] || []).forEach((all, i) => { if (t.sides[i]) t.sides[i].all = all; });
  if (id) {
    const t = tr.trades.find((x) => String(x.id) === String(id));
    if (!t) throw new Error("No trade " + id);
    const M = tr.meta;
    const rows = M.all_cols.filter((c) => t.sides.some((s) => s.all && s.all[c] !== null && s.all[c] !== undefined));
    const cell = (c, v) => v === null || v === undefined ? "—" : typeof v === "string" ? v.split("; ").map(assetLink).join("; ") : fmt(M.fmt[c], v);
    $app.innerHTML = `<p><a href="#/trades">← All trades</a></p>${tradeCard(t, M, true)}
      <div class="card"><h2>Everything on the trades sheet</h2><div class="scroll"><table class="tall"><thead><tr><th class="l pin pin0">Stat</th>${t.sides.map((s) => `<th class="l">${teamLink(s.team)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((c) => { const d = defOf(c, "trades"); return `<tr><td class="l pin pin0"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(M.labels[c] || c)}"` : ""}>${esc(M.labels[c] || c)}${d ? ' <span class="defbtn">ⓘ</span>' : ""}</td>${t.sides.map((s) => `<td class="l">${cell(c, s.all && s.all[c])}</td>`).join("")}</tr>`; }).join("")}</tbody></table></div>
        <p class="muted small">One column per team in the deal. KTC value difference = value received minus value sent on KeepTradeCut (superflex); the FAAB $ figures are the same gap in the league's FAAB dollars.</p></div>`;
    pinColumns(document.querySelector(".tall").parentElement);
    return;
  }
  const params = new URLSearchParams(query || "");
  let team = params.get("team") || "", season = params.get("season") || "", q = "";
  let sort = params.get("sort") || "date", dir = params.get("dir") || "hi", limit = 60;
  const M = tr.meta;
  function draw() {
    let ts = tr.trades.filter((t) => (!team || t.sides.some((s) => s.team === team)) && (!season || String(t.season) === season)
      && (!q || t.sides.some((s) => s.got.concat(s.sent).some((a) => a.toLowerCase().includes(q)))));
    // a trade ranks by its best side for "highest", its worst side for "lowest"
    const key = (t) => { const v = t.sides.map((s) => s.all && s.all[sort]).filter((x) => typeof x === "number"); return v.length ? (dir === "hi" ? Math.max(...v) : Math.min(...v)) : null; };
    if (sort === "date") ts = dir === "hi" ? ts : ts.slice().reverse();
    else ts = ts.filter((t) => key(t) !== null).sort((a, b) => dir === "hi" ? key(b) - key(a) : key(a) - key(b));
    const shown = ts.slice(0, limit);
    document.getElementById("tl").innerHTML = `<p class="muted small">${ts.length} trades${sort !== "date" ? ` by ${esc(M.labels[sort] || sort)}, ${dir === "hi" ? "highest" : "lowest"} first (a trade ranks by its ${dir === "hi" ? "best" : "worst"} side)` : ""}</p>` +
      shown.map((t) => (sort !== "date" ? `<p class="small" style="margin:10px 0 2px"><b>${fmt(M.fmt[sort], key(t))}</b> <span class="muted">${esc(M.labels[sort] || sort)}</span></p>` : "") + tradeCard(t, M)).join("") +
      (ts.length > shown.length ? `<button class="b" id="tmore">Show more (${ts.length - shown.length} left)</button>` : "");
    const more = document.getElementById("tmore");
    if (more) more.onclick = () => { limit += 60; draw(); };
  }
  const seasons = [...new Set(tr.trades.map((t) => t.season))].sort().reverse();
  $app.innerHTML = `<h1>Trade history</h1>
    <div class="controls">
      <select id="ft"><option value="">All teams</option>${meta.teams.map((t) => `<option ${t === team ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <select id="fs"><option value="">All seasons</option>${seasons.map((s) => `<option ${String(s) === season ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <select id="fo" title="Order by"><option value="date">Date</option>${M.sortable.map((c) => `<option value="${esc(c)}" ${c === sort ? "selected" : ""}>${esc(M.labels[c] || c)}</option>`).join("")}</select>
      <span class="seg" style="margin:0"><button data-dir="hi" aria-pressed="${dir === "hi"}">Highest / newest</button><button data-dir="lo" aria-pressed="${dir === "lo"}">Lowest / oldest</button></span>
      <input class="f" id="fq" type="search" placeholder="Player or pick">
    </div>
    <p class="muted small">Order by any stat on the trades sheet. Each side shows the KTC value difference (received − sent) at the deal, at season end, 1 and 2 years later, and the same gap in FAAB dollars; the badge is the latest KTC one available. Tap a trade for everything the sheet has on it.</p>
    <div id="tl"></div>`;
  document.getElementById("ft").onchange = (e) => { team = e.target.value; draw(); };
  document.getElementById("fs").onchange = (e) => { season = e.target.value; draw(); };
  document.getElementById("fo").onchange = (e) => { sort = e.target.value; limit = 60; draw(); };
  $app.querySelectorAll("[data-dir]").forEach((b) => b.onclick = () => { dir = b.dataset.dir; limit = 60; $app.querySelectorAll("[data-dir]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("fq").oninput = (e) => { q = e.target.value.trim().toLowerCase(); draw(); };
  document.getElementById("tl").onclick = (e) => { if (e.target.closest("a") || e.target.closest("button")) return; const c = e.target.closest("[data-go]"); if (c) location.hash = "#/" + c.dataset.go; };
  draw();
}

async function draft() {
  const d = await load("draft.json");
  let which = "rookie", year = "";
  function draw() {
    const t = d[which];
    const yi = idx(t, "Year");
    const years = [...new Set(t.rows.map((r) => r[yi]))];
    const sel = document.getElementById("dy");
    if (!sel.dataset.w || sel.dataset.w !== which) {
      sel.dataset.w = which;
      sel.innerHTML = `<option value="">All years</option>` + years.map((y) => `<option>${esc(y)}</option>`).join("");
      year = "";
    }
    const rows = year ? t.rows.filter((r) => String(r[yi]) === year) : t.rows;
    const sheetName = which === "rookie" ? "rookie_picks" : "non_rookie_picks";
    document.getElementById("dt").innerHTML = dataTable({ ...t, rows }, { hide: ["_row"], pin: 3, defs: sheetName, links: { Number: (v, r, cols) => `<a href="#/pick/${sheetName}/${r[cols.indexOf("_row")]}">${esc(v)}</a>`, "Player Picked": (v) => playerLink(v), Team: (v) => teamLink(v), "Original Team": (v) => teamLink(v) } });
  }
  $app.innerHTML = `<h1>Draft history</h1>
    <div class="controls"><span class="seg" style="margin:0"><button data-w="rookie" aria-pressed="true">Rookie drafts</button>${d.startup ? `<button data-w="startup" aria-pressed="false">Startup &amp; vet picks</button>` : ""}</span>
      <select id="dy"></select></div>
    <div class="card"><div id="dt"></div><p class="muted small">Every column of the pick sheet; scroll sideways with the pick, player and team pinned, and tap a column name for its definition. Pick-adjusted columns compare the pick with what that draft slot usually returns. KTC values are KeepTradeCut superflex. 2.09 is the toilet-bowl reward pick.</p></div>`;
  $app.querySelectorAll("[data-w]").forEach((b) => b.onclick = () => { which = b.dataset.w; $app.querySelectorAll("[data-w]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("dy").onchange = (e) => { year = e.target.value; draw(); };
  draw();
}

async function search(q) {
  q = decodeURIComponent(q || "");
  const ix = await load("search.json");
  const ql = q.trim().toLowerCase();
  document.getElementById("q").value = q;
  const score = (n) => { const s = n.toLowerCase(); if (s === ql) return 0; if (s.startsWith(ql)) return 1; if (s.split(/\s+/).some((w) => w.startsWith(ql))) return 2; return s.includes(ql) ? 3 : 9; };
  const hits = ql ? ix.map((r) => [score(r[2]), r]).filter(([s]) => s < 9).sort((a, b) => a[0] - b[0] || (b[1][4] || 0) - (a[1][4] || 0)).slice(0, 60).map((x) => x[1]) : [];
  $app.innerHTML = `<h1>Search</h1>
    <div class="card"><ul class="res">${hits.map((r) => `<li><a href="#/${r[0] === "t" ? "team" : "player"}/${esc(r[1])}">${esc(r[2])}</a><span class="muted small">${esc(r[3])}</span></li>`).join("") || `<li class="muted">${ql ? "No players or teams match." : "Type a name."}</li>`}</ul></div>
    ${ql ? `<div class="card"><h2>Every row mentioning “${esc(q)}”</h2><p>${["player_week", "player_year", "team_week", "trades", "add_drops", "player_additions", "rookie_picks"].map((k) => `<a class="chip" href="#/data/${k}?q=${encodeURIComponent(q)}${k === "player_week" ? "&y=all" : ""}">${k}</a>`).join("")}</p></div>` : ""}
    ${ql ? `<div class="card"><h2>Stats named “${esc(q)}”</h2><p>${SHEETS.map(([k, n]) => `<a class="chip" href="#/records/${k}?q=${encodeURIComponent(q)}">${n}</a>`).join("")}</p></div>` : ""}`;
}

async function faab(_, query, live) {
  const [B, meta, PK] = await Promise.all([loadBoard(), load("meta.json"), load("picks.json")]);
  if (!B) { $app.innerHTML = `<h1>FAAB values</h1><p class="muted">The board is not published yet.</p>`; return; }
  const held = {};
  for (const [t, ps] of Object.entries(livePicks(PK, live))) held[t] = ps.map(([y, r, o]) => ({ y, r, o, v: pickValue(PK, B, y, r, o) }));
  const params = new URLSearchParams(query || "");
  let pos = params.get("pos") || "", owner = params.get("owner") || "", q = "";
  // owners: Sleeper's rosters right now when reachable, else the board's (its date)
  const rows = B.players.map((x) => ({ ...x, own: live ? (live.owner[x.sid] || null) : ownerTeam(x.owner, meta.teams) }));
  const totals = meta.teams.map((t) => {
    const mine = rows.filter((r) => r.own === t);
    const by = (p) => mine.filter((r) => r.pos === p).reduce((a, r) => a + r.value, 0);
    const picks = held[t] || [];
    const pv = picks.reduce((a, p) => a + p.v, 0), players = mine.reduce((a, r) => a + r.value, 0);
    return { t, total: players + pv, players, picks: pv, np: picks.length, firsts: picks.filter((p) => p.r === 1).length,
             n: mine.length, QB: by("QB"), RB: by("RB"), WR: by("WR"), TE: by("TE"), top: mine[0] };
  });
  const maxT = Math.max(...totals.map((x) => x.total), 1);
  const positions = [...new Set(rows.map((r) => r.pos))].filter(Boolean);
  function draw() {
    const ql = q.toLowerCase();
    let rs = rows.filter((r) => (!pos || r.pos === pos) && (!owner || (owner === "FA" ? !r.own : r.own === owner))
      && (!ql || r.name.toLowerCase().includes(ql)));
    // a team's board includes its future picks, valued on the same scale
    if (owner && owner !== "FA" && (!pos || pos === "PICK") && !ql) {
      rs = rs.concat((held[owner] || []).map((p) => ({ pick: true, name: `${p.y} ${ORD[p.r] || p.r + "th"}${p.o === owner ? "" : " (" + p.o + ")"}`, pos: "PICK", own: owner, value: p.v, rank: null })))
        .sort((a, b) => b.value - a.value);
    }
    const np = rs.filter((r) => r.pick).length;
    document.getElementById("fb").innerHTML = `<p class="muted small">${rs.length - np} players${np ? ` · ${np} picks` : ""}${owner && owner !== "FA" ? ` · ${esc(owner)}: ${money(rs.reduce((a, r) => a + (r.value || 0), 0))} in all` : ""}</p>` + table([
      { k: "rank", label: "#", html: (r) => r.rank ?? "" },
      { k: "name", label: "Player", left: true, html: (r) => r.pick ? `<span class="chip">${esc(r.name)}</span>` : playerLink(r.name) },
      { k: "pos", label: "Pos", left: true }, { k: "team", label: "NFL", left: true, html: (r) => r.pick ? "" : nflLink(r.team) },
      { k: "age", label: "Age", spec: { d: 1 } },
      { k: "own", label: "Owner", left: true, html: (r) => (r.own ? teamLink(r.own) : '<span class="muted">Free agent</span>') },
      { k: "injury", label: "Injury", left: true, html: (r) => (r.injury ? `<span class="chip live">${esc(r.injury)}</span>` : "") },
      { k: "value", label: "Value", html: (r) => `<b>${money(r.value)}</b>` },
      { k: (r) => r.value, label: "≈ rookie picks", left: true, html: (r) => `<span class="muted small">${esc(pickText(B, r.value).replace(/^about the /, ""))}</span>` },
    ], rs.slice(0, 400), { sort: 0, asc: true });
  }
  $app.innerHTML = `<h1>FAAB values</h1>
    <p class="muted">Board of ${esc(B.as_of)} · ${B.players.length} players · a work in progress, rebuilt every week</p>
    <div class="card"><p>The model prices every player in league FAAB (the house 100-dollar budget scale). It uses stats only: general rules fitted to this league's trades, cuts and calls, with no hand-set prices. The league's answers on the rating page show which rules fit. They are a capped signal and never move a player's value directly.</p>
      <p><a class="chip" style="font-size:14px;padding:6px 12px;background:var(--accent);color:var(--accent-ink)" href="rate/">Rate the board →</a> <span class="muted small">Pick which of two players is worth more and say whether each value looks right. It takes a minute.</span></p>
      <details><summary>Answer here without leaving this page</summary><iframe src="rate/" title="LOTG value check" loading="lazy" style="width:100%;height:1100px;border:1px solid var(--line);border-radius:12px;background:var(--bg)"></iframe></details></div>
    <div class="card" id="valuecard"><h2>Roster value by team ${liveNote(live)}</h2>${table([
      { k: "t", label: "Team", left: true, html: (r) => `<a href="#/team/${tslug(r.t)}">${esc(r.t)}</a> <button class="b mini" data-owner="${esc(r.t)}" title="Show this team's board">board ↓</button>` },
      { k: "total", label: "Total", html: (r) => `<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><b>${money(r.total)}</b><div class="bar-h" style="width:90px"><i style="width:${(100 * r.total) / maxT}%"></i></div></div>` },
      { k: "players", label: "Players", html: (r) => money(r.players) },
      { k: "picks", label: `Picks ${PK.years[0]}-${String(PK.years[PK.years.length - 1]).slice(2)}`, html: (r) => `${money(r.picks)} <span class="muted small">${r.np} · ${r.firsts} 1st${r.firsts === 1 ? "" : "s"}</span>` },
      { k: "QB", label: "QB", html: (r) => money(r.QB) }, { k: "RB", label: "RB", html: (r) => money(r.RB) },
      { k: "WR", label: "WR", html: (r) => money(r.WR) }, { k: "TE", label: "TE", html: (r) => money(r.TE) },
      { k: "n", label: "# players" },
      { k: "np", label: "# picks" },
      { k: (r) => r.top?.value, label: "Most valuable", left: true, html: (r) => (r.top ? `${playerLink(r.top.name)} ${money(r.top.value)}` : "—") },
    ], totals, { sort: 1 })}
      <p class="muted small">Total = rostered players' board values + every rookie pick held for the next ${PK.years.length} drafts (${PK.years[0]}–${PK.years[PK.years.length - 1]}, rounds 1–${PK.rounds}). Each pick is priced by the FAAB system's own rule: next year's picks by the original team's projected draft slot (roster strength blended with this season's record), so a likely top pick is worth more; later drafts at the round's average, on the system's weekly pick-price schedule. Pick ownership is the build's (trades, the commissioner's off-platform moves, Sleeper).</p></div>
    <div class="card"><h2>Picks held</h2>${table([
      { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
      ...PK.years.map((y) => ({ k: (r) => (held[r.t] || []).filter((p) => p.y === y).reduce((a, p) => a + p.v, 0), label: String(y), left: true,
        html: (r) => pickDots((held[r.t] || []).filter((p) => p.y === y), r.t) })),
      { k: "np", label: "Picks" },
      { k: "picks", label: "Value", html: (r) => money(r.picks) },
    ], totals, { sort: PK.years.length + 2 })}<p class="muted small">Each square is a pick, numbered by round: outlined = the team's own, filled = acquired (tap or hover for whose). Values are on the FAAB board's pick scale.</p></div>
    <div class="card" id="boardcard"><h2>Board</h2>
      <div class="controls">
        <select id="fp"><option value="">All positions</option>${positions.concat(["PICK"]).map((p) => `<option ${p === pos ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
        <select id="fo"><option value="">All owners</option><option value="FA" ${owner === "FA" ? "selected" : ""}>Free agents</option>${meta.teams.map((t) => `<option ${t === owner ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <input class="f" id="fq" type="search" placeholder="Player">
      </div><div id="fb"></div></div>
    <div class="card"><h2>Rookie pick values</h2><p>${(B.picks || []).map((p) => `<span class="chip">${esc(p.slot)} ${money(p.value)}</span>`).join("")}</p>
      <p class="muted small">What a rookie-draft slot is worth on the same scale.</p></div>`;
  document.getElementById("fp").onchange = (e) => { pos = e.target.value; draw(); };
  document.getElementById("fo").onchange = (e) => { owner = e.target.value; draw(); };
  // "board ↓" on a team: filter the board to that team and scroll down to it
  document.getElementById("valuecard").onclick = (e) => {
    const b = e.target.closest("[data-owner]");
    if (!b) return;
    owner = b.dataset.owner; pos = ""; q = "";
    document.getElementById("fo").value = owner; document.getElementById("fp").value = "";
    draw();
    document.getElementById("boardcard").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  document.getElementById("fq").oninput = (e) => { q = e.target.value.trim(); draw(); };
  draw();
}

// ---------- every export sheet, whole
const PAGE = 100;
const prefs = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } } };
const kb = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB");
const SHEET_NAMES = Object.fromEntries(SHEETS);
SHEET_NAMES.formulas = "Column definitions (formulas)";
SHEET_NAMES.league_all_time = "League all-time";
SHEET_NAMES.non_rookie_picks = "Startup & vet picks";
async function data(sheet, query) {
  const ix = await load("sheets/index.json");
  if (!sheet) {
    $app.innerHTML = `<h1>Data</h1>
      <p class="muted">Every sheet of the league's stats exports, every row and every column, to browse, filter, sort or download. The workbook's sheets, as CSV.</p>
      <div class="card"><h2>Find a record the boards don't keep</h2><p class="small">Pick a sheet, add a filter for each condition, then tap a column to sort. For example:</p>
        <ul class="small">
          <li><a href="#/data/player_week?y=all&c=Position&v=WR&c2=Win%3F&v2=no&c3=Starter%2FBench&v3=Starter&sort=Points">Most points by a WR starter in a loss</a></li>
          <li><a href="#/data/team_week?c=Win%3F&v=yes&sort=PF&dir=lo">Fewest points in a win</a></li>
          <li><a href="#/data/player_week?y=all&c=Rookie%3F&v=yes&c2=Starter%2FBench&v2=Starter&sort=Points">Best week by a rookie starter</a></li>
          <li><a href="#/data/team_week?c=Week%20Name&v=Final&sort=Margin">Biggest final win</a></li>
        </ul></div>
      <div class="grid">${ix.sheets.map((m) => `<div class="card"><h2><a href="#/data/${m.sheet}">${esc(SHEET_NAMES[m.sheet] || m.sheet)}</a></h2>
        <p class="muted small">${m.sheet}.csv · ${m.rows.toLocaleString()} rows · ${m.cols.length} columns${m.chunks.length > 1 ? ` · by ${esc(m.season_col)}` : ""}</p>
        <p><a href="#/data/${m.sheet}">Browse</a> · <a href="${m.csv}" download>Download CSV (${kb(m.csv_bytes)})</a></p></div>`).join("")}</div>`;
    return;
  }
  const m = ix.sheets.find((x) => x.sheet === sheet);
  if (!m) throw new Error("No sheet " + sheet);
  const params = new URLSearchParams(query || "");
  let chunk = params.get("y") || (m.chunks.length > 1 ? m.chunks[m.chunks.length - 1][1] : "all");
  let q = params.get("q") || "";
  // column filters, all must hold: c/o/v, c2/o2/v2, …
  let filters = [];
  for (let i = 1; i <= 8; i++) {
    const sfx = i === 1 ? "" : String(i);
    if (params.get("c" + sfx)) filters.push({ c: params.get("c" + sfx), o: params.get("o" + sfx) || "=", v: params.get("v" + sfx) || "" });
  }
  if (!filters.length) filters.push({ c: "", o: "=", v: "" });
  let sortBy = m.cols.indexOf(params.get("sort") || ""), asc = params.get("dir") === "lo", page = 0;
  const all = m.cols.map((_, i) => i);
  let shown = prefs.get("cols:" + sheet, null);
  if (!Array.isArray(shown) || shown.some((i) => i >= m.cols.length)) shown = m.cols.length <= 30 ? all : all.slice(0, 18);
  let rows = [];
  async function fetchRows() {
    const parts = chunk === "all" && m.chunks.length > 1 ? m.chunks.map((c) => c[1]) : [chunk];
    document.getElementById("dcount").textContent = "Loading…";
    const got = await Promise.all(parts.map((c) => load(`sheets/${sheet}/${c}.json`)));
    rows = [].concat(...got.map((g) => g.rows));
    rows.forEach((r, i) => { r._i = i; });    // the row's place in its sheet (a pick's page key)
    if (sheet === "trades" && !tradeIds) tradeIds = tradeIndex(await load("trades.json"));
  }
  let tradeIds = null;
  // yes/no cells match "yes", "true", "won" … the way people type them
  const asText = (x) => typeof x === "boolean" ? (x ? "true yes y won win" : "false no n lost loss") : String(x ?? "").toLowerCase();
  function passes(r, f) {
    const ci = m.cols.indexOf(f.c);
    if (ci < 0 || f.v === "") return true;
    const x = r[ci], want = f.v.toLowerCase().trim(), num = parseFloat(f.v);
    if (f.o === "=") return typeof x === "boolean" ? asText(x).split(" ").includes(want) : (typeof x === "number" && !isNaN(num) ? x === num : asText(x) === want);
    if (f.o === "!=") return !passes(r, { ...f, o: "=" });
    if (f.o === "~") return asText(x).includes(want);
    if (typeof x !== "number" || isNaN(num)) return false;
    return f.o === ">" ? x > num : f.o === "<" ? x < num : f.o === ">=" ? x >= num : x <= num;
  }
  function filtered() {
    const ql = q.trim().toLowerCase();
    return rows.filter((r) => (!ql || r.some((x) => x !== null && asText(x).includes(ql))) && filters.every((f) => passes(r, f)));
  }
  function draw() {
    let rs = filtered();
    if (sortBy >= 0) rs = rs.slice().sort((a, b) => {
      const x = a[sortBy], y = b[sortBy];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const d = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
      return asc ? d : -d;
    });
    const pages = Math.max(1, Math.ceil(rs.length / PAGE));
    page = Math.min(page, pages - 1);
    const slice = rs.slice(page * PAGE, page * PAGE + PAGE);
    const head = shown.map((i, k) => `<th data-i="${i}" class="l${sortBy === i ? " sorted" + (asc ? " asc" : "") : ""}${k === 0 ? " pin pin1" : ""}"${m.defs[m.cols[i]] ? ` data-def="${esc(m.defs[m.cols[i]])}" data-deflabel="${esc(m.labels[i])}"` : ""}>${esc(m.labels[i])}${m.defs[m.cols[i]] ? ' <span class="defbtn">ⓘ</span>' : ""}</th>`).join("");
    const cell = (i, v, k) => {
      const c = m.cols[i], pin = k === 0 ? " pin pin1" : "";
      if (v === null || v === undefined) return `<td class="muted${pin}">—</td>`;
      if (typeof v === "string") {
        if (["Team", "Top team", "Top Team", "Last team", "Opponent", "Original Team"].includes(c) || c.startsWith("Team's traded with")) return `<td class="l${pin}">${teamLink(v)}</td>`;
        if (["Player", "Player Picked", "Player Added", "Player Dropped"].includes(c)) return `<td class="l${pin}">${playerLink(v)}</td>`;
        if (c === "NFL team") return `<td class="l${pin}">${nflLink(v)}</td>`;
        return `<td class="l${pin}">${esc(v)}</td>`;
      }
      return `<td class="${pin}">${fmt(m.fmt[c], v)}</td>`;
    };
    const go = (r) => { const l = rowLink(sheet, m.cols, r, tradeIds); return l ? `<td class="pin pin0"><a href="#/${l}" title="Details">›</a></td>` : `<td class="pin pin0"></td>`; };
    document.getElementById("dt").innerHTML = `<table><thead><tr><th class="pin pin0"></th>${head}</tr></thead><tbody>${slice.map((r) => `<tr>${go(r)}${shown.map((i, k) => cell(i, r[i], k)).join("")}</tr>`).join("")}</tbody></table>`;
    pinColumns(document.getElementById("dt"));
    document.getElementById("dcount").textContent = `${rs.length.toLocaleString()} of ${rows.length.toLocaleString()} rows · ${shown.length} of ${m.cols.length} columns`;
    document.getElementById("dpg").innerHTML = pages > 1 ? `<button data-p="-1" ${page === 0 ? "disabled" : ""}>‹ Prev</button> <span class="muted small">page ${page + 1} of ${pages}</span> <button data-p="1" ${page >= pages - 1 ? "disabled" : ""}>Next ›</button>` : "";
  }
  const colPicker = () => m.cols.map((c, i) => `<label style="display:inline-flex;gap:4px;margin:0 10px 4px 0;font-size:13px"><input type="checkbox" data-c="${i}" ${shown.includes(i) ? "checked" : ""}>${esc(m.labels[i])}</label>`).join("");
  $app.innerHTML = `<p class="small"><a href="#/data">← All sheets</a></p>
    <h1>${esc(SHEET_NAMES[sheet] || sheet)}</h1>
    <p class="muted small">${sheet}.csv · ${m.rows.toLocaleString()} rows · ${m.cols.length} columns · <a href="${m.csv}" download>Download CSV (${kb(m.csv_bytes)})</a></p>
    <div class="controls">
      ${m.chunks.length > 1 ? `<select id="dy">${m.chunks.map(([n, s, k]) => `<option value="${s}" ${s === chunk ? "selected" : ""}>${esc(m.season_col)} ${esc(n)} (${k.toLocaleString()} rows)</option>`).join("")}<option value="all" ${chunk === "all" ? "selected" : ""}>All (${m.rows.toLocaleString()} rows, slower)</option></select>` : ""}
      <input class="f" id="dq" type="search" placeholder="Search every cell" value="${esc(q)}">
    </div>
    <div id="filters"></div>
    <details><summary>Columns (${m.cols.length})</summary>
      <p><span class="seg" style="margin:0"><button id="call">All</button><button id="cnone">None</button><button id="cdef">Default</button></span></p>
      <div id="cp">${colPicker()}</div></details>
    <details><summary>What each column means</summary><input class="f" id="gq" type="search" placeholder="Filter definitions" style="width:100%;margin-bottom:8px"><div id="gl"></div></details>
    <p class="muted small" id="dcount"></p>
    <div class="card"><div class="scroll" id="dt"></div><div class="seg" id="dpg" style="margin-top:10px"></div>
      <p class="muted small">Numbers show the workbook's decimal places. Team PF includes the semifinal +5; player points do not. Tap a column header to sort; ⓘ = has a definition (hover, or see "What each column means").</p></div>`;
  const glossary = (ql) => m.cols.map((c, i) => [m.labels[i], m.defs[c]]).filter(([l, d]) => !ql || (l + " " + (d || "")).toLowerCase().includes(ql))
    .map(([l, d]) => `<p class="small"><b>${esc(l)}</b> — ${d ? esc(d) : '<span class="muted">no definition in formulas.csv</span>'}</p>`).join("");
  document.getElementById("gl").innerHTML = glossary("");
  document.getElementById("gq").oninput = (e) => (document.getElementById("gl").innerHTML = glossary(e.target.value.trim().toLowerCase()));
  const setShown = (s) => { shown = s; prefs.set("cols:" + sheet, shown); document.getElementById("cp").innerHTML = colPicker(); draw(); };
  document.getElementById("cp").onchange = (e) => { const i = +e.target.dataset.c; setShown(e.target.checked ? [...shown, i].sort((a, b) => a - b) : shown.filter((x) => x !== i)); };
  document.getElementById("call").onclick = () => setShown(all);
  document.getElementById("cnone").onclick = () => setShown([0]);
  document.getElementById("cdef").onclick = () => setShown(m.cols.length <= 30 ? all : all.slice(0, 18));
  document.getElementById("dt").onclick = (e) => { if (e.target.closest(".defbtn")) return; const th = e.target.closest("th"); if (!th || th.dataset.i === undefined) return; const i = +th.dataset.i; if (sortBy === i) asc = !asc; else { sortBy = i; asc = false; } draw(); };
  document.getElementById("dpg").onclick = (e) => { const b = e.target.closest("button[data-p]"); if (!b) return; page += +b.dataset.p; draw(); document.getElementById("dcount").scrollIntoView(); };
  let deb;
  document.getElementById("dq").oninput = (e) => { clearTimeout(deb); deb = setTimeout(() => { q = e.target.value; page = 0; draw(); }, 200); };
  const OPS = { "=": "is", "!=": "is not", "~": "contains", ">": ">", ">=": "≥", "<": "<", "<=": "≤" };
  function drawFilters() {
    document.getElementById("filters").innerHTML = filters.map((f, i) => `<div class="controls frow" data-i="${i}">
      <select data-k="c"><option value="">${i ? "and a column…" : "Filter a column…"}</option>${m.cols.map((c, j) => `<option value="${esc(c)}" ${c === f.c ? "selected" : ""}>${esc(m.labels[j])}</option>`).join("")}</select>
      <select data-k="o">${Object.entries(OPS).map(([o, n]) => `<option value="${o}" ${o === f.o ? "selected" : ""}>${n}</option>`).join("")}</select>
      <input class="f" data-k="v" placeholder="value (yes / no for ✓ columns)" value="${esc(f.v)}">
      ${filters.length > 1 ? `<button class="b" data-x="${i}" title="Remove">×</button>` : ""}</div>`).join("") +
      `<button class="b" id="fadd">+ Add a filter</button>`;
  }
  const fl = document.getElementById("filters");
  fl.onchange = (e) => { const row = e.target.closest(".frow"); if (!row || !e.target.dataset.k) return; filters[+row.dataset.i][e.target.dataset.k] = e.target.value; const ci = m.cols.indexOf(filters[+row.dataset.i].c); if (ci >= 0 && !shown.includes(ci)) shown = [...shown, ci].sort((a, b) => a - b); page = 0; draw(); };
  fl.oninput = (e) => { if (e.target.dataset.k !== "v") return; const row = e.target.closest(".frow"); clearTimeout(deb); deb = setTimeout(() => { filters[+row.dataset.i].v = e.target.value; page = 0; draw(); }, 200); };
  fl.onclick = (e) => {
    if (e.target.id === "fadd") { filters.push({ c: "", o: "=", v: "" }); drawFilters(); }
    if (e.target.dataset.x) { filters.splice(+e.target.dataset.x, 1); drawFilters(); page = 0; draw(); }
  };
  drawFilters();
  if (document.getElementById("dy")) document.getElementById("dy").onchange = async (e) => { chunk = e.target.value; page = 0; await fetchRows(); draw(); };
  // columns a filter uses are shown
  // the columns a link sorts or filters by come right after the first one, so the answer is in view
  const front = [sortBy, ...filters.map((f) => m.cols.indexOf(f.c))].filter((ci) => ci > 0);
  if (front.length) shown = [shown[0], ...front, ...shown.slice(1).filter((ci) => !front.includes(ci))];
  await fetchRows();
  draw();
}

// ---------- details: where a row lives, matchups, weeks, picks
const weekNo = (name) => { const m = /^Week (\d+)$/.exec(String(name)); return m ? m[1] : name; };
function tradeIndex(tr) {
  const out = {};
  for (const t of tr.trades) for (const s of t.sides) out[`${t.date}|${s.team}`] = t.id;
  return out;
}
// the route that shows a Data-page row in full (mirrors Site.row_link)
function rowLink(sheet, cols, r, tradeIds) {
  const v = (c) => { const i = cols.indexOf(c); return i < 0 ? null : r[i]; };
  if (sheet === "trades" && tradeIds) { const id = tradeIds[`${String(v("Date") || "").slice(0, 10)}|${v("Team")}`]; return id ? `trades/${id}` : null; }
  if (sheet === "team_week" && v("Year") != null && v("Week") != null) return `game/${v("Year")}/${v("Week")}/${tslug(v("Team"))}`;
  if (sheet === "league_week" && v("Year") != null && v("Week") != null) return `week/${v("Year")}/${v("Week")}`;
  if (sheet === "rookie_picks" || sheet === "non_rookie_picks") return `pick/${sheet}/${r._i}`;
  if (sheet === "team_week" || sheet === "player_week") { /* fall through to the player / team */ }
  const name = v("Player") || v("Player Added") || v("Player Dropped") || v("Player Picked");
  if (name && NAMES[name]) return `player/${NAMES[name]}`;
  if (v("Team")) return `team/${tslug(v("Team"))}`;
  return null;
}
function historyList(lines) {
  return `<ol class="hist">${lines.map(([t, link]) => `<li>${link ? `<a href="#/${esc(link)}">${esc(t)}</a>` : esc(t)}</li>`).join("")}</ol>`;
}

const award = (a) => `<span class="chip award">${esc(a)}</span>`;
function lineup(team, side) {
  const rows = (s) => side.players.filter((p) => p[5] === s);
  const line = (p) => `<tr><td class="l muted small">${esc(p[3] || p[2] || "")}</td><td class="l">${p[1] ? `<a href="#/player/${esc(p[1])}">${esc(p[0])}</a>` : esc(p[0])} <span class="muted small">${esc(p[2] || "")} ${nflLink(p[6])}</span>${(p[7] || []).map(award).join("")}</td><td>${fmt({ d: 2 }, p[4])}</td></tr>`;
  return `<div class="card"><h2>${teamLink(team)} <span class="${side.win ? "w" : "lo"}">${fmt({ d: 2 }, side.pf)}</span></h2>
    ${(side.awards || []).length ? `<p>${side.awards.map(award).join("")}</p>` : ""}
    <p class="muted small">${side.win ? "Won" : "Lost"} vs ${teamLink(side.opp)} · max possible ${fmt({ d: 2 }, side.max)}</p>
    <table class="rk"><tbody>${rows(true).map(line).join("")}</tbody></table>
    <details><summary class="small muted">Bench (${rows(false).length})</summary><table class="rk"><tbody>${rows(false).map(line).join("")}</tbody></table></details></div>`;
}

async function game(rest) {
  const [y, w, team] = String(rest || "").split("/");
  const wk = await load(`week/${y}-${w}.json`);
  const name = Object.keys(wk.teams).find((t) => tslug(t) === team) || Object.keys(wk.teams)[0];
  const me = wk.teams[name], opp = wk.teams[me.opp];
  $app.innerHTML = `<p class="small"><a href="#/week/${y}/${w}">← All ${esc(wk.week_name)} ${y} matchups</a></p>
    <h1>${esc(name)} vs ${esc(me.opp)}</h1><p class="muted">${y} ${esc(wk.week_name)} · team PF includes the semifinal +5; player points do not</p>
    <div class="grid">${lineup(name, me)}${opp ? lineup(me.opp, opp) : ""}</div>
    <p class="small">More: <a href="#/data/team_week?c=Team&v=${encodeURIComponent(name)}">${esc(name)}'s every week</a> · <a href="#/data/player_week?c=Year&v=${y}&y=${y}">${y} player weeks</a></p>`;
}

async function week(rest) {
  const [y, w] = String(rest || "").split("/");
  const wk = await load(`week/${y}-${w}.json`);
  const seen = new Set(), games = [];
  for (const [t, s] of Object.entries(wk.teams)) {
    if (seen.has(t)) continue;
    seen.add(t); seen.add(s.opp);
    games.push([t, s, s.opp, wk.teams[s.opp]]);
  }
  $app.innerHTML = `<h1>${y} ${esc(wk.week_name)}</h1>
    <div class="games">${games.map(([a, sa, b, sb]) => `<div class="game" onclick="location.hash='#/game/${y}/${w}/${tslug(a)}'" style="cursor:pointer">
      <div><span class="${sa.win ? "w" : ""}">${esc(a)}</span><span>${fmt({ d: 2 }, sa.pf)}</span></div>
      <div><span class="${sb && sb.win ? "w" : ""}">${esc(b)}</span><span>${fmt({ d: 2 }, sb && sb.pf)}</span></div></div>`).join("")}</div>
    <p class="small muted">Tap a matchup for both lineups.</p>`;
}

async function pick(rest) {
  const [sheet, row] = String(rest || "").split("/");
  const [d, hist] = await Promise.all([load("draft.json"), load("pick_history.json")]);
  const t = d[sheet === "rookie_picks" ? "rookie" : "startup"];
  const ri = t.cols.indexOf("_row");
  const r = t.rows.find((x) => String(x[ri]) === String(row));
  if (!r) throw new Error("No such pick");
  const v = (c) => r[t.cols.indexOf(c)];
  const lines = (hist[sheet] || {})[row];
  const tiles = t.cols.map((c, i) => [c, t.labels[i], i]).filter(([c, , i]) => !["_row", "Year", "Number", "Player Picked", "Team", "Original Team"].includes(c) && r[i] !== null)
    .map(([c, l, i]) => `<div class="tile"><b>${fmt(t.fmt[c], r[i])}</b><span>${esc(l)}</span></div>`).join("");
  $app.innerHTML = `<p class="small"><a href="#/draft">← Draft history</a></p>
    <h1>${esc(v("Year"))} pick ${esc(v("Number"))}</h1>
    <p class="muted">${v("Player Picked") ? playerLink(v("Player Picked")) + " · " : ""}made by ${teamLink(v("Team"))}${v("Original Team") && v("Original Team") !== v("Team") ? ` · originally ${teamLink(v("Original Team"))}'s pick` : ""}</p>
    <div class="tiles">${tiles}</div>
    <div class="card"><h2>History</h2>${lines ? historyList(lines) : `<p class="muted">${hist.has_workbook ? "No history note for this pick." : "The history notes come from the weekly build's workbook and appear after the next deploy."}</p>`}</div>`;
}

// ---------- an NFL team: its depth chart, the league's view of its players
async function nfl(code, _q, live) {
  code = String(code || "").toUpperCase();
  const [N, B, meta, SP, LW] = await Promise.all([loadNfl(), loadBoard(), load("meta.json"), load("season_players.json"), load("live_watch.json").catch(() => ({ rates: {}, kickoffs: {} }))]);
  const value = Object.fromEntries((B ? B.players : []).map((x) => [x.sid, x.value]));
  const players = Object.entries(N).filter(([, v]) => v[2] === code).map(([pid, v]) => ({
    pid, name: v[0], pos: v[1], age: v[3], inj: v[4], depth: v[5], dpos: v[6] || v[1],
    own: live ? live.owner[pid] || null : null, value: value[pid] ?? null, proj: LW.rates[pid] ?? null, s: SP.rows[pid] || null }));
  const kos = Object.entries(LW.kickoffs || {}).map(([w, m]) => [+w, m[code]]).filter(([, k]) => k).sort((a, b) => a[0] - b[0]);
  const nowET = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const next = kos.find(([, k]) => new Date(k) > new Date(nowET - 4 * 36e5));
  const nameCell = (r) => `${NAMES_BY_ID[r.pid] ? `<a href="#/player/${esc(r.pid)}">${esc(r.name)}</a>` : esc(r.name)}${r.inj ? ` <span class="chip live">${esc(r.inj)}</span>` : ""}`;
  const owner = (r) => r.own ? teamLink(r.own) : (live ? '<span class="muted">FA</span>' : "—");
  const depth = ["QB", "RB", "WR", "TE"].map((pos) => {
    // grouped by the player's position (Sleeper charts receivers as LWR / RWR / SWR), ordered by depth
    const ps = players.filter((r) => r.pos === pos).sort((a, b) => (a.depth ?? 99) - (b.depth ?? 99) || (b.value ?? 0) - (a.value ?? 0) || (b.proj ?? 0) - (a.proj ?? 0));
    return `<div class="depth"><h3>${pos}</h3>${ps.length ? `<ol>${ps.slice(0, pos === "WR" ? 7 : 6).map((r) => `<li>${nameCell(r)}${r.dpos && r.dpos !== pos ? ` <span class="muted small">${esc(r.dpos)}</span>` : ""} <span class="muted small">${owner(r)}${r.value != null ? " · " + money(r.value) : ""}</span></li>`).join("")}</ol>` : '<p class="muted small">—</p>'}</div>`;
  }).join("");
  const SPc = SP.cols;
  const rows = players.filter((r) => r.own || NAMES_BY_ID[r.pid] || r.value || r.s);
  $app.innerHTML = `<h1>${esc(code)}</h1>
    <p class="muted">${next ? `Next kickoff: week ${next[0]}, ${esc(new Date(next[1]).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))} ET · ` : ""}owners ${liveNote(live)}</p>
    <div class="card"><h2>Depth chart</h2><div class="depthgrid">${depth}</div>
      <p class="muted small">NFL depth chart order from Sleeper's player list (as of the last build); each player's league owner and FAAB value.</p></div>
    <div class="card"><h2>${esc(code)} players and the league</h2>${table([
      { k: "name", label: "Player", left: true, html: nameCell },
      { k: "pos", label: "Pos", left: true }, { k: "age", label: "Age", spec: { d: 2 } },
      { k: "own", label: "Owner", left: true, html: owner },
      { k: "value", label: "FAAB value", html: (r) => r.value == null ? "—" : money(r.value) },
      { k: "proj", label: "Proj./wk", spec: { d: 2 } },
      ...SPc.map((c, i) => ({ k: (r) => r.s ? r.s[i] : null, label: SP.labels[i], spec: SP.fmt[c], col: c })),
    ], rows, { sort: 4, defs: "player_year" })}
      <p class="muted small">${SP.season} stats are the league's (this season, while rostered). Proj./wk = the forecast's rate blended with this season's PPG. Every ${esc(code)} player-week: <a href="#/data/player_week?c=NFL%20team&v=${esc(code)}&y=all">data →</a></p></div>`;
}

// ---------- predictions: set results and roster moves, see the season odds move
// Each team's week is its best lineup from its roster's projections (forecast rate
// blended with this season's PPG), with a spread from its starters. Who can play in
// Every hurt, tagged or ESPN-listed startable player and what the odds assume for
// him (home.json forecast.injuries: [ESPN's timeline, the forecast's basis];
// lotg_support.forecast FieldedDistribution.basis), grouped by team.
function espnCard(F, nfl, live) {
  const E = (F && F.injuries) || {};
  const ids = Object.keys(E);
  if (!ids.length) return "";
  const teamOf = {};
  for (const [t, r] of Object.entries(live.rosterOf || {})) for (const pid of (r.players || [])) teamOf[pid] = t;
  const rows = ids.map((pid) => [teamOf[pid] || "", (nfl[pid] || [])[0] || pid, E[pid][0] || "not listed", E[pid][1]])
    .sort((a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]));
  return `<div class="card"><details><summary><b>Injuries and what the odds assume</b> <span class="muted small">(${ids.length} player${ids.length === 1 ? "" : "s"}${F.espn_at ? "; ESPN captured " + esc(F.espn_at.slice(0, 16).replace("T", " ")) + " UTC" : ""})</span></summary>
    <p class="muted small">ESPN column: ESPN's injury list (an estimated earliest return week, or out for the season when ESPN and the reporting say so). Assumed: what the odds use. A sourced research note wins over ESPN; IR players cannot return before the NFL minimum. ESPN's dates have not been checked against past seasons yet. Taxi-squad players are left out (they cannot start).</p>
    <table><thead><tr><th>Team</th><th>Player</th><th>ESPN</th><th>Assumed</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td>${esc(r[2])}</td><td>${esc(r[3])}</td></tr>`).join("")}</tbody></table></details></div>`;
}

// each week comes from the forecast's injury model (home.json forecast.avail: P(he
// plays) per player per remaining week: Out players back on the league's return
// curve, IR players not before the NFL minimum, a dated "out for the season" note
// honoured), drawn a few dozen times per team-week so depth counts. Without it
// (an older home.json, or a player the forecast did not price) a player who is out,
// on IR or in the reserve slot is left out for the rest of the season, as before. The week in progress counts live points plus what is left. The
// season then runs through the league's rules: standings by wins (ties half) then PF,
// top 4 to the playoffs, 1v4 / 2v3 with +5 to the higher seed, the final over its
// weeks (two from 2026, summed). Everything runs in the browser.
async function predict(_a, _q, live) {
  const [meta, LW, nfl, H] = await Promise.all([load("meta.json"), load("live_watch.json"), loadNfl(), load("home.json")]);
  live = live || await loadLive();
  if (!live) { $app.innerHTML = `<h1>Predictions</h1><p class="muted">Needs Sleeper's rosters and schedule, and Sleeper is unreachable right now.</p>`; return; }
  // the season's calendar (live_watch.json); the 2026 layout if an older file lacks it
  const P = LW.playoff || { teams: 4, regular_weeks: 14, semifinal_week: 15, final_weeks: [16, 17], semifinal_bonus: 5 }, teams = meta.teams;
  const state = await fetch("https://api.sleeper.app/v1/state/nfl", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ week: meta.week + 1 }));
  const curWk = Math.max(meta.week + 1, +state.week || 0);
  const weeks = [];
  for (let w = meta.week + 1; w <= P.regular_weeks; w++) weeks.push(w);
  const mus = await Promise.all(weeks.map((w) => fetch(`https://api.sleeper.app/v1/league/${meta.league_id}/matchups/${w}`, { cache: "no-store" }).then((r) => r.json()).catch(() => [])));
  const games = [];   // {w, a, b, live: {a: {cur, rem, sd}, b: …}}
  weeks.forEach((w, i) => {
    const by = {};
    for (const m of mus[i]) if (m.matchup_id) (by[m.matchup_id] = by[m.matchup_id] || []).push(m);
    for (const pair of Object.values(by)) if (pair.length === 2) games.push({ w, a: live.byRid[pair[0].roster_id], b: live.byRid[pair[1].roster_id], ms: pair });
  });
  const base0 = Object.fromEntries(H.standings.map((r) => [r.team, { w: r.w, l: r.l, pf: r.pf }]));
  const out = (pid, team) => { const lr = live.rosterOf[team] || {}; const inj = (nfl[pid] || [])[4]; return (lr.ir && lr.ir.has(pid)) || ["IR", "Out", "PUP", "Sus", "NA", "DNR", "COV"].includes(inj); };
  // P(pid plays in week w), from the forecast; the old all-or-nothing rule as a fallback
  const AV = (H.forecast && H.forecast.avail) || null, AV0 = (H.forecast && H.forecast.avail_from) || 0;
  const pAvail = (pid, team, w) => {
    const a = AV && AV[pid];
    if (!a || !a.length) return out(pid, team) ? 0 : 1;
    return a[Math.min(Math.max(w - AV0, 0), a.length - 1)];
  };
  const fits = { QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"], FLEX: ["RB", "WR", "TE"], SUPER_FLEX: ["QB", "RB", "WR", "TE"] };
  const lineup = (pids) => {        // best lineup by projection: {mean, sd}
    const pool = pids.map((pid) => ({ pid, pos: (nfl[pid] || [])[1], r: LW.rates[pid] ?? 3 })).sort((x, y) => y.r - x.r), used = new Set();
    let mean = 0, v = 0;
    for (const sl of LW.roster_positions.slice().sort((a, b) => (fits[a] || []).length - (fits[b] || []).length)) {
      const i = pool.findIndex((x, j) => !used.has(j) && (fits[sl] || []).includes(x.pos));
      if (i >= 0) { used.add(i); mean += pool[i].r; v += (0.65 * Math.max(3, pool[i].r)) ** 2; }
    }
    return { mean, sd: Math.sqrt(v) };
  };
  // state the user changes
  let picks = {};           // game index -> "a" | "b"
  let moves = [];           // {pid, to: team | "out"}
  const baseRosters = () => Object.fromEntries(teams.map((t) => [t, (live.rosterOf[t]?.players || []).filter((pid) => AV || !out(pid, t))]));
  const rosterNow = () => {
    const r = baseRosters();
    for (const m of moves) { for (const t of teams) r[t] = r[t].filter((x) => x !== m.pid); if (m.to !== "out") r[m.to].push(m.pid); }
    return r;
  };
  const N = 4000;
  // a seeded stream, restarted for every run, so a change is compared against the same
  // simulated seasons (no noise in the +/−): mulberry32
  let seed = 0;
  const rand = () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const gauss = () => { let u = 0, v = 0; while (!u) u = rand(); while (!v) v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  // a team-week's points when some players may sit: K availability draws, each
  // refilled by the best remaining lineup; its own seeded stream per team and week,
  // so a roster move elsewhere does not shift these draws (or the season draws)
  const K = 32;
  const simWeeks = [...new Set([...weeks, P.semifinal_week, ...P.final_weeks])];
  const lineupAt = (pids, t, w) => {
    const ps = pids.map((pid) => pAvail(pid, t, w));
    if (ps.every((x) => x >= 0.999)) return lineup(pids);
    let h = 2166136261; for (const ch of `${t}|${w}`) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    let s2 = h | 0;
    const r2 = () => { s2 = (s2 + 0x6D2B79F5) | 0; let x = Math.imul(s2 ^ (s2 >>> 15), 1 | s2); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
    let m = 0, m2 = 0, v = 0;
    for (let k = 0; k < K; k++) {
      const x = lineup(pids.filter((_, j) => r2() < ps[j]));
      m += x.mean; m2 += x.mean * x.mean; v += x.sd * x.sd;
    }
    m /= K;
    return { mean: m, sd: Math.sqrt(v / K + Math.max(0, m2 / K - m * m)) };
  };
  const teamWeeks = (pids, t) => {
    const wk = Object.fromEntries(simWeeks.map((w) => [w, lineupAt(pids, t, w)]));
    const reg = weeks.filter((w) => w !== curWk);
    const mean = (reg.length ? reg : simWeeks).reduce((a, w) => a + wk[w].mean, 0) / (reg.length || simWeeks.length);
    return { wk, mean };
  };
  function simulate(withChanges) {
    seed = 20261114;
    const R = withChanges ? rosterNow() : baseRosters();
    const L = Object.fromEntries(teams.map((t) => [t, teamWeeks(R[t], t)]));
    const nowET = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
    // the week in progress: live points plus what each starter has left
    const liveWeek = {};
    for (const g of games) if (g.w === curWk) for (const m of g.ms) {
      const t = live.byRid[m.roster_id], ko = LW.kickoffs[String(g.w)] || {};
      let rem = 0, v = 0;
      for (const pid of m.starters || []) {
        const k = ko[(nfl[pid] || [])[2]]; if (!k || out(pid, t)) continue;
        const h = (nowET - new Date(k)) / 36e5, f = h < 0 ? 1 : Math.max(0, 1 - h / 3.3), r = LW.rates[pid] ?? 3;
        rem += r * f; v += (0.65 * Math.max(3, r)) ** 2 * f;
      }
      if ((m.points || 0) > 0) liveWeek[t] = { mean: (m.points || 0) + rem, sd: Math.sqrt(v) };
    }
    const tally = Object.fromEntries(teams.map((t) => [t, { playoffs: 0, final: 0, title: 0, wins: 0, seed1: 0 }]));
    const score = (t, w) => { const x = (w === curWk && liveWeek[t]) || L[t].wk[w] || lineup(R[t]); return x.mean + gauss() * x.sd; };
    for (let n = 0; n < N; n++) {
      const st = Object.fromEntries(teams.map((t) => [t, { w: (base0[t] || {}).w || 0, pf: (base0[t] || {}).pf || 0 }]));
      games.forEach((g, i) => {
        let sa = score(g.a, g.w), sb = score(g.b, g.w);
        const forced = withChanges && picks[i];
        if (forced === "a" && sa < sb) [sa, sb] = [sb, sa];
        if (forced === "b" && sb < sa) [sa, sb] = [sb, sa];
        st[g.a].pf += sa; st[g.b].pf += sb;
        if (sa > sb) st[g.a].w++; else st[g.b].w++;
      });
      const order = teams.slice().sort((x, y) => st[y].w - st[x].w || st[y].pf - st[x].pf);
      for (const t of teams) tally[t].wins += st[t].w;
      const seeds = order.slice(0, P.teams);
      seeds.forEach((t) => tally[t].playoffs++);
      tally[seeds[0]].seed1++;
      const semi = (hi, lo) => (score(hi, P.semifinal_week) + P.semifinal_bonus > score(lo, P.semifinal_week) ? hi : lo);
      const f1 = semi(seeds[0], seeds[3]), f2 = semi(seeds[1], seeds[2]);
      tally[f1].final++; tally[f2].final++;
      const tot = (t) => P.final_weeks.reduce((a, w) => a + score(t, w), 0);
      tally[tot(f1) >= tot(f2) ? f1 : f2].title++;
    }
    return { tally, L };
  }
  let base = null;
  // clinched / out with the picked games counted as played
  const status = () => {
    const w = Object.fromEntries(teams.map((t) => [t, (base0[t] || {}).w || 0])), left = Object.fromEntries(teams.map((t) => [t, 0]));
    games.forEach((g, i) => { const p = picks[i]; if (p) w[p === "a" ? g.a : g.b]++; else { left[g.a]++; left[g.b]++; } });
    return clinchStatus(w, left, P.teams);
  };
  const delta = (a, b) => { const d = Math.round((a - b) * 100); return d ? `<span class="${d > 0 ? "pos" : "neg"} small">${d > 0 ? "+" : ""}${d}</span>` : ""; };
  // the same, in the column's own units (wins, points), to one decimal
  const delta1 = (a, b) => { const d = Math.round((a - b) * 10) / 10; return d ? `<span class="${d > 0 ? "pos" : "neg"} small">${d > 0 ? "+" : ""}${d.toFixed(1)}</span>` : ""; };
  function draw() {
    const res = simulate(true);
    const T = res.tally;
    const rows = teams.map((t) => ({ t, ...T[t], mean: res.L[t].mean, base: base.tally[t], baseMean: base.L[t].mean })).sort((a, b) => b.title - a.title || b.playoffs - a.playoffs);
    const ST = status();
    const pct = (x, t, cap) => oddsText(x, !cap && ST.sure.has(t), ST.out.has(t), false);
    document.getElementById("pres").innerHTML = table([
      { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
      { k: "playoffs", label: "Playoffs", html: (r) => `<b>${pct(r.playoffs / N, r.t)}</b>${ST.sure.has(r.t) ? ' <span class="chip">clinched</span>' : ST.out.has(r.t) ? ' <span class="chip">out</span>' : ""} ${delta(r.playoffs / N, r.base.playoffs / N)}` },
      { k: "final", label: "Final", html: (r) => `${pct(r.final / N, r.t, true)} ${delta(r.final / N, r.base.final / N)}` },
      { k: "title", label: "Title", html: (r) => `<b>${pct(r.title / N, r.t, true)}</b> ${delta(r.title / N, r.base.title / N)}` },
      { k: (r) => (base0[r.t] || {}).w, label: "Now", html: (r) => `${(base0[r.t] || {}).w || 0}-${(base0[r.t] || {}).l || 0}` },
      { k: "wins", label: "Proj. wins", html: (r) => `${fmt({ d: 1 }, r.wins / N)} ${delta1(r.wins / N, r.base.wins / N)}` },
      { k: "seed1", label: "1st seed", html: (r) => `${pct(r.seed1 / N, r.t, true)} ${delta(r.seed1 / N, r.base.seed1 / N)}` },
      { k: "mean", label: "Pts/wk", html: (r) => `${fmt({ d: 1 }, r.mean)} ${delta1(r.mean, r.baseMean)}` },
    ], rows);
    document.getElementById("pmoves").innerHTML = moves.length ? `<ul class="small">${moves.map((m, i) => `<li>${esc((nfl[m.pid] || [])[0] || m.pid)} → ${m.to === "out" ? "out for the season" : esc(m.to)} <button class="b mini" data-undo="${i}">undo</button></li>`).join("")}</ul>` : `<p class="muted small">No roster changes.</p>`;
    const changed = Object.keys(picks).length + moves.length;
    document.getElementById("pstate").textContent = changed ? `${changed} change${changed === 1 ? "" : "s"} · small +/− = change vs no changes (percentage points for odds; wins and points for those columns)` : "No changes yet: these are the baseline odds.";
  }
  const byWeek = weeks.map((w) => [w, games.map((g, i) => [g, i]).filter(([g]) => g.w === w)]);
  const allPlayers = teams.flatMap((t) => (live.rosterOf[t]?.players || []).map((pid) => [pid, t])).filter(([pid]) => (nfl[pid] || [])[1])
    .sort((a, b) => ((nfl[a[0]] || [])[0] || "").localeCompare((nfl[b[0]] || [])[0] || ""));
  $app.innerHTML = `<h1>Predictions</h1>
    <p class="muted">Pick winners and make roster moves; the rest of ${meta.season} is simulated ${N.toLocaleString()} times in your browser through the league's playoff rules. ${liveNote(live)}</p>
    <div class="card"><h2>Season odds</h2><p class="small muted" id="pstate"></p><div id="pres"><p class="muted">Simulating…</p></div>
      <p class="muted small">Each team's week = its best lineup from its current roster's projections (the forecast's rate blended with this season's PPG), with who can play each week from the forecast's injury model: players listed Out come back on the league's return curve, players on IR not before the NFL's 4-game minimum, Questionable players play 85% of the time this week, a sourced "out for the season" note keeps a player out, and ESPN's injury list (captured daily) holds a player out for the season when ESPN dates his return after the season and the reporting says it is season-ending, or until ESPN's estimated return week, after which he comes back on the return curve. Pts/wk is the expected points a week over the remaining regular season, after injuries. The week in progress counts live points plus what is left. Standings: wins, then PF; top ${P.teams} make the playoffs; semifinal +${P.semifinal_bonus} to the higher seed; the final is ${P.final_weeks.length} week${P.final_weeks.length > 1 ? "s" : ""}. The home page's odds come from the full forecast model, so they differ a little.</p></div>
    ${espnCard(H.forecast, nfl, live)}
    <div class="card"><h2>Roster moves</h2>
      <div class="controls"><select id="mp"><option value="">Player…</option>${allPlayers.map(([pid, t]) => `<option value="${pid}">${esc((nfl[pid] || [])[0])} (${esc((nfl[pid] || [])[1])}, ${esc(t)})</option>`).join("")}</select>
        <select id="mt"><option value="out">Out for the season</option>${teams.map((t) => `<option value="${esc(t)}">Trade to ${esc(t)}</option>`).join("")}</select>
        <button class="b" id="madd">Apply</button></div><div id="pmoves"></div></div>
    <div class="card"><h2>Remaining games</h2><p class="muted small">Tap a team to make it win; tap again for "simulate".</p>
      ${byWeek.map(([w, gs]) => `<h3>Week ${w}${w === curWk ? " (in progress)" : ""}</h3><div class="pgames">${gs.map(([g, i]) => `<div class="pgame" data-g="${i}"><button data-side="a">${esc(g.a)}</button><span class="muted small">vs</span><button data-side="b">${esc(g.b)}</button></div>`).join("")}</div>`).join("")}
      <p><button class="b" id="preset">Clear every pick</button></p></div>`;
  const rerun = () => { document.getElementById("pres").style.opacity = .5; setTimeout(() => { draw(); document.getElementById("pres").style.opacity = 1; }, 20); };
  $app.querySelectorAll(".pgame").forEach((el) => el.onclick = (e) => {
    const b = e.target.closest("button[data-side]"); if (!b) return;
    const i = +el.dataset.g, side = b.dataset.side;
    if (picks[i] === side) delete picks[i]; else picks[i] = side;
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("won", picks[i] === x.dataset.side));
    rerun();
  });
  document.getElementById("preset").onclick = () => { picks = {}; $app.querySelectorAll(".pgame button").forEach((x) => x.classList.remove("won")); rerun(); };
  document.getElementById("madd").onclick = () => { const pid = document.getElementById("mp").value; if (!pid) return; moves = moves.filter((m) => m.pid !== pid); moves.push({ pid, to: document.getElementById("mt").value }); rerun(); };
  document.getElementById("pmoves").onclick = (e) => { const b = e.target.closest("[data-undo]"); if (!b) return; moves.splice(+b.dataset.undo, 1); rerun(); };
  setTimeout(() => { base = simulate(false); draw(); }, 20);
}

// ---------- router
async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const [page, ...rest] = path.split("/");
  const fn = routes[page] || home;
  const pop = document.getElementById("defpop");
  if (pop) pop.style.display = "none";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#/" + (page === "team" ? "teams" : page)));
  try {
    await fn(rest.join("/") || undefined, query);
  } catch (e) {
    $app.innerHTML = `<h1>Not found</h1><p class="muted">${esc(e.message)}</p><p><a href="#/">Home</a></p>`;
  }
  window.scrollTo(0, 0);
  // pages that show rosters or pick ownership redraw once Sleeper answers
  if (LIVE_PAGES.has(fn)) {
    const at = location.hash;
    loadLive().then((live) => {
      if (location.hash !== at) return;
      const y = window.scrollY;
      fn(rest.join("/") || undefined, query, live).then(() => window.scrollTo(0, y)).catch(() => {});
    });
  }
}
const LIVE_PAGES = new Set([team, player, faab, nfl]);
document.getElementById("searchForm").onsubmit = (e) => { e.preventDefault(); location.hash = "#/search/" + encodeURIComponent(document.getElementById("q").value); };
let typing;
document.getElementById("q").oninput = (e) => { clearTimeout(typing); typing = setTimeout(() => { if (e.target.value.trim().length > 1) location.hash = "#/search/" + encodeURIComponent(e.target.value); }, 250); };
window.addEventListener("hashchange", route);
// any card marked data-go (trade cards and the like) opens on a tap anywhere in it
$app.addEventListener("click", (e) => {
  if (e.target.closest("a, button, input, select, summary, .defbtn")) return;
  const c = e.target.closest(".trade[data-go]");
  if (c) location.hash = "#/" + c.dataset.go;
});
load("sheets/index.json").then((ix) => {
  for (const m of ix.sheets) DEFS[m.sheet] = m.defs || {};
  DEFS._any = Object.assign({}, ...ix.sheets.map((m) => m.defs || {}));
}).catch(() => {});
Promise.all([load("search.json"), load("meta.json")]).then(([ix, meta]) => {
  ix.forEach((r) => { if (r[0] === "p") { NAMES[r[2]] = r[1]; NAMES_BY_ID[r[1]] = r[2]; } });
  const built = meta.build_time ? new Date(meta.build_time).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : meta.built;
  document.getElementById("foot").innerHTML = `Stats through ${esc(meta.week_name)} ${meta.season}, from the league's stats exports (${meta.seasons[0]}–${meta.season}) as of the main build${meta.build_run ? ` <a href="https://github.com/Oliverwkw/LOTG-Stats/actions/runs/${esc(meta.build_run)}">run ${esc(meta.build_run)}</a>` : ""} (${esc(built)}); the site rebuilds after every main build. Rosters and pick ownership are read live from Sleeper when a page opens. <a href="rate/">Rate player values</a>.`;
  route();
}).catch((e) => { $app.innerHTML = `<p>Could not load the site data: ${esc(e.message)}</p>`; });
