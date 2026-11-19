// ---------- KTC's own trade-calculator value adjustment (keeptradecut.com site.min.js,
// ALGOTOUSE=2: processVNew / solveForX / adjustPackageNew / evaluateTrade, read 2026-11-19),
// ported line for line. Each asset gets a raw score that grows faster than its value and is
// highest for the best piece in the trade; the gap between the sides' raw totals is turned
// back into "a player worth X" (Newton's method), so the side getting the best asset in a
// 2-for-1 gets a bonus. `one` / `two` = KTC values of what each side GETS; `top` = the best
// KTC value of any player (KTC uses its #1 + 100). Returns both adjusted totals, the
// adjustment, and KTC's verdict (fair within 5%).
const KTC_MAX = 1e4;
function ktcSolveForX(e, a, t) {
  let l = 5 * e;
  const f = (r) => (0.1 * Math.pow(r / a, 1.4) + 0.7 * Math.pow(r / (1.05 * t), 1.25) + 0.2) * r - e;
  const df = (x) => 0.24 * Math.pow(x, 1.4) / Math.pow(a, 1.4) + 1.575 * Math.pow(x, 1.25) / (Math.pow(1.05, 1.25) * Math.pow(t, 1.25)) + 0.2;
  for (let i = 0; i < 20; i++) { const y = f(l), d = df(l); if (Math.abs(d) < 1e-12) return NaN; const n = l - y / d; if (Math.abs(n - l) < 1e-8) return n; l = n; }
  return NaN;
}
const ktcEqual = (e, a, t) => { e = Math.max(0, e); a = Math.max(0, a); const r = e + a, s = Math.abs(e - a), n = Math.min(100, s / r * 100); return !(parseFloat(Math.round(10 * n) / 10) > t); };
function ktcTrade(one, two, top, variance = 5) {
  const T1 = one.reduce((x, v) => x + v, 0), T2 = two.reduce((x, v) => x + v, 0);
  const out = { T1, T2, adj1: 0, adj2: 0, side: -1, value: 0, display: false };
  if (!one.length || !two.length) { out.t1 = T1; out.t2 = T2; return ktcVerdict(out, variance); }
  const t = top + 100, r = Math.max(...one, ...two);
  const pv = (p) => (0.1 * Math.pow(p / 10099, 1.4) + 0.7 * Math.pow(p / (1.05 * r), 1.25) + 0.2) * p;
  const e = one.reduce((x, v) => x + pv(v), 0), a = two.reduce((x, v) => x + pv(v), 0);
  const d = e / T1, u = a / T2, c = Math.floor(Math.abs(e - a));
  const rev = (x) => Math.round(ktcSolveForX(x, t, r));
  let y = true, v, b, g, w, T;
  if (ktcEqual(T1, T2, variance) && ktcEqual(e, a, variance)) {
    if (e > a) { out.side = 1; v = rev(c); b = T2 + v - T1; if (b > 0) { out.value = b; out.adj1 = b; } else { y = false; out.side = 2; out.value = -b; out.adj2 = -b; } }
    else if (a > e) { out.side = 2; v = rev(c); b = T1 + v - T2; if (b > 0) { out.value = b; out.adj2 = b; } else { y = false; out.side = 1; out.value = -b; out.adj1 = -b; } }
  } else if (d > u) {
    out.side = 1;
    if (e > a) { v = rev(c); b = T2 + v - T1; if (b > 0) { out.value = b; out.adj1 = b; } else { y = false; out.side = 2; out.value = Math.abs(b); out.adj2 = Math.abs(b); } }
    else {
      g = -1; if (T1 + out.adj1 < T2 + out.adj2) g = 1; else if (T2 + out.adj2 < T1 + out.adj1) g = 2;
      w = rev(Math.abs(e - a));
      if (w > 0 && g > 0) {
        out.side = g;
        if (g === 2) { T = w - (T1 - T2); out.value = T; out.adj2 = T; if (!(T > 0)) y = false; }
        else { T = w - (T2 - T1); if (T > 0) { if (T > KTC_MAX) { y = false; out.value = 0; out.side = 1; out.adj1 = 0; } else { out.side = 2; out.value = T; out.adj2 = T; } } else { y = true; out.value = -T; out.adj1 = -T; } }
      } else y = false;
    }
  } else {
    out.side = 2;
    if (a > e) { v = rev(c); b = T1 + v - T2; if (b > 0) { out.value = b; out.adj2 = b; } else { y = false; out.side = 1; out.value = Math.abs(b); out.adj1 = Math.abs(b); } }
    else {
      g = -1; if (T1 + out.adj1 < T2 + out.adj2) g = 1; else if (T2 + out.adj2 < T1 + out.adj1) g = 2;
      w = rev(Math.abs(e - a));
      if (w > 0 && g > 0) {
        out.side = g;
        if (g === 1) { T = w - (T2 - T1); out.value = T; out.adj1 = T; if (!(T > 0)) y = false; }
        else { T = w - (T1 - T2); if (T > 0) { if (T > KTC_MAX) { y = false; out.value = 0; out.side = 1; out.adj2 = 0; } else { out.side = 1; out.value = T; out.adj1 = T; } } else { y = true; out.value = -T; out.adj2 = -T; } }
      } else y = false;
    }
  }
  out.display = out.value !== 0 && y && !(Math.abs(out.value / (T1 + T2)) < 0.033);
  out.t1 = Math.max(0, T1 + out.adj1); out.t2 = Math.max(0, T2 + out.adj2);
  return ktcVerdict(out, variance);
}
function ktcVerdict(o, variance) {
  const t = o.t1, r = o.t2, s = t + r, pct = s ? Math.min(100, Math.abs(t - r) / s * 100) : 0;
  o.fair = !(parseFloat(Math.round(10 * pct) / 10) > variance);
  o.favors = o.fair ? 0 : t >= r ? 1 : 2;
  o.toEven = Math.round(Math.abs(t - r));
  return o;
}

