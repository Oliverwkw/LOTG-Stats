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
  "": home, teams, team, player, records, h2h, trades, draft, search,
};

async function home() {
  const [meta, h] = await Promise.all([load("meta.json"), load("home.json")]);
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
  const [p, tr] = await Promise.all([load(`player/${key}.json`), load("trades.json")]);
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const d = p.draft;
  $app.innerHTML = `
    <h1>${esc(p.name)}</h1>
    <p class="muted">${[p.pos, p.nfl, p.team ? "on " + teamLink(p.team) : "not on a roster now"].filter(Boolean).join(" · ")}
      ${d ? ` · drafted ${esc(d.year)} pick ${esc(d.pick)} by ${teamLink(d.team)}` : ""}</p>
    ${tiles(p.summary, p.summary_labels, p.summary_fmt)}
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
    ${ql ? `<div class="card"><h2>Stats named “${esc(q)}”</h2><p>${SHEETS.map(([k, n]) => `<a class="chip" href="#/records/${k}?q=${encodeURIComponent(q)}">${n}</a>`).join("")}</p></div>` : ""}`;
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
