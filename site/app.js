// LOTG league site. Everything is precomputed JSON under data/ (built by
// scripts/build_site.py); this file only fetches and renders. Hash routes:
// #/  #/teams  #/team/<slug>  #/player/<key>  #/records[/<sheet>][?full=<col>]  #/h2h
// #/trades[/<id>]  #/draft  #/search/<q>  #/faab  #/data[/<sheet>]  #/game/<y>/<w>/<team>
// #/week/<y>/<w>  #/pick/<sheet>/<row>  #/nfl/<code>  #/weeks[/<year>]  #/compare[?a=&b=]
// #/mine (your team, set in the header menu)
"use strict";

const $app = document.getElementById("app");
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const cache = {};
// every data file is asked for with this build's stamp (index.html sets it), so a
// browser's cached copy from an earlier build is never mixed with this code
const BUILD = window.SITE_BUILD || "";
const withBuild = (u) => BUILD ? u + (u.includes("?") ? "&" : "?") + "b=" + BUILD : u;
// a thin top bar while any data file is in flight
let inFlight = 0;
const progress = (d) => {
  inFlight = Math.max(0, inFlight + d);
  const el = document.getElementById("progress");
  if (!el) return;
  if (inFlight > 0) { el.classList.add("on"); el.style.width = Math.min(90, 25 + 65 * (1 - 1 / (1 + inFlight))) + "%"; }
  else { el.style.width = "100%"; setTimeout(() => { if (!inFlight) { el.classList.remove("on"); el.style.width = "0"; } }, 250); }
};
// a failed request is retried once, and is never kept in the cache (the next visit asks again)
const getJSON = (url, tries = 2) => fetch(url).then((r) => {
  if (!r.ok) throw new Error(url.replace(/\?.*/, "").replace(/^data\//, "") + " (" + r.status + ")");
  return r.json();
}).catch((e) => (tries > 1 && !/\(\d+\)/.test(e.message) ? new Promise((ok) => setTimeout(ok, 400)).then(() => getJSON(url, tries - 1)) : Promise.reject(e)));
const load = (p) => {
  if (cache[p]) return cache[p];
  progress(1);
  cache[p] = getJSON(withBuild("data/" + p)).finally(() => progress(-1));
  cache[p].catch(() => { delete cache[p]; });
  return cache[p];
};
// warm the cache for a page the reader is about to open (hover / touch on a link)
const prefetch = (p) => { if (!cache[p]) load(p).catch(() => {}); };

// ---------- preferences (localStorage; a private window just forgets them)
const prefs = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
                set(k, v) { try { if (v === null || v === undefined) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } } };
let ME = prefs.get("lotg:me", null);     // the reader's own team, if they set one

// ---------- small UI helpers
function toast(msg) {
  const el = document.getElementById("toast"); if (!el) return;
  el.textContent = msg; el.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("on"), 2200);
}
// copy text to the clipboard; resolves true only when the copy really happened
async function copyText(text, what = "Copied") {
  let ok = false;
  try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); ok = true; } } catch (e) { ok = false; }
  if (!ok) {
    // older / in-app browsers: copy from a selected, read-only text field (iOS needs the range)
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;font-size:16px";
    document.body.appendChild(ta); ta.focus(); ta.select(); ta.setSelectionRange(0, text.length);
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
  }
  if (what) toast(ok ? what : "Couldn't copy here — press and hold the link to copy it");
  return ok;
}
// Share: a dialog that always shows the link, so it works even where the browser blocks
// the clipboard or has no share sheet (in-app browsers in Messages, Sleeper, Gmail)
// The link we share has no "#": chat apps (Sleeper's included) often won't make a URL with
// "#/…", ":" or a second "?" tappable. ?to=<route> opens the same page (see the boot code).
function shareUrl() {
  const route = location.hash.replace(/^#\/?/, "");
  const base = location.origin + location.pathname;
  if (!route) return base;
  return base + "?to=" + encodeURIComponent(route).replace(/%2F/g, "/");
}
function shareLink() {
  const url = shareUrl(), title = document.title;
  const canShare = typeof navigator.share === "function";
  openModal(`<button class="b sm x" data-close aria-label="Close">✕</button><h2 id="modalTitle">Share this page</h2>
    <p class="muted small">${esc(title)}</p>
    <input class="f" id="shareurl" readonly value="${esc(url)}" aria-label="Link to this page" style="width:100%;font-size:14px">
    <p class="small" id="sharemsg" aria-live="polite"></p>
    <div class="controls" style="margin:4px 0 0">
      <button class="b pri" id="sharecopy">Copy link</button>
      ${canShare ? `<button class="b" id="sharenative">Share…</button>` : ""}
      <a class="btn sec" href="sms:?&body=${encodeURIComponent(title + " " + url)}">Text</a>
      <a class="btn sec" href="mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(url)}">Email</a>
    </div>`);
  const inp = $("#shareurl"), msg = $("#sharemsg");
  const sel = () => { inp.focus(); inp.select(); inp.setSelectionRange(0, url.length); };
  inp.onclick = sel;
  setTimeout(sel, 30);
  $("#sharecopy").onclick = async () => {
    const ok = await copyText(url, "");
    msg.innerHTML = ok ? '<span class="pos">✓ Link copied</span>' : "This browser won't copy for us: the link above is selected — press and hold (or Ctrl/⌘ C) to copy it.";
    if (ok) toast("Link copied"); else sel();
  };
  if (canShare) $("#sharenative").onclick = () => navigator.share({ title, url }).catch((e) => { if (e && e.name !== "AbortError") msg.textContent = "Sharing didn't open here — use Copy link instead."; });
}
const announce = (t) => { const el = document.getElementById("announce"); if (el) el.textContent = t; };
function setTitle(t) { document.title = t ? `${t} · LOTG` : "LOTG League"; }
// "Home › Teams › Oliverwkw"
const crumbs = (...xs) => `<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">Home</a>${xs.map(([n, h]) => `<span aria-hidden="true">›</span>${h ? `<a href="#/${h}">${esc(n)}</a>` : `<span>${esc(n)}</span>`}`).join("")}</nav>`;
const shareBtn = () => `<button class="b sm" data-share title="Copy a link to this page">🔗 Share</button>`;
const debounce = (fn, ms = 200) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
// keep a page's filters in the address bar (replaceState: no history entry per keystroke)
function setQuery(obj) {
  const [path] = location.hash.split("?");
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== "" && v !== null && v !== undefined && v !== false) p.set(k, v);
  const s = p.toString();
  history.replaceState(history.state, "", path + (s ? "?" + s : ""));
}
const plural = (n, w, ws) => `${n.toLocaleString()} ${n === 1 ? w : (ws || w + "s")}`;
const ago = (d) => {
  const s = (Date.now() - d) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400 * 1.5) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
};
const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");

// ---------- formatting (workbook decimals: number_format.col_number_format)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function fmt(spec, v) {
  if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "number") return esc(v);
  if (!isFinite(v)) return '<span class="muted">—</span>';
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
// an odds cell with a small bar behind the number (p 0-1)
const oddsBar = (text, p) => `<span class="oddcell">${text}<i style="--w:${Math.max(0, Math.min(100, (p || 0) * 100)).toFixed(1)}%" aria-hidden="true"></i></span>`;
const signed = (spec, v) => (typeof v === "number" && v > 0 ? "+" : "") + fmt(spec, v);
const tslug = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// ---------- team identity: a fixed colour per team (by its place in meta.teams), and
// its Sleeper avatar and team name once Sleeper has answered (kept in localStorage, so
// the next visit shows them at once)
const PALETTE = ["#2d5bd7", "#d4483b", "#16936a", "#8a4fd1", "#c97a12", "#0f8a9a", "#c43c86", "#5b6b7a", "#7a8f1c", "#a0522d"];
let TEAMS = [];
let TINFO = prefs.get("lotg:teaminfo", {});    // team -> {av: url, name: fantasy team name}
const teamColor = (t) => { const i = TEAMS.findIndex((x) => x.toLowerCase() === String(t).toLowerCase()); return PALETTE[(i < 0 ? [...String(t)].reduce((a, c) => a + c.charCodeAt(0), 0) : i) % PALETTE.length]; };
const avatar = (t, cls = "") => {
  const inf = TINFO[t] || {};
  return inf.av ? `<img class="tav ${cls}" data-t="${esc(t)}" src="${esc(inf.av)}" alt="" loading="lazy" decoding="async" width="20" height="20">`
    : `<i class="tav ${cls}" data-t="${esc(t)}" style="--tc:${teamColor(t)}" aria-hidden="true">${esc(String(t).charAt(0).toUpperCase())}</i>`;
};
const teamLink = (t, opts) => t ? `<a class="tlink" href="#/team/${tslug(t)}" title="${esc((TINFO[t] || {}).name || t)}">${opts === false ? "" : avatar(t)}${esc(t)}${ME && ME === t ? " ★" : ""}</a>` : "—";
// swap the colour circles on the page for avatars once they are known
function refreshAvatars() {
  for (const el of $$("i.tav[data-t]")) {
    const inf = TINFO[el.dataset.t]; if (!inf || !inf.av) continue;
    const img = document.createElement("img");
    img.className = el.className; img.src = inf.av; img.alt = ""; img.dataset.t = el.dataset.t; img.loading = "lazy";
    el.replaceWith(img);
  }
}
let NAMES = {}, NAMES_BY_ID = {}, POS_OF = {};   // player name -> page key, from search.json
const playerLink = (n) => NAMES[n] ? `<a href="#/player/${NAMES[n]}">${esc(n)}</a>` : esc(n);
const posBadge = (p) => p ? `<span class="pos-b pos-${esc(p)}">${esc(p)}</span>` : "";
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

// ---------- definitions: tap, hover or focus a stat's name for its formula (formulas.csv),
// on every table header, tile and record board. DEFS[sheet][column] = text.
let DEFS = {};
const defOf = (col, sheet) => (sheet && DEFS[sheet] && DEFS[sheet][col]) || DEFS._any?.[col] || "";
const defAttr = (col, sheet) => { const d = defOf(col, sheet); return d ? ` data-def="${esc(d)}" class="hasdef"` : ""; };
const DEFBTN = '<span class="defbtn" role="button" tabindex="0" aria-label="What is this?" title="What is this?">ⓘ</span>';
function showDef(el) {
  let pop = document.getElementById("defpop");
  if (!pop) { pop = document.createElement("div"); pop.id = "defpop"; pop.className = "defpop"; pop.setAttribute("role", "tooltip"); document.body.appendChild(pop); }
  pop.innerHTML = `<b>${esc(el.dataset.deflabel || el.textContent.replace(/[▾▴↕ⓘ]/g, "").trim())}</b><br>${esc(el.dataset.def)}`;
  const r = el.getBoundingClientRect();
  pop.style.display = "block";
  const w = Math.min(340, window.innerWidth - 24);
  pop.style.width = w + "px";
  pop.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left)) + "px";
  // below the label, or above it when there is no room underneath
  const h = pop.offsetHeight, below = r.bottom + 6 + h < window.innerHeight;
  pop.style.top = (window.scrollY + (below ? r.bottom + 6 : r.top - h - 6)) + "px";
}
const hideDef = () => { const pop = document.getElementById("defpop"); if (pop) pop.style.display = "none"; };
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-def]");
  if (el && e.target.closest(".defbtn")) { e.preventDefault(); e.stopPropagation(); showDef(el); return; }
  if (!e.target.closest("#defpop")) hideDef();
}, true);
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("defbtn")) { e.preventDefault(); e.stopPropagation(); const el = e.target.closest("[data-def]"); if (el) showDef(el); }
}, true);
document.addEventListener("mouseover", (e) => { const el = e.target.closest("[data-def]"); if (el && matchMedia("(hover: hover)").matches) showDef(el); });
document.addEventListener("mouseout", (e) => { const el = e.target.closest("[data-def]"); if (el && matchMedia("(hover: hover)").matches && !el.contains(e.relatedTarget)) hideDef(); });
window.addEventListener("scroll", () => { if (matchMedia("(hover: hover)").matches) hideDef(); }, { passive: true });
const defMark = (col, sheet) => defOf(col, sheet) ? " " + DEFBTN : "";

// ---------- sortable table
// cols: [{k: index or fn, label, spec, left, html(row), col (formulas.csv name), nosort}]
// opts: sort, asc, pin, defs, rowLink(r), rowClass(r), teamOf(r) (highlights your team),
//       cut (a dashed line under that many rows when sorted the default way), tools (force
//       the filter / CSV bar), limit (rows drawn before "Show all"), name (CSV file name)
let tableSeq = 0;
const stripHtml = (h) => { const d = document.createElement("div"); d.innerHTML = String(h); return d.textContent.trim(); };
function toCSV(head, rows) {
  const q = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [head, ...rows].map((r) => r.map(q).join(",")).join("\n");
}
function downloadText(name, text, type = "text/csv") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" }));
  a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
function table(cols, rows, opts = {}) {
  const id = "t" + (++tableSeq);
  const state = { by: opts.sort ?? null, asc: !!opts.asc, q: "", all: false };
  const def0 = { by: state.by, asc: state.asc };
  const val = (c, r) => (typeof c.k === "function" ? c.k(r) : r[c.k]);
  const tools = opts.tools ?? rows.length > 15;
  const limit = opts.limit ?? 150;
  const text = (r) => cols.map((c) => { const v = val(c, r); return typeof v === "string" ? v : ""; }).join(" ").toLowerCase()
    + " " + (opts.teamOf ? String(opts.teamOf(r) || "").toLowerCase() : "");
  function current() {
    let rs = rows.slice();
    if (state.q) { const ws = state.q.toLowerCase().split(/\s+/).filter(Boolean); rs = rs.filter((r) => { const t = text(r) + " " + stripHtml(cols.map((c) => (c.html ? c.html(r) : "")).join(" ")).toLowerCase(); return ws.every((w) => t.includes(w)); }); }
    if (state.by !== null) {
      const c = cols[state.by];
      rs.sort((a, b) => {
        const x = val(c, a), y = val(c, b);
        if (x === y) return 0;
        if (x === null || x === undefined || (typeof x === "number" && isNaN(x))) return 1;
        if (y === null || y === undefined || (typeof y === "number" && isNaN(y))) return -1;
        const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
        return state.asc ? r : -r;
      });
    }
    return rs;
  }
  function render() {
    const rs = current();
    const shown = state.all || rs.length <= limit ? rs : rs.slice(0, limit);
    const isDefault = !state.q && state.by === def0.by && state.asc === def0.asc;
    const head = cols.map((c, i) => {
      const d = c.col ? defOf(c.col, opts.defs) : "";
      const sorted = state.by === i;
      return `<th scope="col" data-i="${i}" tabindex="${c.nosort ? -1 : 0}" ${c.nosort ? "" : `aria-sort="${sorted ? (state.asc ? "ascending" : "descending") : "none"}"`} class="${c.left ? "l" : ""}${sorted ? " sorted" + (state.asc ? " asc" : "") : ""}${c.nosort ? " nosort" : ""}${i < (opts.pin || 1) ? " pin pin" + i : ""}"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(c.label)}"` : ""}${c.title ? ` title="${esc(c.title)}"` : ""}>${esc(c.label)}${d ? " " + DEFBTN : ""}</th>`;
    }).join("");
    const body = shown.map((r, ri) => {
      const cls = [opts.rowClass ? opts.rowClass(r) : "", opts.teamOf && ME && opts.teamOf(r) === ME ? "me" : "", isDefault && opts.cut && ri === opts.cut - 1 ? "cut" : "", opts.rowLink && opts.rowLink(r) ? "go" : ""].filter(Boolean).join(" ");
      return "<tr" + (cls ? ` class="${cls}"` : "") + (opts.rowLink ? ` data-go="${esc(opts.rowLink(r) || "")}"` : "") + ">" + cols.map((c, i) =>
        `<td class="${c.left ? "l" : ""}${i < (opts.pin || 1) ? " pin pin" + i : ""}">${c.html ? c.html(r) : fmt(c.spec, val(c, r))}</td>`).join("") + "</tr>";
    }).join("") || `<tr><td colspan="${cols.length}" class="l muted">No rows match.</td></tr>`;
    const el = document.getElementById(id);
    if (!el) return;
    const sc = el.querySelector(".scroll");
    const x = sc ? sc.scrollLeft : 0;
    el.querySelector(".tb") && (el.querySelector(".tcount").textContent = state.q ? `${rs.length} of ${rows.length}` : plural(rows.length, "row"));
    el.querySelector(".scroll").innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    el.querySelector(".scroll").scrollLeft = x;
    el.querySelector(".tmorew").innerHTML = shown.length < rs.length ? `<button class="b sm tmore" data-all>Show all ${rs.length.toLocaleString()} rows</button>` : "";
    pinColumns(el.querySelector(".scroll"));
    if (ME) refreshAvatars();
  }
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    const sortBy = (th) => {
      const i = +th.dataset.i;
      if (cols[i].nosort) return;
      if (state.by === i) state.asc = !state.asc; else { state.by = i; state.asc = !!cols[i].left; }
      render();
      const nt = el.querySelector(`th[data-i="${i}"]`); if (nt && document.activeElement === document.body) nt.focus({ preventScroll: true });
      announce(`Sorted by ${cols[i].label}, ${state.asc ? "ascending" : "descending"}`);
    };
    el.addEventListener("click", (e) => {
      if (e.target.closest(".defbtn")) return;
      if (e.target.closest("[data-all]")) { state.all = true; render(); return; }
      if (e.target.closest("[data-csv]")) {
        const rs = current();
        downloadText((opts.name || (document.title.split(" · ")[0] || "table")).replace(/[^\w-]+/g, "_") + ".csv",
          toCSV(cols.map((c) => c.label), rs.map((r) => cols.map((c) => { const v = val(c, r); return typeof v === "number" && !c.html ? v : stripHtml(c.html ? c.html(r) : fmt(c.spec, v)).replace(/^—$/, ""); }))));
        return;
      }
      if (e.target.closest("[data-copy]")) {
        const rs = current();
        copyText([cols.map((c) => c.label).join("\t"), ...rs.map((r) => cols.map((c) => stripHtml(c.html ? c.html(r) : fmt(c.spec, val(c, r)))).join("\t"))].join("\n"), `Copied ${plural(rs.length, "row")} — paste into a spreadsheet`);
        return;
      }
      const th = e.target.closest("th");
      if (th) { sortBy(th); return; }
      if (!e.target.closest("a, button, input, select")) { const tr = e.target.closest("tr[data-go]"); if (tr && tr.dataset.go) location.hash = "#/" + tr.dataset.go; }
    });
    el.addEventListener("keydown", (e) => { const th = e.target.closest && e.target.closest("th[data-i]"); if (th && (e.key === "Enter" || e.key === " ") && !e.target.classList.contains("defbtn")) { e.preventDefault(); sortBy(th); } });
    const inp = el.querySelector(".tq");
    if (inp) inp.addEventListener("input", debounce(() => { state.q = inp.value.trim(); render(); }, 120));
    render();
  });
  const bar = tools ? `<div class="tbar tb"><input class="tq" type="search" placeholder="Filter rows…" aria-label="Filter rows"><span class="tcount">${plural(rows.length, "row")}</span><span class="sp"></span><button class="b sm ghost" data-copy title="Copy as tab-separated text, for a spreadsheet">Copy</button><button class="b sm ghost" data-csv title="Download these rows as CSV">CSV ↓</button></div>` : "";
  return `<div id="${id}" class="tbl">${bar}<div class="scroll sx"></div><div class="tmorew"></div></div>`;
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
  const ti = t.cols.indexOf("Team");
  return table(cols, t.rows, { teamOf: ti >= 0 ? (r) => r[ti] : undefined, ...opts });
}
const idx = (t, c) => t.cols.indexOf(c);

// ---------- tiny SVG charts (no library): bars with labels, and a line
function barChart(items, o = {}) {
  // items: [{label, v, cls, title, href}]
  if (!items.length) return "";
  const W = o.w || 640, H = o.h || 170, pl = 34, pb = 22, pt = 14;
  const vs = items.map((x) => x.v).filter((v) => typeof v === "number");
  if (!vs.length) return "";
  const lo = Math.min(0, ...vs), hi = Math.max(0, ...vs) || 1;
  const y = (v) => pt + (H - pt - pb) * (1 - (v - lo) / (hi - lo || 1));
  const bw = (W - pl) / items.length;
  const ticks = [lo, (lo + hi) / 2, hi].filter((v, i, a) => a.indexOf(v) === i);
  const f = o.fmt || ((v) => fmt({ d: 0 }, v));
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || "chart")}">
    ${ticks.map((t) => `<line class="gl" x1="${pl}" x2="${W}" y1="${y(t)}" y2="${y(t)}"/><text x="${pl - 4}" y="${y(t) + 4}" text-anchor="end">${stripHtml(f(t))}</text>`).join("")}
    ${items.map((x, i) => { if (typeof x.v !== "number") return ""; const y0 = y(Math.max(0, x.v)), h = Math.max(1, Math.abs(y(x.v) - y(0)));
      const bar = `<rect class="b ${x.cls || ""}${x.v < 0 ? " neg" : ""}" x="${pl + i * bw + bw * 0.15}" y="${y0}" width="${bw * 0.7}" height="${h}" rx="2"><title>${esc(x.title || x.label + ": " + stripHtml(f(x.v)))}</title></rect>`;
      return (x.href ? `<a href="${esc(x.href)}">${bar}</a>` : bar) + (items.length <= 24 || i % Math.ceil(items.length / 24) === 0 ? `<text x="${pl + i * bw + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(x.label)}</text>` : ""); }).join("")}
    <line class="ax" x1="${pl}" x2="${W}" y1="${y(0)}" y2="${y(0)}"/></svg>`;
}

// ---------- pages
const routes = {
  "": home, teams, team, player, records, h2h, trades, draft, search, faab, data, game, week, pick, nfl, predict, weeks, compare, calc,
};

// ---------- live layer: rosters and traded picks straight from Sleeper on open.
// Stats come from the last main build (the site redeploys after each one); rosters
// and pick ownership come from Sleeper as of this page view, so a trade made since
// the build already shows. Three small requests (~40 KB, ~0.2 s); on any failure or
// after 4 s the page keeps the build's rosters and says so.
let liveP = null, nflP = null, liveStatus = "pending";
const loadNfl = () => nflP || (nflP = load("nfl_players.json").catch(() => { nflP = null; return {}; }));
// a failed or slow answer is not kept: the next page that needs Sleeper asks again
// (the first try waits 4 s, a retry 8 s), and the Retry chip asks at once
function loadLive(force) {
  if (liveP && !force) return liveP;
  const tries = (loadLive.tries = (loadLive.tries || 0) + 1);
  liveP = (async () => {
    const meta = await load("meta.json");
    if (!meta.league_id) return null;
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), tries > 1 ? 8000 : 4000);
    try {
      const base = `https://api.sleeper.app/v1/league/${meta.league_id}`;
      const [rosters, users, traded, league] = await Promise.all(["/rosters", "/users", "/traded_picks", ""].map((p) =>
        fetch(base + p, { signal: ctl.signal, cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(p || "league"); return r.json(); })));
      const uname = Object.fromEntries(users.map((u) => [u.user_id, u.display_name]));
      const canon = (n) => meta.teams.find((t) => t.toLowerCase() === String(n || "").toLowerCase()) || n;
      const byRid = {}, rosterOf = {}, owner = {};
      for (const r of rosters) {
        const t = canon(uname[r.owner_id]);
        byRid[r.roster_id] = t;
        rosterOf[t] = { players: r.players || [], starters: new Set(r.starters || []), taxi: new Set(r.taxi || []), ir: new Set(r.reserve || []),
                        rec: r.settings ? { w: r.settings.wins, l: r.settings.losses, faab: r.settings.waiver_budget_used, moves: r.settings.total_moves } : null };
        for (const p of r.players || []) owner[p] = t;
      }
      const picks = traded.map((p) => [+p.season, +p.round, byRid[p.roster_id], byRid[p.owner_id]]);
      // team avatars and names, the league's logo: shown on every page from now on
      const info = {};
      for (const u of users) {
        const md = u.metadata || {}, t = canon(u.display_name);
        info[t] = { av: md.avatar || (u.avatar ? `https://sleepercdn.com/avatars/thumbs/${u.avatar}` : ""), name: md.team_name || "" };
      }
      if (JSON.stringify(info) !== JSON.stringify(TINFO)) { TINFO = info; prefs.set("lotg:teaminfo", info); refreshAvatars(); }
      if (league) {
        const lg = { name: league.name, av: league.avatar ? `https://sleepercdn.com/avatars/thumbs/${league.avatar}` : "" };
        prefs.set("lotg:league", lg); showLeague(lg);
      }
      liveStatus = "ok";
      return { at: new Date(), rosterOf, owner, picks, byRid, league };
    } catch (e) {
      liveStatus = "failed";
      liveP = null;
      return null;
    } finally { clearTimeout(timer); }
  })();
  return liveP;
}
// the league's Sleeper logo and name in the header and as the tab icon
function showLeague(lg) {
  if (!lg) return;
  const el = document.getElementById("logo");
  if (lg.av && el && el.tagName !== "IMG") {
    const img = document.createElement("img");
    img.className = "logo"; img.id = "logo"; img.alt = ""; img.src = lg.av; img.width = 32; img.height = 32;
    img.onerror = () => img.replaceWith(el);
    el.replaceWith(img);
    const fav = document.getElementById("favicon"); if (fav) { fav.href = lg.av; fav.type = "image/png"; }
  }
  const n = document.getElementById("lname"); if (n && lg.name) n.textContent = lg.name;
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
const liveNote = (live) => live ? `<span class="chip ok" title="Rosters read from Sleeper when this page opened"><span class="dotl"></span>live from Sleeper ${live.at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>`
  : (liveStatus === "failed" ? '<span class="chip live" title="Sleeper did not answer in time: rosters are as of the last build">Sleeper unreachable: as of the last build <button class="b mini" data-relive>Retry</button></span>' : '<span class="chip">as of the last build</span>');

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
  setTitle(`${meta.season} season`);
  // who has clinched / is out, from the standings and the regular-season games left
  const regW = (LWh.playoff || {}).regular_weeks || 14, spots = (LWh.playoff || {}).teams || 4;
  const wins = Object.fromEntries(h.standings.map((r) => [r.team, r.w]));
  const leftG = Object.fromEntries(h.standings.map((r) => [r.team, Math.max(0, regW - r.w - r.l)]));
  const CL = clinchStatus(wins, leftG, spots);
  const oddsCell = (t, v, cap) => oddsText(v == null ? null : v / 100, !cap && CL.sure.has(t), CL.out.has(t), true);
  const odds = {};
  (h.forecast?.odds || []).forEach((o) => (odds[o.team] = o));
  const hasOdds = h.forecast && h.forecast.odds;
  const formHtml = (f) => `<span class="form" aria-label="Last ${f.length}: ${f.split("").join(", ")}">${f.split("").map((c) => `<b class="${c}">${c}</b>`).join("")}</span>`;
  const cols = [
    { k: "rank", label: "#", html: (r) => r.rank <= 3 ? `<span class="medal m${r.rank}">${r.rank}</span>` : String(r.rank) },
    { k: "team", label: "Team", left: true, html: (r) => `${teamLink(r.team)}${CL.sure.has(r.team) ? ' <span class="chip ok" title="Clinched a playoff spot">x</span>' : CL.out.has(r.team) ? ' <span class="chip" title="Eliminated from the playoffs">e</span>' : ""}` },
    { k: (r) => r.w - r.l, label: "W-L", html: (r) => `<b>${r.w}-${r.l}</b>` },
    { k: "pf", label: "PF", spec: { d: 2 } },
    { k: "pa", label: "PA", spec: { d: 2 } },
    { k: (r) => r.pf - r.pa, label: "Diff", html: (r) => `<span class="${r.pf >= r.pa ? "pos" : "neg"}">${signed({ d: 2 }, r.pf - r.pa)}</span>`, title: "Points for minus points against" },
    { k: "max_pf", label: "Max PF", spec: { d: 2 } },
    { k: (r) => +r.ap.split("-")[0], label: "All-play", html: (r) => r.ap, title: "Record if every team played every other team every week" },
    { k: "streak", label: "Streak", left: true, html: (r) => r.streak ? `<span class="${String(r.streak).startsWith("W") ? "w" : "lo"}">${esc(r.streak)}</span>` : "" },
    { k: "form", label: "Last 5", left: true, html: (r) => formHtml(r.form), nosort: true },
  ];
  if (hasOdds) cols.push(
    { k: (r) => odds[r.team]?.playoffs, label: "Playoffs", html: (r) => oddsBar(oddsCell(r.team, odds[r.team]?.playoffs), (odds[r.team]?.playoffs ?? 0) / 100) },
    { k: (r) => odds[r.team]?.finals, label: "Final", html: (r) => oddsCell(r.team, odds[r.team]?.finals, true) },
    { k: (r) => odds[r.team]?.champion, label: "Title", html: (r) => `<b>${oddsCell(r.team, odds[r.team]?.champion, true)}</b>` },
    { k: (r) => odds[r.team]?.wins, label: "Proj. wins", html: (r) => fmt({ d: 2 }, odds[r.team]?.wins) },
  );
  // this week's headlines
  const res = h.results || [];
  const sides = res.flatMap((g) => [{ t: g.a, p: g.pa, o: g.b, q: g.pb }, { t: g.b, p: g.pb, o: g.a, q: g.pa }]);
  const top = sides.slice().sort((x, y) => y.p - x.p)[0];
  const close = res.slice().sort((x, y) => Math.abs(x.pa - x.pb) - Math.abs(y.pa - y.pb))[0];
  const blow = res.slice().sort((x, y) => Math.abs(y.pa - y.pb) - Math.abs(x.pa - x.pb))[0];
  const fav = hasOdds ? h.forecast.odds.slice().sort((x, y) => (y.champion ?? 0) - (x.champion ?? 0))[0] : null;
  const leader = h.standings.slice().sort((x, y) => x.rank - y.rank)[0];
  const meRow = ME && h.standings.find((r) => r.team === ME);
  const gLink = (g) => `#/game/${meta.season}/${meta.week}/${tslug(g.a)}`;
  const heroT = (lab, val, sub, href) => `<div class="tile">${href ? `<a href="${href}">` : ""}<span>${lab}</span><b>${val}</b>${sub ? `<small>${sub}</small>` : ""}${href ? "</a>" : ""}</div>`;
  const hero = [
    meRow ? heroT("★ Your team", `${esc(ME)} ${meRow.w}-${meRow.l}`, `${ordinal(meRow.rank)} place${odds[ME] ? " · " + oddsCell(ME, odds[ME].playoffs) + " playoffs" : ""}`, `#/team/${tslug(ME)}`) : "",
    leader ? heroT("League leader", esc(leader.team), `${leader.w}-${leader.l} · ${fmt({ d: 2 }, leader.pf)} PF`, `#/team/${tslug(leader.team)}`) : "",
    top ? heroT(`Top score · ${esc(meta.week_name)}`, `${esc(top.t)} ${fmt({ d: 2 }, top.p)}`, `vs ${esc(top.o)}`, `#/game/${meta.season}/${meta.week}/${tslug(top.t)}`) : "",
    close ? heroT("Closest game", `${fmt({ d: 2 }, Math.abs(close.pa - close.pb))} pts`, `${esc(close.a)} v ${esc(close.b)}`, gLink(close)) : "",
    blow && blow !== close ? heroT("Biggest blowout", `${fmt({ d: 2 }, Math.abs(blow.pa - blow.pb))} pts`, `${esc(blow.pa > blow.pb ? blow.a : blow.b)} over ${esc(blow.pa > blow.pb ? blow.b : blow.a)}`, gLink(blow)) : "",
    fav ? heroT("Title favourite", esc(fav.team), `${oddsCell(fav.team, fav.champion, true)} to win it all`, `#/team/${tslug(fav.team)}`) : "",
  ].join("");
  const games = res.map((g) => {
    const aw = g.pa > g.pb, m = Math.abs(g.pa - g.pb);
    return `<a class="game${ME && (g.a === ME || g.b === ME) ? " mine" : ""}" href="${gLink(g)}" title="Open the matchup">
      <div class="${aw ? "won" : ""}"><span>${avatar(g.a)}${esc(g.a)}</span><span>${fmt({ d: 2 }, g.pa)}</span></div>
      <div class="${aw ? "" : "won"}"><span>${avatar(g.b)}${esc(g.b)}</span><span>${fmt({ d: 2 }, g.pb)}</span></div>
      <div class="gm"><span>${aw ? esc(g.a) : esc(g.b)} by ${fmt({ d: 2 }, m)}</span><span>${m < 5 ? "nail-biter" : m > 50 ? "blowout" : ""}</span></div></a>`;
  }).join("");
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
  const nItems = (g) => g.secs.reduce((a, s) => a + s.items.length, 0);
  const digestHtml = groups.map((g, gi) => `<details ${gi < 2 && !g.edits ? "open" : ""}><summary>${esc(g.name)} <span class="muted small">(${nItems(g)})</span></summary>
      ${g.secs.map((s) => `${s.title === g.name ? "" : `<h3>${esc(s.title)}</h3>`}<ul>${s.items.slice(0, 8).map(item).join("")}</ul>
      ${s.items.length > 8 ? `<details><summary class="small muted">${s.items.length - 8} more</summary><ul>${s.items.slice(8).map(item).join("")}</ul></details>` : ""}`).join("")}
    </details>`).join("");
  const fcNote = h.forecast?.error ? `<p class="muted small">Forecast unavailable this build.</p>` :
    hasOdds ? `<p class="muted small">Odds: ${h.forecast.sims.toLocaleString()} simulations of the rest of ${h.forecast.year} from the league's roster projection (lotg_support.forecast). Reads no news. <span class="chip ok">x</span> clinched a playoff spot · <span class="chip">e</span> eliminated · the dashed line is the playoff cut (top ${spots}). <a href="#/predict">Play out the rest of the season →</a></p>` : "";
  $app.innerHTML = `
    <div class="page-head"><div><h1>${meta.season} season</h1>
      <p class="lede">Through ${esc(meta.week_name)} · rebuilt ${esc(meta.built)}${regW > meta.week ? ` · ${plural(regW - meta.week, "regular-season week")} left` : ""}</p></div>
      <div class="actions">${ME ? "" : '<a class="btn sec" href="#/mine">★ Pick your team</a>'}${shareBtn()}</div></div>
    <div class="hero">${hero}</div>
    <div class="card nocv"><div class="chead"><h2>Standings${hasOdds ? " &amp; odds" : ""}</h2><a class="small" href="#/teams">All-time standings →</a></div>${table(cols, h.standings, { sort: 0, asc: true, cut: spots, teamOf: (r) => r.team, rowLink: (r) => `team/${tslug(r.team)}`, tools: false, name: `standings_${meta.season}` })}${fcNote}</div>
    <div class="card" id="watch"><h2>Record watch</h2><p class="muted small">Checking this week's games on Sleeper…</p><div class="skel ln"></div><div class="skel ln" style="width:70%"></div></div>
    <div class="card"><div class="chead"><h2>${esc(meta.week_name)} results</h2><span class="small"><a href="#/week/${meta.season}/${meta.week}">Week page</a> · <a href="#/weeks/${meta.season}">every ${meta.season} week</a></span></div><div class="games">${games}</div></div>
    ${B ? `<div class="card"><div class="chead"><h2>FAAB values</h2><a class="small" href="#/faab">Full board →</a></div><p class="muted small">Board of ${esc(B.as_of)} · stats-only values in league FAAB</p>
      <ol>${B.players.slice(0, 5).map((x) => `<li>${playerLink(x.name)} ${posBadge(x.pos)} <b>${money(x.value)}</b>${x.owner ? ` <span class="muted small">${esc(ownerTeam(x.owner, meta.teams))}</span>` : ""}</li>`).join("")}</ol>
      <p><a class="btn sec" href="rate/">Rate the board</a></p></div>` : ""}
    <div class="card digest"><div class="chead"><h2>This week in the digest</h2>${groups.length ? `<span><button class="b sm ghost" id="dgopen">Expand all</button><button class="b sm ghost" id="dgclose">Collapse all</button></span>` : ""}</div>
      ${d.lede ? `<p>${esc(d.lede)}</p>` : `<p class="muted">No digest yet.</p>`}${digestHtml}</div>`;
  const dg = (open) => () => $$(".digest details", $app).forEach((x) => (x.open = open));
  if ($("#dgopen")) { $("#dgopen").onclick = dg(true); $("#dgclose").onclick = dg(false); }
  recordWatch(meta).catch((e) => {
    const el = document.getElementById("watch");
    if (el) el.innerHTML = `<h2>Record watch</h2><p class="muted small">${e && e.message === "offline" ? "Sleeper did not answer in time." : "Couldn't check this week's games" + (e && e.message ? ": " + esc(e.message) : ".")} <button class="b sm" id="rwretry">Try again</button></p>`;
    const b = document.getElementById("rwretry");
    if (b) b.onclick = () => { b.disabled = true; b.textContent = "Checking…"; loadLive(true).then(() => recordWatch(meta)).catch(() => { b.disabled = false; b.textContent = "Try again"; toast("Sleeper is still unreachable"); }); };
  });
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
// the normal curve (Abramowitz-Stegun 7.1.26) and its inverse (Acklam)
const Phi = (z) => { const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2); return 0.5 * (1 + (z < 0 ? -y : y)); };
function invPhi(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const q0 = Math.min(p, 1 - p);
  let x;
  if (q0 < 0.02425) { const q = Math.sqrt(-2 * Math.log(q0)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); x = p < 0.5 ? x : -x; return p < 0.5 ? x : x; }
  const q = p - 0.5, r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
// The Sleeper app-style win % (lotg_support.gametime.app_win_pct): A^k/(A^k+B^k),
// k = 3.757/(1-f)^0.6, f = share of the two projected finals scored; 1-99% held.
const appPct = (a, b, f, hold) => {
  a = Math.max(a, 0.01); b = Math.max(b, 0.01);
  const k = 3.757 / Math.pow(1 - Math.min(Math.max(f, 0), 0.999), 0.6), x = Math.min(Math.max(k * Math.log(b / a), -700), 700), p = 1 / (1 + Math.exp(x));
  return hold ? Math.min(Math.max(p, 0.01), 0.99) : p;
};
const r2 = (v) => v == null ? null : Math.round(v * 100) / 100, r4 = (v) => v == null ? null : Math.round(v * 1e4) / 1e4;
// The matchup's comeback columns for one side (lotg_support.gametime, Sleeper set):
// own / opp = its starters as [kickoff ms or null, points, Sleeper projection, out?].
function comebackSide(own, opp, pf, pa, stageT, lateT) {
  const GH = 3 * 36e5, S = {}, choke = {};
  const mu = (s) => s[3] ? 0 : s[2];
  const fromT = (pl, t) => pl.reduce((a, s) => a + (s[0] != null && s[0] >= t ? s[1] : 0), 0);
  const leftOf = (pl, t) => pl.filter((s) => s[0] != null && s[0] >= t);
  const ks = [...new Set(own.concat(opp).map((s) => s[0]).filter((k) => k != null))].sort((x, y) => x - y);
  const ws = []; let prev = null;
  for (const k of ks) { if (prev === null || k - prev >= GH) ws.push(k); prev = k; }
  const share = (oi, pi, a, b) => a + b > 0 ? (oi + pi) / (a + b) : 0;
  const appZ = (a, b, f) => Math.max(-10, Math.min(10, invPhi(Math.min(Math.max(appPct(a, b, f, false), 1e-12), 1 - 1e-12))));
  const sumMu = (pl) => pl.reduce((x, s) => x + mu(s), 0);
  const check = (t) => {
    const ol = leftOf(own, t), pl = leftOf(opp, t), oi = pf - fromT(own, t), pi = pa - fromT(opp, t);
    const a = oi + sumMu(ol), b = pi + sumMu(pl), z = appZ(a, b, share(oi, pi, a, b));
    return [z, ol.reduce((x, s) => x + s[1] - mu(s), 0), pl.reduce((x, s) => x + mu(s) - s[1], 0), z, oi - pi];
  };
  const ownPart = (h, l) => { const o = h[1] - l[1], turn = o + (h[2] - l[2]); return 0.25 + 0.75 * (turn > 0 ? Math.min(1, Math.max(0, o / turn)) : 0); };
  const size = (pts, final, first, side) => {
    const later = pts.map((p) => [Phi(p[0]), p]).concat([[final, [null, 0, 0]]]);
    let best = 0;
    (first ? pts.slice(0, 1) : pts).forEach((h, i) => {
      if (!(h[4] !== undefined && (side === "down" ? h[4] < 0 : h[4] > 0))) return;
      const depth = Math.max(0, -h[3]);
      if (depth) for (const [c, p] of later.slice(i + 1)) best = Math.max(best, depth * c * ownPart(h, p));
    });
    return r2(Math.min(100, best * 100 / 3.5));
  };
  const finalOf = (pl, fin, t) => t == null ? sumMu(pl) + (fin - pl.reduce((x, s) => x + s[1], 0)) : fin - fromT(pl, t) + sumMu(leftOf(pl, t));
  const livePct = (t) => { const a = finalOf(own, pf, t), b = finalOf(opp, pa, t); return appPct(a, b, share(pf - fromT(own, t), pa - fromT(opp, t), a, b), true); };
  const won = pf > pa, final = won ? 1 : pf === pa ? 0.5 : 0, over = (p) => won && p < 0.5 ? 1 - p : null;
  const pre = appPct(finalOf(own, pf, null), finalOf(opp, pa, null), 0, true);
  S.sl_pre = r2(pre); S.sl_prediff = r2(2 * pre - 1); S.sl_preover = r2(over(pre));
  const lows = [pre].concat(ws.slice(1).map(livePct)).filter((p) => p < 0.5).map((p) => 1 - p);
  S.sl_largest = won && lows.length ? r2(Math.max(...lows)) : null;
  const zw = ws.slice(1).map(check);
  S.sl_cb = ws.length ? size(zw, final, false, "down") : null;
  choke.all = ws.length ? (won ? size(zw, final, false, "up") : 0) : null;
  [0, 1, 2].forEach((i) => {
    const t = i === 2 ? (ws.length && lateT != null && ws[ws.length - 1] >= lateT ? ws[ws.length - 1] : null) : stageT[i];
    const keys = ["cb_m_", "cb_mo_", "cb_po_", "cb_own_", "cb_pof_", "cb_ppl_", "cb_mpl_", "cb_pos_", "sl_cb_", "sl_wo_"];
    if (t == null) { keys.forEach((k) => (S[k + i] = null)); choke[i] = null; return; }
    const oi = r2(pf - fromT(own, t)), pi = r2(pa - fromT(opp, t)), m = r2(oi - pi), left = leftOf(own, t).length;
    const deficit = r2(pa - oi), cb = won && deficit > 0, mo = won && m < 0 ? -m : null;
    S["cb_m_" + i] = m; S["cb_mo_" + i] = mo; S["cb_po_" + i] = cb ? deficit : null;
    S["cb_own_" + i] = pf > 0 ? r4((pf - oi) / pf) : null;
    S["cb_pof_" + i] = cb && pa > 0 ? r4(deficit / pa) : null;
    S["cb_ppl_" + i] = cb && left > 0 ? r2(deficit / left) : null;
    S["cb_mpl_" + i] = mo != null && left ? r2(mo / left) : null;
    S["cb_pos_" + i] = mo != null && pi > 0 ? r4(mo / pi) : null;
    const k0 = ws.find((k) => k >= t), zs = [check(t)].concat(ws.filter((k) => k0 != null && k > k0).map(check));
    S["sl_cb_" + i] = size(zs, final, true, "down"); choke[i] = won ? size(zs, final, true, "up") : 0;
    S["sl_wo_" + i] = r2(over(livePct(t)));
  });
  return { S, choke };
}
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
  // Sleeper's projections for the week, in this league's scoring (lotg_support.projections):
  // they move until kickoff, so every projection stat counts until then
  const KEEP = new Set(["pass_yd", "pass_td", "pass_int", "pass_2pt", "rush_yd", "rush_td", "rush_2pt", "rec", "rec_yd",
    "rec_td", "rec_2pt", "fum", "fum_lost", "fum_rec_td", "st_td"]);
  let proj = null;
  try {
    const [lg, ...pp] = await Promise.all([fetch(`https://api.sleeper.app/v1/league/${meta.league_id}`).then((r) => r.json()),
      ...["QB", "RB", "WR", "TE"].map((pos) => fetch(`https://api.sleeper.app/projections/nfl/${LW.season}/${wk}?season_type=regular&position[]=${pos}`).then((r) => r.json()))]);
    const sc = lg.scoring_settings || {};
    proj = {};
    for (const arr of pp) for (const r of arr || []) {
      const st = r.stats || {};
      if (!("pts_ppr" in st)) continue;               // adp only: no projection
      let v = 0;
      for (const [k, x] of Object.entries(st)) if (typeof x === "number" && (KEEP.has(k) || k.startsWith("bonus_")) && sc[k] != null) v += x * sc[k];
      proj[r.player_id] = v;
    }
  } catch (e) { proj = null; }
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
      const f = out ? 0 : left(pid), kt = ko[(nfl[pid] || [])[2]];
      // his NFL game has kicked off (a bye, or out before kickoff, is not a start)
      const kicked = !!kt && nowET >= new Date(kt);
      // a bench player on a bye or out is absent: not in the roster donut / under-10 counts
      // his Sleeper projection (0 when out; a hole under 0.5 falls back to his rate, standing in
      // for the build's model fallback)
      const pj = proj && proj[pid] != null && proj[pid] >= 0.5 ? proj[pid] : LW.rates[pid] ?? 3;
      return { pid, pos: (nfl[pid] || [])[1], nfl: (nfl[pid] || [])[2], st, rk: rookies.has(pid), out, mu: pj,
        slot: st ? slots[(m.starters || []).indexOf(pid)] : null, kt: kt ? +new Date(kt) : null, sp: out || !kt ? 0 : pj,
        absent: !st && (out || !ko[(nfl[pid] || [])[2]]), cur: (m.players_points || {})[pid] || 0, f, kicked, rate: LW.rates[pid] ?? 3 }; }) };
  });
  teams.forEach((t) => (t.opp = teams.findIndex((o) => o !== t && o.m.matchup_id === t.m.matchup_id)));
  const anyLeft = teams.some((t) => t.players.some((p) => p.f > 0));
  const anyPlayed = teams.some((t) => t.m.points > 0);
  const POS = ["QB", "RB", "WR", "TE"];
  // the week's stages (lotg_support.gametime): SNF = first Sunday kickoff at 7 pm+,
  // Monday = first kickoff after Sunday; the last game is per matchup (comebackSide)
  const wkKs = [...new Set(Object.values(ko).map((k) => +new Date(k)))].sort((x, y) => x - y);
  const sun = wkKs.map((k) => new Date(k)).find((d) => d.getDay() === 0);
  const sunKey = sun ? sun.toDateString() : null;
  const snfT = wkKs.find((k) => new Date(k).toDateString() === sunKey && new Date(k).getHours() >= 19) ?? null;
  const monT = sun ? wkKs.find((k) => k > new Date(sun.getFullYear(), sun.getMonth(), sun.getDate() + 1).getTime() - 1) ?? null : null;
  const lateT = sun ? new Date(sun.getFullYear(), sun.getMonth(), sun.getDate(), 19).getTime() : null;
  // streaks carry from last week's exports: only when they run through last week
  const fresh = Object.values(LW.prev || {}).some((v) => v[0] === wk - 1);
  const stkPrev = (kind, who, sid) => { const v = ((LW.streaks || {})[kind] || {})[who]; return v && v[sid] ? v[sid][2] : 0; };
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
    for (const s of LW.stats.filter((s) => s.kind === "team" && !s.streak)) reach(s.id, t.team, (R) => R.team[i][s.id], resultScopes([]).map(([sc, c]) => [sc, c === 0 ? 0 : { team: i, w: c }]), { i, dep: s.dep || (s.id === "pa" || s.id === "margin" ? "both" : "own") });
    if (fresh) for (const s of LW.stats.filter((s) => s.kind === "team" && s.streak)) reach(s.id, t.team, (R) => R.stk.team[i][s.id], [["all", 0]], { i, dep: s.dep, streak: true });
    if (t.team < teams[t.opp].team) for (const s of LW.stats.filter((s) => s.kind === "game"))
      reach(s.id, `${t.team} v ${teams[t.opp].team}`, (R) => R.game[i][s.id], [["all", 0]], { i, dep: s.dep || "both" });
    t.players.forEach((p, k) => {
      const role = p.st ? "st" : "bn";
      const sc = () => resultScopes(p.rk ? [["rookie", 0]] : [])
        .map(([s, c]) => [s, c === 0 ? 0 : { team: i, w: c }]);
      const get = (R) => R.pts[i][k], who = "pid:" + p.pid;
      const cx = { i, p, dep: "self" };
      reach(`p_${role}_ALL`, who, get, sc(), cx); reach(`p_ro_ALL`, who, get, sc(), cx);
      if (POS.includes(p.pos)) { reach(`p_${role}_${p.pos}`, who, get, sc(), cx); reach(`p_ro_${p.pos}`, who, get, sc(), cx); }
      if (p.st) reach("p_share", who, (R) => R.team[i].pf ? R.pts[i][k] / R.team[i].pf : null, [["all", 0]], { i, p, dep: "self", own: true });
      if (fresh) for (const s of LW.stats.filter((s) => s.kind === "player" && s.streak)) reach(s.id, who, (R) => R.stk.pl[i][k][s.id], [["all", 0]], { i, p, dep: s.dep, streak: true });
    });
  });
  // Sleeper Lineup Boldness (lotg_support.boldness.team_boldness on Sleeper projections):
  // the best lineup the projections allowed over the slots filled (a dead start, out or on
  // a bye, counts as empty) from his starters and available bench, minus the lineup set
  const bold = (t) => {
    const live = t.players.filter((p) => p.st && !p.out && p.kt != null), used = new Set();
    const pool = t.players.filter((p) => (p.st && !p.out && p.kt != null) || (!p.st && !p.out && p.kt != null)).map((p) => ({ pos: p.pos, p: p.sp }))
      .sort((a, b) => b.p - a.p);
    let best = 0;
    for (const sl of live.map((p) => p.slot).sort((a, b) => (fits[a] || []).length - (fits[b] || []).length)) {
      const i = pool.findIndex((x, j) => !used.has(j) && (fits[sl] || []).includes(x.pos));
      if (i >= 0) { used.add(i); best += pool[i].p; }
    }
    return r2(Math.max(0, best - live.reduce((a, p) => a + p.sp, 0)));
  };
  const BOLD = teams.map(bold);
  const plays = (t, pts) => t.players.map((p, k) => [p, pts[k]]).filter(([p]) => p.st).map(([p, v]) => [p.kt, v, p.sp, (p.out || p.kt == null) && v === 0]);
  const TSTK = LW.stats.filter((x) => x.streak && x.kind === "team"), PSTK = LW.stats.filter((x) => x.streak && x.kind === "player");
  const run = (pts) => {
    const team = teams.map((t, i) => teamStats(t, pts[i]));
    team.forEach((S, i) => withOpp(S, team[teams[i].opp]));
    teams.forEach((t, i) => {
      const S = team[i], j = t.opp;
      S.sl_proj = r2(t.players.reduce((a, p) => a + (p.st ? p.sp : 0), 0));
      S.sl_above = r2(S.pf - S.sl_proj); S.sl_bold = BOLD[i];
      const { S: C, choke } = comebackSide(plays(t, pts[i]), plays(teams[j], pts[j]), r2(S.pf), r2(team[j].pf), [snfT, monT], lateT);
      Object.assign(S, C);
      const O = team[j];                       // the choke goes on the loser's row
      O.sl_ch = choke.all; [0, 1, 2].forEach((k) => (O["sl_ch_" + k] = choke[k]));
    });
    teams.forEach((t, i) => { team[i].sl_diff = r2(team[i].sl_proj - team[t.opp].sl_proj); });
    const game = teams.map((t, i) => gameStats(team[i], team[t.opp]));
    game.forEach((G, i) => { const A = team[i], O = team[teams[i].opp]; G.c_slproj = r2(A.sl_proj + O.sl_proj); G.c_slabove = r2(A.sl_above + O.sl_above); });
    // streaks: last week's count + 1 if it keeps going this week, else it ends
    const stk = { team: teams.map(() => ({})), pl: teams.map((t) => t.players.map(() => ({}))) };
    if (fresh) {
      const pf = team.map((S) => S.pf), sorted = pf.slice().sort((a, b) => b - a), n = pf.length;
      const med = n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
      const wins = team.map((S) => S.margin > 0), wm = team.filter((S, i) => wins[i]).map((S) => S.margin);
      const eff = team.map((S) => S.eff), topShare = team.map((S) => S.pf ? S.hist / S.pf : 0);
      const cond = {
        "Win streak": (i) => wins[i], "Loss streak": (i) => team[i].margin < 0,
        "Win streak counting previous season": (i) => wins[i], "Loss streak counting previous season": (i) => team[i].margin < 0,
        "Highest score streak": (i) => pf[i] === sorted[0], "Lowest score streak": (i) => pf[i] === sorted[n - 1],
        "Narrowest victory streak": (i) => wins[i] && team[i].margin === Math.min(...wm),
        "Largest blowout streak": (i) => wins[i] && team[i].margin === Math.max(...wm),
        "Most efficient streak": (i) => eff[i] === Math.max(...eff), "Least efficient streak": (i) => eff[i] === Math.min(...eff),
        "Top half streak": (i) => pf[i] >= med, "Bottom half streak": (i) => pf[i] < med, "Podium streak": (i) => pf[i] >= sorted[2],
        "One-man army streak": (i) => topShare[i] === Math.max(...topShare),
        "Most bench points streak": (i) => team[i].bench === Math.max(...team.map((S) => S.bench)), "150+ PF streak": (i) => pf[i] >= 150 };
      teams.forEach((t, i) => TSTK.forEach((x) => { const c = cond[x.streak]; if (c) stk.team[i][x.id] = c(i) ? stkPrev("team", t.team, x.id) + 1 : 0; }));
      // player awards over every lineup this week
      const all = []; teams.forEach((t, i) => t.players.forEach((p, k) => all.push({ i, k, p, v: pts[i][k] })));
      // award rules = the build's (src/lotg.py, 2026-11-18): an injured / suspended player
      // (out and on 0 with a game this week; a bye stays eligible) can't win; every tie wins,
      // except a tie at 0 (2+ on 0): nobody
      const el = all.filter((x) => !(x.p.out && x.v === 0 && x.p.kt != null));
      const win = (xs, val, how) => {
        const v = xs.map((x) => r2(val(x)));
        if (!v.length) return new Set();
        const e = how === "max" ? Math.max(...v) : Math.min(...v), t = xs.filter((x, j) => v[j] === e);
        return new Set(e === 0 && t.length > 1 ? [] : t);
      };
      const pv = (x) => x.v, est = el.filter((x) => x.p.st), ebn = el.filter((x) => !x.p.st);
      const W = {
        "Player of the week streak": win(est, pv, "max"), "Dud of the week streak": win(est, pv, "min"),
        "Benchwarmer of the week streak": win(ebn, pv, "max"), "Roster dud of the week streak": win(el, pv, "min"),
        "Captain streak": win(est.filter((x) => team[x.i].pf > 0), (x) => x.v / team[x.i].pf * 1e4, "max"),
        "Highest starter on team streak": new Set(), "Lowest starter on team streak": new Set() };
      for (const P of POS) {
        W[`${P} of the week streak`] = win(est.filter((y) => y.p.pos === P), pv, "max");
        W[`Bench ${P} of the week streak`] = win(ebn.filter((y) => y.p.pos === P), pv, "max");
      }
      teams.forEach((t, i) => {
        const ts = est.filter((x) => x.i === i);
        win(ts, pv, "max").forEach((x) => W["Highest starter on team streak"].add(x));
        win(ts, pv, "min").forEach((x) => W["Lowest starter on team streak"].add(x));
      });
      const pcond = {};
      for (const k of Object.keys(W)) pcond[k] = (x) => W[k].has(x);
      for (const n of [10, 20, 30, 40, 50]) pcond[`${n}+ point streak`] = (x) => x.v >= n;
      for (const x of all) {
        if (x.p.out || x.p.kt == null) continue;          // a bye / injury week neither adds nor breaks
        PSTK.forEach((sx) => { const c = pcond[sx.streak]; if (c) stk.pl[x.i][x.k][sx.id] = c(x) ? stkPrev("player", x.p.pid, sx.id) + 1 : 0; });
      }
    }
    return { pts, team, game, stk };
  };
  const now = run(teams.map((t) => t.players.map((p) => p.cur)));
  window.LOTG_WATCH = { wk, teams, now };          // for checking against the sheets
  // the seed: this week's live points (and the 10-minute clock)
  const rand = mulberry(hashStr(`${wk}|${+nowET}|` + teams.map((t) => t.team + ":" + t.players.map((p) => p.pid + "=" + p.cur).join(",")).join(";")));
  const gauss = () => { let u = 0, v = 0; while (!u) u = rand(); while (!v) v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const N = anyLeft ? 2000 : 1;
  // Win chances are Sleeper's (the app-style win %, lotg_support.gametime.app_win_pct, on the
  // starters' points so far + their Sleeper projections for what is left): the simulated weeks
  // are tallied by which side won each matchup, then reweighted so every matchup's win chance
  // is Sleeper's — what happens given a result is simulated, how likely the result is is Sleeper's
  const MU = teams.map((t, i) => i).filter((i) => i < teams[i].opp);
  const projFinal = (t) => t.players.reduce((a, p) => a + (p.st ? p.cur + p.sp * p.f : 0), 0);
  const curPF = (t) => t.players.reduce((a, p) => a + (p.st ? p.cur : 0), 0);
  const SLW = MU.map((i) => { const A = teams[i], B = teams[A.opp], a = projFinal(A), b = projFinal(B);
    return appPct(a, b, a + b > 0 ? (curPF(A) + curPF(B)) / (a + b) : 0, true); });
  const C = 1 << MU.length, nC = new Float64Array(C);
  const acc = targets.map(() => ({ t5: new Float64Array(C), r1: new Float64Array(C), ti: new Float64Array(C), sum: new Float64Array(C), seen: new Float64Array(C) }));
  for (let n = 0; n < N; n++) {
    const R = run(teams.map((t) => t.players.map((p) => p.f > 0 ? p.cur + Math.max(0, p.mu * p.f + gauss() * Math.min(9.5, 3 + 0.35 * p.mu) * Math.sqrt(p.f)) : p.cur)));
    let c = 0;
    MU.forEach((i, k) => { if (R.team[i].margin > 0) c |= 1 << k; });
    nC[c]++;
    targets.forEach((x, j) => {
      if (x.cond && Math.sign(R.team[x.cond.team].margin) !== x.cond.w) return;
      const v = x.get(R); if (v === null || v === undefined || isNaN(v)) return;
      const A = acc[j]; A.seen[c]++; A.sum[c] += v;
      const r = boardPlace(x.b[1], v, x.d === "h");
      if (r) { A.t5[c]++; if (r === 1) A.r1[c]++; else if (r === 0.5) A.ti[c]++; }
    });
  }
  // each outcome's weight: Sleeper's chance of it over the simulation's
  const simW = MU.map((i, k) => { let w = 0; for (let c = 0; c < C; c++) if (c & (1 << k)) w += nC[c]; return w / N; });
  const W = new Float64Array(C);
  for (let c = 0; c < C; c++) W[c] = MU.reduce((w, i, k) => {
    const ps = simW[k], pa = SLW[k];
    if (!anyLeft || ps <= 0 || ps >= 1) return w;           // a result the simulation never drew: leave it
    return w * (c & (1 << k) ? pa / ps : (1 - pa) / (1 - ps));
  }, 1);
  const total = nC.reduce((a, n, c) => a + n * W[c], 0) || 1;
  const wsum = (arr) => arr.reduce((a, v, c) => a + v * W[c], 0);
  targets.forEach((x, j) => { const A = acc[j]; x.top5 = wsum(A.t5) / total * N; x.rec = wsum(A.r1) / total * N; x.tie = wsum(A.ti) / total * N; });
  const sums = acc.map((A) => wsum(A.sum)), seen = acc.map((A) => wsum(A.seen));
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
    const head = s.streak ? `Longest ${s.label.charAt(0).toLowerCase() + s.label.slice(1)}` : s.kind === "player" ? `${x.d === "h" ? "Most" : "Fewest"} ${s.label.charAt(0).toLowerCase() + s.label.slice(1)}`
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
  // nothing still counting is "certain": the top reads 99%+
  const pctTxt = (x) => x >= 0.995 ? "99%+" : x < 0.01 ? "<1%" : Math.round(x * 100) + "%";
  const fmtS = (x, v) => fmt(statById[x.stat].fmt || { d: 2 }, v);
  if (!el()) return;
  const nBoards = Object.keys(BD).length;
  // where each mark stands: "pre" (its numbers not started), "live" (still counting),
  // "done" (counting has stopped: every game it waits on is over)
  const begun = (p) => p.kicked || p.cur !== 0;
  const tBegun = (i) => teams[i].players.some(begun), tDone = (i) => teams[i].players.every((p) => p.f === 0);
  const mBegun = (i) => tBegun(i) || tBegun(teams[i].opp), mDone = (i) => tDone(i) && tDone(teams[i].opp);
  // a projection stat counts until every starter it depends on has kicked off (or has no game)
  const locked = (i) => teams[i].players.every((p) => !p.st || p.kt == null || p.kicked);
  const allDone = () => teams.every((t, i) => tDone(i)), anyBegun = () => teams.some((t, i) => tBegun(i));
  const status = (x) => {
    if (!anyLeft) return "done";
    const dep = x.dep || "own";
    if (dep === "proj_own" || dep === "proj_both") return locked(x.i) && (dep === "proj_own" || locked(teams[x.i].opp)) ? "done" : "live";
    if (dep === "league") return allDone() ? "done" : x.streak || anyBegun() ? "live" : "pre";
    if (x.p) {                                   // a player mark (his team's result too if filtered by it)
      const done = x.p.f === 0 && (!x.cond || mDone(x.i)) && (!(x.own || dep === "own") || tDone(x.i)) && (dep !== "both" || mDone(x.i));
      if (done && (begun(x.p) || x.streak)) return "done";
      return begun(x.p) || x.streak ? "live" : "pre";   // a running streak counts already
    }
    const both = dep === "both" || x.cond;
    if ((both ? mDone(x.i) : tDone(x.i)) && (both ? mBegun(x.i) : tBegun(x.i))) return "done";
    return (both ? mBegun(x.i) : tBegun(x.i)) || x.streak ? "live" : "pre";
  };
  rows.forEach((x) => (x.st = status(x)));
  const VIEWS = { "Not started": (x) => x.st === "pre", Counting: (x) => x.st === "live", Finished: (x) => x.st === "done" };
  let view = ["Counting", "Not started", "Finished"].find((v) => rows.some(VIEWS[v])) || "Not started";
  // one entry per stat, end and team / player / game, with every version of its board under it
  const SCOPE_NAME = { all: "Unfiltered", win: "In a win", loss: "In a loss", rookie: "By a rookie" };
  const LINEUP = /^(nst_|nro_|rk_|c_rk$|same_nfl$|nfl_teams$)/;   // fixed by who is rostered / started
  const groupsOf = (list) => {
    const g = new Map();
    for (const x of list) { const k = `${x.stat}|${x.d}|${x.who}`; if (!g.has(k)) g.set(k, []); g.get(k).push(x); }
    return [...g.values()].map((xs) => {
      xs.sort((a, b) => Object.keys(SCOPE_NAME).indexOf(a.sc) - Object.keys(SCOPE_NAME).indexOf(b.sc));
      return { xs, x: xs[0], p5: Math.max(...xs.map((x) => x.p5)), p1: Math.max(...xs.map((x) => x.p1 + x.pt)), n: Math.max(...xs.map((x) => x.b[0])) };
    });
  };
  // a Sleeper-projection stat on its unfiltered board has no chance to give (nothing here
  // models projections or lineups moving before kickoff): where it would rank now instead
  const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
  const isProj = (x) => /^proj_/.test(statById[x.stat].dep || "");
  const rankNow = (x) => { const r = x.curV == null ? 0 : boardPlace(x.b[1], x.curV, x.d === "h");
    return r === 1 ? "the record" : r === 0.5 ? "tying the record" : r ? `${ordinal(r)}` : "off the top 5"; };
  const odds = (x) => x.st === "done" ? `<b>${x.p1 >= 0.5 ? "record" : x.pt >= 0.5 ? "ties the record" : "top 5"}</b>`
    : isProj(x) && !x.cond ? `<b>${rankNow(x)}</b> as projected now`
    : `<b>${pctTxt(x.p5)}</b> top 5 · ${pctTxt(x.p1)} record${x.pt >= 0.01 ? ` · ${pctTxt(x.pt)} tie` : ""}`;
  const item = (G) => { const x = G.x; return `<li>
      <div class="wtop"><span><b>${esc(boardLabel({ ...x, sc: "all" }))}</b> · ${whoHtml(x.who)}</span></div>
      <div class="muted small">${x.st === "done" ? `final ${x.curV == null ? "—" : fmtS(x, x.curV)}` : `${x.st === "live" && x.curV != null ? `now ${fmtS(x, x.curV)} → ` : ""}projected ${x.med == null ? "—" : fmtS(x, x.med)}`}${statById[x.stat].kind !== "game" && (MU.includes(x.i) || MU.includes((teams[x.i] || {}).opp)) ? ` · Sleeper win % ${teams[x.i] ? Math.round(100 * (MU.includes(x.i) ? SLW[MU.indexOf(x.i)] : 1 - SLW[MU.indexOf(teams[x.i].opp)])) + "%" : ""}` : ""}</div>
      <ul class="wscopes">${G.xs.map((y) => `<li><div>${odds(y)} · <span class="muted">${SCOPE_NAME[y.sc] || esc(y.sc)}</span></div><div class="muted small">record ${fmtS(y, y.b[1][0])} (${rowLabel(statById[y.stat], y.b[2][0])}) · 5th ${fmtS(y, y.b[1][4])} · ${y.b[0].toLocaleString()} on the board</div></li>`).join("")}</ul></li>`; };
  const draw = () => {
    const groups = groupsOf(rows.filter(VIEWS[view]));
    // the preview: the view's top 20 by chance of a top-5 place on any version of the board;
    // lineup counts (already fixed by who is rostered or started) go below
    const fin = view === "Finished";
    const eligible = groups.filter((G) => !LINEUP.test(G.x.stat))
      .sort(fin ? (a, b) => b.p1 - a.p1 || b.n - a.n : (a, b) => b.p5 - a.p5 || b.p1 - a.p1 || b.n - a.n);
    const shown = eligible.slice(0, 20), rest = groups.filter((G) => !shown.includes(G)).sort((a, b) => b.p5 - a.p5 || b.p1 - a.p1);
    el().innerHTML = `<div class="chead"><h2>Record watch · week ${esc(wk)} ${liveNote(live)}</h2><button class="b sm" id="rwrefresh" title="Read the live scores again">↻ Refresh</button></div>
    <p class="muted small">${anyLeft ? (anyPlayed ? "Games under way: chances come from simulating the rest of the week." : "Before kickoff: chances come from simulating the whole week from projections.") : "Every game is over: these are where this week's numbers landed."} ${LW.stats.length} weekly stats on ${nBoards.toLocaleString()} boards (unfiltered; in a win, in a loss, by a rookie).</p>
    <div class="seg">${Object.keys(VIEWS).map((v) => { const n = groupsOf(rows.filter(VIEWS[v])).length; return `<button aria-pressed="${v === view}" data-wview="${v}"${n ? "" : " disabled"}>${v} <span class="n">${n}</span></button>`; }).join("")}</div>
    ${shown.length ? `<h3>${view} · top ${shown.length}</h3><ul class="wlist">${shown.map(item).join("")}</ul>`
      : `<p class="muted">${fin ? "No finished mark has made a top 5." : "Nothing here has even a 1% chance of a top-5 place."}</p>`}
    ${rest.length ? `<details${shown.length ? "" : " open"}><summary><b>Every other board (${rest.length})</b> <span class="muted small">— ${fin ? "the rest of the finished marks" : "beyond the top 20, and lineup counts already fixed by who is rostered or started"}</span></summary><ul class="wlist">${rest.map(item).join("")}</ul></details>` : ""}
    <details class="note info"><summary>How the record watch works</summary>Not started = no game the mark depends on has kicked off; Counting = under way (a Sleeper-projection stat counts until its games kick off and the projections lock; a streak counts from the start of the week); Finished = counting has stopped. Each mark lists every version of its board it could make: the unfiltered board (every week since 2020), and the in a win / in a loss / by a rookie versions — the chance on an "in a win" line includes the chance of winning. A Sleeper-projection stat's unfiltered line gives where it would rank as projected now, not a chance (nothing here models projections or lineups moving before kickoff); nothing still counting is called certain (99%+ at most). Win chances are Sleeper's own (its app-style win %, on points so far plus Sleeper's projections for what is left): the simulation decides what happens given a result, Sleeper how likely each result is. Top 5 follows the digest's tie rule: a mark ties its way in only if everything tied with it fits; "record" is an outright record, "tie" a share of it. Projected = the average simulated outcome. Each player is simulated from his Sleeper projection (his blended rate where Sleeper has none) for the part of his game left, with the spread real starts have had around Sleeper's projections since 2020 (about ±7 points for a 10-point projection, ±9 for 20; a team ±25, a matchup's margin ±34); a player who is out, on IR or on a bye adds nothing. ${anyLeft ? `${N.toLocaleString()} simulations, run in your browser and seeded from the live scores and a 10-minute clock: the same scores give everyone the same odds, on every reload.` : ""} Boards count every finished week since 2020 (all week types unless filtered); team marks include the semifinal +5 bonus, live points do not. Rosters count every player (taxi and IR too). <a href="#/records/team_week">Record book →</a></details>`;
    el().querySelectorAll("[data-wview]").forEach((b) => (b.onclick = () => { view = b.dataset.wview; draw(); }));
    const rf = document.getElementById("rwrefresh");
    if (rf) rf.onclick = () => { rf.disabled = true; rf.textContent = "Refreshing…"; recordWatch(meta).then(() => toast("Record watch updated")).catch(() => { toast("Sleeper did not answer"); rf.disabled = false; rf.textContent = "↻ Refresh"; }); };
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
  // the roll of honour: each finished season's champion and runner-up (team_year Result)
  const roll = {};
  for (const t of ts) {
    const sc = (c) => t.seasons.cols.indexOf(c);
    for (const r of t.seasons.rows || []) {
      const res = String(r[sc("Result")] || ""), y = r[sc("Year")];
      if (/champion/i.test(res)) (roll[y] = roll[y] || {}).champ = [t.team, r[sc("Record")]];
      else if (/^2nd/i.test(res)) (roll[y] = roll[y] || {}).second = [t.team, r[sc("Record")]];
      else if (/^3rd/i.test(res)) (roll[y] = roll[y] || {}).third = [t.team, r[sc("Record")]];
    }
  }
  const years = Object.keys(roll).sort((a, b) => b - a);
  setTitle("All-time standings");
  $app.innerHTML = `${crumbs(["All-time standings"])}<div class="page-head"><h1>All-time standings</h1><div class="actions">${shareBtn()}</div></div>
    <p class="lede">Every season since ${meta.seasons[0]}, ${plural(meta.teams.length, "team")}.</p>
    ${years.length ? `<div class="card"><h2>Roll of honour</h2><div class="games">${years.map((y) => `<div class="game"><div><b>${y}</b><span class="chip gold">🏆 ${roll[y].champ ? teamLink(roll[y].champ[0]) : "—"}</span></div>
      ${roll[y].second ? `<div class="small"><span class="muted">Runner-up</span><span>${teamLink(roll[y].second[0])}</span></div>` : ""}${roll[y].third ? `<div class="small"><span class="muted">3rd</span><span>${teamLink(roll[y].third[0])}</span></div>` : ""}</div>`).join("")}</div></div>` : ""}
    <div class="card">${table([
    { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
    { k: "Championships", label: "Titles", html: (r) => r.Championships ? `<b>${"🏆".repeat(Math.min(5, r.Championships))}</b> ${r.Championships}` : '<span class="muted">0</span>' },
    { k: "All time record", label: "Record", left: true },
    { k: "All time win %", label: "Win %", html: (r) => oddsBar(fmt(S["All time win %"], r["All time win %"]), r["All time win %"]), col: "All time win %" },
    { k: "Number of playoff appearances", label: "Playoffs", col: "Number of playoff appearances" },
    { k: "Number of championship appearances", label: "Finals", col: "Number of championship appearances" },
    { k: "Avg points", label: "Avg PF", spec: S["Avg points"], col: "Avg points" },
    { k: "All-play win %", label: "All-play", spec: S["All-play win %"], col: "All-play win %" },
    { k: "Drafting skill", label: "Drafting", spec: S["Drafting skill"], col: "Drafting skill" },
    { k: "Trading skill", label: "Trading", spec: S["Trading skill"], col: "Trading skill" },
    { k: "Add/Drop skill", label: "Add/Drop", spec: S["Add/Drop skill"], col: "Add/Drop skill" },
    { k: "age", label: "Roster age", spec: { d: 2 }, title: "Current roster age" },
  ], rows, { teamOf: (r) => r.t, rowLink: (r) => `team/${tslug(r.t)}`, defs: "team_all_time", tools: false, name: "all_time_standings" })}<p class="muted small">Ordered by titles, then all-time win %; tap a header to re-sort, a row to open the team. Roster age = the average age of each team's roster as of the last build, using this season's ages.</p></div>
  <div class="card"><h2>Every all-time stat</h2>${dataTable({ ...AT, rows: allRows }, { links: { Team: (v) => teamLink(v) }, defs: "team_all_time", tools: true, name: "team_all_time" })}
    <p class="muted small">Every team_all_time column except the head-to-head ones (those are on <a href="#/h2h">Head to head</a>). Scroll sideways; the team stays pinned.</p></div>`;
}

function tiles(summary, labels, specs, keys, sheet) {
  return `<div class="tiles">${(keys || Object.keys(summary)).filter((k) => k in summary).map((k) => {
    const d = defOf(k, sheet), v = summary[k];
    const shown = typeof v === "string" && TEAMS.includes(v) ? teamLink(v) : fmt(specs[k], v);
    return `<div class="tile"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(labels[k] || k)}"` : ""}><b title="${esc(stripHtml(shown))}">${shown}</b><span>${esc(labels[k] || k)}${d ? " " + DEFBTN : ""}</span></div>`; }).join("")}</div>`;
}
const niceDate = (d) => { const x = new Date(String(d).slice(0, 10) + "T12:00:00"); return isNaN(x) ? esc(d) : x.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }); };

function tradeCard(t, meta, full) {
  const F = meta.fmt, L = meta.labels;
  const best = t.sides[0];
  const ktcNow = (s) => { for (let i = meta.ktc.length - 1; i >= 0; i--) { const v = s[meta.ktc[i][1]]; if (typeof v === "number") return [meta.ktc[i][0], v]; } return null; };
  const vals = (cols, s) => cols.map(([lab, c]) => `<span>${esc(lab)}: <b class="${(s[c] ?? 0) > 0 ? "pos" : (s[c] ?? 0) < 0 ? "neg" : ""}">${s[c] === null || s[c] === undefined ? "—" : signed(F[c], s[c])}</b></span>`).join("");
  const sides = t.sides.map((s) => {
    const k = ktcNow(s);
    return `<div class="side${k && k[1] > 0 ? " win" : ""}"><h4>${teamLink(s.team)} ${k ? `<span class="grade ${k[1] >= 0 ? "pos" : "neg"}" title="KTC value difference, latest available (${esc(k[0])})">${signed(F["KTC value difference at deal time"], k[1])} KTC</span>` : ""}</h4>
      <div class="gl">Got</div><ul>${s.got.map((a) => `<li>${assetLink(a)}</li>`).join("") || '<li class="muted">nothing</li>'}</ul>
      ${t.sides.length > 2 || full ? `<div class="gl">Sent</div><ul>${s.sent.map((a) => `<li>${assetLink(a)}</li>`).join("") || '<li class="muted">nothing</li>'}</ul>` : ""}
      <div class="ktc" title="KeepTradeCut value received minus sent, at each checkpoint"><span class="muted">KTC</span>${vals(meta.ktc, s)}</div>
      ${meta.faab ? `<div class="ktc" title="FAAB Value difference: the same received − sent gap in the league's FAAB dollars (FAAB value system)"><span class="muted">FAAB $</span>${vals(meta.faab, s)}</div>` : ""}
      <div class="ktc">${["Trade impact score", "Wins added", "Net points", "O-Score"].map((c) => `<span title="${esc(L[c])}">${esc(L[c])}: <b>${fmt(F[c], s[c])}</b></span>`).join("")}</div>
    </div>`;
  }).join("");
  const mine = ME && t.sides.some((s) => s.team === ME);
  return `<article class="trade${full ? "" : " go"}${mine ? " mine" : ""}" id="trade-${t.id}"${full ? "" : ` data-go="trades/${t.id}" tabindex="0" aria-label="Trade #${t.id}, ${esc(t.sides.map((s) => s.team).join(" and "))}"`}><div class="small muted"><a href="#/trades/${t.id}">Trade #${t.id}</a> · <time datetime="${esc(String(t.date).slice(0, 10))}">${niceDate(t.date)}</time> · ${t.sides.map((s) => esc(s.team)).join(" ⇄ ")}${t.sides.length > 1 && (best["Trade impact score"] ?? 0) > (t.sides[1]["Trade impact score"] ?? 0) ? ` · impact edge: <b>${esc(best.team)}</b>` : ""}</div><div class="sides">${sides}</div></article>`;
}

async function team(slug, _q, live) {
  const [t, tr, PK, B, , AT, meta] = await Promise.all([load(`team/${slug}.json`), load("trades.json"), load("picks.json"), loadBoard(), loadPickRows(), load("all_time.json"), load("meta.json")]);
  const atRow = AT.rows.find((r) => r[AT.cols.indexOf("Team")] === t.team) || [];
  const allStats = {}, allLabels = {};
  AT.cols.forEach((c, i) => { if (c !== "Team" && atRow[i] !== null && atRow[i] !== undefined) { allStats[c] = atRow[i]; allLabels[c] = AT.labels[i]; } });
  const mine = (livePicks(PK, live)[t.team] || []).map(([y, r, o]) => ({ y, r, o, v: pickValue(PK, B, y, r, o) }));
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const ages = t.ages || {};
  const leagueAvg = (k) => { const v = Object.values(t.league_ages).map((a) => k ? a.by_pos?.[k] : a.avg).filter((x) => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const ageRows = ["QB", "RB", "WR", "TE"].map((p) => [p, ages.by_pos?.[p], leagueAvg(p)]);
  const ri = idx(t.roster, "slug");
  const posI = idx(t.roster, "Pos") >= 0 ? idx(t.roster, "Pos") : idx(t.roster, "Position");
  let roster = dataTable(t.roster, { hide: ["slug"], defs: "player_week", teamOf: undefined, links: { Player: (v, r) => ri >= 0 && r[ri] ? `<a href="#/player/${r[ri]}">${esc(v)}</a>` : esc(v), "NFL team": (v) => nflLink(v), ...(posI >= 0 ? { [t.roster.cols[posI]]: (v) => posBadge(v) } : {}) }, name: `${t.team}_roster` });
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
      return { pid, name: n[0] || (b && b[0]) || pid, pos: n[1] || "", nfl: n[2] || "", inj: n[4] || "", age: (b && age >= 0 ? b[age] : null) ?? n[3] ?? null,
               role: lr.ir.has(pid) ? "IR" : lr.taxi.has(pid) ? "Taxi" : lr.starters.has(pid) ? "Starter" : "Bench", isNew: !b };
    }).sort((a, b) => (a.role === "Starter" ? 0 : a.role === "Bench" ? 1 : 2) - (b.role === "Starter" ? 0 : b.role === "Bench" ? 1 : 2) || (pos[a.pos] ?? 9) - (pos[b.pos] ?? 9));
    const gone = [...built.keys()].filter((pid) => !lr.players.includes(pid)).map((pid) => built.get(pid)[0]);
    const roleChip = { Starter: "acc", Bench: "", Taxi: "gold", IR: "bad" };
    roster = table([
      { k: "name", label: "Player", left: true, html: (r) => `${NAMES_BY_ID[r.pid] ? `<a href="#/player/${esc(r.pid)}">${esc(r.name)}</a>` : esc(r.name)}${r.inj ? ` <span class="chip bad">${esc(r.inj)}</span>` : ""}${r.isNew ? ' <span class="chip live">new since the build</span>' : ""}` },
      { k: (r) => (pos[r.pos] ?? 9), label: "Pos", left: true, html: (r) => posBadge(r.pos) }, { k: "nfl", label: "NFL", left: true, html: (r) => nflLink(r.nfl) },
      { k: "age", label: "Age", spec: { d: 2 } }, { k: (r) => ({ Starter: 0, Bench: 1, Taxi: 2, IR: 3 })[r.role], label: "Now", left: true, html: (r) => `<span class="chip ${roleChip[r.role]}">${r.role}</span>` },
    ], rows, { name: `${t.team}_roster` });
    const cnt = (k) => rows.filter((r) => r.role === k).length;
    rosterNote = `${rows.length} players on Sleeper now: ${cnt("Starter")} starting, ${cnt("Bench")} bench, ${cnt("Taxi")} taxi, ${cnt("IR")} IR.${gone.length ? ` Gone since the last build: ${gone.map(esc).join(", ")}.` : ""} Ages are this season's, for players the build has seen.`;
  }
  const HEAD = ["All time record", "All time win %", "Championships", "Number of playoff appearances", "Number of championship appearances", "Avg points", "All-play win %", "Trading skill"];
  const sec = (id, title, html) => `<section class="card" id="sec-${id}" aria-labelledby="h-${id}"><h2 id="h-${id}">${title}</h2>${html}</section>`;
  // this season, one square per week (W / L), each opening its matchup
  const W = t.weeks, wc = (c) => W.cols.indexOf(c);
  const thisYear = W.rows.filter((r) => r[wc("Year")] === meta.season);
  const strip = thisYear.length ? `<div class="strip" aria-label="${meta.season} results">${thisYear.map((r) => { const won = r[wc("Win?")]; return `<a class="${won === true ? "W" : won === false ? "L" : "P"}" href="#/game/${r[wc("Year")]}/${r[wc("Week")]}/${tslug(t.team)}" title="${esc(r[wc("Week Name")])}: ${won ? "W" : "L"} ${stripHtml(fmt({ d: 2 }, r[wc("PF")]))}–${stripHtml(fmt({ d: 2 }, r[wc("Points against")]))} vs ${esc(r[wc("Opponent")])}">${String(r[wc("Week Name")]).replace(/^Week /, "")}</a>`; }).join("")}</div>` : "";
  // points per season, title seasons in gold
  const S = t.seasons, sc = (c) => S.cols.indexOf(c);
  const seasonChart = S.rows && S.rows.length > 1 ? barChart(S.rows.slice().sort((a, b) => a[sc("Year")] - b[sc("Year")]).map((r) => ({ label: String(r[sc("Year")]), v: r[sc("Avg points")] ?? r[sc("Points")], cls: /champion/i.test(String(r[sc("Result")] || "")) ? "g" : "", title: `${r[sc("Year")]}: ${stripHtml(fmt({ d: 2 }, r[sc("Avg points")]))} avg points · ${r[sc("Record")] || ""} ${r[sc("Result")] || ""}` })), { label: "Average points per week by season", h: 150, fmt: (v) => fmt({ d: 0 }, v) }) : "";
  const titles = (S.rows || []).filter((r) => /champion/i.test(String(r[sc("Result")] || ""))).map((r) => r[sc("Year")]);
  const nav = [["season", "This season"], ["roster", "Roster"], ["picks", "Picks"], ["h2h", "Head to head"], ["seasons", "Seasons"], ["style", "Style"], ["trades", "Trades"], ["draft", "Draft"]];
  const isMe = ME === t.team;
  setTitle(t.team);
  $app.innerHTML = `${crumbs(["All-time standings", "teams"], [t.team])}
    <div class="page-head"><div class="thead2">${avatar(t.team, "lg")}<div><h1>${esc(t.team)}${titles.length ? ` <span class="chip gold" title="Titles: ${titles.join(", ")}">🏆 ×${titles.length}</span>` : ""}</h1>${TINFO[t.team]?.name ? `<div class="tname">${esc(TINFO[t.team].name)}</div>` : ""}</div></div>
      <div class="actions"><button class="b sm${isMe ? " on" : ""}" id="setme" aria-pressed="${isMe}">${isMe ? "★ My team" : "☆ This is my team"}</button><a class="btn sec" href="#/compare?a=t:${encodeURIComponent(t.team)}${ME && !isMe ? "&b=t:" + encodeURIComponent(ME) : ""}">⚖️ Compare</a><a class="btn sec" href="#/calc?${ME && !isMe ? `a=${encodeURIComponent(ME)}&b=${encodeURIComponent(t.team)}` : `a=${encodeURIComponent(t.team)}`}">🔁 Trade</a>${shareBtn()}</div></div>
    ${tiles(t.summary, t.summary_labels, t.summary_fmt, HEAD, "team_all_time")}
    <details class="more"><summary class="small">All ${Object.keys(allStats).length} all-time stats</summary>${tiles(allStats, allLabels, AT.fmt, Object.keys(allStats).filter((k) => !HEAD.includes(k)), "team_all_time")}</details>
    <nav class="secnav" aria-label="Sections">${nav.map(([id, n]) => `<button data-sec="${id}">${n}</button>`).join("")}</nav>
    ${sec("season", `This season`, `${strip}${dataTable(t.weeks, { hide: ["Week"], defs: "team_week", teamOf: undefined, rowLink: (r) => `game/${r[wc("Year")]}/${r[wc("Week")]}/${tslug(t.team)}`, links: { "Week Name": (v, r, cols) => `<a href="#/game/${r[cols.indexOf("Year")]}/${r[cols.indexOf("Week")]}/${tslug(t.team)}">${esc(v)}</a>`, Opponent: (v) => teamLink(v), "Win?": (v) => v === true ? '<span class="w">W</span>' : v === false ? '<span class="lo">L</span>' : "—" }, name: `${t.team}_weeks` })}`)}
    ${sec("roster", `Current roster ${liveNote(live)}`, `${roster}<p class="muted small">${rosterNote}</p>
      <h3>Roster age</h3><p>Whole roster <b>${fmt({ d: 2 }, ages.avg)}</b> · starters <b>${fmt({ d: 2 }, ages.starters)}</b> · league avg ${fmt({ d: 2 }, leagueAvg(null))} <span class="muted small">(current roster, this season's ages)</span></p>
      ${table([{ k: 0, label: "Pos", left: true, html: (r) => posBadge(r[0]) }, { k: 1, label: "Age", spec: { d: 2 } }, { k: 2, label: "League avg", spec: { d: 2 } },
               { k: (r) => (r[1] ?? 0) - (r[2] ?? 0), label: "vs league", html: (r) => r[1] == null ? "—" : `<span class="${r[1] > r[2] ? "neg" : "pos"}">${signed({ d: 2 }, r[1] - r[2])}</span> <span class="muted small">${r[1] > r[2] ? "older" : "younger"}</span>` }], ageRows, { tools: false })}`)}
    ${sec("picks", `Future picks held (${mine.length}) ${liveNote(live)}`, `${table([{ k: "y", label: "Draft", left: true }, { k: (r) => r.ps.length, label: "Picks", left: true, html: (r) => pickDots(r.ps, t.team) },
        { k: (r) => r.ps.map((p) => p.o === t.team ? "" : `${ORD[p.r]} from ${p.o}`).filter(Boolean).join(", "), label: "Acquired", left: true },
        { k: (r) => r.ps.reduce((a, p) => a + (p.v || 0), 0), label: "Value", html: (r) => B ? money(r.ps.reduce((a, p) => a + (p.v || 0), 0)) : "—" }],
        PK.years.map((y) => ({ y, ps: mine.filter((p) => p.y === y) })), { tools: false })}
      ${B ? `<p class="small">Worth <b>${money(mine.reduce((a, p) => a + (p.v || 0), 0))}</b> on the FAAB board's pick scale. <a href="#/faab?owner=${encodeURIComponent(t.team)}">FAAB board →</a></p>` : ""}`)}
    ${sec("h2h", "Head to head", `${table([
        { k: "opp", label: "Opponent", left: true, html: (r) => teamLink(r.opp) },
        { k: (r) => r.w / Math.max(1, r.w + r.l), label: "W-L", html: (r) => `<b class="${r.w > r.l ? "pos" : r.w < r.l ? "neg" : ""}">${r.w}-${r.l}</b>` },
        { k: (r) => r.w / Math.max(1, r.w + r.l), label: "Win %", html: (r) => r.w + r.l ? oddsBar(Math.round(100 * r.w / (r.w + r.l)) + "%", r.w / (r.w + r.l)) : "—" },
        ...[["reg", "Regular"], ["playoffs", "Playoffs"], ["final", "Final"], ["third", "3rd place"], ["toilet", "Toilet"], ["trash", "Toilet losers"]].map(([k, n]) =>
          ({ k: (r) => r[k + "w"] / Math.max(1, r[k + "w"] + r[k + "l"]), label: n, html: (r) => (r[k + "w"] || r[k + "l"]) ? `${r[k + "w"]}-${r[k + "l"]}` : '<span class="muted">—</span>' })),
        { k: "pf", label: "Avg PF", spec: { d: 2 } },
        { k: "pa", label: "Avg PA", spec: { d: 2 } },
      ], t.h2h, { sort: 1, tools: false, teamOf: (r) => r.opp, rowLink: (r) => `compare?a=t:${encodeURIComponent(t.team)}&b=t:${encodeURIComponent(r.opp)}` })}<p class="small"><a href="#/h2h?a=${encodeURIComponent(t.team)}">Full matrix →</a> · tap a row to compare the two teams</p>`)}
    ${sec("seasons", "Seasons", `${seasonChart}${seasonChart ? '<div class="legend"><span><i style="background:var(--accent)"></i>average points per week</span><span><i style="background:var(--gold)"></i>title season</span></div>' : ""}${dataTable(t.seasons, { defs: "team_year", teamOf: undefined, name: `${t.team}_seasons`, links: { Result: (v) => v ? (/champion/i.test(v) ? `<span class="chip gold">🏆 ${esc(v)}</span>` : esc(v)) : '<span class="muted">—</span>' } })}`)}
    ${t.swing && t.swing.rows && t.swing.rows.length && t.swing.cols.length > 1 ? sec("style", "Scoring style", `${dataTable(t.swing, { defs: "team_year", teamOf: undefined })}
      <p class="muted small">Swing = how far a typical week lands from the team's average (starters' points; the semifinal +5 left out). "To this point" compares every season over the weeks played so far this season. Boom / bust = a week at least 120% / at most 80% of the league's middle score.</p>
      <h3>Lineup risk and stacks</h3>${dataTable(t.risk, { defs: "team_year", teamOf: undefined })}
      <p class="muted small">Riskiness 1.00 = the usual swing for a lineup of that projected strength; above 1 = boom-or-bust picks. Underdog = pre-week win % under 50%; risky = riskiness 1.00 or more.</p>`) : ""}
    ${sec("trades", `Trades (${t.trades.length})`, `${t.trades.slice(0, 15).map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("") || '<p class="muted">No trades yet.</p>'}
      ${t.trades.length > 15 ? `<p><a class="btn sec" href="#/trades?team=${encodeURIComponent(t.team)}">All ${t.trades.length} trades →</a></p>` : ""}`)}
    ${sec("draft", "Rookie draft picks", dataTable(t.draft, { hide: ["Team", "_row"], pin: 2, defs: "rookie_picks", teamOf: undefined, rowLink: (r) => `pick/rookie_picks/${r[t.draft.cols.indexOf("_row")]}`, links: { Number: (v, r, cols) => `<a href="#/pick/rookie_picks/${r[cols.indexOf("_row")]}">${esc(v)}</a>`, "Player Picked": (v) => playerLink(v), "Original Team": (v) => teamLink(v) } }))}
    <p class="small">Every row in the data: ${[["team_week", "weeks"], ["team_year", "seasons"], ["team_all_time", "all-time"], ["trades", "trades"], ["add_drops", "add/drops"], ["player_additions", "pickups"], ["rookie_picks", "rookie picks"]].map(([s, n]) => `<a class="chip" href="#/data/${s}?c=Team&v=${encodeURIComponent(t.team)}">${n}</a>`).join("")}</p>`;
  const secnav = $(".secnav", $app);
  secnav.onclick = (e) => { const b = e.target.closest("[data-sec]"); if (!b) return; const el = document.getElementById("sec-" + b.dataset.sec); if (el) { window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - secnav.offsetHeight - document.getElementById("top").offsetHeight - 8, behavior: "smooth" }); el.focus?.(); } };
  // the section in view is lit in the section bar
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((es) => {
      for (const e of es) if (e.isIntersecting) { const id = e.target.id.slice(4); $$("button", secnav).forEach((b) => b.classList.toggle("on", b.dataset.sec === id)); const on = $(`[data-sec="${id}"]`, secnav); if (on) secnav.scrollTo({ left: on.offsetLeft - 20, behavior: "smooth" }); }
    }, { rootMargin: "-45% 0px -50% 0px" });
    $$("section[id^='sec-']", $app).forEach((s) => io.observe(s));
  }
  $("#setme").onclick = () => { setMe(isMe ? null : t.team); route(); };
}
async function player(key, _q, live) {
  const [p, tr, B] = await Promise.all([load(`player/${key}.json`), load("trades.json"), loadBoard(), loadPickRows()]);
  const byId = Object.fromEntries(tr.trades.map((x) => [x.id, x]));
  const d = p.draft;
  // the board by Sleeper id when the page key is one (names get re-spelled), else by name
  const fv = B && (B.players.find((x) => String(x.sid) === String(key)) || B.players.find((x) => x.name === p.name));
  const enc = encodeURIComponent(p.name);
  const nowTeam = live && /^\d+$/.test(key) ? live.owner[key] : p.team;
  const S = p.seasons, sc = (c) => (S ? S.cols.indexOf(c) : -1);
  const chart = S && S.rows && S.rows.length > 1 && sc("Points") >= 0 ? barChart(S.rows.slice().sort((a, b) => a[sc("Year")] - b[sc("Year")]).map((r) => ({ label: String(r[sc("Year")]), v: r[sc("Points")], title: `${r[sc("Year")]}: ${stripHtml(fmt({ d: 2 }, r[sc("Points")]))} points${r[sc("Top Team")] ? " · " + r[sc("Top Team")] : ""}` })), { label: `${p.name}'s points per season`, h: 140 }) : "";
  setTitle(p.name);
  $app.innerHTML = `${crumbs(["Players", "search/" + enc], [p.name])}
    <div class="page-head"><div><h1>${esc(p.name)} ${posBadge(p.pos)}</h1>
      <p class="lede">${[nflLink(p.nfl), ((t) => t ? "on " + teamLink(t) : "not on a roster now")(nowTeam)].filter(Boolean).join(" · ")} ${live ? liveNote(live) : ""}
      ${d ? `<br>Drafted ${esc(d.year)} pick ${esc(d.pick)} by ${teamLink(d.team)}${typeof d.faab === "number" ? ` (FAAB value on draft day ${money(d.faab)})` : ""}` : ""}</p></div>
      <div class="actions"><a class="btn sec" href="#/compare?a=p:${encodeURIComponent(key)}">⚖️ Compare</a>${shareBtn()}</div></div>
    ${fv ? `<div class="card note info nocv" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b style="font-size:18px">${money(fv.value)}</b> <span>FAAB value · #${fv.rank} on the board of ${esc(B.as_of)} · ${esc(pickText(B, fv.value))}</span><span style="flex:1"></span><a href="#/faab?q=${enc}">board</a> · <a href="rate/">rate it</a></div>` : ""}
    ${tiles(p.summary, p.summary_labels, p.summary_fmt, null, "player_all_time")}
    <p class="small">Every row: ${[["player_week", "weeks", "&y=all"], ["player_year", "seasons", ""], ["player_all_time", "career", ""], ["player_additions", "acquisitions", ""]].map(([s, n, x]) => `<a class="chip" href="#/data/${s}?c=Player&v=${enc}${x}">${n}</a>`).join("")}<a class="chip" href="#/data/add_drops?q=${enc}">add/drops</a><a class="chip" href="#/records?find=${enc}">record boards</a></p>
    ${chart ? `<div class="card"><h2>Points by season</h2>${chart}<p class="muted small">Points while on a league roster, each season.</p></div>` : ""}
    <div class="card"><h2>Career by team</h2>${table([
      { k: "team", label: "Team", left: true, html: (r) => teamLink(r.team) },
      { k: "from", label: "From", left: true }, { k: "to", label: "To", left: true },
      { k: "weeks", label: "Weeks" }, { k: "starts", label: "Starts" },
      { k: (r) => r.weeks ? r.starts / r.weeks : null, label: "Start %", html: (r) => r.weeks ? Math.round(100 * r.starts / r.weeks) + "%" : "—" },
      { k: "pts", label: "Pts as starter", spec: { d: 2 } }, { k: "ppg", label: "PPG starter", spec: { d: 2 } },
      { k: "best", label: "Best week", spec: { d: 2 } }], p.teams, { tools: false, teamOf: (r) => r.team, rowLink: (r) => `team/${tslug(r.team)}` })}</div>
    <div class="card"><h2>Acquisitions</h2>${dataTable(p.stints, { pin: 2, defs: "player_additions", links: { Team: (v) => teamLink(v) } })}</div>
    <div class="card"><h2>Seasons</h2>${dataTable(p.seasons, { defs: "player_year", links: { "Top Team": (v) => teamLink(v), "Last team": (v) => teamLink(v) } })}</div>
    ${p.usage && p.usage.rows.length ? `<div class="card"><h2>Usage</h2><p class="muted small">Snaps, targets, carries and red-zone looks while rostered. xFP = the points his targets and carries usually produce in this league's scoring; points minus xFP above 0 = scoring beyond the opportunity (rarely sticky), rising xFP = a bigger role.</p>${dataTable(p.usage)}</div>` : ""}
    ${p.history ? `<div class="card"><h2>History</h2>${historyList(p.history)}<p class="muted small">Every draft, add, drop and trade, as the workbook's history note has it. Tap a trade to open it.</p></div>` : ""}
    ${p.trades.length ? `<div class="card"><h2>Trades (${p.trades.length})</h2>${p.trades.map((id) => byId[id] && tradeCard(byId[id], tr.meta)).join("")}</div>` : ""}`;
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
  let q = params.get("q") || "", end = params.get("end") === "lo" ? "lo" : "hi";
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
  const medal = (rows, i) => { const p = place(rows, i), n = rows[i][3]; return n <= 3 ? `<span class="medal m${n}" title="${p}">${p}</span>` : p; };
  const isMine = (x) => ME && x[1].includes(ME);
  function card(c) {
    const b = (c.scopes || {})[scope] || {};
    const useEnd = c.mirror ? "hi" : end;
    const rows = b[useEnd] || [];
    const body = rows.length
      ? `<table class="rk"><tbody>${rows.map((x, i) => `<tr class="${x[4] ? "go" : ""}${isMine(x) ? " me" : ""}"${x[4] ? ` data-go="${esc(x[4])}" tabindex="0"` : ""}><td class="muted">${medal(rows, i)}</td><td class="v">${x[4] ? `<a href="#/${esc(x[4])}" tabindex="-1">${fmt(c.fmt, x[0])}</a>` : fmt(c.fmt, x[0])}</td><td class="l">${lab(x[1])}${x[2] ? ` <span class="chip live">${esc(r.flag || "")}</span>` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<p class="muted small">No board: ${b.hi || b.lo ? "a tie for the last places doesn't fit in the top " + r.depth : "no values"}.</p>`;
    const d = defOf(c.col, sheet);
    const href = `#/records/${sheet}?full=${encodeURIComponent(c.col)}&end=${useEnd}&w=${scope}`;
    return `<div class="card rec"><div class="rh"><a class="stat" href="${href}"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(c.label)}"` : ""}><b>${esc(c.label)}</b></a>${d ? `<span data-def="${esc(d)}" data-deflabel="${esc(c.label)}">${DEFBTN}</span>` : ""} <span class="muted small">${useEnd === "hi" ? "highest" : "lowest"}${c.mirror ? " · each trade once" : ""}</span><span style="flex:1"></span><a class="small" href="${href}" title="Every row, ranked">all →</a></div>
      ${body}${c.mirror && end === "lo" ? `<p class="muted small">Lowest is the same trades from the losing side, so only the highest is shown.</p>` : ""}</div>`;
  }
  function draw() {
    const ql = q.trim().toLowerCase();
    let cs = r.columns;
    if (ql) { const ws = ql.split(/\s+/); cs = cs.filter((c) => ws.every((w) => (c.label + " " + c.col).toLowerCase().includes(w))); }
    else if (FEATURED[sheet]) { const f = FEATURED[sheet]; cs = f.map((n) => cs.find((c) => c.col === n)).filter(Boolean).concat(cs.filter((c) => !f.includes(c.col))); }
    shownCards = 24;
    const paint = () => {
      $("#recs").innerHTML = cs.slice(0, shownCards).map(card).join("") || `<div class="card empty" style="grid-column:1/-1"><div class="big">🔍</div><p>No stat on ${esc(SHEET_NAMES[sheet] || sheet)} matches “${esc(q)}”. <button class="b sm" id="rqclear">Clear the filter</button></p><p class="small">Try another sheet: ${SHEETS.filter(([k]) => k !== sheet).map(([k, n]) => `<a class="chip" href="#/records/${k}?q=${encodeURIComponent(q)}">${n}</a>`).join("")}</p></div>`;
      $("#recmore").innerHTML = cs.length > shownCards ? `<button class="b" id="recmorebtn">Show ${Math.min(24, cs.length - shownCards)} more boards (${cs.length - shownCards} left)</button>` : "";
      const cl = $("#rqclear"); if (cl) cl.onclick = () => { q = ""; $("#rq").value = ""; sync(); draw(); };
      const mb = $("#recmorebtn"); if (mb) mb.onclick = () => { shownCards += 24; paint(); };
      refreshAvatars();
    };
    paint();
    $("#reccount").textContent = `${cs.length} of ${r.columns.length} stats${ql ? "" : " · featured first"} · tap a stat's name for its full all-time list`;
  }
  let shownCards = 24;
  const sync = () => setQuery({ q, end: end === "lo" ? "lo" : "", w: scope === "all" ? "" : scope });
  const full = params.get("full");
  if (full) return fullList(sheet, r, full, end, scope, lab);
  const name = SHEET_NAMES[sheet] || sheet;
  setTitle(`Record book · ${name}`);
  $app.innerHTML = `${crumbs(["Record book", "records"], [name])}<div class="page-head"><h1>Record book</h1><div class="actions">${shareBtn()}</div></div>
    <div class="seg tabs" role="tablist" aria-label="Sheet">${SHEETS.map(([k, n]) => `<button role="tab" aria-pressed="${k === sheet}" data-s="${k}">${n}</button>`).join("")}</div>
    <div class="card nocv"><h2>Where does a player, team or week rank?</h2><div class="controls" style="margin:0"><input class="f" id="appq" type="search" placeholder="e.g. Josh Allen, Oliverwkw, 2025 Week 3" value="${esc(params.get("find") || "")}" aria-label="Find a player, team or week on any board"><button class="b pri" id="appgo">Find on every board</button></div><div id="appres"></div></div>
    <div class="controls sticky"><input class="f" id="rq" type="search" placeholder="Filter ${r.columns.length} stats (e.g. bench, boldness, KTC)" value="${esc(q)}" aria-label="Filter stats">
      <span class="seg" style="margin:0" role="group" aria-label="Which end"><button data-e="hi" aria-pressed="${end === "hi"}">Highest</button><button data-e="lo" aria-pressed="${end === "lo"}">Lowest</button></span>
      ${r.scopes.length > 1 ? `<select id="rw" aria-label="Which games">${r.scopes.map((k) => `<option value="${k}" ${k === scope ? "selected" : ""}>${esc(r.scope_names[k])}</option>`).join("")}</select>` : ""}</div>
    <p class="muted small" id="reccount"></p>
    <details class="note"><summary>How the boards are ranked</summary>Top and bottom ${r.depth}, as the digest ranks them: a shared place reads "T2", and a tie that would not fit inside the ${r.depth} is left off. Team PF includes the semifinal +5 bonus; player points do not. Lineups were 9 starters 2020-23 and 10 from 2024.${r.flag ? ` "${esc(r.flag)}" marks a value that can still change, each stat on its own clock: fixed at the move (deal-time KTC, prices, ages, form before the move, a used pick's trade count: never tagged); while the player or received assets are still on the team (points added, on-team PPG, tenure); the sent side over that same span; until the traded picks are drafted; while he's active in the NFL (a pick's career PPG); until a KTC checkpoint's date; or always moving (wins added, impact score, O-Score and pick-adjusted figures, which are re-ranked as other rows change).` : ""}${sheet === "team_all_time" || sheet === "league_all_time" ? " All-time team and league totals move every week of a season." : ""}${sheet === "trades" ? " Each trade is listed once per board (the side that ranks), even though the trades sheet has a row for each side." : ""}${ME ? ` Rows with ${esc(ME)} are highlighted.` : ""}</details>
    <div class="recgrid" id="recs"></div><p id="recmore" style="text-align:center"></p>`;
  $$("[data-s]", $app).forEach((b) => b.onclick = () => (location.hash = `#/records/${b.dataset.s}${q ? "?q=" + encodeURIComponent(q) : ""}`));
  const on = $('[data-s][aria-pressed="true"]', $app); if (on) on.scrollIntoView({ block: "nearest", inline: "center" });
  $$("[data-e]", $app).forEach((b) => b.onclick = () => { end = b.dataset.e; $$("[data-e]", $app).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); draw(); });
  if ($("#rw")) $("#rw").onchange = (e) => { scope = e.target.value; e.target.classList.toggle("on", scope !== "all"); sync(); draw(); };
  $("#rq").oninput = debounce((e) => { q = e.target.value; sync(); draw(); }, 120);
  const find = () => { const v = $("#appq").value.trim(); appearances(v); };
  $("#appgo").onclick = find;
  $("#appq").onkeydown = (e) => { if (e.key === "Enter") find(); };
  // tap anywhere on a board row (not on a link inside it) to open its details
  const open = (e) => { if (e.target.closest("a") && !e.target.closest("tr[data-go] a[tabindex='-1']")) return; const tr = e.target.closest("tr[data-go]"); if (tr) location.hash = "#/" + tr.dataset.go; };
  $("#recs").onclick = open;
  $("#recs").onkeydown = (e) => { if (e.key === "Enter") open(e); };
  draw();
  if (params.get("find")) find();
}

// every top/bottom-5 board place a player, team or week holds, across all sheets
async function appearances(q) {
  const out = document.getElementById("appres");
  if (!q) { out.innerHTML = ""; return; }
  out.innerHTML = `<p class="muted small">Searching every board on ${SHEETS.length} sheets…</p>`;
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
  const bySheet = {}; hits.forEach((h) => (bySheet[h.sheet] = (bySheet[h.sheet] || 0) + 1));
  const records = hits.filter((h) => h.x[3] === 1).length;
  out.innerHTML = `<h3>${plural(hits.length, "board place")} for “${esc(q)}”${records ? ` · <span class="chip gold">🏆 ${plural(records, "record")}</span>` : ""}</h3>
    ${hits.length ? `<p>${Object.entries(bySheet).map(([k, n]) => `<span class="chip">${esc(name[k])} ${n}</span>`).join("")}</p><table class="rk"><tbody>${hits.slice(0, 300).map((h) => `<tr class="go"${h.x[4] ? ` data-go="${esc(h.x[4])}"` : ""}><td class="muted">${h.x[3] <= 3 ? `<span class="medal m${h.x[3]}">${h.x[3]}</span>` : h.x[3]}</td><td class="v">${fmt(h.c.fmt, h.x[0])}</td><td class="l"><a href="#/records/${h.sheet}?full=${encodeURIComponent(h.c.col)}&end=${h.end}&w=${h.scope}">${esc(h.c.label)}</a> <span class="muted small">${esc(name[h.sheet])} · ${h.end === "hi" ? "highest" : "lowest"}${h.scope !== "all" ? " · " + esc(h.scopeName || h.scope) : ""}</span><br><span class="small">${esc(h.x[1].filter((v) => v !== null).join(" · "))}</span></td></tr>`).join("")}</tbody></table>${hits.length > 300 ? `<p class="muted small">First 300 shown; add a word to narrow it.</p>` : ""}`
      : `<p class="muted">Not in any top or bottom 5. Open a stat's full list to see where it ranks.</p>`}`;
  out.onclick = (e) => { if (e.target.closest("a")) return; const tr = e.target.closest("tr[data-go]"); if (tr && tr.dataset.go) location.hash = "#/" + tr.dataset.go; };
}

// a stat's full all-time list, ranked from the whole sheet (the Data page's rows)
const WEEK_KIND = (n) => { n = String(n); if (n.startsWith("Week ")) return "reg"; const l = n.toLowerCase(); if (l.includes("3rd") || l.includes("third")) return "third"; if (l.startsWith("toilet")) return (l.includes("trash") || l.includes("loser")) ? "trash" : "toilet"; return "playoffs"; };
async function fullList(sheet, r, col, end, scope, lab) {
  const c = r.columns.find((x) => x.col === col);
  if (!c) throw new Error("No stat " + col);
  const name = SHEET_NAMES[sheet] || sheet;
  setTitle(`${c.label} · ${name}`);
  $app.innerHTML = `${crumbs(["Record book", "records"], [name, `records/${sheet}?w=${scope}&end=${end}`], [c.label])}
    <div class="page-head"><h1>${esc(c.label)}${defOf(c.col, sheet) ? `<span data-def="${esc(defOf(c.col, sheet))}" data-deflabel="${esc(c.label)}"> ${DEFBTN}</span>` : ""}</h1><div class="actions">${shareBtn()}</div></div>
    ${defOf(c.col, sheet) ? `<p class="lede">${esc(defOf(c.col, sheet))}</p>` : ""}
    <p class="muted" id="flmeta">Loading every row…</p><div class="controls"><input class="f" id="flq" type="search" placeholder="Find a player, team or year in this list" aria-label="Filter this list"></div><div id="fl"><div class="skel blk"></div></div>`;
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
  let shown = 100, fq = "";
  const placeOf = (i) => { let k = i; while (k > 0 && rows[k - 1][ci] === rows[i][ci]) k--; return k + 1; };
  const ranked = rows.map((x, i) => ({ x, place: placeOf(i), text: labIdx.map((j) => (j < 0 ? "" : String(rows[i][j] ?? ""))).join(" ").toLowerCase() }));
  const vals = rows.map((x) => x[ci]), mean = vals.reduce((a, v) => a + v, 0) / (vals.length || 1);
  const median = vals.length ? vals.slice().sort((a, b) => a - b)[Math.floor(vals.length / 2)] : null;
  const draw = () => {
    const ws = fq.toLowerCase().split(/\s+/).filter(Boolean);
    const list = ws.length ? ranked.filter((y) => ws.every((w) => y.text.includes(w))) : ranked;
    $("#flmeta").innerHTML = `${rows.length.toLocaleString()} rows · ${end === "hi" ? "highest first" : "lowest first"}${scope !== "all" ? " · " + esc(r.scope_names?.[scope] || scope) : ""} · average ${fmt(c.fmt, mean)} · median ${fmt(c.fmt, median)} · <a href="#/records/${sheet}?full=${encodeURIComponent(col)}&end=${end === "hi" ? "lo" : "hi"}&w=${scope}">flip to ${end === "hi" ? "lowest" : "highest"} first</a>${ws.length ? ` · <b>${list.length.toLocaleString()} match</b>` : ""}`;
    $("#fl").innerHTML = `<div class="card"><table class="rk"><tbody>${list.slice(0, shown).map(({ x, place }) => { const link = rowLink(sheet, m.cols, x, tradeIds); const lb = lab(labIdx.map((j) => (j < 0 ? null : x[j]))); return `<tr class="go${ME && lb.includes(">" + esc(ME) + "<") ? " me" : ""}"${link ? ` data-go="${esc(link)}" tabindex="0"` : ""}><td class="muted">${place <= 3 ? `<span class="medal m${place}">${place}</span>` : place}</td><td class="v">${fmt(c.fmt, x[ci])}</td><td class="l">${lb}</td></tr>`; }).join("") || '<tr><td class="muted">Nothing matches.</td></tr>'}</tbody></table>
      ${list.length > shown ? `<p style="text-align:center"><button class="b" id="flmore">Show ${Math.min(100, list.length - shown)} more</button> <button class="b ghost" id="flall">Show all ${list.length.toLocaleString()}</button></p>` : ""}</div>`;
    const more = $("#flmore"); if (more) more.onclick = () => { shown += 100; draw(); };
    const al = $("#flall"); if (al) al.onclick = () => { shown = Infinity; draw(); };
    refreshAvatars();
  };
  const open = (e) => { if (e.target.closest("a") || e.target.closest("button")) return; const tr = e.target.closest("tr[data-go]"); if (tr && tr.dataset.go) location.hash = "#/" + tr.dataset.go; };
  $("#fl").onclick = open;
  $("#fl").onkeydown = (e) => { if (e.key === "Enter") open(e); };
  $("#flq").oninput = debounce((e) => { fq = e.target.value.trim(); shown = 100; draw(); }, 150);
  draw();
}

async function h2h(_a, query) {
  const m = await load("h2h.json");
  const params = new URLSearchParams(query || "");
  let mode = params.get("m") && (params.get("m") === "all" || m.kinds[params.get("m")]) ? params.get("m") : "all";
  let show = params.get("show") === "pct" ? "pct" : "wl";
  let selA = params.get("a") || ME || "", selB = params.get("b") || "";
  const sync = () => setQuery({ m: mode === "all" ? "" : mode, show: show === "pct" ? "pct" : "", a: selA, b: selB });
  function draw() {
    const key = mode === "all" ? ["w", "l"] : [mode + "w", mode + "l"];
    const head = `<tr><th class="l nosort">Team ↓ vs →</th>${m.teams.map((t) => `<th class="nosort" title="${esc(t)}">${avatar(t)}<br>${esc(t.slice(0, 8))}</th>`).join("")}<th class="nosort">Total</th></tr>`;
    const body = m.teams.map((a, ai) => {
      let W = 0, L = 0;
      const cells = m.teams.map((b, bi) => {
        if (a === b) return `<td class="self" data-col="${bi}"></td>`;
        const c = m.cells[`${a}|${b}`];
        if (!c) return `<td data-col="${bi}">—</td>`;
        const w = c[key[0]], l = c[key[1]];
        if (!w && !l) return `<td class="self" title="Never met here" data-col="${bi}"></td>`;
        W += w; L += l;
        const p = w + l ? w / (w + l) : 0.5;
        const bg = w + l ? `background:color-mix(in srgb, ${p >= 0.5 ? "var(--good)" : "var(--bad)"} ${Math.round(Math.abs(p - 0.5) * 120)}%, transparent)` : "";
        return `<td style="${bg}" data-a="${esc(a)}" data-b="${esc(b)}" data-col="${bi}" tabindex="0" title="${esc(a)} ${w}-${l} vs ${esc(b)}" class="${a === selA && b === selB ? "sel" : ""}">${show === "pct" ? Math.round(p * 100) + "%" : `${w}-${l}`}</td>`;
      }).join("");
      return `<tr class="${ME === a ? "me" : ""}"><td class="l">${teamLink(a)}</td>${cells}<td><b>${show === "pct" ? (W + L ? Math.round(100 * W / (W + L)) + "%" : "—") : `${W}-${L}`}</b></td></tr>`;
    }).join("");
    $("#mx").innerHTML = `<table class="matrix"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }
  function cell(a, b) {
    const c = m.cells[`${a}|${b}`];
    if (!c) return;
    selA = a; selB = b; sync();
    $$("#mx td.sel").forEach((x) => x.classList.remove("sel"));
    const td = $(`#mx td[data-a="${CSS.escape(a)}"][data-b="${CSS.escape(b)}"]`); if (td) td.classList.add("sel");
    const games = c.games || [];
    const streak = (() => { if (!games.length) return ""; const last = games[games.length - 1][5]; let n = 0; for (let i = games.length - 1; i >= 0 && games[i][5] === last; i--) n++; return `${last ? "W" : "L"}${n}`; })();
    $("#cell").innerHTML = `<div class="chead"><h2>${teamLink(a)} vs ${teamLink(b)}</h2><span><a class="btn sec" href="#/compare?a=t:${encodeURIComponent(a)}&b=t:${encodeURIComponent(b)}">⚖️ Compare</a> <button class="b sm" id="flip" title="See it from ${esc(b)}'s side">⇄ Flip</button></span></div>
      <div class="tiles"><div class="tile"><b>${c.w}-${c.l}</b><span>All games</span></div>${Object.entries(m.kinds).filter(([k]) => c[k + "w"] || c[k + "l"]).map(([k, n]) => `<div class="tile"><b>${c[k + "w"]}-${c[k + "l"]}</b><span>${esc(n)}</span></div>`).join("")}
        <div class="tile"><b>${fmt({ d: 2 }, c.pf)}</b><span>Avg points for</span></div><div class="tile"><b>${fmt({ d: 2 }, c.pa)}</b><span>Avg points against</span></div>${streak ? `<div class="tile"><b class="${streak[0] === "W" ? "pos" : "neg"}">${streak}</b><span>Current streak</span></div>` : ""}</div>
      <div class="strip">${games.map(([y, w, n, pf, pa, won]) => `<a class="${won ? "W" : "L"}" href="#/game/${y}/${w}/${tslug(a)}" title="${y} ${esc(n)}: ${stripHtml(fmt({ d: 2 }, pf))}–${stripHtml(fmt({ d: 2 }, pa))}">${won ? "W" : "L"}</a>`).join("")}</div>
      <table class="rk"><tbody>${games.slice().reverse().map(([y, w, n, pf, pa, won]) => `<tr class="go" data-go="game/${y}/${w}/${tslug(a)}" tabindex="0"><td class="l"><a href="#/game/${y}/${w}/${tslug(a)}">${y} ${esc(n)}</a></td><td class="${won ? "w" : "lo"}">${won ? "W" : "L"}</td><td>${fmt({ d: 2 }, pf)}–${fmt({ d: 2 }, pa)}</td><td class="muted small">${signed({ d: 2 }, pf - pa)}</td></tr>`).join("")}</tbody></table>
      <p class="muted small">Newest first. The squares run oldest → newest.</p>`;
    $("#flip").onclick = () => cell(b, a);
    refreshAvatars();
  }
  setTitle("Head to head");
  $app.innerHTML = `${crumbs(["Head to head"])}<div class="page-head"><h1>Head to head</h1><div class="actions">${shareBtn()}</div></div>
    <div class="controls"><span class="seg" style="margin:0" role="group" aria-label="Games"><button data-m="all" aria-pressed="${mode === "all"}">All games</button>${Object.entries(m.kinds).map(([k, n]) => `<button data-m="${k}" aria-pressed="${mode === k}">${esc(n)}</button>`).join("")}</span>
      <span class="seg" style="margin:0" role="group" aria-label="Show"><button data-show="wl" aria-pressed="${show === "wl"}">W-L</button><button data-show="pct" aria-pressed="${show === "pct"}">Win %</button></span></div>
    <div class="card"><div class="scroll sx" id="mx"></div><p class="muted small">Row team's record against the column team; green = winning record, red = losing, darker = more lopsided. Tap (or Tab to and press Enter on) a cell for every meeting. Playoffs = semifinals and final; the 3rd-place game, the toilet bowl (toilet semis and final) and the toilet losers game are each their own record, as on the team sheets. ${esc(m.note)}</p></div>
    <div class="card" id="cell"><p class="muted">Tap a cell to see every meeting between two teams.</p></div>`;
  $$("[data-m]", $app).forEach((b) => b.onclick = () => { mode = b.dataset.m; $$("[data-m]", $app).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); draw(); });
  $$("[data-show]", $app).forEach((b) => b.onclick = () => { show = b.dataset.show; $$("[data-show]", $app).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); draw(); });
  const pick = (e) => { const td = e.target.closest("td[data-a]"); if (!td) return; cell(td.dataset.a, td.dataset.b); $("#cell").scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  $("#mx").onclick = pick;
  $("#mx").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(e); } };
  // crosshair: the row and column under the pointer
  $("#mx").onmouseover = (e) => { const td = e.target.closest("td"); $$("#mx .hx").forEach((x) => x.classList.remove("hx")); if (!td || td.dataset.col === undefined) return; td.parentElement.classList.add("hx"); $$(`#mx td[data-col="${td.dataset.col}"]`).forEach((x) => x.classList.add("hx")); };
  $("#mx").onmouseleave = () => $$("#mx .hx").forEach((x) => x.classList.remove("hx"));
  $("#cell").onclick = (e) => { if (e.target.closest("a, button")) return; const tr = e.target.closest("tr[data-go]"); if (tr) location.hash = "#/" + tr.dataset.go; };
  draw();
  if (selA && selB) cell(selA, selB);
}

async function trades(id, query) {
  const [tr, meta, FULL] = await Promise.all([load("trades.json"), load("meta.json"), load("trades_full.json"), loadPickRows()]);
  for (const t of tr.trades) (FULL[t.id] || []).forEach((all, i) => { if (t.sides[i]) t.sides[i].all = all; });
  if (id) {
    const i0 = tr.trades.findIndex((x) => String(x.id) === String(id));
    const t = tr.trades[i0];
    if (!t) throw new Error("No trade #" + id + " — it may be newer than this build.");
    const M = tr.meta;
    const rows = M.all_cols.filter((c) => t.sides.some((s) => s.all && s.all[c] !== null && s.all[c] !== undefined));
    const cell = (c, v) => v === null || v === undefined ? '<span class="muted">—</span>' : typeof v === "string" ? v.split("; ").map(assetLink).join("; ") : fmt(M.fmt[c], v);
    // trades are listed newest first: the previous trade is the next one down the list
    const older = tr.trades[i0 + 1], newer = tr.trades[i0 - 1];
    setTitle(`Trade #${t.id}`);
    $app.innerHTML = `${crumbs(["Trades", "trades"], [`#${t.id}`])}
      <div class="page-head"><h1>Trade #${t.id} <span class="muted" style="font-weight:500;font-size:16px">${niceDate(t.date)}</span></h1><div class="actions">${shareBtn()}</div></div>
      <div class="weeknav">${older ? `<a href="#/trades/${older.id}" data-prev>‹ Trade #${older.id}</a>` : '<span class="dis">‹ First trade</span>'}<a class="small" href="#/trades">All trades</a>${newer ? `<a href="#/trades/${newer.id}" data-next>Trade #${newer.id} ›</a>` : '<span class="dis">Latest trade ›</span>'}</div>
      ${tradeCard(t, M, true)}
      <div class="card"><h2>Everything on the trades sheet</h2><div class="controls"><input class="f" id="tsq" type="search" placeholder="Filter ${rows.length} stats" aria-label="Filter stats"></div><div class="scroll sx"><table class="tall"><thead><tr><th class="l pin pin0 nosort">Stat</th>${t.sides.map((s) => `<th class="l nosort">${teamLink(s.team)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((c) => { const d = defOf(c, "trades"); return `<tr data-k="${esc((M.labels[c] || c).toLowerCase())}"><td class="l pin pin0"${d ? ` data-def="${esc(d)}" data-deflabel="${esc(M.labels[c] || c)}"` : ""}>${esc(M.labels[c] || c)}${d ? " " + DEFBTN : ""}</td>${t.sides.map((s) => `<td class="l">${cell(c, s.all && s.all[c])}</td>`).join("")}</tr>`; }).join("")}</tbody></table></div>
        <p class="muted small">One column per team in the deal. KTC value difference = value received minus value sent on KeepTradeCut (superflex); the FAAB $ figures are the same gap in the league's FAAB dollars.</p></div>`;
    pinColumns(document.querySelector(".tall").parentElement);
    $("#tsq").oninput = (e) => { const v = e.target.value.trim().toLowerCase(); $$(".tall tbody tr").forEach((r) => (r.hidden = !!v && !r.dataset.k.includes(v))); };
    return;
  }
  const params = new URLSearchParams(query || "");
  let team = params.get("team") || "", season = params.get("season") || "", q = params.get("q") || "";
  let sort = params.get("sort") || "date", dir = params.get("dir") || "hi", limit = 60;
  const M = tr.meta;
  const sync = () => setQuery({ team, season, q, sort: sort === "date" ? "" : sort, dir: dir === "hi" ? "" : dir });
  function draw() {
    const ql = q.trim().toLowerCase();
    let ts = tr.trades.filter((t) => (!team || t.sides.some((s) => s.team === team)) && (!season || String(t.season) === season)
      && (!ql || t.sides.some((s) => s.got.concat(s.sent).some((a) => a.toLowerCase().includes(ql)))));
    // a trade ranks by its best side for "highest", its worst side for "lowest"
    const key = (t) => { const v = t.sides.map((s) => s.all && s.all[sort]).filter((x) => typeof x === "number"); return v.length ? (dir === "hi" ? Math.max(...v) : Math.min(...v)) : null; };
    if (sort === "date") ts = dir === "hi" ? ts : ts.slice().reverse();
    else ts = ts.filter((t) => key(t) !== null).sort((a, b) => dir === "hi" ? key(b) - key(a) : key(a) - key(b));
    const shown = ts.slice(0, limit);
    const active = [team && `team ${team}`, season && `season ${season}`, ql && `“${q}”`].filter(Boolean);
    $("#tl").innerHTML = `<p class="muted small">${plural(ts.length, "trade")}${active.length ? ` · ${esc(active.join(" · "))} <button class="b sm ghost" id="tclear">Clear filters</button>` : ""}${sort !== "date" ? ` · by ${esc(M.labels[sort] || sort)}, ${dir === "hi" ? "highest" : "lowest"} first (a trade ranks by its ${dir === "hi" ? "best" : "worst"} side)` : ""}</p>` +
      (shown.map((t) => (sort !== "date" ? `<p class="small" style="margin:10px 0 2px"><b>${fmt(M.fmt[sort], key(t))}</b> <span class="muted">${esc(M.labels[sort] || sort)}</span></p>` : "") + tradeCard(t, M)).join("") || `<div class="card empty"><div class="big">🤝</div><p>No trade matches.</p></div>`) +
      (ts.length > shown.length ? `<p style="text-align:center"><button class="b" id="tmore">Show ${Math.min(60, ts.length - shown.length)} more (${ts.length - shown.length} left)</button></p>` : "");
    const more = $("#tmore"); if (more) more.onclick = () => { limit += 60; draw(); };
    const cl = $("#tclear"); if (cl) cl.onclick = () => { team = season = q = ""; $("#ft").value = ""; $("#fs").value = ""; $("#fq").value = ""; sync(); draw(); };
    $("#ft").classList.toggle("on", !!team); $("#fs").classList.toggle("on", !!season);
    refreshAvatars();
  }
  const seasons = [...new Set(tr.trades.map((t) => t.season))].sort().reverse();
  // trades per season, for a quick picture of how busy each year was
  const perSeason = seasons.slice().reverse().map((s) => ({ label: String(s), v: tr.trades.filter((t) => t.season === s).length, href: `#/trades?season=${s}` }));
  const perTeam = meta.teams.map((t) => [t, tr.trades.filter((x) => x.sides.some((s) => s.team === t)).length]).sort((a, b) => b[1] - a[1]);
  setTitle("Trades");
  $app.innerHTML = `${crumbs(["Trades"])}<div class="page-head"><h1>Trade history</h1><div class="actions"><a class="btn" href="#/calc">⚖️ Trade calculator</a>${shareBtn()}</div></div>
    <div class="grid2"><div class="card"><h2>Trades per season</h2>${barChart(perSeason, { label: "Trades per season", h: 130 })}</div>
      <div class="card"><h2>Most active traders</h2>${perTeam.map(([t, n]) => `<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="width:150px">${teamLink(t)}</span><div class="bar-h" style="flex:1"><i style="width:${100 * n / (perTeam[0][1] || 1)}%"></i></div><a class="small" href="#/trades?team=${encodeURIComponent(t)}" style="width:36px;text-align:right">${n}</a></div>`).join("")}</div></div>
    <div class="controls sticky">
      <select id="ft" aria-label="Team"><option value="">All teams</option>${meta.teams.map((t) => `<option ${t === team ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <select id="fs" aria-label="Season"><option value="">All seasons</option>${seasons.map((s) => `<option ${String(s) === season ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <select id="fo" aria-label="Order by"><option value="date">Order: date</option>${M.sortable.map((c) => `<option value="${esc(c)}" ${c === sort ? "selected" : ""}>Order: ${esc(M.labels[c] || c)}</option>`).join("")}</select>
      <span class="seg" style="margin:0" role="group" aria-label="Direction"><button data-dir="hi" aria-pressed="${dir === "hi"}">Highest / newest</button><button data-dir="lo" aria-pressed="${dir === "lo"}">Lowest / oldest</button></span>
      <input class="f" id="fq" type="search" placeholder="Player or pick" value="${esc(q)}" aria-label="Player or pick">
    </div>
    <details class="note info"><summary>Reading a trade card</summary>Each side shows the KTC value difference (received − sent) at the deal, at season end, 1 and 2 years later, and the same gap in FAAB dollars; the badge is the latest KTC one available, and the side ahead on it gets a green outline. Tap a trade for everything the sheet has on it.${ME ? ` Trades involving ${esc(ME)} have a gold edge.` : ""}</details>
    <div id="tl"></div>`;
  $("#ft").onchange = (e) => { team = e.target.value; limit = 60; sync(); draw(); };
  $("#fs").onchange = (e) => { season = e.target.value; limit = 60; sync(); draw(); };
  $("#fo").onchange = (e) => { sort = e.target.value; limit = 60; sync(); draw(); };
  $$("[data-dir]", $app).forEach((b) => b.onclick = () => { dir = b.dataset.dir; limit = 60; $$("[data-dir]", $app).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); draw(); });
  $("#fq").oninput = debounce((e) => { q = e.target.value.trim(); limit = 60; sync(); draw(); }, 150);
  $("#tl").onclick = (e) => { if (e.target.closest("a") || e.target.closest("button")) return; const c = e.target.closest("[data-go]"); if (c) location.hash = "#/" + c.dataset.go; };
  draw();
}

async function draft(_a, query) {
  const d = await load("draft.json");
  const params = new URLSearchParams(query || "");
  let which = params.get("w") === "startup" && d.startup ? "startup" : "rookie", year = params.get("year") || "", tm = params.get("team") || "", round = params.get("round") || "";
  const sync = () => setQuery({ w: which === "rookie" ? "" : which, year, team: tm, round });
  function draw() {
    const t = d[which];
    const yi = idx(t, "Year"), ti = idx(t, "Team"), ni = idx(t, "Number");
    const years = [...new Set(t.rows.map((r) => String(r[yi])))].sort().reverse();
    const teams = [...new Set(t.rows.map((r) => r[ti]).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const rounds = [...new Set(t.rows.map((r) => String(r[ni] ?? "").split(".")[0]).filter((x) => /^\d+$/.test(x)))].sort((a, b) => a - b);
    if (year && !years.includes(year)) year = "";
    $("#dy").innerHTML = `<option value="">All years</option>` + years.map((y) => `<option ${y === year ? "selected" : ""}>${esc(y)}</option>`).join("");
    $("#dteam").innerHTML = `<option value="">All teams</option>` + teams.map((x) => `<option ${x === tm ? "selected" : ""}>${esc(x)}</option>`).join("");
    $("#dround").innerHTML = `<option value="">All rounds</option>` + rounds.map((x) => `<option value="${x}" ${x === round ? "selected" : ""}>Round ${x}</option>`).join("");
    for (const [id, v] of [["#dy", year], ["#dteam", tm], ["#dround", round]]) $(id).classList.toggle("on", !!v);
    const rows = t.rows.filter((r) => (!year || String(r[yi]) === year) && (!tm || r[ti] === tm) && (!round || String(r[ni] ?? "").split(".")[0] === round));
    const sheetName = which === "rookie" ? "rookie_picks" : "non_rookie_picks";
    $("#dcnt").textContent = `${plural(rows.length, "pick")}${year ? " in " + year : ""}${tm ? " by " + tm : ""}${round ? ", round " + round : ""}`;
    $("#dt").innerHTML = dataTable({ ...t, rows }, { hide: ["_row"], pin: 3, defs: sheetName, name: `${sheetName}${year ? "_" + year : ""}`, rowLink: (r) => `pick/${sheetName}/${r[t.cols.indexOf("_row")]}`, links: { Number: (v, r, cols) => `<a href="#/pick/${sheetName}/${r[cols.indexOf("_row")]}">${esc(v)}</a>`, "Player Picked": (v) => playerLink(v), Team: (v) => teamLink(v), "Original Team": (v) => teamLink(v) } });
  }
  setTitle("Draft history");
  $app.innerHTML = `${crumbs(["Draft history"])}<div class="page-head"><h1>Draft history</h1><div class="actions">${shareBtn()}</div></div>
    <div class="seg tabs" role="tablist"><button role="tab" data-w="rookie" aria-pressed="${which === "rookie"}">Rookie drafts</button>${d.startup ? `<button role="tab" data-w="startup" aria-pressed="${which === "startup"}">Startup &amp; vet picks</button>` : ""}</div>
    <div class="controls"><select id="dy" aria-label="Year"></select><select id="dteam" aria-label="Team"></select><select id="dround" aria-label="Round"></select><span class="muted small" id="dcnt"></span></div>
    <div class="card"><div id="dt"></div><p class="muted small">Every column of the pick sheet; scroll sideways with the pick, player and team pinned, and tap a column name for its definition, a row for the pick's page. Pick-adjusted columns compare the pick with what that draft slot usually returns. KTC values are KeepTradeCut superflex. 2.09 is the toilet-bowl reward pick.</p></div>`;
  $$("[data-w]", $app).forEach((b) => b.onclick = () => { which = b.dataset.w; year = tm = round = ""; $$("[data-w]", $app).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); draw(); });
  $("#dy").onchange = (e) => { year = e.target.value; sync(); draw(); };
  $("#dteam").onchange = (e) => { tm = e.target.value; sync(); draw(); };
  $("#dround").onchange = (e) => { round = e.target.value; sync(); draw(); };
  draw();
}

// edit distance, for "did you mean" when a search finds nothing
function lev(a, b) {
  if (Math.abs(a.length - b.length) > 3) return 9;
  const v = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = v[0]; v[0] = i;
    for (let j = 1; j <= b.length; j++) { const t = v[j]; v[j] = Math.min(v[j] + 1, v[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = t; }
  }
  return v[b.length];
}
async function search(q) {
  q = q || "";
  const ix = await load("search.json");
  const ql = q.trim().toLowerCase();
  $q.value = q;
  setTitle(q ? `Search: ${q}` : "Search");
  const score = (n) => { const s = n.toLowerCase(); if (s === ql) return 0; if (s.startsWith(ql)) return 1; if (s.split(/[\s.'-]+/).some((w) => w.startsWith(ql))) return 2; return s.includes(ql) ? 3 : 9; };
  let hits = ql ? ix.map((r) => [score(r[2]), r]).filter(([s]) => s < 9).sort((a, b) => a[0] - b[0] || (b[1][4] || 0) - (a[1][4] || 0)).slice(0, 80).map((x) => x[1]) : [];
  // fantasy team names (from Sleeper) find their team too
  const fant = Object.entries(TINFO).filter(([t, i]) => ql && i.name && i.name.toLowerCase().includes(ql) && !hits.some((r) => r[0] === "t" && r[1] === t)).map(([t]) => ["t", t, t, "Team"]);
  hits = fant.concat(hits);
  let near = [];
  if (ql && !hits.length) near = ix.map((r) => { const n = r[2].toLowerCase(); return [Math.min(lev(ql, n), ...n.split(/\s+/).map((w) => lev(ql, w))), r]; }).filter(([dd]) => dd <= 2).sort((a, b) => a[0] - b[0]).slice(0, 6).map((x) => x[1]);
  const li = (r) => r[0] === "t" ? `<li><a href="#/team/${tslug(r[1])}">${avatar(r[1])}${hilite(r[2], ql)}</a><span class="muted small">${esc(TINFO[r[1]]?.name || "Team")}</span></li>`
    : `<li><span>${posBadge(String(r[3] || "").split(" ")[0])} <a href="#/player/${esc(r[1])}">${hilite(r[2], ql)}</a></span><span class="muted small">${esc(String(r[3] || "").split(" ").slice(1).join(" · "))}</span></li>`;
  const T = hits.filter((r) => r[0] === "t"), P = hits.filter((r) => r[0] === "p");
  const nfl = NFL_TEAMS.filter((c) => c.toLowerCase() === ql);
  $app.innerHTML = `${crumbs(["Search"])}<h1>${q ? `Results for “${esc(q)}”` : "Search"}</h1>
    <form class="controls" id="sform"><input class="f" id="sq" type="search" value="${esc(q)}" placeholder="A player, team, NFL team or stat" aria-label="Search"><button class="b pri">Search</button></form>
    ${ql ? `<p class="muted small">${plural(T.length, "team")} · ${plural(P.length, "player")}${P.length >= 80 ? " (first 80)" : ""}</p>` : ""}
    ${nfl.length ? `<div class="card"><a href="#/nfl/${nfl[0]}">🏈 ${nfl[0]}: depth chart and the league's players →</a></div>` : ""}
    ${T.length ? `<div class="card"><h2>Teams</h2><ul class="res">${T.map(li).join("")}</ul></div>` : ""}
    ${P.length ? `<div class="card"><h2>Players</h2><ul class="res">${P.map(li).join("")}</ul></div>` : ""}
    ${ql && !hits.length ? `<div class="card empty"><div class="big">🔍</div><p>No players or teams match “${esc(q)}”.</p>${near.length ? `<p>Did you mean: ${near.map((r) => `<a class="chip" href="#/${r[0] === "t" ? "team/" + tslug(r[1]) : "player/" + esc(r[1])}">${esc(r[2])}</a>`).join("")}</p>` : ""}</div>` : ""}
    ${!ql ? `<div class="card"><p class="muted">Type a name above, or press <kbd>/</kbd> anywhere to search from the top bar.</p></div>` : ""}
    ${ql ? `<div class="card"><h2>Every row mentioning “${esc(q)}”</h2><p>${[["player_week", "Player weeks"], ["player_year", "Player seasons"], ["team_week", "Team weeks"], ["trades", "Trades"], ["add_drops", "Add/drops"], ["player_additions", "Pickups"], ["rookie_picks", "Rookie picks"]].map(([k, n]) => `<a class="chip" href="#/data/${k}?q=${encodeURIComponent(q)}${k === "player_week" ? "&y=all" : ""}">${n}</a>`).join("")}</p></div>
      <div class="card"><h2>Record boards</h2><p><a class="chip" href="#/records?find=${encodeURIComponent(q)}">🏆 Every board place for “${esc(q)}”</a></p><p class="small muted">Stats whose name matches: ${SHEETS.map(([k, n]) => `<a class="chip" href="#/records/${k}?q=${encodeURIComponent(q)}">${n}</a>`).join("")}</p></div>` : ""}`;
  $("#sform").onsubmit = (e) => { e.preventDefault(); location.hash = "#/search/" + encodeURIComponent($("#sq").value.trim()); };
}

async function faab(_, query, live) {
  const [B, meta, PK] = await Promise.all([loadBoard(), load("meta.json"), load("picks.json")]);
  setTitle("FAAB values");
  if (!B) { $app.innerHTML = `${crumbs(["FAAB values"])}<h1>FAAB values</h1><div class="card empty"><div class="big">💲</div><p>The board is not published yet.</p></div>`; return; }
  const held = {};
  for (const [t, ps] of Object.entries(livePicks(PK, live))) held[t] = ps.map(([y, r, o]) => ({ y, r, o, v: pickValue(PK, B, y, r, o) }));
  const params = new URLSearchParams(query || "");
  let pos = params.get("pos") || "", owner = params.get("owner") || "", q = params.get("q") || "";
  const sync = () => setQuery({ pos, owner, q });
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
  const maxT = Math.max(...totals.map((x) => x.total), 1), maxV = Math.max(...rows.map((r) => r.value || 0), 1);
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
    $$("[data-pos]", $app).forEach((b) => b.setAttribute("aria-pressed", b.dataset.pos === pos));
    $("#fo").classList.toggle("on", !!owner);
    $("#fb").innerHTML = `<p class="muted small">${plural(rs.length - np, "player")}${np ? ` · ${plural(np, "pick")}` : ""}${owner && owner !== "FA" ? ` · ${esc(owner)}: <b>${money(rs.reduce((a, r) => a + (r.value || 0), 0))}</b> in all` : ""}${pos || owner || q ? ` <button class="b sm ghost" id="fclear">Clear filters</button>` : ""}</p>` + table([
      { k: "rank", label: "#", html: (r) => r.rank ?? "" },
      { k: "name", label: "Player", left: true, html: (r) => r.pick ? `<span class="chip">${esc(r.name)}</span>` : playerLink(r.name) },
      { k: "pos", label: "Pos", left: true, html: (r) => posBadge(r.pos) }, { k: "team", label: "NFL", left: true, html: (r) => r.pick ? "" : nflLink(r.team) },
      { k: "age", label: "Age", spec: { d: 1 } },
      { k: "own", label: "Owner", left: true, html: (r) => (r.own ? teamLink(r.own) : '<span class="muted">Free agent</span>') },
      { k: "injury", label: "Injury", left: true, html: (r) => (r.injury ? `<span class="chip bad">${esc(r.injury)}</span>` : "") },
      { k: "value", label: "Value", html: (r) => `<span class="oddcell"><b>${money(r.value)}</b><i style="--w:${(100 * (r.value || 0) / maxV).toFixed(1)}%" aria-hidden="true"></i></span>` },
      { k: (r) => r.value, label: "≈ rookie picks", left: true, html: (r) => `<span class="muted small">${esc(pickText(B, r.value).replace(/^about the /, ""))}</span>` },
    ], rs.slice(0, 400), { sort: 0, asc: true, teamOf: (r) => r.own, name: `faab_board_${B.as_of}`, limit: 100 });
    const cl = $("#fclear"); if (cl) cl.onclick = () => { pos = owner = q = ""; $("#fo").value = ""; $("#fq").value = ""; sync(); draw(); };
  }
  $app.innerHTML = `${crumbs(["FAAB values"])}<div class="page-head"><div><h1>FAAB values</h1><p class="lede">Board of ${esc(B.as_of)} · ${B.players.length} players · a work in progress, rebuilt every week</p></div><div class="actions"><a class="btn" href="rate/">Rate the board →</a>${shareBtn()}</div></div>
    <div class="card"><p>The model prices every player in league FAAB (the house 100-dollar budget scale). It uses stats only: general rules fitted to this league's trades, cuts and calls, with no hand-set prices. The league's answers on the rating page show which rules fit. They are a capped signal and never move a player's value directly.</p>
      <p class="muted small">Rate the board: pick which of two players is worth more and say whether each value looks right. It takes a minute.</p>
      <details><summary>Answer here without leaving this page</summary><iframe src="rate/" title="LOTG value check" loading="lazy" style="width:100%;height:1100px;border:1px solid var(--line);border-radius:12px;background:var(--bg)"></iframe></details></div>
    <div class="card" id="valuecard"><h2>Roster value by team ${liveNote(live)}</h2>${table([
      { k: "t", label: "Team", left: true, html: (r) => `${teamLink(r.t)} <button class="b mini" data-owner="${esc(r.t)}" title="Show this team's board">board ↓</button>` },
      { k: "total", label: "Total", html: (r) => `<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><b>${money(r.total)}</b><div class="bar-h" style="width:90px"><i style="width:${(100 * r.total) / maxT}%"></i></div></div>` },
      { k: "players", label: "Players", html: (r) => money(r.players) },
      { k: "picks", label: `Picks ${PK.years[0]}-${String(PK.years[PK.years.length - 1]).slice(2)}`, html: (r) => `${money(r.picks)} <span class="muted small">${r.np} · ${r.firsts} 1st${r.firsts === 1 ? "" : "s"}</span>` },
      { k: "QB", label: "QB", html: (r) => money(r.QB) }, { k: "RB", label: "RB", html: (r) => money(r.RB) },
      { k: "WR", label: "WR", html: (r) => money(r.WR) }, { k: "TE", label: "TE", html: (r) => money(r.TE) },
      { k: "n", label: "# players" },
      { k: "np", label: "# picks" },
      { k: (r) => r.top?.value, label: "Most valuable", left: true, html: (r) => (r.top ? `${playerLink(r.top.name)} ${money(r.top.value)}` : "—") },
    ], totals, { sort: 1, teamOf: (r) => r.t, tools: false, name: "roster_value" })}
      <p class="muted small">Total = rostered players' board values + every rookie pick held for the next ${PK.years.length} drafts (${PK.years[0]}–${PK.years[PK.years.length - 1]}, rounds 1–${PK.rounds}). Each pick is priced by the FAAB system's own rule: next year's picks by the original team's projected draft slot (roster strength blended with this season's record), so a likely top pick is worth more; later drafts at the round's average, on the system's weekly pick-price schedule. Pick ownership is the build's (trades, the commissioner's off-platform moves, Sleeper).</p></div>
    <div class="card"><h2>Picks held</h2>${table([
      { k: "t", label: "Team", left: true, html: (r) => teamLink(r.t) },
      ...PK.years.map((y) => ({ k: (r) => (held[r.t] || []).filter((p) => p.y === y).reduce((a, p) => a + p.v, 0), label: String(y), left: true,
        html: (r) => pickDots((held[r.t] || []).filter((p) => p.y === y), r.t) })),
      { k: "np", label: "Picks" },
      { k: "picks", label: "Value", html: (r) => money(r.picks) },
    ], totals, { sort: PK.years.length + 2, teamOf: (r) => r.t, tools: false })}<p class="muted small">Each square is a pick, numbered by round: outlined = the team's own, filled = acquired (tap or hover for whose). Values are on the FAAB board's pick scale.</p></div>
    <div class="card nocv" id="boardcard"><h2>Board</h2>
      <div class="seg" role="group" aria-label="Position"><button data-pos="" aria-pressed="${!pos}">All</button>${positions.concat(["PICK"]).map((p) => `<button data-pos="${esc(p)}" aria-pressed="${p === pos}">${esc(p)}</button>`).join("")}</div>
      <div class="controls">
        <select id="fo" aria-label="Owner"><option value="">All owners</option><option value="FA" ${owner === "FA" ? "selected" : ""}>Free agents</option>${meta.teams.map((t) => `<option ${t === owner ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
        <input class="f" id="fq" type="search" placeholder="Player" value="${esc(q)}" aria-label="Player">
      </div><div id="fb"></div></div>
    <div class="card"><h2>Rookie pick values</h2><p>${(B.picks || []).map((p) => `<span class="chip">${esc(p.slot)} <b>${money(p.value)}</b></span>`).join("")}</p>
      <p class="muted small">What a rookie-draft slot is worth on the same scale.</p></div>`;
  $$("[data-pos]", $app).forEach((b) => b.onclick = () => { pos = b.dataset.pos; sync(); draw(); });
  $("#fo").onchange = (e) => { owner = e.target.value; sync(); draw(); };
  // "board ↓" on a team: filter the board to that team and scroll down to it
  $("#valuecard").onclick = (e) => {
    const b = e.target.closest("[data-owner]");
    if (!b) return;
    owner = b.dataset.owner; pos = ""; q = "";
    $("#fo").value = owner; $("#fq").value = "";
    sync(); draw();
    $("#boardcard").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  $("#fq").oninput = debounce((e) => { q = e.target.value.trim(); sync(); draw(); }, 150);
  draw();
}

// ---------- every export sheet, whole
const PAGE = 100;
const kb = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB");
const SHEET_NAMES = Object.fromEntries(SHEETS);
SHEET_NAMES.formulas = "Column definitions (formulas)";
SHEET_NAMES.league_all_time = "League all-time";
SHEET_NAMES.non_rookie_picks = "Startup & vet picks";
async function data(sheet, query) {
  const ix = await load("sheets/index.json");
  if (!sheet) {
    setTitle("Data");
    $app.innerHTML = `${crumbs(["Data"])}<div class="page-head"><h1>Data</h1><div class="actions">${shareBtn()}</div></div>
      <p class="lede">Every sheet of the league's stats exports, every row and every column, to browse, filter, sort or download. The workbook's sheets, as CSV. ${plural(ix.sheets.reduce((a, m) => a + m.rows, 0), "row")} in all.</p>
      <div class="controls"><input class="f" id="shq" type="search" placeholder="Find a sheet or a column (e.g. boldness, KTC, snap)" aria-label="Find a sheet or column"></div><div id="shhits"></div>
      <div class="card"><h2>Find a record the boards don't keep</h2><p class="small">Pick a sheet, add a filter for each condition, then tap a column to sort. For example:</p>
        <ul class="small">
          <li><a href="#/data/player_week?y=all&c=Position&v=WR&c2=Win%3F&v2=no&c3=Starter%2FBench&v3=Starter&sort=Points">Most points by a WR starter in a loss</a></li>
          <li><a href="#/data/team_week?c=Win%3F&v=yes&sort=PF&dir=lo">Fewest points in a win</a></li>
          <li><a href="#/data/player_week?y=all&c=Rookie%3F&v=yes&c2=Starter%2FBench&v2=Starter&sort=Points">Best week by a rookie starter</a></li>
          <li><a href="#/data/team_week?c=Week%20Name&v=Final&sort=Margin">Biggest final win</a></li>
        </ul></div>
      <div class="grid" id="shgrid">${ix.sheets.map((m) => `<div class="card" data-sheet="${esc((m.sheet + " " + (SHEET_NAMES[m.sheet] || "")).toLowerCase())}"><h2><a href="#/data/${m.sheet}">${esc(SHEET_NAMES[m.sheet] || m.sheet)}</a></h2>
        <p class="muted small">${m.sheet}.csv · ${m.rows.toLocaleString()} rows · ${m.cols.length} columns${m.chunks.length > 1 ? ` · by ${esc(m.season_col)}` : ""}</p>
        <p><a class="btn sec" href="#/data/${m.sheet}">Browse</a> <a class="btn sec" href="${m.csv}" download>CSV ↓ ${kb(m.csv_bytes)}</a></p></div>`).join("")}</div>`;
    // which sheets have a column matching the words typed
    $("#shq").oninput = debounce((e) => {
      const v = e.target.value.trim().toLowerCase();
      $$("#shgrid [data-sheet]").forEach((c) => (c.hidden = false));
      if (!v) { $("#shhits").innerHTML = ""; return; }
      const hits = [];
      for (const m of ix.sheets) m.cols.forEach((c, i) => { if ((c + " " + (m.labels[i] || "")).toLowerCase().includes(v)) hits.push([m, c, m.labels[i]]); });
      $$("#shgrid [data-sheet]").forEach((c) => (c.hidden = !c.dataset.sheet.includes(v) && !hits.some(([m]) => c.dataset.sheet.startsWith(m.sheet + " "))));
      $("#shhits").innerHTML = hits.length ? `<div class="card"><h2>${plural(hits.length, "column")} matching “${esc(v)}”</h2><ul class="res">${hits.slice(0, 60).map(([m, c, l]) => `<li><a href="#/data/${m.sheet}?sort=${encodeURIComponent(c)}">${esc(l || c)}</a><span class="muted small">${esc(SHEET_NAMES[m.sheet] || m.sheet)}${m.defs[c] ? " · " + esc(m.defs[c].slice(0, 90)) + (m.defs[c].length > 90 ? "…" : "") : ""}</span></li>`).join("")}</ul></div>` : `<p class="muted small">No column matches.</p>`;
    }, 150);
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
  let pageSize = prefs.get("lotg:pagesize", PAGE);
  const teamCol = m.cols.indexOf("Team");
  // the view lives in the address bar, so a link reproduces it exactly
  const sync = () => {
    const o = { y: m.chunks.length > 1 ? chunk : "", q };
    filters.filter((f) => f.c).forEach((f, i) => { const sfx = i ? String(i + 1) : ""; o["c" + sfx] = f.c; if (f.o !== "=") o["o" + sfx] = f.o; o["v" + sfx] = f.v; });
    if (sortBy >= 0) { o.sort = m.cols[sortBy]; if (asc) o.dir = "lo"; }
    setQuery(o);
  };
  const all = m.cols.map((_, i) => i);
  let shown = prefs.get("cols:" + sheet, null);
  if (!Array.isArray(shown) || shown.some((i) => i >= m.cols.length)) shown = m.cols.length <= 30 ? all : all.slice(0, 18);
  let rows = [], lastRows = [];
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
    lastRows = rs;
    sync();
    const pages = Math.max(1, Math.ceil(rs.length / pageSize));
    page = Math.min(page, pages - 1);
    const slice = rs.slice(page * pageSize, page * pageSize + pageSize);
    const head = shown.map((i, k) => `<th scope="col" tabindex="0" data-i="${i}" aria-sort="${sortBy === i ? (asc ? "ascending" : "descending") : "none"}" class="l${sortBy === i ? " sorted" + (asc ? " asc" : "") : ""}${k === 0 ? " pin pin1" : ""}"${m.defs[m.cols[i]] ? ` data-def="${esc(m.defs[m.cols[i]])}" data-deflabel="${esc(m.labels[i])}"` : ""}>${esc(m.labels[i])}${m.defs[m.cols[i]] ? " " + DEFBTN : ""}</th>`).join("");
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
    document.getElementById("dt").innerHTML = `<table><thead><tr><th class="pin pin0 nosort"><span class="sr">Open</span></th>${head}</tr></thead><tbody>${slice.map((r) => `<tr${ME && teamCol >= 0 && r[teamCol] === ME ? ' class="me"' : ""}>${go(r)}${shown.map((i, k) => cell(i, r[i], k)).join("")}</tr>`).join("") || `<tr><td></td><td colspan="${shown.length}" class="l muted">No rows match these filters.</td></tr>`}</tbody></table>`;
    pinColumns(document.getElementById("dt"));
    document.getElementById("dcount").textContent = `${rs.length.toLocaleString()} of ${rows.length.toLocaleString()} rows · ${shown.length} of ${m.cols.length} columns`;
    document.getElementById("dpg").innerHTML = (pages > 1 ? `<button data-p="first" ${page === 0 ? "disabled" : ""} aria-label="First page">«</button><button data-p="-1" ${page === 0 ? "disabled" : ""}>‹ Prev</button> <span class="muted small" style="align-self:center">rows ${(page * pageSize + 1).toLocaleString()}–${Math.min(rs.length, (page + 1) * pageSize).toLocaleString()} · page ${page + 1} of ${pages}</span> <button data-p="1" ${page >= pages - 1 ? "disabled" : ""}>Next ›</button><button data-p="last" ${page >= pages - 1 ? "disabled" : ""} aria-label="Last page">»</button>` : "")
      + ` <select id="dps" aria-label="Rows per page" style="min-height:32px">${[50, 100, 250, 500].map((n) => `<option value="${n}" ${n === pageSize ? "selected" : ""}>${n} per page</option>`).join("")}</select>`;
  }
  const colPicker = () => m.cols.map((c, i) => `<label style="display:inline-flex;gap:4px;margin:0 10px 4px 0;font-size:13px"><input type="checkbox" data-c="${i}" ${shown.includes(i) ? "checked" : ""}>${esc(m.labels[i])}</label>`).join("");
  setTitle(SHEET_NAMES[sheet] || sheet);
  $app.innerHTML = `${crumbs(["Data", "data"], [SHEET_NAMES[sheet] || sheet])}
    <h1>${esc(SHEET_NAMES[sheet] || sheet)}</h1>
    <div class="page-head"><p class="muted small" style="margin:0">${sheet}.csv · ${m.rows.toLocaleString()} rows · ${m.cols.length} columns</p><div class="actions"><a class="btn sec" href="${m.csv}" download>Whole sheet CSV ↓ ${kb(m.csv_bytes)}</a><button class="b" id="dcsv" title="Only the rows these filters keep, only the columns shown">Filtered rows CSV ↓</button>${shareBtn()}</div></div>
    <div class="controls">
      ${m.chunks.length > 1 ? `<select id="dy">${m.chunks.map(([n, s, k]) => `<option value="${s}" ${s === chunk ? "selected" : ""}>${esc(m.season_col)} ${esc(n)} (${k.toLocaleString()} rows)</option>`).join("")}<option value="all" ${chunk === "all" ? "selected" : ""}>All (${m.rows.toLocaleString()} rows, slower)</option></select>` : ""}
      <input class="f" id="dq" type="search" placeholder="Search every cell" value="${esc(q)}">
    </div>
    <div id="filters"></div>
    <details><summary>Columns (${m.cols.length})</summary>
      <p><span class="seg" style="margin:0"><button id="call">All</button><button id="cnone">None</button><button id="cdef">Default</button></span></p>
      <input class="f" id="cpq" type="search" placeholder="Find a column" style="width:100%;margin-bottom:8px" aria-label="Find a column"><div id="cp">${colPicker()}</div></details>
    <details><summary>What each column means</summary><input class="f" id="gq" type="search" placeholder="Filter definitions" style="width:100%;margin-bottom:8px"><div id="gl"></div></details>
    <p class="muted small" id="dcount"></p>
    <div class="card"><div class="scroll sx tallbox" id="dt"></div><div class="seg" id="dpg" style="margin-top:10px;align-items:center"></div>
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
  document.getElementById("dpg").onclick = (e) => { const b = e.target.closest("button[data-p]"); if (!b) return; const v = b.dataset.p; page = v === "first" ? 0 : v === "last" ? 1e9 : page + +v; draw(); document.getElementById("dcount").scrollIntoView({ block: "start" }); };
  document.getElementById("dpg").onchange = (e) => { if (e.target.id !== "dps") return; pageSize = +e.target.value; prefs.set("lotg:pagesize", pageSize); page = 0; draw(); };
  document.getElementById("dt").onkeydown = (e) => { const th = e.target.closest && e.target.closest("th[data-i]"); if (th && (e.key === "Enter" || e.key === " ") && !e.target.classList.contains("defbtn")) { e.preventDefault(); th.click(); } };
  document.getElementById("cpq").oninput = (e) => { const v = e.target.value.trim().toLowerCase(); $$("#cp label").forEach((l) => (l.hidden = !!v && !l.textContent.toLowerCase().includes(v))); };
  document.getElementById("dcsv").onclick = () => downloadText(`${sheet}_filtered.csv`, toCSV(shown.map((i) => m.labels[i]), lastRows.map((r) => shown.map((i) => r[i] === null || r[i] === undefined ? "" : typeof r[i] === "boolean" ? (r[i] ? "TRUE" : "FALSE") : r[i]))));
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
  return `<ol class="hist timeline">${lines.map(([t, link]) => `<li>${link ? `<a href="#/${esc(link)}">${esc(t)}</a>` : esc(t)}</li>`).join("")}</ol>`;
}

const award = (a) => `<span class="chip award">${esc(a)}</span>`;
function lineup(team, side) {
  const rows = (s) => side.players.filter((p) => p[5] === s);
  const st = rows(true), bn = rows(false);
  const bestBench = bn.length ? Math.max(...bn.map((p) => p[4] || 0)) : null;
  const line = (p, bench) => `<tr><td class="l muted small">${esc(p[3] || p[2] || "")}</td><td class="l">${p[1] ? `<a href="#/player/${esc(p[1])}">${esc(p[0])}</a>` : esc(p[0])} ${posBadge(p[2])} <span class="muted small">${nflLink(p[6])}</span>${(p[7] || []).map(award).join("")}</td><td class="${!bench && (p[4] || 0) >= 20 ? "w" : bench && p[4] === bestBench && bestBench > 0 ? "muted" : ""}">${fmt({ d: 2 }, p[4])}</td></tr>`;
  const eff = side.max ? side.pf / side.max : null;
  return `<div class="card"><h2>${teamLink(team)} <span class="${side.win ? "w" : "lo"}">${fmt({ d: 2 }, side.pf)}</span> <span class="chip ${side.win ? "ok" : "bad"}">${side.win ? "Won" : "Lost"}</span></h2>
    ${(side.awards || []).length ? `<p>${side.awards.map(award).join("")}</p>` : ""}
    <p class="muted small">vs ${teamLink(side.opp)} · max possible ${fmt({ d: 2 }, side.max)}${eff != null ? ` · ${Math.round(eff * 100)}% efficient` : ""}${side.max != null ? ` · ${fmt({ d: 2 }, side.max - side.pf)} left on the bench` : ""}</p>
    <table class="rk"><tbody>${st.map((p) => line(p, false)).join("")}</tbody></table>
    <details><summary class="small muted">Bench (${bn.length}) · ${fmt({ d: 2 }, bn.reduce((a, p) => a + (p[4] || 0), 0))} pts</summary><table class="rk"><tbody>${bn.slice().sort((a, b) => (b[4] || 0) - (a[4] || 0)).map((p) => line(p, true)).join("")}</tbody></table></details></div>`;
}

async function game(rest) {
  const [y, w, team] = String(rest || "").split("/");
  const wk = await load(`week/${y}-${w}.json`);
  const name = Object.keys(wk.teams).find((t) => tslug(t) === team) || Object.keys(wk.teams)[0];
  const me = wk.teams[name], opp = wk.teams[me.opp];
  const margin = opp ? me.pf - opp.pf : null;
  setTitle(`${name} vs ${me.opp}, ${y} ${wk.week_name}`);
  const nav = await weekNav(y, w, (x) => `game/${x.y}/${x.w}/${tslug(name)}`).catch(() => "");
  $app.innerHTML = `${crumbs(["Weeks", "weeks/" + y], [`${y} ${wk.week_name}`, `week/${y}/${w}`], [`${name} vs ${me.opp}`])}
    <div class="page-head"><div><h1>${esc(name)} vs ${esc(me.opp)}</h1><p class="lede">${y} ${esc(wk.week_name)} · ${margin != null ? `${esc(margin >= 0 ? name : me.opp)} by <b>${fmt({ d: 2 }, Math.abs(margin))}</b>` : ""} · team PF includes the semifinal +5; player points do not</p></div>
      <div class="actions"><a class="btn sec" href="#/h2h?a=${encodeURIComponent(name)}&b=${encodeURIComponent(me.opp)}">All their meetings</a>${shareBtn()}</div></div>
    ${nav}
    ${opp ? `<div class="card nocv" style="padding:12px 16px"><div style="display:flex;justify-content:space-between;font-weight:700;margin-bottom:6px"><span>${avatar(name)}${esc(name)} ${fmt({ d: 2 }, me.pf)}</span><span>${fmt({ d: 2 }, opp.pf)} ${esc(me.opp)}${avatar(me.opp)}</span></div>
      <div style="display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--chip)"><i style="width:${(100 * me.pf / ((me.pf + opp.pf) || 1)).toFixed(1)}%;background:${teamColor(name)}"></i><i style="flex:1;background:${teamColor(me.opp)}"></i></div></div>` : ""}
    <div class="grid">${lineup(name, me)}${opp ? lineup(me.opp, opp) : ""}</div>
    <p class="small">More: <a class="chip" href="#/data/team_week?c=Team&v=${encodeURIComponent(name)}">${esc(name)}'s every week</a><a class="chip" href="#/data/player_week?c=Year&v=${y}&y=${y}&c2=Week&v2=${w}">every player that week</a><a class="chip" href="#/week/${y}/${w}">every ${esc(wk.week_name)} game</a></p>`;
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
  // the week's best and worst: top team score, top player, closest game
  const sides = Object.entries(wk.teams);
  const topT = sides.slice().sort((a, b) => b[1].pf - a[1].pf)[0], lowT = sides.slice().sort((a, b) => a[1].pf - b[1].pf)[0];
  const allP = sides.flatMap(([t, s]) => s.players.filter((p) => p[5]).map((p) => [t, p]));
  const topP = allP.slice().sort((a, b) => (b[1][4] || 0) - (a[1][4] || 0))[0];
  const close = games.filter((g) => g[3]).sort((a, b) => Math.abs(a[1].pf - a[3].pf) - Math.abs(b[1].pf - b[3].pf))[0];
  setTitle(`${y} ${wk.week_name}`);
  const nav = await weekNav(y, w, (x) => `week/${x.y}/${x.w}`).catch(() => "");
  $app.innerHTML = `${crumbs(["Weeks", "weeks/" + y], [`${y} ${wk.week_name}`])}<div class="page-head"><h1>${y} ${esc(wk.week_name)}</h1><div class="actions">${shareBtn()}</div></div>
    ${nav}
    <div class="hero">
      ${topT ? `<div class="tile"><a href="#/game/${y}/${w}/${tslug(topT[0])}"><span>Top score</span><b>${esc(topT[0])} ${fmt({ d: 2 }, topT[1].pf)}</b></a></div>` : ""}
      ${lowT ? `<div class="tile"><a href="#/game/${y}/${w}/${tslug(lowT[0])}"><span>Low score</span><b>${esc(lowT[0])} ${fmt({ d: 2 }, lowT[1].pf)}</b></a></div>` : ""}
      ${topP ? `<div class="tile">${topP[1][1] ? `<a href="#/player/${esc(topP[1][1])}">` : ""}<span>Top starter</span><b>${esc(topP[1][0])} ${fmt({ d: 2 }, topP[1][4])}</b><small>${esc(topP[0])}</small>${topP[1][1] ? "</a>" : ""}</div>` : ""}
      ${close ? `<div class="tile"><a href="#/game/${y}/${w}/${tslug(close[0])}"><span>Closest game</span><b>${fmt({ d: 2 }, Math.abs(close[1].pf - close[3].pf))} pts</b><small>${esc(close[0])} v ${esc(close[2])}</small></a></div>` : ""}
    </div>
    <div class="games">${games.map(([a, sa, b, sb]) => { const aw = sa.win; return `<a class="game${ME && (a === ME || b === ME) ? " mine" : ""}" href="#/game/${y}/${w}/${tslug(a)}">
      <div class="${aw ? "won" : ""}"><span>${avatar(a)}${esc(a)}</span><span>${fmt({ d: 2 }, sa.pf)}</span></div>
      <div class="${sb && sb.win ? "won" : ""}"><span>${avatar(b)}${esc(b)}</span><span>${fmt({ d: 2 }, sb && sb.pf)}</span></div>
      ${sb ? `<div class="gm">${esc(aw ? a : b)} by ${fmt({ d: 2 }, Math.abs(sa.pf - sb.pf))}</div>` : ""}</a>`; }).join("")}</div>
    <p class="small muted">Tap a matchup for both lineups. <kbd>[</kbd> and <kbd>]</kbd> step through the weeks.</p>`;
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
    .map(([c, l, i]) => { const dd = defOf(c, sheet); return `<div class="tile"${dd ? ` data-def="${esc(dd)}" data-deflabel="${esc(l)}"` : ""}><b>${fmt(t.fmt[c], r[i])}</b><span>${esc(l)}${dd ? " " + DEFBTN : ""}</span></div>`; }).join("");
  // the picks before and after this one in the same draft order
  const yi = t.cols.indexOf("Year"), ni = t.cols.indexOf("Number");
  const order = t.rows.slice().sort((a, b) => String(a[yi]).localeCompare(String(b[yi])) || String(a[ni]).localeCompare(String(b[ni]), undefined, { numeric: true }));
  const k = order.indexOf(r), prev = order[k - 1], next = order[k + 1];
  const pl = (x) => `${esc(x[yi])} ${esc(x[ni])}`;
  setTitle(`${v("Year")} pick ${v("Number")}`);
  $app.innerHTML = `${crumbs(["Draft history", "draft"], [`${v("Year")} pick ${v("Number")}`])}
    <div class="page-head"><h1>${esc(v("Year"))} pick ${esc(v("Number"))}</h1><div class="actions">${shareBtn()}</div></div>
    <div class="weeknav">${prev ? `<a href="#/pick/${sheet}/${prev[ri]}" data-prev>‹ ${pl(prev)}</a>` : '<span class="dis">‹ First pick</span>'}<a class="small" href="#/draft?year=${encodeURIComponent(v("Year"))}">The whole ${esc(v("Year"))} draft</a>${next ? `<a href="#/pick/${sheet}/${next[ri]}" data-next>${pl(next)} ›</a>` : '<span class="dis">Last pick ›</span>'}</div>
    <p class="lede">${v("Player Picked") ? playerLink(v("Player Picked")) + " · " : ""}made by ${teamLink(v("Team"))}${v("Original Team") && v("Original Team") !== v("Team") ? ` · originally ${teamLink(v("Original Team"))}'s pick` : ""}</p>
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
    return `<div class="depth"><h3>${posBadge(pos)}</h3>${ps.length ? `<ol>${ps.slice(0, pos === "WR" ? 7 : 6).map((r) => `<li>${nameCell(r)}${r.dpos && r.dpos !== pos ? ` <span class="muted small">${esc(r.dpos)}</span>` : ""} <span class="muted small">${owner(r)}${r.value != null ? " · " + money(r.value) : ""}</span></li>`).join("")}</ol>` : '<p class="muted small">—</p>'}</div>`;
  }).join("");
  const SPc = SP.cols;
  const rows = players.filter((r) => r.own || NAMES_BY_ID[r.pid] || r.value || r.s);
  setTitle(`${code} · NFL`);
  $app.innerHTML = `${crumbs(["NFL teams"], [code])}<div class="page-head"><h1>${esc(code)}</h1><div class="actions">${shareBtn()}</div></div>
    <nav class="nflgrid" aria-label="NFL teams">${NFL_TEAMS.map((c) => `<a href="#/nfl/${c}" class="${c === code ? "on" : ""}"${c === code ? ' aria-current="page"' : ""}>${c}</a>`).join("")}</nav>
    <p class="muted">${next ? `Next kickoff: week ${next[0]}, ${esc(new Date(next[1]).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))} ET · ` : ""}owners ${liveNote(live)}</p>
    <div class="card"><h2>Depth chart</h2><div class="depthgrid">${depth}</div>
      <p class="muted small">NFL depth chart order from Sleeper's player list (as of the last build); each player's league owner and FAAB value.</p></div>
    <div class="card"><h2>${esc(code)} players and the league</h2>${table([
      { k: "name", label: "Player", left: true, html: nameCell },
      { k: "pos", label: "Pos", left: true, html: (r) => posBadge(r.pos) }, { k: "age", label: "Age", spec: { d: 2 } },
      { k: "own", label: "Owner", left: true, html: owner },
      { k: "value", label: "FAAB value", html: (r) => r.value == null ? "—" : money(r.value) },
      { k: "proj", label: "Proj./wk", spec: { d: 2 } },
      ...SPc.map((c, i) => ({ k: (r) => r.s ? r.s[i] : null, label: SP.labels[i], spec: SP.fmt[c], col: c })),
    ], rows, { sort: 4, defs: "player_year", teamOf: (r) => r.own, name: `${code}_players` })}
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
async function predict(_a, query, live) {
  setTitle("Predictions");
  $app.innerHTML = `${crumbs(["Predictions"])}<h1>Predictions</h1><p class="muted">Loading the schedule, rosters and the forecast's simulated seasons…</p><div class="skel blk"></div>`;
  const [meta, LW, nfl, H] = await Promise.all([load("meta.json"), load("live_watch.json"), loadNfl(), load("home.json")]);
  // the home page's forecast seasons, replayed here (lotg_support.league_site.forecast_odds)
  const SIM = H.forecast && H.forecast.sim;
  const SB = SIM ? await fetch(withBuild("data/" + SIM.file)).then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null) : null;
  live = live || await loadLive();
  if (!live) { $app.innerHTML = `${crumbs(["Predictions"])}<h1>Predictions</h1><div class="card empty"><div class="big">📡</div><p>Needs Sleeper's rosters and schedule, and Sleeper is unreachable right now.</p><p><button class="b pri" data-relive>Try again</button></p></div>`; return; }
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
  const params = new URLSearchParams(query || "");
  for (const x of (params.get("p") || "").split(",")) { const mm = /^(\d+)([ab])$/.exec(x); if (mm) picks[+mm[1]] = mm[2]; }
  for (const x of (params.get("mv") || "").split(",")) { const [pid, to] = x.split(">"); if (pid && to) moves.push({ pid, to }); }
  const syncScenario = () => setQuery({ p: Object.entries(picks).map(([i, sd]) => i + sd).join(","), mv: moves.map((m) => m.pid + ">" + m.to).join(",") });
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
  // ---- the full forecast: replay the home page's simulated seasons ----------------
  // forecast_sims.bin = int16 tenths of a point, sims x SIM.weeks x SIM.teams, raw
  // points (no +5). With no changes this counts exactly what the home page counted
  // (league_site.replay_sims, line for line, in integer hundredths). A pick puts the
  // picked side's score on top in that game; a roster move shifts the team's
  // simulated weeks by the forecast's slope x the change in its fielded lineup
  // (forecast rates, forecast availability); a week Sleeper has finished since the
  // build uses its real scores, and the week in progress its live points plus what
  // is left once its games have started.
  const S16 = SB && SIM ? new Int16Array(SB) : null;
  const FULL = !!(S16 && S16.length && S16.length % (SIM.weeks.length * SIM.teams.length) === 0);
  const SW = FULL ? SIM.weeks : [], TN = FULL ? SIM.teams : [], nW = SW.length, nT = TN.length;
  const NS = FULL ? S16.length / (nW * nT) : 0;
  const tIdx = Object.fromEntries(TN.map((t, k) => [t, k])), wCol = Object.fromEntries(SW.map((w, j) => [w, j]));
  const nameRank = (() => { const o = TN.map((_, k) => k).sort((a, b) => (TN[a] < TN[b] ? -1 : TN[a] > TN[b] ? 1 : 0)); const r = []; o.forEach((k, i) => (r[k] = i)); return r; })();
  const FR = (FULL && SIM.rates) || {};
  const rateOf = (pid) => FR[pid] ?? LW.rates[pid] ?? 3;
  // fielded lineup's expected points in week w: K availability draws, each player's
  // draw hashed from (player, week, k) so two rosters share draws for shared players
  const hash01 = (str) => { let h = 2166136261; for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619); h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995); h ^= h >>> 15; return (h >>> 0) / 4294967296; };
  const bestMean = (pids) => {
    const pool = pids.map((pid) => ({ pos: (nfl[pid] || [])[1], r: rateOf(pid) })).sort((x, y) => y.r - x.r), used = new Set();
    let m = 0;
    for (const sl of LW.roster_positions.slice().sort((a, b) => (fits[a] || []).length - (fits[b] || []).length)) {
      const i = pool.findIndex((x, j) => !used.has(j) && (fits[sl] || []).includes(x.pos));
      if (i >= 0) { used.add(i); m += pool[i].r; }
    }
    return m;
  };
  const fielded = (pids, t, w) => {
    const ps = pids.map((pid) => pAvail(pid, t, w));
    if (ps.every((x) => x >= 0.999)) return bestMean(pids);
    let m = 0;
    for (let k = 0; k < K; k++) m += bestMean(pids.filter((pid, j) => hash01(`${pid}|${w}|${k}`) < ps[j]));
    return m / K;
  };
  const startable = (t) => (live.rosterOf[t]?.players || []).filter((pid) => !(live.rosterOf[t].taxi || new Set()).has(pid));
  // real scores Sleeper has for weeks the forecast simulated (finished since the build)
  const doneWk = {};
  weeks.forEach((w, i) => {
    if (!FULL || !(w in wCol) || w >= curWk) return;
    const row = new Array(nT).fill(0);
    for (const m of mus[i]) { const k = tIdx[live.byRid[m.roster_id]]; if (k != null) row[k] = Math.round((m.points || 0) * 100); }
    if (row.some((x) => x)) doneWk[w] = row;
  });
  // regular-season games by (week, team index), to apply picks
  const pickAt = (withChanges) => {
    const o = {};
    if (!withChanges) return o;
    games.forEach((g, i) => { const p = picks[i]; if (!p) return; (o[g.w] = o[g.w] || []).push([tIdx[g.a], tIdx[g.b], p]); });
    return o;
  };
  function simulateFull(withChanges) {
    seed = 20261114;
    // per team, per simulated week: the roster-move shift in hundredths
    const shift = TN.map(() => new Array(nW).fill(0));
    const R = withChanges ? rosterNow() : null;
    if (withChanges && moves.length) {
      const touched = new Set(moves.map((m) => m.to).filter((t) => t !== "out"));
      for (const m of moves) for (const t of teams) if ((live.rosterOf[t]?.players || []).includes(m.pid)) touched.add(t);
      for (const t of touched) {
        const k = tIdx[t]; if (k == null) continue;
        const b = startable(t), a = R[t].filter((pid) => !(live.rosterOf[t]?.taxi || new Set()).has(pid));
        SW.forEach((w, j) => (shift[k][j] = Math.round(100 * SIM.slope * (fielded(a, t, w) - fielded(b, t, w)))));
      }
    }
    // the week in progress: live points + what each starter has left
    const nowET = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
    const liveWk = {};
    for (const g of games) if (g.w === curWk && g.w in wCol) for (const m of g.ms) {
      const t = live.byRid[m.roster_id], ko = LW.kickoffs[String(g.w)] || {};
      let rem = 0, v = 0;
      for (const pid of m.starters || []) {
        const kk = ko[(nfl[pid] || [])[2]]; if (!kk || out(pid, t)) continue;
        const h = (nowET - new Date(kk)) / 36e5, f = h < 0 ? 1 : Math.max(0, 1 - h / 3.3), r = LW.rates[pid] ?? 3;
        rem += r * f; v += (0.65 * Math.max(3, r)) ** 2 * f;
      }
      if ((m.points || 0) > 0) liveWk[tIdx[t]] = { mean: 100 * ((m.points || 0) + rem), sd: 100 * Math.sqrt(v) };
    }
    const anyLive = Object.keys(liveWk).length > 0;
    const PK = pickAt(withChanges), obs = SIM.obs || {}, pairs = SIM.pairs || {};
    const tally = Object.fromEntries(teams.map((t) => [t, { playoffs: 0, final: 0, title: 0, wins: 0, seed1: 0, pts: 0 }]));
    const regLeft = SW.filter((w) => w <= SIM.regular_weeks && w !== curWk);
    const cur = new Array(nW);
    for (let s = 0; s < NS; s++) {
      const off = s * nW * nT;
      for (let j = 0; j < nW; j++) {
        const w = SW[j], row = new Array(nT);
        if (doneWk[w]) for (let k = 0; k < nT; k++) row[k] = doneWk[w][k];
        else for (let k = 0; k < nT; k++) row[k] = S16[off + j * nT + k] * 10 + shift[k][j];
        if (w === curWk && anyLive) for (const k in liveWk) row[k] = Math.round(liveWk[k].mean + gauss() * liveWk[k].sd);
        for (const [a, b, p] of PK[w] || []) {
          if (a == null || b == null) continue;
          if ((p === "a" && row[a] < row[b]) || (p === "b" && row[b] < row[a]) || row[a] === row[b]) {
            if (row[a] === row[b]) row[p === "a" ? a : b] += 1; else { const x = row[a]; row[a] = row[b]; row[b] = x; }
          }
        }
        cur[j] = row;
      }
      const pts = (w, k) => (w in wCol ? cur[wCol[w]][k] : (obs[w] || [])[k] || 0);
      const half = new Array(nT).fill(0), pf = new Array(nT).fill(0);
      for (let w = 1; w <= SIM.regular_weeks; w++) {
        if (!(w in wCol) && !(w in obs)) continue;
        for (const [a, b] of pairs[w] || []) {
          const x = pts(w, a), y = pts(w, b);
          pf[a] += x; pf[b] += y;
          if (x > y) half[a] += 2; else if (y > x) half[b] += 2; else { half[a]++; half[b]++; }
        }
      }
      const table = TN.map((_, k) => k).sort((a, b) => half[b] - half[a] || pf[b] - pf[a] || nameRank[a] - nameRank[b]);
      for (let k = 0; k < nT; k++) { tally[TN[k]].wins += half[k] / 2; for (const w of regLeft) tally[TN[k]].pts += pts(w, k); }
      for (const k of table.slice(0, SIM.playoff_teams)) tally[TN[k]].playoffs++;
      tally[TN[table[0]]].seed1++;
      const sfw = SIM.semifinal_week;
      if (SIM.playoff_teams < 4 || (!(sfw in wCol) && !(sfw in obs))) continue;
      const sd = table.slice(0, 4);
      const win = [[sd[0], sd[3]], [sd[1], sd[2]]].map(([hi, lo]) => (pts(sfw, hi) + SIM.bonus >= pts(sfw, lo) ? hi : lo));
      win.forEach((k) => tally[TN[k]].final++);
      const fw = SIM.final_weeks.filter((w) => w in wCol || w in obs);
      if (!fw.length) continue;
      const [a, b] = win, tot = (k) => fw.reduce((z, w) => z + pts(w, k), 0);
      tally[TN[tot(a) >= tot(b) ? a : b]].title++;
    }
    const L = Object.fromEntries(teams.map((t) => [t, { mean: regLeft.length ? tally[t].pts / NS / regLeft.length / 100 : NaN }]));
    return { tally, L, n: NS };
  }
  const runSim = (withChanges) => (FULL ? simulateFull(withChanges) : { ...simulate(withChanges), n: N });
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
    const res = runSim(true);
    const T = res.tally, N = res.n;
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
    syncScenario();
    $$(".pgame", $app).forEach((el) => { const i = +el.dataset.g; el.querySelectorAll("button").forEach((x) => { x.classList.toggle("won", picks[i] === x.dataset.side); x.classList.toggle("lost", !!picks[i] && picks[i] !== x.dataset.side); x.setAttribute("aria-pressed", picks[i] === x.dataset.side); }); });
    document.getElementById("pstate").textContent = changed ? `${changed} change${changed === 1 ? "" : "s"} · small +/− = change vs no changes (percentage points for odds; wins and points for those columns)` : "No changes yet: these are the baseline odds.";
  }
  const byWeek = weeks.map((w) => [w, games.map((g, i) => [g, i]).filter(([g]) => g.w === w)]);
  const allPlayers = teams.flatMap((t) => (live.rosterOf[t]?.players || []).map((pid) => [pid, t])).filter(([pid]) => (nfl[pid] || [])[1])
    .sort((a, b) => ((nfl[a[0]] || [])[0] || "").localeCompare((nfl[b[0]] || [])[0] || ""));
  $app.innerHTML = `${crumbs(["Predictions"])}<div class="page-head"><h1>Predictions</h1><div class="actions">${shareBtn()}</div></div>
    <p class="muted">Pick winners and make roster moves; the rest of ${meta.season} is replayed ${(FULL ? NS : N).toLocaleString()} times in your browser through the league's playoff rules. ${liveNote(live)}</p>
    <div class="card"><h2>Season odds</h2><p class="small muted" id="pstate"></p><div id="pres"><p class="muted">Simulating…</p></div>
      <p class="muted small">${FULL ? `These are the home page's forecast seasons: the same ${NS.toLocaleString()} simulations (lotg_support.forecast, built ${esc((meta.built || "").slice(0, 16))}), replayed here through the league's rules, so with no changes the odds are the home page's exactly. Each simulated season draws every team's true level (its roster projection, calibrated on past seasons and updated with this season's scores), a league-wide swing each week, each team's own weekly spread, and who is available each week from the forecast's injury model: players listed Out come back on the league's return curve, players on IR not before the NFL's 4-game minimum, Questionable players play 85% of the time this week, a sourced "out for the season" note keeps a player out, and ESPN's injury list (captured daily) sets return weeks. A pick puts the picked team's score on top in that game. A roster move moves each of the team's simulated weeks by the change in its best fielded lineup (the forecast's player rates and availability) times the forecast's calibration slope (${SIM.slope}). A week Sleeper has finished since the build uses its real scores; once the week in progress has started, it uses live points plus what each starter has left. Pts/wk is the expected points a week over the remaining regular season.` : `Each team's week = its best lineup from its current roster's projections (the forecast's rate blended with this season's PPG), with who can play each week from the forecast's injury model. The forecast's own simulations are not in this build, so these odds come from a simpler model than the home page's and differ from it.`} Standings: wins, then PF; top ${P.teams} make the playoffs; semifinal +${P.semifinal_bonus} to the higher seed; the final is ${P.final_weeks.length} week${P.final_weeks.length > 1 ? "s" : ""}.</p></div>
    ${espnCard(H.forecast, nfl, live)}
    <div class="card"><h2>Roster moves</h2>
      <div class="controls"><select id="mp"><option value="">Player…</option>${allPlayers.map(([pid, t]) => `<option value="${pid}">${esc((nfl[pid] || [])[0])} (${esc((nfl[pid] || [])[1])}, ${esc(t)})</option>`).join("")}</select>
        <select id="mt"><option value="out">Out for the season</option>${teams.map((t) => `<option value="${esc(t)}">Trade to ${esc(t)}</option>`).join("")}</select>
        <button class="b" id="madd">Apply</button></div><div id="pmoves"></div></div>
    <div class="card"><h2>Remaining games</h2><p class="muted small">Tap a team to make it win; tap again for "simulate".</p>
      ${byWeek.map(([w, gs]) => `<h3>Week ${w}${w === curWk ? " (in progress)" : ""}</h3><div class="pgames">${gs.map(([g, i]) => `<div class="pgame" data-g="${i}"><button data-side="a">${esc(g.a)}</button><span class="muted small">vs</span><button data-side="b">${esc(g.b)}</button></div>`).join("")}</div>`).join("")}
      <p><button class="b" id="preset">Clear every pick</button>${ME && teams.includes(ME) ? ` <button class="b" id="pme">★ ${esc(ME)} wins out</button>` : ""} <button class="b" id="pfav" title="Each game to the side with more projected points per week">Pick the favourites</button> ${shareBtn().replace("Share", "Share this scenario")}</p></div>`;
  const rerun = () => { document.getElementById("pres").style.opacity = .5; setTimeout(() => { draw(); document.getElementById("pres").style.opacity = 1; }, 20); };
  $app.querySelectorAll(".pgame").forEach((el) => el.onclick = (e) => {
    const b = e.target.closest("button[data-side]"); if (!b) return;
    const i = +el.dataset.g, side = b.dataset.side;
    if (picks[i] === side) delete picks[i]; else picks[i] = side;
    el.querySelectorAll("button").forEach((x) => x.classList.toggle("won", picks[i] === x.dataset.side));
    rerun();
  });
  document.getElementById("preset").onclick = () => { picks = {}; $app.querySelectorAll(".pgame button").forEach((x) => x.classList.remove("won", "lost")); rerun(); };
  if ($("#pme")) $("#pme").onclick = () => { games.forEach((g, i) => { if (g.a === ME) picks[i] = "a"; else if (g.b === ME) picks[i] = "b"; }); rerun(); toast(`${ME} wins every remaining game`); };
  $("#pfav").onclick = () => { if (!base) return; games.forEach((g, i) => { const a = base.L[g.a]?.mean, b = base.L[g.b]?.mean; if (isFinite(a) && isFinite(b)) picks[i] = a >= b ? "a" : "b"; }); rerun(); toast("Every game to the projected favourite"); };
  document.getElementById("madd").onclick = () => { const pid = document.getElementById("mp").value; if (!pid) return; moves = moves.filter((m) => m.pid !== pid); moves.push({ pid, to: document.getElementById("mt").value }); rerun(); };
  document.getElementById("pmoves").onclick = (e) => { const b = e.target.closest("[data-undo]"); if (!b) return; moves.splice(+b.dataset.undo, 1); rerun(); };
  setTimeout(() => { base = runSim(false); draw(); }, 20);
  if (moves.length) toast(`${plural(moves.length, "roster move")} from the link applied`);
}

// ---------- weeks: every week the league has played (league_week), for the week index
// and the previous / next links on week and matchup pages
let WEEKS = null;
const loadWeeks = () => WEEKS ? Promise.resolve(WEEKS) : load("sheets/index.json").then((ix) => {
  const m = ix.sheets.find((x) => x.sheet === "league_week");
  if (!m) return [];
  return Promise.all(m.chunks.map(([, k]) => load(`sheets/league_week/${k}.json`))).then((parts) => {
    const yi = m.cols.indexOf("Year"), wi = m.cols.indexOf("Week"), ni = m.cols.indexOf("Week Name");
    WEEKS = [].concat(...parts.map((p) => p.rows)).map((r) => ({ y: +r[yi], w: +r[wi], n: r[ni], r, cols: m.cols, fmt: m.fmt, labels: m.labels }))
      .filter((x) => x.y && x.w).sort((a, b) => a.y - b.y || a.w - b.w);
    return WEEKS;
  });
}).catch(() => []);
const weekNav = (y, w, toHref) => loadWeeks().then((ws) => {
  const i = ws.findIndex((x) => x.y === +y && x.w === +w);
  const p = ws[i - 1], n = ws[i + 1];
  return `<div class="weeknav">${p ? `<a href="#/${toHref(p)}" data-prev>‹ ${p.y} ${esc(p.n)}</a>` : '<span class="dis">‹ First week</span>'}
    <a href="#/weeks/${y}" class="small">All ${y} weeks</a>
    ${n ? `<a href="#/${toHref(n)}" data-next>${n.y} ${esc(n.n)} ›</a>` : '<span class="dis">Latest week ›</span>'}</div>`;
});

// ---------- trade calculator: two teams, any players and future picks, on the league's
// own scale (the FAAB board's values; picks by the FAAB system's pick rule), with each
// roster's value and rank and its projected points a week before and after.
// State lives in the URL: ?a=<team>&b=<team>&sa=<assets A sends>&sb=<assets B sends>,
// assets "p<sleeper id>" or "k<year>-<round>-<original team>".
async function calc(_a, query, live) {
  setTitle("Trade calculator");
  $app.innerHTML = `${crumbs(["Trade calculator"])}<h1>Trade calculator</h1><div class="skel blk"></div>`;
  const [meta, B, PK, nfl, LW] = await Promise.all([load("meta.json"), loadBoard(), load("picks.json"), loadNfl(), load("live_watch.json").catch(() => ({ rates: {}, roster_positions: [] }))]);
  live = live || await loadLive();
  if (!B) { $app.innerHTML = `${crumbs(["Trade calculator"])}<h1>Trade calculator</h1><div class="card empty"><div class="big">💲</div><p>The FAAB board isn't published yet, so there are no values to compare.</p></div>`; return; }
  const teams = meta.teams;
  const params = new URLSearchParams(query || "");
  let A = teams.includes(params.get("a")) ? params.get("a") : (ME && teams.includes(ME) ? ME : teams[0]);
  let Bt = teams.includes(params.get("b")) && params.get("b") !== A ? params.get("b") : teams.find((t) => t !== A);
  const split = (v) => (v || "").split(",").filter(Boolean);
  let SA = split(params.get("sa")), SB = split(params.get("sb"));
  const board = Object.fromEntries(B.players.map((x) => [String(x.sid), x]));
  // whose players and picks: Sleeper now when it answered, else the board's owners and the build's picks
  const rosterOf = (t) => live && live.rosterOf[t] ? live.rosterOf[t].players.map(String) : B.players.filter((x) => ownerTeam(x.owner, teams) === t).map((x) => String(x.sid));
  const blocked = (t) => live && live.rosterOf[t] ? new Set([...(live.rosterOf[t].taxi || []), ...(live.rosterOf[t].ir || [])].map(String)) : new Set();
  const HELD = livePicks(PK, live);
  const picksOf = (t) => (HELD[t] || []).map(([y, r, o]) => `k${y}-${r}-${o}`);
  const info = (k) => {
    if (k[0] === "k") {
      const [y, r, ...o] = k.slice(1).split("-"), orig = o.join("-");
      return { k, pick: true, name: `${y} ${ORD[+r] || r + "th"}${orig ? ` (${orig})` : ""}`, pos: "PICK", value: pickValue(PK, B, +y, +r, orig) || 0, y: +y, r: +r };
    }
    const pid = k.slice(1), b = board[pid], n = nfl[pid] || [];
    return { k, pid, name: (b && b.name) || n[0] || NAMES_BY_ID[pid] || pid, pos: (b && b.pos) || n[1] || "", nfl: (b && b.team) || n[2] || "", age: b ? b.age : n[3], inj: (b && b.injury) || n[4] || "", value: b ? b.value : 0, rate: LW.rates[pid] };
  };
  const assetsOf = (t) => rosterOf(t).map((pid) => "p" + pid).concat(picksOf(t));
  // keep only assets the team still has (a link can outlive a roster move)
  const clean = () => { const a = new Set(assetsOf(A)), b = new Set(assetsOf(Bt)); SA = SA.filter((k) => a.has(k)); SB = SB.filter((k) => b.has(k)); };
  clean();
  const sum = (ks) => ks.reduce((x, k) => x + (info(k).value || 0), 0);
  const fits = { QB: ["QB"], RB: ["RB"], WR: ["WR"], TE: ["TE"], FLEX: ["RB", "WR", "TE"], SUPER_FLEX: ["QB", "RB", "WR", "TE"], REC_FLEX: ["WR", "TE"], WRRB_FLEX: ["RB", "WR"] };
  const slots = (LW.roster_positions || []).filter((s) => fits[s]).sort((a, b) => fits[a].length - fits[b].length);
  // the best lineup by projected points a week (forecast rate blended with this season), taxi and IR left out
  const weekly = (pids, t) => {
    const no = blocked(t);
    const pool = pids.filter((p) => !no.has(p)).map((p) => ({ pos: (board[p] || {}).pos || (nfl[p] || [])[1], r: LW.rates[p] ?? 0 })).sort((x, y) => y.r - x.r), used = new Set();
    let m = 0;
    for (const sl of slots) { const i = pool.findIndex((x, j) => !used.has(j) && fits[sl].includes(x.pos)); if (i >= 0) { used.add(i); m += pool[i].r; } }
    return m;
  };
  // every team's roster value (players + picks), to rank before and after
  const teamValue = (t, give = [], get = []) => {
    const ks = assetsOf(t).filter((k) => !give.includes(k)).concat(get);
    const by = { QB: 0, RB: 0, WR: 0, TE: 0 };
    let total = 0, picks = 0;
    for (const k of ks) { const x = info(k); total += x.value || 0; if (x.pick) picks += x.value || 0; else if (x.pos in by) by[x.pos] += x.value || 0; }
    return { total, picks, by, ks, n: ks.filter((k) => k[0] === "p").length, wk: weekly(ks.filter((k) => k[0] === "p").map((k) => k.slice(1)), t) };
  };
  const sync = () => setQuery({ a: A, b: Bt, sa: SA.join(","), sb: SB.join(",") });
  const row = (x, side, inDeal) => `<button class="asset${inDeal ? " in" : ""}" data-side="${side}" data-k="${esc(x.k)}" title="${inDeal ? "Take out of the deal" : "Add to the deal"}">
      <span class="ai">${inDeal ? "✕" : "+"}</span>${posBadge(x.pos)} <span class="an">${esc(x.name)}${x.inj ? ` <span class="chip bad">${esc(x.inj)}</span>` : ""}</span>
      <span class="muted small">${x.pick ? "" : esc([x.nfl, x.age ? Math.floor(x.age) : ""].filter(Boolean).join(" · "))}</span><b>${x.value ? money(x.value) : '<span class="muted">—</span>'}</b></button>`;
  const filt = { a: "", b: "" };
  function sideHtml(side) {
    const t = side === "a" ? A : Bt, other = side === "a" ? Bt : A, sends = side === "a" ? SA : SB;
    return `<div class="card nocv calcside"><div class="chead"><h2>${avatar(t, "")}<select data-team="${side}" aria-label="Team ${side.toUpperCase()}">${teams.map((x) => `<option ${x === t ? "selected" : ""} ${x === other ? "disabled" : ""}>${esc(x)}</option>`).join("")}</select></h2><span class="muted small">sends</span></div>
      <div class="sends">${sends.map((k) => row(info(k), side, true)).join("") || `<p class="muted small" style="margin:6px 0">Nothing yet — add players or picks below.</p>`}</div>
      <p class="small" style="text-align:right;margin:4px 0 10px">Sends <b>${money(sum(sends))}</b></p>
      <input class="f" data-filter="${side}" type="search" placeholder="Find a player or pick on ${esc(t)}" value="${esc(filt[side])}" aria-label="Find a player or pick" style="width:100%">
      <div class="pool" data-pool="${side}"></div></div>`;
  }
  function poolHtml(side) {
    const t = side === "a" ? A : Bt, sends = side === "a" ? SA : SB, q = filt[side].toLowerCase();
    const xs = assetsOf(t).filter((k) => !sends.includes(k)).map(info).filter((x) => !q || x.name.toLowerCase().includes(q) || x.pos.toLowerCase() === q)
      .sort((x, y) => (y.value || 0) - (x.value || 0));
    return xs.map((x) => row(x, side, false)).join("") || `<p class="muted small">Nothing matches.</p>`;
  }
  function resultHtml() {
    if (!SA.length && !SB.length) return `<div class="card empty"><div class="big">⚖️</div><p>Add what each team sends. Values are the league's FAAB board of ${esc(B.as_of)}; picks use the FAAB system's pick prices.</p></div>`;
    const getA = sum(SB), getB = sum(SA), gap = getA - getB, big = Math.max(getA, getB, 1);
    const even = Math.abs(gap) <= Math.max(25, big * 0.05);
    const winner = gap > 0 ? A : Bt, loser = gap > 0 ? Bt : A;
    const before = Object.fromEntries(teams.map((t) => [t, teamValue(t)]));
    const after = { ...before, [A]: teamValue(A, SA, SB), [Bt]: teamValue(Bt, SB, SA) };
    const rank = (tbl, t) => 1 + teams.filter((u) => tbl[u].total > tbl[t].total).length;
    const d = (x, f = money, keep) => { const v = Math.round(x * 10) / 10; return v ? `<span class="${v > 0 ? "pos" : "neg"}">${v > 0 ? "+" : "−"}${f(Math.abs(v))}</span>` : (keep ? '<span class="muted">±0</span>' : ""); };
    const pts = (v) => fmt({ d: 1 }, v);
    const line = (lab, f, fmtv, dv) => `<tr><td class="l">${lab}</td>${[A, Bt].map((t) => `<td>${fmtv(f(before[t], t))} → <b>${fmtv(f(after[t], t))}</b> ${dv(f(after[t], t) - f(before[t], t))}</td>`).join("")}</tr>`;
    // what would even it up: the team getting more sends one more asset near the gap
    let fix = "";
    if (!even) {
      // the team that comes out ahead sends one more asset near the gap
      const giver = gap > 0 ? A : Bt, sends = gap > 0 ? SA : SB, need = Math.abs(gap);
      const opts = assetsOf(giver).filter((k) => !sends.includes(k)).map(info).filter((x) => x.value > 0)
        .sort((x, y) => Math.abs(x.value - need) - Math.abs(y.value - need)).slice(0, 5);
      const side = giver === A ? "a" : "b";
      fix = opts.length ? `<h3>To even it up, ${esc(giver)} could add</h3><div class="pool short">${opts.map((x) => row(x, side, false)).join("")}</div><p class="muted small">The ${esc(giver)} assets closest to the ${money(need)} gap. Or take something out of what ${esc(giver === A ? Bt : A)} sends.</p>` : "";
    }
    const mv = SA.filter((k) => k[0] === "p").map((k) => `${k.slice(1)}>${Bt}`).concat(SB.filter((k) => k[0] === "p").map((k) => `${k.slice(1)}>${A}`));
    const pctA = getA + getB ? 100 * getA / (getA + getB) : 50;
    return `<div class="card nocv"><h2>Verdict</h2>
      <div class="meter" role="img" aria-label="${esc(A)} gets ${Math.round(pctA)}% of the value"><i style="width:${pctA.toFixed(1)}%;background:${teamColor(A)}"></i><i style="flex:1;background:${teamColor(Bt)}"></i><span style="left:50%"></span></div>
      <div style="display:flex;justify-content:space-between;gap:10px;margin-top:6px"><span>${avatar(A)}<b>${esc(A)}</b> gets ${money(getA)}</span><span>${esc(Bt)} gets ${money(getB)} ${avatar(Bt)}</span></div>
      <p class="verdict">${even ? `<b>About even</b> — within ${money(Math.max(25, big * 0.05))}.` : `<b>${esc(winner)}</b> comes out ${money(Math.abs(gap))} ahead — ${esc(pickText(B, Math.abs(gap)))}. ${esc(loser)} gives up ${Math.round(100 * Math.abs(gap) / big)}% more than it gets.`}</p>
      ${fix}</div>
      <div class="card nocv"><h2>Before → after</h2><div class="scroll"><table><thead><tr><th class="l nosort"></th><th class="nosort">${teamLink(A)}</th><th class="nosort">${teamLink(Bt)}</th></tr></thead><tbody>
        ${line("Roster value", (x) => x.total, money, (v) => d(v))}
        ${line("Value rank", (x, t) => rank(before[t] === x ? before : after, t), (v) => ordinal(v), (v) => v ? `<span class="${v < 0 ? "pos" : "neg"}">${v < 0 ? "▲" : "▼"}${Math.abs(v)}</span>` : "")}
        ${["QB", "RB", "WR", "TE"].map((p) => line(`${posBadge(p)} value`, (x) => x.by[p], money, (v) => d(v))).join("")}
        ${line("Picks value", (x) => x.picks, money, (v) => d(v))}
        ${slots.length ? line("Proj. points a week", (x) => x.wk, pts, (v) => d(v, (z) => pts(z))) : ""}
        ${line("Players on roster", (x) => x.n, (v) => String(v), (v) => v ? `<span class="muted">${v > 0 ? "+" : ""}${v}</span>` : "")}
      </tbody></table></div>
      <p class="muted small">Values: the stats-only FAAB board of ${esc(B.as_of)} (league trades, cuts and calls; no news). Picks: next year's by the original team's projected slot, later years at the round average. Proj. points a week: the best lineup from the forecast's player rates (this season blended in), taxi and IR left out. Ownership is ${live ? "Sleeper's right now" : "the last build's (Sleeper didn't answer)"}. Roster limits aren't checked.</p>
      <p>${mv.length ? `<a class="btn" href="#/predict?mv=${encodeURIComponent(mv.join(","))}">Title odds with this trade →</a> ` : ""}<button class="b" id="cswap">⇄ Swap sides</button> <button class="b" id="cclear">Clear</button> ${shareBtn()}</p></div>`;
  }
  function draw() {
    sync();
    $("#calcsides").innerHTML = sideHtml("a") + sideHtml("b");
    $$("[data-pool]").forEach((el) => (el.innerHTML = poolHtml(el.dataset.pool)));
    $("#calcres").innerHTML = resultHtml();
    refreshAvatars();
    const sw = $("#cswap"); if (sw) sw.onclick = () => { [A, Bt] = [Bt, A]; [SA, SB] = [SB, SA]; draw(); };
    const cl = $("#cclear"); if (cl) cl.onclick = () => { SA = []; SB = []; draw(); };
  }
  $app.innerHTML = `${crumbs(["Trades", "trades"], ["Trade calculator"])}<div class="page-head"><div><h1>Trade calculator</h1><p class="lede">Pick two teams and tap what each sends. Values are the league's own FAAB board ${liveNote(live)}</p></div><div class="actions">${shareBtn()}</div></div>
    <div id="calc"><div class="grid2" id="calcsides"></div><div id="calcres"></div></div>`;
  const root = $("#calc");
  // one listener for both sides: add / remove assets, switch teams, filter
  root.addEventListener("click", (e) => {
    const b = e.target.closest("button.asset"); if (!b) return;
    const k = b.dataset.k, side = b.dataset.side, list = side === "a" ? SA : SB;
    if (list.includes(k)) list.splice(list.indexOf(k), 1); else list.push(k);
    draw();
  });
  root.addEventListener("change", (e) => {
    const s = e.target.closest("select[data-team]"); if (!s) return;
    if (s.dataset.team === "a") { A = s.value; SA = []; } else { Bt = s.value; SB = []; }
    draw();
  });
  root.addEventListener("input", (e) => {
    const f = e.target.closest("input[data-filter]"); if (!f) return;
    filt[f.dataset.filter] = f.value;
    const el = $(`[data-pool="${f.dataset.filter}"]`); if (el) el.innerHTML = poolHtml(f.dataset.filter);
  });
  draw();
}

// ---------- every week the league has played, by season (league_week)
async function weeks(year) {
  const [ws, meta] = await Promise.all([loadWeeks(), load("meta.json")]);
  if (!ws.length) throw new Error("The week list is not in this build.");
  const years = [...new Set(ws.map((x) => x.y))].sort((a, b) => b - a);
  const y = years.includes(+year) ? +year : years[0];
  const mine = ws.filter((x) => x.y === y);
  const C = ["PF", "Max PF", "Efficiency", "Highest starter score", "Avg margin", "Number of games within 10", "Number of trades", "Number of Add/Drops", "Amount of FAAB spent"];
  const m0 = mine[0], ci = (c) => m0.cols.indexOf(c), lab = (c) => m0.labels[ci(c)] || c;
  const cols = [{ k: (x) => x.w, label: "Week", left: true, html: (x) => `<a href="#/week/${x.y}/${x.w}">${esc(x.n)}</a>${x.y === meta.season && x.w === meta.week ? ' <span class="chip acc">latest</span>' : ""}` },
    ...C.filter((c) => ci(c) >= 0).map((c) => ({ k: (x) => x.r[ci(c)], label: lab(c), spec: m0.fmt[c], col: c }))];
  setTitle(`${y} weeks`);
  $app.innerHTML = `${crumbs(["Weeks"])}<div class="page-head"><h1>${y} week by week</h1><div class="actions">${shareBtn()}</div></div>
    <p class="lede">Every week of ${y}: the league's totals, and a link to each week's matchups. Tap a week for every game.</p>
    <div class="seg tabs" role="tablist">${years.map((x) => `<button role="tab" aria-pressed="${x === y}" data-y="${x}">${x}</button>`).join("")}</div>
    <div class="card"><h2>League points by week</h2>${barChart(mine.map((x) => ({ label: String(x.n).replace(/^Week /, "").replace(/^Toilet /, "T.").slice(0, 8), v: x.r[ci("PF")], href: `#/week/${x.y}/${x.w}`, title: `${x.n}: ${stripHtml(fmt({ d: 2 }, x.r[ci("PF")]))} points league-wide`, cls: /^Week /.test(x.n) ? "" : "g" })), { label: `League points per week, ${y}`, h: 180 })}
      <div class="legend"><span><i style="background:var(--accent)"></i>regular season</span><span><i style="background:var(--gold)"></i>playoffs and consolation games</span></div></div>
    <div class="card">${table(cols, mine, { sort: 0, asc: true, defs: "league_week", rowLink: (x) => `week/${x.y}/${x.w}`, name: `weeks_${y}` })}
      <p class="muted small">League totals over every team that week (team PF includes the semifinal +5). Every column: <a href="#/data/league_week?c=Year&v=${y}">league_week data →</a></p></div>`;
  $$("[data-y]", $app).forEach((b) => b.onclick = () => (location.hash = "#/weeks/" + b.dataset.y));
}

// ---------- compare two players or two teams side by side
async function compare(_a, query) {
  const [ix, meta] = await Promise.all([load("search.json"), load("meta.json")]);
  const params = new URLSearchParams(query || "");
  const label = (r) => r[0] === "t" ? `${r[2]} (team)` : `${r[2]} (${r[3] || "player"})`;
  const byLabel = Object.fromEntries(ix.map((r) => [label(r), r]));
  const find = (k) => ix.find((r) => `${r[0]}:${r[1]}` === k);
  let A = find(params.get("a") || ""), Bx = find(params.get("b") || "");
  if (!A && !Bx && ME) A = find("t:" + ME);
  setTitle("Compare");
  const pickers = `<datalist id="cmpl">${ix.map((r) => `<option value="${esc(label(r))}">`).join("")}</datalist>
    <div class="controls"><input class="f" id="ca" list="cmpl" placeholder="A player or team…" value="${A ? esc(label(A)) : ""}" aria-label="First player or team">
      <span class="muted">vs</span><input class="f" id="cb" list="cmpl" placeholder="…and another" value="${Bx ? esc(label(Bx)) : ""}" aria-label="Second player or team">
      <button class="b" id="cswap" title="Swap sides" aria-label="Swap sides">⇄</button></div>`;
  let body = `<div class="card empty"><div class="big">⚖️</div><p>Pick two players or two teams. Try <a href="#/compare?a=t:${esc(meta.teams[0])}&b=t:${esc(meta.teams[1])}">${esc(meta.teams[0])} v ${esc(meta.teams[1])}</a>.</p></div>`;
  if (A && Bx && A[0] !== Bx[0]) body = `<div class="note">Compare two players or two teams, not one of each.</div>`;
  else if (A && Bx) {
    const isT = A[0] === "t";
    const [x, y, H] = await Promise.all([load(isT ? `team/${tslug(A[1])}.json` : `player/${A[1]}.json`), load(isT ? `team/${tslug(Bx[1])}.json` : `player/${Bx[1]}.json`), isT ? load("h2h.json") : null]);
    const keys = [...new Set([...Object.keys(x.summary), ...Object.keys(y.summary)])];
    const L = { ...y.summary_labels, ...x.summary_labels }, F = { ...y.summary_fmt, ...x.summary_fmt };
    const nameA = isT ? x.team : x.name, nameB = isT ? y.team : y.name;
    const link = (r, n) => isT ? teamLink(n) : `<a href="#/player/${esc(r[1])}">${esc(n)}</a>`;
    const rows = keys.map((k) => {
      const a = x.summary[k], b = y.summary[k], num = typeof a === "number" && typeof b === "number";
      const hi = num && a !== b ? (a > b ? "a" : "b") : "";
      return `<tr><td class="l"${defAttr(k, isT ? "team_all_time" : "player_all_time")}>${esc(L[k] || k)}</td><td class="${hi === "a" ? "w" : ""}">${fmt(F[k], a)}</td><td class="${hi === "b" ? "w" : ""}">${fmt(F[k], b)}</td>${num ? `<td class="muted small">${signed(F[k], a - b)}</td>` : "<td></td>"}</tr>`;
    }).join("");
    let extra = "";
    if (isT && H) {
      const c = H.cells[`${x.team}|${y.team}`];
      if (c) extra = `<div class="card"><h2>Head to head</h2><p><b style="font-size:22px">${c.w}-${c.l}</b> <span class="muted">${esc(x.team)}'s record against ${esc(y.team)} · points ${fmt({ d: 2 }, c.pf)} – ${fmt({ d: 2 }, c.pa)}</span></p>
        <div class="strip">${(c.games || []).map(([yy, w, n, pf, pa, won]) => `<a class="${won ? "W" : "L"}" href="#/game/${yy}/${w}/${tslug(x.team)}" title="${yy} ${esc(n)}: ${stripHtml(fmt({ d: 2 }, pf))}–${stripHtml(fmt({ d: 2 }, pa))}">${won ? "W" : "L"}</a>`).join("")}</div>
        <p class="small"><a href="#/h2h?a=${encodeURIComponent(x.team)}&b=${encodeURIComponent(y.team)}">Every meeting →</a></p></div>`;
    } else if (!isT) {
      const pts = (p) => { const t = p.seasons; if (!t || !t.rows) return {}; const yi = t.cols.indexOf("Year"), pi = t.cols.indexOf("Points"); return Object.fromEntries(t.rows.map((r) => [r[yi], r[pi]])); };
      const pa = pts(x), pb = pts(y), yrs = [...new Set([...Object.keys(pa), ...Object.keys(pb)])].sort();
      extra = `<div class="card"><h2>Points by season</h2>${table([{ k: 0, label: "Season", left: true }, { k: 1, label: nameA, spec: { d: 2 } }, { k: 2, label: nameB, spec: { d: 2 } }, { k: (r) => (r[1] ?? 0) - (r[2] ?? 0), label: "Difference", html: (r) => r[1] == null || r[2] == null ? "—" : `<span class="${r[1] >= r[2] ? "pos" : "neg"}">${signed({ d: 2 }, r[1] - r[2])}</span>` }], yrs.map((yy) => [yy, pa[yy] ?? null, pb[yy] ?? null]), { tools: false })}<p class="muted small">Points while rostered in this league.</p></div>`;
    }
    const head = (o, r, n) => `<div class="card"><div class="thead2">${isT ? avatar(o.team, "lg") : posBadge(o.pos)}<div><h2 style="margin:0">${link(r, n)}</h2><span class="muted small">${esc(isT ? (TINFO[o.team]?.name || "") : [o.nfl, o.team].filter(Boolean).join(" · "))}</span></div></div></div>`;
    body = `<div class="grid2">${head(x, A, nameA)}${head(y, Bx, nameB)}</div>${extra}
      <div class="card"><h2>${isT ? "All-time" : "Career"} side by side</h2><div class="scroll"><table><thead><tr><th class="l nosort">Stat</th><th class="nosort">${esc(nameA)}</th><th class="nosort">${esc(nameB)}</th><th class="nosort">A − B</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted small">Green = the higher of the two (not always the better: fewer is better for some stats). A − B = the first minus the second.</p></div>`;
    setTitle(`${nameA} vs ${nameB}`);
  }
  $app.innerHTML = `${crumbs(["Compare"])}<div class="page-head"><h1>Compare</h1><div class="actions">${shareBtn()}</div></div>
    <p class="lede">Two players or two teams, every career / all-time stat side by side.</p>${pickers}${body}`;
  const go = () => {
    const a = byLabel[$("#ca").value], b = byLabel[$("#cb").value];
    const q = new URLSearchParams(); if (a) q.set("a", `${a[0]}:${a[1]}`); if (b) q.set("b", `${b[0]}:${b[1]}`);
    location.hash = "#/compare?" + q.toString();
  };
  $("#ca").onchange = go; $("#cb").onchange = go;
  $("#cswap").onclick = () => { const v = $("#ca").value; $("#ca").value = $("#cb").value; $("#cb").value = v; go(); };
}

// ---------- router
const NAV_OF = { team: "teams", calc: "calc", game: "weeks", week: "weeks", pick: "draft", player: "", nfl: "", search: "" };
const TITLES = { "": "Home", teams: "All-time standings", records: "Record book", h2h: "Head to head", trades: "Trades", draft: "Draft history",
  predict: "Predictions", calc: "Trade calculator", faab: "FAAB values", data: "Data", weeks: "Weeks", compare: "Compare", search: "Search" };
// scroll positions by history entry: back / forward lands where you were, a new page at the top
const SCROLL = {};
let navSeq = 0, routeSeq = 0;
if ("scrollRestoration" in history) history.scrollRestoration = "manual";
const stateKey = () => { if (!history.state || !history.state.k) history.replaceState({ k: "e" + Date.now() + "-" + (++navSeq) }, ""); return history.state.k; };
window.addEventListener("scroll", debounce(() => { SCROLL[stateKey()] = window.scrollY; }, 80), { passive: true });
async function route() {
  const seq = ++routeSeq;
  const h = location.hash.replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  let [page, ...rest] = path.split("/").map((x) => { try { return decodeURIComponent(x); } catch (e) { return x; } });
  if (page === "mine") { if (ME) { location.replace("#/team/" + tslug(ME)); return; } page = "mine"; }
  const fn = routes[page] || (page === "mine" ? mine : notFound);
  const back = SCROLL[stateKey()];
  hideDef(); closeSugg(); closeMenu(); closeModal();
  if (page !== "search" && document.activeElement !== $q) $q.value = "";
  const navKey = page in NAV_OF ? NAV_OF[page] : page;
  for (const a of $$("#nav a")) {
    const on = a.getAttribute("href") === "#/" + navKey || (page === "team" && ME && a.id === "navMine" && rest[0] === tslug(ME));
    a.classList.toggle("on", on);
    if (on) { a.setAttribute("aria-current", "page"); a.scrollIntoView({ block: "nearest", inline: "nearest" }); } else a.removeAttribute("aria-current");
  }
  setTitle(TITLES[page] ?? "");
  $app.setAttribute("aria-busy", "true");
  const slow = setTimeout(() => { if (seq === routeSeq) $app.classList.add("loading"); }, 120);
  try {
    await fn(rest.join("/") || undefined, query);
  } catch (e) {
    if (seq !== routeSeq) return;
    setTitle("Not found");
    $app.innerHTML = `<div class="card err empty"><div class="big">🏈</div><h1>That page didn't load</h1><p>${esc(e.message)}</p>
      <p><button class="b pri" id="retry">Try again</button> <a class="btn sec" href="#/">Home</a> <a class="btn sec" href="#/search/${encodeURIComponent(rest[0] || page || "")}">Search instead</a></p></div>`;
    $("#retry").onclick = () => route();
  } finally {
    clearTimeout(slow);
    if (seq === routeSeq) { $app.classList.remove("loading"); $app.setAttribute("aria-busy", "false"); }
  }
  if (seq !== routeSeq) return;
  window.scrollTo(0, back || 0);
  const h1 = $("h1", $app);
  if (h1 && !back) { announce(h1.textContent); if (document.activeElement && document.activeElement !== document.body && !document.activeElement.closest(".top")) $app.focus({ preventScroll: true }); }
  if (h1 && !TITLES[page]) setTitle(h1.textContent.trim());
  refreshAvatars();
  rememberVisit(page, rest, document.title.split(" · ")[0]);
  // pages that show rosters or pick ownership redraw once Sleeper answers
  if (LIVE_PAGES.has(fn)) {
    const at = location.hash;
    loadLive().then((live) => {
      if (location.hash !== at || !live) return;
      const y = window.scrollY;
      fn(rest.join("/") || undefined, query, live).then(() => { window.scrollTo(0, y); refreshAvatars(); }).catch(() => {});
    });
  }
}
async function notFound(_a, _q) {
  throw new Error(`There is no "${location.hash.replace(/^#\/?/, "")}" page.`);
}
// #/mine without a team chosen yet: ask which one
async function mine() {
  const meta = await load("meta.json");
  setTitle("My team");
  $app.innerHTML = `${crumbs(["My team"])}<h1>Which team is yours?</h1><p class="lede">Pick it once: it gets a ★ link in the menu bar and is highlighted in every table. Saved in this browser only; change it any time from the ☰ menu.</p>
    <div class="games">${meta.teams.map((t) => `<button class="b" data-me="${esc(t)}" style="justify-content:flex-start">${avatar(t)}${esc(t)}${TINFO[t]?.name ? ` <span class="muted small">${esc(TINFO[t].name)}</span>` : ""}</button>`).join("")}</div>`;
  $$("[data-me]", $app).forEach((b) => b.onclick = () => { setMe(b.dataset.me); location.hash = "#/team/" + tslug(b.dataset.me); });
}
function setMe(t) {
  ME = t || null; prefs.set("lotg:me", ME);
  const a = document.getElementById("navMine");
  if (a) { a.hidden = !ME; a.textContent = ME ? "My team" : ""; a.title = ME ? ME : ""; }
  toast(ME ? `${ME} is your team: highlighted everywhere` : "Your team is cleared");
}
// recently opened players and teams, offered when the search box is empty
function rememberVisit(page, rest, title) {
  if (!["team", "player", "nfl"].includes(page) || !title) return;
  const href = `#/${page}/${rest.join("/")}`;
  const r = prefs.get("lotg:recent", []).filter((x) => x.h !== href);
  r.unshift({ h: href, t: title.replace(/\s+★$/, ""), k: page });
  prefs.set("lotg:recent", r.slice(0, 8));
}
const LIVE_PAGES = new Set([team, player, faab, nfl]);

// ---------- search: suggestions as you type (players, teams, NFL teams, pages, stats);
// arrows move, Enter opens, Esc closes; Enter with nothing picked opens the full results
let SIX = [];
const PAGES = [["Home", "#/"], ["All-time standings", "#/teams"], ["Weeks", "#/weeks"], ["Record book", "#/records"], ["Head to head", "#/h2h"],
  ["Trades", "#/trades"], ["Trade calculator", "#/calc"], ["Draft history", "#/draft"], ["Predictions", "#/predict"], ["FAAB values", "#/faab"], ["Compare players or teams", "#/compare"], ["Data: every sheet", "#/data"], ["Rate players", "rate/"]];
const NFL_TEAMS = "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split(" ");
let suggAct = -1;
const $q = document.getElementById("q"), $sugg = document.getElementById("sugg");
const hilite = (text, q) => { const i = text.toLowerCase().indexOf(q); return i < 0 ? esc(text) : esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length)); };
function suggest() {
  const raw = $q.value.trim(), ql = raw.toLowerCase();
  let html = "";
  if (!ql) {
    const rec = prefs.get("lotg:recent", []);
    html = (rec.length ? `<div class="sh">Recent</div>` + rec.map((r) => `<a href="${esc(r.h)}" role="option">${r.k === "team" ? avatar(r.t) : r.k === "nfl" ? "🏈" : "👤"} ${esc(r.t)}<span class="k">${r.k}</span></a>`).join("") : "")
      + `<div class="sh">Pages</div>` + PAGES.slice(0, 8).map(([n, h]) => `<a href="${h}" role="option">${esc(n)}</a>`).join("");
  } else {
    const score = (n) => { const s = n.toLowerCase(); if (s === ql) return 0; if (s.startsWith(ql)) return 1; if (s.split(/[\s.'-]+/).some((w) => w.startsWith(ql))) return 2; return s.includes(ql) ? 3 : 9; };
    const hits = SIX.map((r) => [score(r[2]), r]).filter(([s]) => s < 9).sort((a, b) => a[0] - b[0] || (b[1][4] || 0) - (a[1][4] || 0) || a[1][2].localeCompare(b[1][2])).slice(0, 8).map((x) => x[1]);
    const teams = hits.filter((r) => r[0] === "t"), players = hits.filter((r) => r[0] === "p");
    const pages = PAGES.filter(([n]) => n.toLowerCase().includes(ql)).slice(0, 3);
    const nfl = NFL_TEAMS.filter((c) => c.toLowerCase() === ql);
    const fantasy = Object.entries(TINFO).filter(([t, i]) => i.name && i.name.toLowerCase().includes(ql) && !teams.some((r) => r[1] === t)).slice(0, 3);
    if (teams.length || fantasy.length) html += `<div class="sh">Teams</div>` + teams.map((r) => `<a href="#/team/${tslug(r[1])}" role="option">${avatar(r[1])}${hilite(r[2], ql)}<span class="k">${esc(TINFO[r[1]]?.name || "Team")}</span></a>`).join("")
      + fantasy.map(([t, i]) => `<a href="#/team/${tslug(t)}" role="option">${avatar(t)}${esc(t)}<span class="k">${hilite(i.name, ql)}</span></a>`).join("");
    if (players.length) html += `<div class="sh">Players</div>` + players.map((r) => { const [pos, ...more] = String(r[3] || "").split(" "); return `<a href="#/player/${esc(r[1])}" role="option">${posBadge(pos)} ${hilite(r[2], ql)}<span class="k">${esc(more.join(" · "))}</span></a>`; }).join("");
    if (nfl.length) html += `<div class="sh">NFL team</div>` + nfl.map((c) => `<a href="#/nfl/${c}" role="option">🏈 ${c} depth chart and players<span class="k">NFL</span></a>`).join("");
    if (pages.length) html += `<div class="sh">Pages</div>` + pages.map(([n, h]) => `<a href="${h}" role="option">${hilite(n, ql)}</a>`).join("");
    html += `<div class="sh">Everywhere</div><a href="#/search/${encodeURIComponent(raw)}" role="option">🔎 All results for “${esc(raw)}”<span class="k">Enter</span></a>
      <a href="#/records?q=${encodeURIComponent(raw)}" role="option">🏆 Record boards whose stat matches “${esc(raw)}”</a>`;
  }
  $sugg.innerHTML = html + `<div class="foot2"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div>`;
  suggAct = -1;
  $sugg.classList.add("on"); $q.setAttribute("aria-expanded", "true");
}
function closeSugg() { $sugg.classList.remove("on"); $q.setAttribute("aria-expanded", "false"); suggAct = -1; }
function moveSugg(d) {
  const items = $$("a", $sugg); if (!items.length) return;
  suggAct = (suggAct + d + items.length) % items.length;
  items.forEach((a, i) => { a.classList.toggle("act", i === suggAct); a.setAttribute("aria-selected", i === suggAct); });
  items[suggAct].scrollIntoView({ block: "nearest" });
}
$q.addEventListener("input", debounce(suggest, 60));
$q.addEventListener("focus", suggest);
$q.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); if (!$sugg.classList.contains("on")) suggest(); moveSugg(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSugg(-1); }
  else if (e.key === "Escape") { closeSugg(); $q.blur(); }
  else if (e.key === "Enter" && suggAct >= 0) { e.preventDefault(); const a = $$("a", $sugg)[suggAct]; if (a) { a.click(); } }
});
$sugg.addEventListener("mousedown", (e) => e.preventDefault());   // keep focus while clicking a suggestion
$sugg.addEventListener("click", (e) => { const a = e.target.closest("a"); if (a) { closeSugg(); $q.blur(); if (a.getAttribute("href") === location.hash) route(); } });
$q.addEventListener("blur", () => setTimeout(closeSugg, 120));
document.getElementById("searchForm").onsubmit = (e) => { e.preventDefault(); const v = $q.value.trim(); if (!v) return; closeSugg(); $q.blur(); location.hash = "#/search/" + encodeURIComponent(v); };

// ---------- settings menu (☰): your team, theme, density, shortcuts, share
const $menu = document.getElementById("menu"), $menuBtn = document.getElementById("menuBtn");
function drawMenu() {
  const theme = prefs.get("lotg:theme", "dark"), dens = prefs.get("lotg:density", "comfy");
  $menu.innerHTML = `<div class="mh">Your team</div>${TEAMS.map((t) => `<button role="menuitemradio" aria-checked="${ME === t}" data-set-me="${esc(t)}">${avatar(t)}${esc(t)}</button>`).join("")}
    ${ME ? `<button role="menuitem" data-set-me="">Clear my team</button>` : ""}<hr>
    <div class="mh">Theme</div>${[["dark", "Sleeper dark"], ["light", "Light"], ["auto", "Match the device"]].map(([k, n]) => `<button role="menuitemradio" aria-checked="${theme === k}" data-theme-set="${k}">${n}</button>`).join("")}<hr>
    <div class="mh">Tables</div>${[["comfy", "Comfortable"], ["compact", "Compact"]].map(([k, n]) => `<button role="menuitemradio" aria-checked="${dens === k}" data-dens="${k}">${n}</button>`).join("")}<hr>
    <button role="menuitem" data-share-page>🔗 Copy a link to this page</button>
    <button role="menuitem" data-keys>⌨️ Keyboard shortcuts <kbd style="margin-left:auto">?</kbd></button>
    <a role="menuitem" href="rate/">⭐ Rate player values</a>`;
}
// dark (default) / light / follow the device, live when the device switches
function applyTheme() {
  const v = prefs.get("lotg:theme", "dark");
  const light = v === "light" || (v === "auto" && matchMedia("(prefers-color-scheme: light)").matches);
  if (light) document.documentElement.dataset.theme = "light"; else delete document.documentElement.dataset.theme;
}
matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", applyTheme);
function openMenu() { drawMenu(); $menu.classList.add("on"); $menuBtn.setAttribute("aria-expanded", "true"); const f = $("button", $menu); if (f) f.focus(); }
function closeMenu() { $menu.classList.remove("on"); $menuBtn.setAttribute("aria-expanded", "false"); }
$menuBtn.onclick = (e) => { e.stopPropagation(); $menu.classList.contains("on") ? closeMenu() : openMenu(); };
$menu.addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.setMe !== undefined) { setMe(b.dataset.setMe); closeMenu(); route(); }
  else if (b.dataset.themeSet) { const v = b.dataset.themeSet; prefs.set("lotg:theme", v === "dark" ? null : v); applyTheme(); drawMenu(); }
  else if (b.dataset.dens) { const v = b.dataset.dens; prefs.set("lotg:density", v === "comfy" ? null : v); if (v === "comfy") delete document.documentElement.dataset.density; else document.documentElement.dataset.density = v; drawMenu(); }
  else if (b.dataset.sharePage !== undefined) { closeMenu(); shareLink(); }
  else if (b.dataset.keys !== undefined) { closeMenu(); showKeys(); }
});
$menu.addEventListener("keydown", (e) => {
  const items = $$("button, a", $menu), i = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  if (e.key === "Escape") { closeMenu(); $menuBtn.focus(); }
});
document.addEventListener("click", (e) => { if (!e.target.closest("#menu, #menuBtn")) closeMenu(); });

// ---------- a modal (keyboard shortcuts, small dialogs)
function openModal(html) { const m = document.getElementById("modal"); $("#modalBox").innerHTML = html; m.classList.add("on"); const f = $("button, a, input", m); if (f) f.focus(); }
function closeModal() { document.getElementById("modal").classList.remove("on"); }
document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-close]")) closeModal(); });
const KEYS = [["/ or Ctrl K", "Search"], ["g h", "Home"], ["g m", "My team"], ["g t", "All-time standings"], ["g w", "Weeks"], ["g r", "Record book"], ["g x", "Head to head"],
  ["g d", "Draft"], ["g p", "Predictions"], ["g f", "FAAB values"], ["g c", "Compare"], ["g v", "Trade calculator"], ["g a", "Data"], ["[ / ]", "Previous / next week or pick"], ["s", "Copy a link to this page"], ["?", "This list"], ["Esc", "Close"]];
const GO = { h: "#/", m: "#/mine", t: "#/teams", w: "#/weeks", r: "#/records", x: "#/h2h", d: "#/draft", p: "#/predict", f: "#/faab", c: "#/compare", a: "#/data", s: "#/trades", v: "#/calc" };
function showKeys() {
  openModal(`<button class="b sm x" data-close aria-label="Close">✕</button><h2 id="modalTitle">Keyboard shortcuts</h2>
    <table class="rk"><tbody>${KEYS.map(([k, n]) => `<tr><td class="l" style="width:40%">${k.split(" ").map((x) => x === "or" || x === "/" ? ` ${x} ` : `<kbd>${esc(x)}</kbd>`).join(" ")}</td><td class="l">${esc(n)}</td></tr>`).join("")}</tbody></table>
    <p class="muted small">Table headers sort with Enter too; every table has a row filter and CSV download once it is long.</p>`);
}
let gPending = 0;
document.addEventListener("keydown", (e) => {
  const t = e.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); $q.focus(); $q.select(); return; }
  if (e.key === "Escape") { closeModal(); closeMenu(); hideDef(); return; }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (gPending && Date.now() - gPending < 1200 && GO[e.key]) { gPending = 0; location.hash = GO[e.key]; return; }
  gPending = e.key === "g" ? Date.now() : 0;
  if (e.key === "?") showKeys();
  else if (e.key === "s" && !gPending) shareLink();
  else if (e.key === "[" || e.key === "]") { const a = $(e.key === "[" ? "[data-prev]" : "[data-next]", $app); if (a) a.click(); }
});

// ---------- page-wide clicks: share buttons, Sleeper retry, cards that open on a tap
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-share]")) { shareLink(); return; }
  if (e.target.closest("[data-relive]")) { e.preventDefault(); toast("Asking Sleeper again…"); loadLive(true).then((l) => { toast(l ? "Sleeper answered" : "Sleeper is still unreachable"); if (l) route(); }); return; }
});
$app.addEventListener("click", (e) => {
  if (e.target.closest("a, button, input, select, summary, .defbtn")) return;
  const c = e.target.closest(".trade[data-go]");
  if (c) location.hash = "#/" + c.dataset.go;
});
$app.addEventListener("keydown", (e) => {
  const c = e.target.closest && e.target.closest(".trade[data-go], tr[data-go]");
  if (c && e.key === "Enter" && e.target === c) location.hash = "#/" + c.dataset.go;
});
// warm the data a link will need while the pointer is on it
const PREFETCH = [[/^#\/team\/([^/?]+)/, (m) => `team/${m[1]}.json`], [/^#\/player\/([^/?]+)/, (m) => `player/${m[1]}.json`],
  [/^#\/(?:game|week)\/(\d+)\/(\d+)/, (m) => `week/${m[1]}-${m[2]}.json`], [/^#\/records\/([^/?]+)/, (m) => `records/${m[1]}.json`],
  [/^#\/trades/, () => "trades.json"], [/^#\/h2h/, () => "h2h.json"], [/^#\/draft/, () => "draft.json"], [/^#\/teams/, () => "all_time.json"]];
const onIntent = (e) => {
  const a = e.target.closest && e.target.closest("a[href^='#/']"); if (!a) return;
  const h = a.getAttribute("href");
  for (const [re, f] of PREFETCH) { const m = re.exec(h); if (m) { prefetch(f(m)); break; } }
};
document.addEventListener("mouseover", onIntent, { passive: true });
document.addEventListener("touchstart", onIntent, { passive: true });
document.addEventListener("focusin", onIntent);
// back to top, and the nav's edge fades when it can scroll sideways
const $totop = document.getElementById("totop");
$totop.onclick = () => { window.scrollTo({ top: 0, behavior: "smooth" }); $app.focus({ preventScroll: true }); };
window.addEventListener("scroll", () => $totop.classList.toggle("on", window.scrollY > 900), { passive: true });
const $nav = document.getElementById("nav"), $navwrap = document.getElementById("navwrap");
const navFade = () => { $navwrap.classList.toggle("fl", $nav.scrollLeft > 4); $navwrap.classList.toggle("fr", $nav.scrollLeft + $nav.clientWidth < $nav.scrollWidth - 4); };
$nav.addEventListener("scroll", navFade, { passive: true });
window.addEventListener("resize", debounce(() => { navFade(); for (const el of $$(".scroll")) pinColumns(el); }, 150));
// the header's height, for sticky bars under it
const topH = () => document.documentElement.style.setProperty("--top-h", document.getElementById("top").offsetHeight + "px");
window.addEventListener("resize", debounce(topH, 100));

window.addEventListener("hashchange", route);
window.addEventListener("offline", () => toast("You're offline: pages you've opened still work"));
window.addEventListener("online", () => { toast("Back online"); if (liveStatus === "failed") loadLive(true); });
load("sheets/index.json").then((ix) => {
  for (const m of ix.sheets) DEFS[m.sheet] = m.defs || {};
  DEFS._any = Object.assign({}, ...ix.sheets.map((m) => m.defs || {}));
}).catch(() => {});
// a shared link (?to=<route>) opens that page; the address bar shows the usual #/ form
(() => {
  const to = new URLSearchParams(location.search).get("to");
  if (to !== null) history.replaceState(null, "", location.pathname + "#/" + to.replace(/^#?\/?/, ""));
})();
showLeague(prefs.get("lotg:league", null));
Promise.all([load("search.json"), load("meta.json")]).then(([ix, meta]) => {
  SIX = ix;
  TEAMS = meta.teams.slice();
  ix.forEach((r) => { if (r[0] === "p") { NAMES[r[2]] = r[1]; NAMES_BY_ID[r[1]] = r[2]; POS_OF[r[1]] = String(r[3] || "").split(" ")[0]; } });
  if (ME && !TEAMS.includes(ME)) ME = null;
  const a = document.getElementById("navMine"); if (a && ME) { a.hidden = false; a.title = ME; }
  const bt = meta.build_time ? new Date(meta.build_time) : null;
  const built = bt ? bt.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : meta.built;
  document.getElementById("foot").innerHTML = `<div class="fl2"><a href="#/">Home</a><a href="#/teams">Standings</a><a href="#/weeks">Weeks</a><a href="#/records">Records</a><a href="#/trades">Trades</a><a href="#/data">Data &amp; downloads</a><a href="rate/">Rate players</a><a href="#" data-keys-foot>Keyboard shortcuts</a></div>
    Stats through ${esc(meta.week_name)} ${meta.season}, from the league's stats exports (${meta.seasons[0]}–${meta.season}) as of the main build${meta.build_run ? ` <a href="https://github.com/Oliverwkw/LOTG-Stats/actions/runs/${esc(meta.build_run)}">run ${esc(meta.build_run)}</a>` : ""} (${esc(built)}${bt ? ", " + ago(bt) : ""}); the site rebuilds after every main build. Rosters and pick ownership are read live from Sleeper when a page opens.`;
  $("[data-keys-foot]").onclick = (e) => { e.preventDefault(); showKeys(); };
  topH(); navFade();
  route();
  // once the first page is up: Sleeper's avatars, and the files the next click most likely needs
  const idle = window.requestIdleCallback || ((f) => setTimeout(f, 1200));
  idle(() => { loadLive(); ["home.json", "all_time.json", "h2h.json"].forEach(prefetch); });
}).catch((e) => { $app.innerHTML = `<div class="card err empty"><div class="big">⚠️</div><h1>Could not load the site data</h1><p>${esc(e.message)}</p><p><button class="b pri" onclick="location.reload()">Reload</button></p></div>`; });
