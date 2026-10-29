// LOTG league site. Everything is precomputed JSON under data/ (built by
// scripts/build_site.py); this file only fetches and renders. Hash routes:
// #/  #/teams  #/team/<slug>  #/player/<key>  #/records[/<sheet>]  #/h2h
// #/trades[/<id>]  #/draft  #/search/<q>
"use strict";

const $app = document.getElementById("app");
const cache = {};
const load = (p) => cache[p] || (cache[p] = fetch("data/" + p).then((r) => {
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
const signed = (spec, v) => (typeof v === "number" && v > 0 ? "+" : "") + fmt(spec, v);
const tslug = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const teamLink = (t) => t ? `<a href="#/team/${tslug(t)}">${esc(t)}</a>` : "—";
let NAMES = {};   // player name -> page key, from search.json
const playerLink = (n) => NAMES[n] ? `<a href="#/player/${NAMES[n]}">${esc(n)}</a>` : esc(n);
const assetLink = (a) => NAMES[a] ? playerLink(a) : esc(a);

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
    const head = cols.map((c, i) => `<th data-i="${i}" class="${c.left ? "l" : ""}${state.by === i ? " sorted" + (state.asc ? " asc" : "") : ""}">${esc(c.label)}</th>`).join("");
    const body = rs.map((r) => "<tr" + (opts.rowClass ? ` class="${opts.rowClass(r)}"` : "") + ">" + cols.map((c) =>
      `<td class="${c.left ? "l" : ""}">${c.html ? c.html(r) : fmt(c.spec, val(c, r))}</td>`).join("") + "</tr>").join("");
    const el = document.getElementById(id);
    if (el) el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("click", (e) => {
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
// a {cols, labels, fmt, rows} table from the generator
function dataTable(t, opts = {}) {
  if (!t || !t.rows || !t.rows.length) return `<p class="muted small">None.</p>`;
  const hide = new Set(opts.hide || []);
  const cols = [];
  t.cols.forEach((c, i) => {
    if (hide.has(c)) return;
    const col = { k: i, label: t.labels[i], spec: t.fmt[c] };
    if (opts.links && opts.links[c]) col.html = (r) => opts.links[c](r[i], r, t.cols);
    if (typeof t.rows[0][i] === "string" || opts.left?.includes(c)) col.left = true;
    cols.push(col);
  });
  return table(cols, t.rows, opts);
}
const idx = (t, c) => t.cols.indexOf(c);

// ---------- pages
const routes = {
  "": home, teams, team, player, records, h2h, trades, draft, search, faab, data,
};

// ---------- FAAB board (docs/rate/board.json, published with the rating page)
let boardP = null;
const loadBoard = () => boardP || (boardP = fetch("rate/board.json").then((r) => (r.ok ? r.json() : null)).catch(() => null));
const money = (v) => (typeof v === "number" ? "$" + Math.round(v).toLocaleString("en-US") : "—");
function ownerTeam(o, teams) {
  if (!o) return null;
  return teams.find((t) => t.toLowerCase() === String(o).toLowerCase()) || o;
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
  const [meta, h, B] = await Promise.all([load("meta.json"), load("home.json"), loadBoard()]);
  const odds = {};
  (h.forecast?.odds || []).forEach((o) => (odds[o.team] = o));
  const hasOdds = h.forecast && h.forecast.odds;
  const cols = [
    { k: "rank", label: "#" },
    { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
    { k: (r) => r.w - r.l, label: "W-L", html: (r) => `${r.w}-${r.l}` },
    { k: "pf", label: "PF", spec: { d: 2 } },
    { k: "pa", label: "PA", spec: { d: 2 } },
    { k: (r) => +r.ap.split("-")[0], label: "All-play", html: (r) => r.ap },
    { k: "form", label: "Last 5", left: true, html: (r) => r.form.split("").map((c) => `<span class="${c === "W" ? "w" : "lo"}">${c}</span>`).join("") },
  ];
  if (hasOdds) cols.push(
    { k: (r) => odds[r.team]?.playoffs, label: "Playoffs", html: (r) => pct1(odds[r.team]?.playoffs) },
    { k: (r) => odds[r.team]?.finals, label: "Final", html: (r) => pct1(odds[r.team]?.finals) },
    { k: (r) => odds[r.team]?.champion, label: "Title", html: (r) => `<b>${pct1(odds[r.team]?.champion)}</b>` },
    { k: (r) => odds[r.team]?.wins, label: "Proj. wins", html: (r) => fmt({ d: 2 }, odds[r.team]?.wins) },
  );
  const games = h.results.map((g) => `<div class="game">
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
    ${hasOdds ? `<div class="card"><h2>Title odds</h2>${table([
      { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
      { k: "champion", label: "Title", html: (r) => `<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><b>${pct1(r.champion)}</b><div class="bar-h" style="width:90px"><i style="width:${Math.min(100, r.champion)}%"></i></div></div>` },
      { k: "finals", label: "Final", html: (r) => pct1(r.finals) },
      { k: "playoffs", label: "Playoffs", html: (r) => pct1(r.playoffs) },
    ], h.forecast.odds, { sort: 1 })}</div>` : ""}
    <div class="card"><h2>${esc(meta.week_name)} results</h2><div class="games">${games}</div></div>
    ${B ? `<div class="card"><h2>FAAB values</h2><p class="muted small">Board of ${esc(B.as_of)} · stats-only values in league FAAB</p>
      <ol>${B.players.slice(0, 5).map((x) => `<li>${playerLink(x.name)} <span class="muted small">${esc(x.pos)}</span> <b>${money(x.value)}</b></li>`).join("")}</ol>
      <p><a href="#/faab">Full board →</a> · <a href="rate/">Rate the board</a></p></div>` : ""}
    <div class="card digest"><h2>This week in the digest</h2>
      ${d.lede ? `<p>${esc(d.lede)}</p>` : `<p class="muted">No digest yet.</p>`}${digestHtml}</div>`;
}

async function teams() {
  const [meta, h] = await Promise.all([load("meta.json"), load("home.json")]);
  const ts = await Promise.all(meta.teams.map((t) => load(`team/${tslug(t)}.json`)));
  const rows = ts.map((t) => ({ t: t.team, ...t.summary, age: t.ages.avg }));
  const S = ts[0]?.summary_fmt || {};
  $app.innerHTML = `<h1>Teams</h1><div class="card">${table([
    { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
    { k: "Championships", label: "Titles" },
    { k: "All time record", label: "Record", left: true },
    { k: "All time win %", label: "Win %", spec: S["All time win %"] },
    { k: "Number of playoff appearances", label: "Playoffs" },
    { k: "Avg points", label: "Avg PF", spec: S["Avg points"] },
    { k: "Drafting skill", label: "Drafting", spec: S["Drafting skill"] },
    { k: "Trading skill", label: "Trading", spec: S["Trading skill"] },
    { k: "Add/Drop skill", label: "Add/Drop", spec: S["Add/Drop skill"] },
    { k: "age", label: "Roster age", spec: { d: 2 } },
  ], rows, { sort: 1 })}</div>`;
}

function tiles(summary, labels, specs, keys) {
  return `<div class="tiles">${(keys || Object.keys(summary)).filter((k) => k in summary).map((k) =>
    `<div class="tile"><b>${fmt(specs[k], summary[k])}</b><span>${esc(labels[k] || k)}</span></div>`).join("")}</div>`;
}

function tradeCard(t, meta) {
  const F = meta.fmt, L = meta.labels;
  const best = t.sides[0];
  const ktcNow = (s) => { for (let i = meta.ktc.length - 1; i >= 0; i--) { const v = s[meta.ktc[i][1]]; if (typeof v === "number") return [meta.ktc[i][0], v]; } return null; };
  const sides = t.sides.map((s) => {
    const k = ktcNow(s);
    return `<div class="side"><h4>${teamLink(s.team)} ${k ? `<span class="grade ${k[1] >= 0 ? "pos" : "neg"}" title="KTC value difference, latest available (${esc(k[0])})">${signed(F["KTC value difference at deal time"], k[1])} KTC</span>` : ""}</h4>
      <div class="small muted">Got</div><ul>${s.got.map((a) => `<li>${assetLink(a)}</li>`).join("") || '<li class="muted">nothing</li>'}</ul>
      <div class="ktc">${meta.ktc.map(([lab, c]) => `<span>${esc(lab)}: <b class="${(s[c] ?? 0) > 0 ? "pos" : (s[c] ?? 0) < 0 ? "neg" : ""}">${s[c] === null || s[c] === undefined ? "—" : signed(F[c], s[c])}</b></span>`).join("")}</div>
      <div class="ktc">${["Trade impact score", "Wins added", "Net points", "O-Score"].map((c) => `<span title="${esc(L[c])}">${esc(L[c])}: <b>${fmt(F[c], s[c])}</b></span>`).join("")}</div>
    </div>`;
  }).join("");
  return `<div class="trade" id="trade-${t.id}"><div class="small muted"><a href="#/trades/${t.id}">Trade #${t.id}</a> · ${esc(t.date)}${t.sides.length > 1 && (best["Trade impact score"] ?? 0) > (t.sides[1]["Trade impact score"] ?? 0) ? ` · impact edge: ${esc(best.team)}` : ""}</div><div class="sides">${sides}</div></div>`;
}

async function team(slug) {
  const [t, tr] = await Promise.all([load(`team/${slug}.json`), load("trades.json")]);
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const ages = t.ages || {};
  const leagueAvg = (k) => { const v = Object.values(t.league_ages).map((a) => k ? a.by_pos?.[k] : a.avg).filter((x) => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const ageRows = ["QB", "RB", "WR", "TE"].map((p) => [p, ages.by_pos?.[p], leagueAvg(p)]);
  const ri = idx(t.roster, "slug");
  const roster = dataTable(t.roster, { hide: ["slug"], links: { Player: (v, r) => ri >= 0 && r[ri] ? `<a href="#/player/${r[ri]}">${esc(v)}</a>` : esc(v) } });
  $app.innerHTML = `
    <h1>${esc(t.team)}</h1>
    ${tiles(t.summary, t.summary_labels, t.summary_fmt)}
    <p class="small">Every row: ${[["team_week", "weeks"], ["team_year", "seasons"], ["team_all_time", "all-time"], ["trades", "trades"], ["add_drops", "add/drops"], ["player_additions", "pickups"], ["rookie_picks", "rookie picks"]].map(([s, n]) => `<a href="#/data/${s}?c=Team&v=${encodeURIComponent(t.team)}">${n}</a>`).join(" · ")} · <a href="#/faab?owner=${encodeURIComponent(t.team)}">FAAB values</a></p>
    <div class="grid">
      <div class="card"><h2>Head to head</h2>${table([
        { k: "opp", label: "Opponent", left: true, html: (r) => teamLink(r.opp) },
        { k: (r) => r.w / Math.max(1, r.w + r.l), label: "W-L", html: (r) => `${r.w}-${r.l}` },
        { k: "pw", label: "Playoffs", html: (r) => `${r.pw}-${r.pl}` },
        { k: "pf", label: "Avg PF", spec: { d: 2 } },
        { k: "pa", label: "Avg PA", spec: { d: 2 } },
      ], t.h2h, { sort: 1 })}<p class="small"><a href="#/h2h">Full matrix →</a></p></div>
      <div class="card"><h2>Roster age</h2>
        <p>Whole roster <b>${fmt({ d: 2 }, ages.avg)}</b> · starters <b>${fmt({ d: 2 }, ages.starters)}</b> · league avg ${fmt({ d: 2 }, leagueAvg(null))}</p>
        ${table([{ k: 0, label: "Pos", left: true }, { k: 1, label: "Age", spec: { d: 2 } }, { k: 2, label: "League avg", spec: { d: 2 } },
                 { k: (r) => (r[1] ?? 0) - (r[2] ?? 0), label: "vs league", html: (r) => r[1] == null ? "—" : `<span class="${r[1] > r[2] ? "neg" : "pos"}">${signed({ d: 2 }, r[1] - r[2])}</span>` }], ageRows)}
      </div>
    </div>
    <div class="card"><h2>This season</h2>${dataTable(t.weeks)}</div>
    <div class="card"><h2>Seasons</h2>${dataTable(t.seasons)}</div>
    <div class="card"><h2>Current roster</h2>${roster}<p class="muted small">Bench includes taxi and IR. Age is the player's age for this season.</p></div>
    <div class="card"><h2>Trades (${t.trades.length})</h2>${t.trades.slice(0, 15).map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("")}
      ${t.trades.length > 15 ? `<p><a href="#/trades?team=${encodeURIComponent(t.team)}">All ${t.trades.length} trades →</a></p>` : ""}</div>
    <div class="card"><h2>Rookie draft picks</h2>${dataTable(t.draft, { hide: ["Team"], links: { "Player Picked": (v) => playerLink(v), "Original Team": (v) => teamLink(v) } })}</div>`;
}

async function player(key) {
  const [p, tr, B] = await Promise.all([load(`player/${key}.json`), load("trades.json"), loadBoard()]);
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const d = p.draft;
  const fv = B && B.players.find((x) => x.name === p.name);
  const enc = encodeURIComponent(p.name);
  $app.innerHTML = `
    <h1>${esc(p.name)}</h1>
    <p class="muted">${[p.pos, p.nfl, p.team ? "on " + teamLink(p.team) : "not on a roster now"].filter(Boolean).join(" · ")}
      ${d ? ` · drafted ${esc(d.year)} pick ${esc(d.pick)} by ${teamLink(d.team)}` : ""}</p>
    ${fv ? `<div class="card"><b>FAAB value ${money(fv.value)}</b> <span class="muted">· #${fv.rank} on the board of ${esc(B.as_of)} · ${esc(pickText(B, fv.value))}</span> · <a href="#/faab">board</a> · <a href="rate/">rate it</a></div>` : ""}
    ${tiles(p.summary, p.summary_labels, p.summary_fmt)}
    <p class="small">Every row: <a href="#/data/player_week?c=Player&v=${enc}&y=all">weeks</a> · <a href="#/data/player_year?c=Player&v=${enc}">seasons</a> · <a href="#/data/player_all_time?c=Player&v=${enc}">career</a> · <a href="#/data/player_additions?c=Player&v=${enc}">acquisitions</a> · <a href="#/data/add_drops?q=${enc}">add/drops</a></p>
    <div class="card"><h2>Career by team</h2>${table([
      { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
      { k: "from", label: "From", left: true }, { k: "to", label: "To", left: true },
      { k: "weeks", label: "Weeks" }, { k: "starts", label: "Starts" },
      { k: "pts", label: "Pts as starter", spec: { d: 2 } }, { k: "ppg", label: "PPG starter", spec: { d: 2 } },
      { k: "best", label: "Best week", spec: { d: 2 } }], p.teams)}</div>
    <div class="card"><h2>Acquisitions</h2>${dataTable(p.stints, { links: { Team: (v) => teamLink(v) } })}</div>
    <div class="card"><h2>Seasons</h2>${dataTable(p.seasons, { links: { "Top Team": (v) => teamLink(v), "Last team": (v) => teamLink(v) } })}</div>
    ${p.trades.length ? `<div class="card"><h2>Trades</h2>${p.trades.map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("")}</div>` : ""}`;
}

const SHEETS = [
  ["team_week", "Team week"], ["team_year", "Team season"], ["team_all_time", "Team all-time"],
  ["player_week", "Player week"], ["player_year", "Player season"], ["player_all_time", "Player career"],
  ["league_week", "League week"], ["league_year", "League season"], ["trades", "Trades"],
  ["add_drops", "Add/drops"], ["player_additions", "Pickups"], ["rookie_picks", "Rookie picks"],
];
const FEATURED = {
  team_week: ["PF", "Margin", "Max PF", "Efficiency", "Points left on bench", "Bench points"],
  team_year: ["Points", "Win %", "All-play win %", "Efficiency", "Differential", "Lineup Boldness"],
  team_all_time: ["Championships", "All time win %", "Avg points", "Trading skill", "Drafting skill", "Add/Drop skill"],
  player_week: ["Points"],
  player_year: ["Points", "PPG starter", "Starter PAR", "Times as Player of the week?"],
  player_all_time: ["Points", "Total points as starter", "Starter PAR", "Number of teams", "Number of trades"],
};

async function records(sheet, query) {
  sheet = sheet || "team_week";
  const params = new URLSearchParams(query || "");
  const r = await load(`records/${sheet}.json`);
  let q = params.get("q") || "", end = params.get("end") || "hi";
  const labelCols = r.labels;
  const lab = (row) => row.map((x, i) => {
    const c = labelCols[i];
    if (x === null) return "";
    if (c === "Team" || c === "Top team" || c === "Top Team" || c === "Opponent" || c === "Team's traded with 1") return (c === "Opponent" ? "vs " : "") + teamLink(x);
    if (c === "Player" || c === "Player Picked") return playerLink(x);
    if (c === "Assets received") return `<span class="muted">got ${esc(String(x).slice(0, 60))}</span>`;
    return esc(x);
  }).filter(Boolean).join(" · ");
  function card(c) {
    const rows = c[end] || [];
    const more = c[end + "_more"];
    return `<div class="card rec"><b>${esc(c.label)}</b> <span class="muted small">${end === "hi" ? "highest" : "lowest"} · ${c.n} rows</span>
      <ol>${rows.map(([v, l, live]) => `<li><span class="v">${fmt(c.fmt, v)}</span> ${lab(l)}${live ? ' <span class="chip live">in progress</span>' : ""}</li>`).join("")}</ol>
      ${more ? `<p class="muted small">+${more} more tied at the cut</p>` : ""}</div>`;
  }
  function draw() {
    const ql = q.trim().toLowerCase();
    let cs = r.columns;
    if (ql) cs = cs.filter((c) => c.label.toLowerCase().includes(ql) || c.col.toLowerCase().includes(ql));
    else if (FEATURED[sheet]) { const f = FEATURED[sheet]; cs = f.map((n) => cs.find((c) => c.col === n)).filter(Boolean).concat(cs.filter((c) => !f.includes(c.col))); }
    const shown = cs.slice(0, 24);
    document.getElementById("recs").innerHTML = shown.map(card).join("") || `<p class="muted">No column matches.</p>`;
    document.getElementById("reccount").textContent = `${cs.length} of ${r.columns.length} stats${cs.length > shown.length ? ` · showing ${shown.length}, narrow the filter for more` : ""}`;
  }
  $app.innerHTML = `<h1>Record book</h1>
    <div class="seg">${SHEETS.map(([k, n]) => `<button aria-pressed="${k === sheet}" data-s="${k}">${n}</button>`).join("")}</div>
    <div class="controls"><input class="f" id="rq" type="search" placeholder="Filter ${r.columns.length} stats (e.g. bench, boldness, KTC)" value="${esc(q)}">
      <span class="seg" style="margin:0"><button data-e="hi" aria-pressed="${end === "hi"}">Highest</button><button data-e="lo" aria-pressed="${end === "lo"}">Lowest</button></span></div>
    <p class="muted small" id="reccount"></p>
    <div class="note">Team PF includes the semifinal +5 bonus; player points do not. Lineups were 9 starters 2020-23 and 10 from 2024. "In progress" rows are from the ${r.live_season} season, still being played. Every week type counts (playoffs and toilet bowl too).</div>
    <div class="recgrid" id="recs"></div>`;
  $app.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => (location.hash = `#/records/${b.dataset.s}${q ? "?q=" + encodeURIComponent(q) : ""}`));
  $app.querySelectorAll("[data-e]").forEach((b) => b.onclick = () => { end = b.dataset.e; $app.querySelectorAll("[data-e]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("rq").oninput = (e) => { q = e.target.value; draw(); };
  draw();
}

async function h2h() {
  const m = await load("h2h.json");
  let mode = "all";
  function draw() {
    const key = { all: ["w", "l"], reg: ["rw", "rl"], po: ["pw", "pl"] }[mode];
    const head = `<tr><th class="l">Team ↓ vs →</th>${m.teams.map((t) => `<th>${esc(t.slice(0, 8))}</th>`).join("")}<th>Total</th></tr>`;
    const body = m.teams.map((a) => {
      let W = 0, L = 0;
      const cells = m.teams.map((b) => {
        if (a === b) return `<td class="self"></td>`;
        const c = m.cells[`${a}|${b}`];
        if (!c) return "<td>—</td>";
        const w = c[key[0]], l = c[key[1]];
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
    <div class="seg"><button data-m="all" aria-pressed="true">All games</button><button data-m="reg" aria-pressed="false">Regular season</button><button data-m="po" aria-pressed="false">Postseason</button></div>
    <div class="card"><div class="scroll" id="mx"></div><p class="muted small">Row team's record against the column team. Tap a cell for details. Postseason = every non-regular week (playoffs, 3rd place and toilet bowl). ${esc(m.note)}</p></div>
    <div class="card" id="cell"><p class="muted">Tap a cell.</p></div>`;
  $app.querySelectorAll("[data-m]").forEach((b) => b.onclick = () => { mode = b.dataset.m; $app.querySelectorAll("[data-m]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); });
  document.getElementById("mx").onclick = (e) => {
    const td = e.target.closest("td[data-a]");
    if (!td) return;
    const c = m.cells[`${td.dataset.a}|${td.dataset.b}`];
    document.getElementById("cell").innerHTML = `<h2>${teamLink(td.dataset.a)} vs ${teamLink(td.dataset.b)}</h2>
      <p>All games <b>${c.w}-${c.l}</b> · regular season ${c.rw}-${c.rl} · postseason ${c.pw}-${c.pl}</p>
      <p>Points ${fmt({ d: 2 }, c.pf)} – ${fmt({ d: 2 }, c.pa)} · last meeting: ${esc(c.last)}</p>`;
  };
  draw();
}

async function trades(id, query) {
  const [tr, meta] = await Promise.all([load("trades.json"), load("meta.json")]);
  if (id) {
    const t = tr.trades.find((x) => String(x.id) === String(id));
    $app.innerHTML = `<p><a href="#/trades">← All trades</a></p>${t ? tradeCard(t, tr.meta) : "<p>Not found.</p>"}
      <p class="muted small">KTC value difference = value received minus value sent on KeepTradeCut (superflex), at the deal and later. Trade impact score, wins added and net points come from the trades sheet.</p>`;
    return;
  }
  const params = new URLSearchParams(query || "");
  let team = params.get("team") || "", season = params.get("season") || "", sort = "date", q = "";
  function draw() {
    let ts = tr.trades.filter((t) => (!team || t.sides.some((s) => s.team === team)) && (!season || String(t.season) === season)
      && (!q || t.sides.some((s) => s.got.concat(s.sent).some((a) => a.toLowerCase().includes(q)))));
    const swing = (t) => Math.max(...t.sides.map((s) => { for (let i = tr.meta.ktc.length - 1; i >= 0; i--) { const v = s[tr.meta.ktc[i][1]]; if (typeof v === "number") return Math.abs(v); } return 0; }));
    const impact = (t) => Math.max(...t.sides.map((s) => Math.abs(s["Trade impact score"] || 0)));
    if (sort === "ktc") ts = ts.slice().sort((a, b) => swing(b) - swing(a));
    if (sort === "impact") ts = ts.slice().sort((a, b) => impact(b) - impact(a));
    const shown = ts.slice(0, 60);
    document.getElementById("tl").innerHTML = `<p class="muted small">${ts.length} trades${ts.length > shown.length ? `, showing ${shown.length}` : ""}</p>` + shown.map((t) => tradeCard(t, tr.meta)).join("");
  }
  const seasons = [...new Set(tr.trades.map((t) => t.season))].sort().reverse();
  $app.innerHTML = `<h1>Trade history</h1>
    <div class="controls">
      <select id="ft"><option value="">All teams</option>${meta.teams.map((t) => `<option ${t === team ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <select id="fs"><option value="">All seasons</option>${seasons.map((s) => `<option ${String(s) === season ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <select id="fo"><option value="date">Newest first</option><option value="ktc">Biggest KTC swing</option><option value="impact">Biggest impact score</option></select>
      <input class="f" id="fq" type="search" placeholder="Player or pick">
    </div>
    <p class="muted small">Each side shows the KTC value difference (received − sent) at the deal, at season end, 1 and 2 years later; the badge is the latest one available. Trades from this season have only the deal-time value so far.</p>
    <div id="tl"></div>`;
  document.getElementById("ft").onchange = (e) => { team = e.target.value; draw(); };
  document.getElementById("fs").onchange = (e) => { season = e.target.value; draw(); };
  document.getElementById("fo").onchange = (e) => { sort = e.target.value; draw(); };
  document.getElementById("fq").oninput = (e) => { q = e.target.value.trim().toLowerCase(); draw(); };
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
    document.getElementById("dt").innerHTML = dataTable({ ...t, rows }, { links: { "Player Picked": (v) => playerLink(v), Team: (v) => teamLink(v), "Original Team": (v) => teamLink(v) } });
  }
  $app.innerHTML = `<h1>Draft history</h1>
    <div class="controls"><span class="seg" style="margin:0"><button data-w="rookie" aria-pressed="true">Rookie drafts</button>${d.startup ? `<button data-w="startup" aria-pressed="false">Startup &amp; vet picks</button>` : ""}</span>
      <select id="dy"></select></div>
    <div class="card"><div id="dt"></div><p class="muted small">Pick-adjusted columns compare the pick with what that draft slot usually returns. KTC values are KeepTradeCut superflex.</p></div>`;
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

async function faab(_, query) {
  const [B, meta] = await Promise.all([loadBoard(), load("meta.json")]);
  if (!B) { $app.innerHTML = `<h1>FAAB values</h1><p class="muted">The board is not published yet.</p>`; return; }
  const params = new URLSearchParams(query || "");
  let pos = params.get("pos") || "", owner = params.get("owner") || "", q = "";
  const rows = B.players.map((x) => ({ ...x, own: ownerTeam(x.owner, meta.teams) }));
  const totals = meta.teams.map((t) => {
    const mine = rows.filter((r) => r.own === t);
    const by = (p) => mine.filter((r) => r.pos === p).reduce((a, r) => a + r.value, 0);
    return { t, total: mine.reduce((a, r) => a + r.value, 0), n: mine.length, QB: by("QB"), RB: by("RB"), WR: by("WR"), TE: by("TE"),
             top: mine[0] };
  });
  const maxT = Math.max(...totals.map((x) => x.total), 1);
  const positions = [...new Set(rows.map((r) => r.pos))].filter(Boolean);
  function draw() {
    const ql = q.toLowerCase();
    const rs = rows.filter((r) => (!pos || r.pos === pos) && (!owner || (owner === "FA" ? !r.own : r.own === owner))
      && (!ql || r.name.toLowerCase().includes(ql)));
    document.getElementById("fb").innerHTML = `<p class="muted small">${rs.length} players</p>` + table([
      { k: "rank", label: "#" },
      { k: "name", label: "Player", left: true, html: (r) => playerLink(r.name) },
      { k: "pos", label: "Pos", left: true }, { k: "team", label: "NFL", left: true },
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
    <div class="card"><h2>Roster value by team</h2>${table([
      { k: "t", label: "Team", left: true, html: (r) => `<a href="#/faab?owner=${encodeURIComponent(r.t)}" onclick="">${esc(r.t)}</a>` },
      { k: "total", label: "Total", html: (r) => `<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><b>${money(r.total)}</b><div class="bar-h" style="width:90px"><i style="width:${(100 * r.total) / maxT}%"></i></div></div>` },
      { k: "QB", label: "QB", html: (r) => money(r.QB) }, { k: "RB", label: "RB", html: (r) => money(r.RB) },
      { k: "WR", label: "WR", html: (r) => money(r.WR) }, { k: "TE", label: "TE", html: (r) => money(r.TE) },
      { k: "n", label: "Players" },
      { k: (r) => r.top?.value, label: "Most valuable", left: true, html: (r) => (r.top ? `${playerLink(r.top.name)} ${money(r.top.value)}` : "—") },
    ], totals, { sort: 1 })}</div>
    <div class="card"><h2>Board</h2>
      <div class="controls">
        <select id="fp"><option value="">All positions</option>${positions.map((p) => `<option ${p === pos ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
        <select id="fo"><option value="">All owners</option><option value="FA" ${owner === "FA" ? "selected" : ""}>Free agents</option>${meta.teams.map((t) => `<option ${t === owner ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <input class="f" id="fq" type="search" placeholder="Player">
      </div><div id="fb"></div></div>
    <div class="card"><h2>Rookie pick values</h2><p>${(B.picks || []).map((p) => `<span class="chip">${esc(p.slot)} ${money(p.value)}</span>`).join("")}</p>
      <p class="muted small">What a rookie-draft slot is worth on the same scale.</p></div>`;
  document.getElementById("fp").onchange = (e) => { pos = e.target.value; draw(); };
  document.getElementById("fo").onchange = (e) => { owner = e.target.value; draw(); };
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
      <div class="grid">${ix.sheets.map((m) => `<div class="card"><h2><a href="#/data/${m.sheet}">${esc(SHEET_NAMES[m.sheet] || m.sheet)}</a></h2>
        <p class="muted small">${m.sheet}.csv · ${m.rows.toLocaleString()} rows · ${m.cols.length} columns${m.chunks.length > 1 ? ` · by ${esc(m.season_col)}` : ""}</p>
        <p><a href="#/data/${m.sheet}">Browse</a> · <a href="${m.csv}" download>Download CSV (${kb(m.csv_bytes)})</a></p></div>`).join("")}</div>`;
    return;
  }
  const m = ix.sheets.find((x) => x.sheet === sheet);
  if (!m) throw new Error("No sheet " + sheet);
  const params = new URLSearchParams(query || "");
  let chunk = params.get("y") || (m.chunks.length > 1 ? m.chunks[m.chunks.length - 1][1] : "all");
  let q = params.get("q") || "", fc = params.get("c") || "", fo = params.get("o") || "=", fv = params.get("v") || "";
  let sortBy = -1, asc = false, page = 0;
  const all = m.cols.map((_, i) => i);
  let shown = prefs.get("cols:" + sheet, null);
  if (!Array.isArray(shown) || shown.some((i) => i >= m.cols.length)) shown = m.cols.length <= 30 ? all : all.slice(0, 18);
  let rows = [];
  async function fetchRows() {
    const parts = chunk === "all" && m.chunks.length > 1 ? m.chunks.map((c) => c[1]) : [chunk];
    document.getElementById("dcount").textContent = "Loading…";
    const got = await Promise.all(parts.map((c) => load(`sheets/${sheet}/${c}.json`)));
    rows = [].concat(...got.map((g) => g.rows));
  }
  const fi = () => m.cols.indexOf(fc);
  function filtered() {
    const ql = q.trim().toLowerCase();
    const ci = fi();
    const num = parseFloat(fv);
    return rows.filter((r) => {
      if (ql && !r.some((x) => x !== null && String(x).toLowerCase().includes(ql))) return false;
      if (ci >= 0 && fv !== "") {
        const x = r[ci];
        if (fo === "=") return String(x ?? "").toLowerCase() === fv.toLowerCase();
        if (fo === "~") return String(x ?? "").toLowerCase().includes(fv.toLowerCase());
        if (typeof x !== "number" || isNaN(num)) return false;
        return fo === ">" ? x > num : fo === "<" ? x < num : fo === ">=" ? x >= num : x <= num;
      }
      return true;
    });
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
    const head = shown.map((i) => `<th data-i="${i}" class="l${sortBy === i ? " sorted" + (asc ? " asc" : "") : ""}" title="${esc(m.defs[m.cols[i]] || "")}">${esc(m.labels[i])}${m.defs[m.cols[i]] ? " ⓘ" : ""}</th>`).join("");
    const cell = (i, v) => {
      const c = m.cols[i];
      if (v === null || v === undefined) return '<td class="muted">—</td>';
      if (typeof v === "string") {
        if (["Team", "Top team", "Top Team", "Last team", "Opponent", "Original Team"].includes(c) || c.startsWith("Team's traded with")) return `<td class="l">${teamLink(v)}</td>`;
        if (["Player", "Player Picked", "Player Added", "Player Dropped"].includes(c)) return `<td class="l">${playerLink(v)}</td>`;
        return `<td class="l">${esc(v)}</td>`;
      }
      return `<td>${fmt(m.fmt[c], v)}</td>`;
    };
    document.getElementById("dt").innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${slice.map((r) => `<tr>${shown.map((i) => cell(i, r[i])).join("")}</tr>`).join("")}</tbody></table>`;
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
    <div class="controls">
      <select id="dc"><option value="">Filter a column…</option>${m.cols.map((c, i) => `<option value="${esc(c)}" ${c === fc ? "selected" : ""}>${esc(m.labels[i])}</option>`).join("")}</select>
      <select id="do">${["=", "~", ">", ">=", "<", "<="].map((o) => `<option value="${o}" ${o === fo ? "selected" : ""}>${{ "=": "is", "~": "contains", ">": ">", ">=": "≥", "<": "<", "<=": "≤" }[o]}</option>`).join("")}</select>
      <input class="f" id="dv" placeholder="value" value="${esc(fv)}">
    </div>
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
  document.getElementById("dt").onclick = (e) => { const th = e.target.closest("th"); if (!th) return; const i = +th.dataset.i; if (sortBy === i) asc = !asc; else { sortBy = i; asc = false; } draw(); };
  document.getElementById("dpg").onclick = (e) => { const b = e.target.closest("button[data-p]"); if (!b) return; page += +b.dataset.p; draw(); document.getElementById("dcount").scrollIntoView(); };
  let deb;
  document.getElementById("dq").oninput = (e) => { clearTimeout(deb); deb = setTimeout(() => { q = e.target.value; page = 0; draw(); }, 200); };
  document.getElementById("dc").onchange = (e) => { fc = e.target.value; page = 0; draw(); };
  document.getElementById("do").onchange = (e) => { fo = e.target.value; page = 0; draw(); };
  document.getElementById("dv").oninput = (e) => { clearTimeout(deb); deb = setTimeout(() => { fv = e.target.value; page = 0; draw(); }, 200); };
  if (document.getElementById("dy")) document.getElementById("dy").onchange = async (e) => { chunk = e.target.value; page = 0; await fetchRows(); draw(); };
  // a column filter from a link shows that column
  if (fi() >= 0 && !shown.includes(fi())) shown = [fi(), ...shown];
  await fetchRows();
  draw();
}

// ---------- router
async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const [page, ...rest] = path.split("/");
  const fn = routes[page] || home;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#/" + (page === "team" ? "teams" : page)));
  try {
    await fn(rest.join("/") || undefined, query);
  } catch (e) {
    $app.innerHTML = `<h1>Not found</h1><p class="muted">${esc(e.message)}</p><p><a href="#/">Home</a></p>`;
  }
  window.scrollTo(0, 0);
}
document.getElementById("searchForm").onsubmit = (e) => { e.preventDefault(); location.hash = "#/search/" + encodeURIComponent(document.getElementById("q").value); };
let typing;
document.getElementById("q").oninput = (e) => { clearTimeout(typing); typing = setTimeout(() => { if (e.target.value.trim().length > 1) location.hash = "#/search/" + encodeURIComponent(e.target.value); }, 250); };
window.addEventListener("hashchange", route);
Promise.all([load("search.json"), load("meta.json")]).then(([ix, meta]) => {
  ix.forEach((r) => { if (r[0] === "p") NAMES[r[2]] = r[1]; });
  document.getElementById("foot").innerHTML = `Built from the league's stats exports (${meta.seasons[0]}–${meta.season}), through ${esc(meta.week_name)} ${meta.season}. Rebuilt after every weekly build. <a href="rate/">Rate player values</a>.`;
  route();
}).catch((e) => { $app.innerHTML = `<p>Could not load the site data: ${esc(e.message)}</p>`; });
