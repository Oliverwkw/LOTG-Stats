# League site UX overhaul (2026-11-18)

A design and usability pass over the league site (`site/index.html`, `site/app.js`,
`site/style.css`, new `site/manifest.webmanifest`). Shell only: no generator, export or
data-file change, so every existing page, route, link and number is unchanged. Each line
below is one discrete change. The league's logo, team avatars and fantasy team names come
from Sleeper (the league and users endpoints the page already calls), cached in the
browser.

## A. Shell, head and app chrome
1. Skip-to-content link, visible on keyboard focus.
2. The search box has a real `<label>` (screen readers announce it).
3. Search box is an ARIA combobox (`role`, `aria-autocomplete`, `aria-controls`).
4. Search box reports `aria-expanded` while suggestions are open.
5. Phone keyboards show a "Search" key (`enterkeyhint`).
6. Spellcheck off in the search box (names aren't dictionary words).
7. A `/` key hint inside the search box on desktop.
8. Light `theme-color` for the browser chrome.
9. Dark `theme-color` for the browser chrome.
10. `color-scheme` meta, so form controls and scrollbars follow dark mode.
11. Home-screen web-app metas for iOS.
12. Home-screen web-app meta for Android.
13. Home-screen app title "LOTG".
14. Open Graph title for link previews in chats.
15. Open Graph description.
16. Open Graph type.
17. Open Graph image: the league's Sleeper logo.
18. A favicon (SVG "LOTG" mark) where there was none.
19. The favicon switches to the league's Sleeper logo once Sleeper answers.
20. Apple touch icon: the league logo.
21. Web-app manifest (installable "Add to home screen", standalone window).
22. Preconnect to Sleeper's API, so the first live request starts sooner.
23. Preconnect to Sleeper's image CDN for avatars.
24. Theme applied before first paint (no flash of the wrong theme).
25. Table density applied before first paint.
26. `viewport-fit=cover` so the notch / home bar areas are handled.
27. The script loads with `defer`.
28. Skeleton placeholders while the first page loads, instead of "Loading…".
29. `aria-busy` on the main region while a page loads.
30. A thin progress bar at the top while any data file is in flight.
31. A toast for confirmations ("Link copied", "Your team is set").
32. A back-to-top button after scrolling down a long page.
33. Back-to-top moves keyboard focus to the content.
34. A modal dialog component (keyboard shortcuts), closes on Esc or backdrop.
35. A polite live region that announces page changes to screen readers.
36. League logo in the header (from Sleeper), replacing the plain "LOTG" text.
37. League name ("Life of the Grind") under the brand on wide screens.
38. Logo falls back to the text mark if the image fails.
39. Settings (☰) button in the header, with `aria-haspopup` / `aria-expanded`.
40. Settings menu: pick your team.
41. Settings menu: clear your team.
42. Settings menu: theme — match device.
43. Settings menu: theme — light.
44. Settings menu: theme — dark.
45. Settings menu: table density — comfortable.
46. Settings menu: table density — compact.
47. Settings menu: copy a link to this page.
48. Settings menu: keyboard shortcuts.
49. Settings menu: link to the rating page.
50. Settings menu items show a ✓ for the current choice (`menuitemradio`, `aria-checked`).
51. Settings menu is arrow-key navigable.
52. Esc closes the settings menu and returns focus to its button.
53. Clicking outside closes the settings menu.
54. "My team" ★ link in the menu bar once a team is chosen.
55. "Weeks" in the menu bar (new page).
56. "Compare" in the menu bar (new page).
57. "Rate players ↗" marks the link that leaves the app.
58. Menu bar fades at the edge that can still scroll (phones), so hidden items are discoverable.
59. The active menu item scrolls into view on phones.
60. Active menu item carries `aria-current="page"`.
61. Sub-pages light their section (team → standings, game/week → Weeks, pick → Draft).
62. Header is translucent with a blur, so content reads through while scrolling.
63. Header height is measured, so sticky bars beneath it never overlap it.
64. Footer: a row of quick links.
65. Footer: "how long ago" the build ran, next to its date.
66. Footer: keyboard-shortcuts link.
67. Safe-area padding at the bottom on phones with a home bar.

## B. Navigation and routing
68. Every page sets the browser tab title ("Oliverwkw · LOTG", "Trade #284 · LOTG"…).
69. Back / forward returns to where you were on the page (scroll restored per history entry).
70. A newly opened page starts at the top.
71. Browser's own scroll restoration turned off, so it can't fight the app's.
72. After navigation, keyboard focus moves to the content (not stuck in the old page).
73. The new page's heading is announced to screen readers.
74. Unknown routes show a "That page didn't load" card instead of silently showing Home.
75. Error card: "Try again" re-runs the route.
76. Error card: link home.
77. Error card: "Search instead" for what was typed.
78. A slow page dims the old content after 120 ms instead of looking frozen.
79. A fast click-through can't let a slower earlier page overwrite the newer one.
80. Route parts are URL-decoded (team and search links with spaces or symbols work).
81. Popovers, menu, suggestions and modal all close on navigation.
82. The search box clears when you leave the search page.
83. After Sleeper answers, live pages redraw without jumping the scroll.
84. Avatars refresh in place after every render.
85. Breadcrumbs on every inner page (Home › Section › Item).
86. Breadcrumbs carry `aria-label="Breadcrumb"`.
87. New `#/mine` route: opens your team, or asks which team is yours.
88. "Which team is yours?" picker page with avatars and fantasy names.
89. Recently opened teams, players and NFL teams are remembered (8, newest first).
90. A Share button on every main page: native share sheet on phones, copy link on desktop.
91. Filters on Trades, Draft, FAAB, Records, H2H, Data and Predictions are kept in the URL (shareable, survive reload) without adding a history entry per keystroke.

## C. Keyboard shortcuts
92. `/` focuses search.
93. Ctrl/⌘ K focuses search.
94. `g h` home.
95. `g m` my team.
96. `g t` all-time standings.
97. `g w` weeks.
98. `g r` record book.
99. `g x` head to head.
100. `g d` draft.
101. `g p` predictions.
102. `g f` FAAB values.
103. `g c` compare.
104. `g a` data.
105. `g s` trades.
106. `[` / `]` previous / next week, matchup, pick or trade.
107. `s` copies a link to the page.
108. `?` lists the shortcuts.
109. Esc closes any dialog, menu or definition.
110. Shortcuts are ignored while typing in a field.

## D. Search
111. Suggestions appear as you type, instead of the page jumping to the search route on every keystroke.
112. Suggestions grouped: Teams, Players, NFL team, Pages, Everywhere.
113. The matched part of each name is highlighted.
114. Players show a coloured position badge.
115. Players show their team and NFL team.
116. Teams show their avatar.
117. Teams show their fantasy team name.
118. Searching a fantasy team name ("Hall of Purdy Good") finds the team.
119. Typing an NFL code (BUF) offers that NFL team's page.
120. Page names are searchable ("draft", "faab").
121. "All results" entry, opened by Enter.
122. "Record boards whose stat matches" entry.
123. ↑ / ↓ move through suggestions; Enter opens; Esc closes.
124. The active suggestion scrolls into view.
125. With an empty box, focus shows recent pages and the main pages.
126. Clicking a suggestion doesn't lose focus mid-click.
127. Word-start matching includes names with periods, apostrophes and hyphens (A.J., Ja'Marr, Amon-Ra).
128. Search results page: separate Teams and Players lists with counts.
129. Results page: its own search box.
130. Results page: "Did you mean" suggestions (edit distance) when nothing matches.
131. Results page: empty-state card.
132. Results page: friendly names on the "every row" chips (Player weeks, not player_week).
133. Results page: "Every board place for …" link into the record book.
134. Fixed: team results linked to `#/team/AceMatthew` (a 404 on case-sensitive hosting); they now use the slug.
135. Results page title reads "Search: allen".

## E. Tables (every table on the site)
136. Header cells are focusable and sort with Enter or Space.
137. `aria-sort` on every sortable header.
138. A faint ↕ on hover shows a header can sort.
139. The sorted header is coloured.
140. Sorting is announced to screen readers.
141. Focus stays on the header after sorting.
142. Horizontal scroll position is kept when re-sorting.
143. Long tables (16+ rows) get a "Filter rows…" box.
144. Row count beside the filter ("12 of 284").
145. "CSV ↓" downloads exactly the rows shown, in the current order.
146. "Copy" puts the rows on the clipboard as tab-separated text for a spreadsheet.
147. Very long tables draw 150 rows, with "Show all N rows" (faster first paint).
148. "No rows match." row when a filter empties a table.
149. Your team's rows highlighted in gold, everywhere a table has a team.
150. A gold edge on the first cell of your team's row.
151. A dashed line marks the playoff cut in the standings (only in the default order).
152. Rows that open something are marked and open on a tap anywhere in the row.
153. Scroll shadows show when a wide table has more to the left or right.
154. Pinned columns re-measure when the window is resized or the phone rotates.
155. Columns that can't sort (form strips) don't pretend to.
156. Header tooltips explain abbreviations (Diff, All-play).
157. Missing numbers print a muted "—".
158. Infinite or NaN values print "—" instead of "NaN".
159. Missing values sort last in both directions.
160. Headers have `scope="col"`.
161. Tables use separate borders so sticky headers keep their bottom line.
162. Last row has no bottom border.
163. Row hover tint.
164. Compact density option tightens every table.

## F. Definitions (the ⓘ popover)
165. The ⓘ is keyboard-focusable (`role="button"`, `tabindex`).
166. Enter / Space on ⓘ opens the definition.
167. The popover opens above the label when there's no room below.
168. The popover has `role="tooltip"`.
169. The popover closes on scroll (desktop), Esc, or navigation.
170. Moving between a label and its ⓘ no longer flickers the popover.
171. The popover animates in.
172. Wider popover (340 px) for long formulas.

## G. Visual design
173. New design tokens: background, surface, ink, secondary ink, muted, two line weights.
174. Accent, accent-soft and accent-line tokens.
175. Good / bad / warn tokens with soft backgrounds.
176. Gold, silver and bronze tokens (medals, titles, your team).
177. Three shadow levels.
178. Three radius levels.
179. One focus-ring token used by every control.
180. One easing curve for motion.
181. A full dark palette with the same tokens.
182. Forced dark (menu) uses the same palette as automatic dark.
183. Muted text colour darkened for contrast in light mode.
184. Font smoothing and legibility rendering.
185. A visible focus ring on every interactive element (`:focus-visible`).
186. Text selection colour.
187. Heading scale and letter-spacing tightened.
188. Paragraph spacing evened.
189. Page width 1180 px (was 1100) for wide tables.
190. Body is a column flexbox, so the footer stays at the bottom of short pages.
191. Cards: larger radius, subtle shadow.
192. Card headers with a right-hand action link ("All-time standings →").
193. Tiles: white on the page, tinted inside cards.
194. Tile values never overflow (ellipsis + full value on hover).
195. Tile labels wrap cleanly.
196. A "hero" row of headline tiles.
197. Segmented buttons: hover state, 32 px minimum height.
198. Segmented buttons can carry a dimmed count.
199. Tab bars (underline style) for sheet / season / draft switches.
200. Tab bars scroll sideways on phones.
201. Selects get a custom chevron and consistent height.
202. A select with an active filter is tinted, so you can see what's filtering.
203. Inputs and selects: hover border.
204. Inputs and selects: focus ring.
205. Primary, secondary, ghost, small and "on" button styles.
206. Link-buttons (`.btn`) for calls to action.
207. Chips: ok / bad / gold / accent variants.
208. A pulsing dot on the "live from Sleeper" chip.
209. Position badges coloured by position (QB, RB, WR, TE, PICK).
210. W / L form squares instead of bare letters.
211. Medals (gold, silver, bronze circles) for places 1-3.
212. Team avatars: the Sleeper team logo, or a coloured initial until it loads.
213. A fixed colour per team for charts and fallbacks.
214. Large team avatar on team and compare pages.
215. Fantasy team name under the team's heading.
216. Odds cells with a small bar behind the number.
217. Simple SVG bar charts (no library), themed in light and dark.
218. Chart bars have hover titles.
219. Chart bars can be links.
220. Chart legends.
221. Result strips: one square per game, W green, L red, each a link.
222. Game cards: hover lift, winner in bold, margin line.
223. Game cards for your team get a gold border.
224. Trade cards: subtle shadow; hover accent border.
225. Trade side "Got" / "Sent" labels as small caps.
226. Trade side ahead on KTC gets a green outline.
227. Trades involving your team get a gold left edge.
228. Timeline style for asset histories (dots on a line).
229. Empty-state cards with an icon.
230. Error cards with a red edge.
231. Skeleton shimmer.
232. Info notes (blue) separate from caution notes (amber).
233. Sticky filter bars blur what scrolls under them.
234. Section bar on team pages blurs what scrolls under it.
235. `prefers-reduced-motion` turns animation off.
236. Larger tap targets (38 px) on touch screens.
237. Phone layout: 12 px gutters, smaller headings, tighter cells.
238. Phone layout: headline tiles two across.
239. Phone layout: brand text hidden, logo kept, so search gets the width.
240. Print stylesheet: no header, nav, buttons or filters.
241. Print: cards don't split across pages; tables print in full.
242. Print: black text on white.

## H. Live layer (Sleeper)
243. A failed Sleeper read is no longer cached for the whole visit; the next page asks again.
244. A retry waits 8 s instead of 4 s (slow networks).
245. "Sleeper unreachable" chip has a Retry button.
246. Coming back online retries Sleeper automatically.
247. Going offline shows a toast.
248. Data files retry once on a network error.
249. A failed data file is not cached, so "Try again" really retries.
250. Error messages name the file and HTTP status.
251. The league endpoint is read with the others: logo and name.
252. Team avatars and fantasy names are read from the users call already made.
253. Avatars and names are kept in localStorage, so the next visit shows them at once.
254. Roster records (wins, losses, FAAB used, moves) kept from the rosters call for later use.
255. Live chip: green with a pulsing dot when live, amber when not.
256. Live chip tooltips explain what "live" covers.

## I. Speed
257. Data a link needs is fetched while the pointer is on it (team, player, week, records, trades, H2H, draft, standings).
258. The same on touchstart (phones).
259. The same on keyboard focus.
260. After the first page, Sleeper, home, all-time and H2H data load in idle time.
261. Record boards and trade cards below the fold skip layout until scrolled near (`content-visibility`); cards holding sticky or pinned tables are left out, since those need measuring.
262. Record book draws 24 boards, then "Show more boards" (was all 249 at once).
263. Full stat lists: "Show all" alongside "Show 100 more".
264. Long tables draw 150 rows until asked.
265. Typing in filters is debounced everywhere (records, trades, FAAB, full lists, data, tables).
266. Search suggestions debounced to 60 ms.
267. Scroll listeners are passive.
268. Resize work is debounced.
269. Avatars load lazily and decode off the main thread.

## J. Home
270. Page head with the season, the week and how many regular-season weeks are left.
271. "★ Pick your team" call to action until a team is chosen.
272. Share button.
273. Headline tile: your team's record, place and playoff odds.
274. Headline tile: league leader.
275. Headline tile: top score of the week (opens the matchup).
276. Headline tile: closest game (opens it).
277. Headline tile: biggest blowout (opens it).
278. Headline tile: title favorite from the forecast.
279. Standings: medals for the top three.
280. Standings: avatars.
281. Standings: "x" chip for a clinched playoff spot.
282. Standings: "e" chip for an eliminated team.
283. Standings: point differential column, coloured.
284. Standings: streak column (W5 / L2), coloured.
285. Standings: last-5 form as coloured squares.
286. Standings: W-L in bold.
287. Standings: playoff odds with bars.
288. Standings: dashed playoff-cut line.
289. Standings: your team highlighted.
290. Standings: tap a row to open the team.
291. Standings: link to all-time standings.
292. Standings: a legend for x / e / the cut line.
293. Standings: link to Predictions.
294. Record watch: skeleton while it loads.
295. Record watch: ↻ Refresh button.
296. Record watch: the long explanation folded into "How the record watch works".
297. Record watch: counts on the view buttons dimmed.
298. Record watch: an honest error ("Sleeper did not answer in time" vs the real error) instead of always "unreachable".
299. Record watch: "Try again" button when it fails.
300. Results: each game is a real link (keyboard, middle-click, long-press) instead of a clickable div.
301. Results: avatars.
302. Results: winning line in bold with a green score.
303. Results: margin line; "nail-biter" / "blowout" tags.
304. Results: your game outlined in gold.
305. Results: links to the week page and every week of the season.
306. FAAB card: position badges.
307. FAAB card: each player's owner.
308. FAAB card: "Full board →" in the header.
309. FAAB card: "Rate the board" as a button.
310. Digest: item count beside each section.
311. Digest: "Expand all" / "Collapse all".
312. Digest: empty sub-headings no longer render.

## K. All-time standings
313. Breadcrumbs, title and share.
314. Intro line (seasons, team count).
315. New "Champions" card: champion, runner-up and 3rd for every finished season.
316. Trophies in the Titles column.
317. Win % with a bar.
318. New Finals column (championship appearances).
319. New All-play column.
320. Definitions on the columns.
321. Tap a row to open the team.
322. Your team highlighted.
323. "Every all-time stat" table gets filter, copy and CSV.

## L. Team page
324. Breadcrumbs.
325. Large team avatar.
326. Fantasy team name.
327. Titles chip (🏆 ×2) with the years on hover.
328. "☆ This is my team" toggle.
329. Compare button (against your team when set).
330. Share button.
331. This season as a W/L strip; each square opens the matchup with score and opponent on hover.
332. This season table: W / L instead of Yes / No.
333. This season table: tap a row for the matchup.
334. Section bar highlights the section on screen (scrollspy).
335. Section bar scrolls itself to keep the lit section visible.
336. Section jumps account for the header and bar height.
337. Sections are labelled regions (`aria-labelledby`).
338. Live roster: injury chip on each player.
339. Live roster: position badges.
340. Live roster: role as a chip (Starter / Bench / Taxi / IR).
341. Live roster: sorts by position and role properly.
342. Live roster: count of starters, bench, taxi and IR.
343. Build roster (before Sleeper answers): position badges.
344. Roster age table: position badges.
345. Roster age table: "older" / "younger" beside the difference.
346. Head to head: W-L coloured by winning or losing record.
347. Head to head: win % column with a bar.
348. Head to head: tap a row to compare the two teams.
349. Head to head: link to the matrix with this team preselected.
350. Seasons: chart of average points per season, title seasons in gold.
351. Seasons: 🏆 chip on championship results.
352. Trades: "No trades yet" empty state.
353. Trades: "All N trades →" as a button.
354. Rookie draft table: tap a row to open the pick.
355. "Every row in the data" links as chips.

## M. Player page
356. Breadcrumbs.
357. Position badge in the heading.
358. Owner shown with avatar.
359. Draft line on its own row.
360. Compare button.
361. Share button.
362. FAAB value matched by Sleeper id, not name (Jr./II re-spellings no longer drop it).
363. FAAB value as a highlighted strip.
364. FAAB "board" link opens the board filtered to him.
365. New: points-by-season chart.
366. Career by team: new Start % column.
367. Career by team: tap a row to open the team.
368. Career by team: your team highlighted.
369. "Every row" links as chips.
370. New "record boards" chip: every board place he holds.
371. History as a timeline.
372. Trades heading shows the count.

## N. Record book
373. Breadcrumbs, title per sheet, share.
374. Sheet switcher as a scrollable tab bar (was 13 wrapping buttons).
375. The current sheet tab scrolls into view.
376. "Where does a player, team or week rank?" gets its own card and a primary button.
377. `?find=` link runs that search on arrival (used by player pages and search).
378. Find results: board places per sheet as chips.
379. Find results: count of outright records.
380. Find results: medals for places 1-3.
381. The stat filter, highest / lowest and game-type controls stick under the header.
382. Game type (all / regular / playoffs…) as a compact select instead of a second button row.
383. Filter, end and game type are written to the URL.
384. Multi-word stat filter ("bench points") matches words in any order.
385. Boards: medals for places 1-3.
386. Boards: rows with your team highlighted.
387. Boards: each row is keyboard-focusable and opens with Enter.
388. Boards: an "all →" link to the full list.
389. Boards: ⓘ beside the title (focusable).
390. Board count says "featured first" when unfiltered.
391. No-match state: clear button and the same filter on other sheets.
392. The ranking rules note is collapsed under "How the boards are ranked".
393. The note mentions your-team highlighting.
394. Full list: breadcrumbs back to the sheet.
395. Full list: the stat's definition shown under the heading.
396. Full list: average and median of the whole column.
397. Full list: filter the list by player, team or year (keeps true ranks).
398. Full list: "flip" spelled out (flip to lowest first).
399. Full list: "Show all".
400. Full list: medals for 1-3.
401. Full list: your team highlighted.
402. Full list: rows open with Enter.
403. Full list: title "PF · Team week".

## O. Head to head
404. Breadcrumbs, title, share.
405. Team avatars in the column headers.
406. Full team name on header hover.
407. Show W-L or win % (new toggle).
408. Game type and display written to the URL.
409. Row and column of the hovered cell are lit (crosshair).
410. Cells are keyboard-focusable; Enter opens the meeting list.
411. Cell tooltip: "A 7-3 vs B".
412. The selected cell stays outlined.
413. `?a=&b=` opens a pair directly (team page and compare link here).
414. Your team's row highlighted.
415. Meeting card: tiles per game type, avg points for and against.
416. Meeting card: current streak.
417. Meeting card: a W/L strip of every meeting.
418. Meeting card: list newest first with the margin.
419. Meeting card: ⇄ Flip to the other team's side.
420. Meeting card: Compare button.
421. Meeting card scrolls into view on phones.
422. Legend for the colour scale.

## P. Trades
423. Breadcrumbs, title, share.
424. New: trades-per-season chart (bars link to that season).
425. New: most-active-traders bars (link to their trades).
426. Filter bar sticks under the header.
427. Team, season, search, order and direction written to the URL.
428. `?q=` prefills the player / pick search.
429. Active filters summarised with "Clear filters".
430. Active selects tinted.
431. Search debounced.
432. "Show 60 more (N left)" centred.
433. Empty state when nothing matches.
434. The how-to-read note folded into a details box.
435. Trade cards: date as "Nov 10, 2026".
436. Trade cards: the teams in the deal in the header line.
437. Trade cards: impact edge team in bold.
438. Trade cards: keyboard-focusable, open with Enter.
439. Trade cards: accessible label naming the trade and teams.
440. Trade cards: `<article>` and `<time>` elements.
441. Trade cards: a "KTC" label on the KTC row.
442. Trade page: breadcrumbs and title.
443. Trade page: previous / next trade links (and `[` / `]`).
444. Trade page: filter the sheet's stats by name.
445. Trade page: ⓘ definitions focusable.
446. Trade page: a clearer not-found message ("may be newer than this build").

## Q. Draft
447. Breadcrumbs, title, share.
448. Rookie / startup switch as tabs.
449. New team filter.
450. New round filter.
451. Year, team, round and draft type written to the URL (`?year=2025` links work).
452. Years newest first.
453. Count of picks shown.
454. Tap a row to open the pick.
455. Active filters tinted.
456. CSV file named after the draft and year.

## R. Pick page
457. Breadcrumbs.
458. Previous / next pick links (and `[` / `]`).
459. "The whole draft" link to that year.
460. Definitions on the pick's tiles.
461. Share button.

## S. Weeks (new page, `#/weeks/<year>`)
462. Every week of a season with the league's totals.
463. Season tabs, 2020 to now.
464. League points per week chart; playoff weeks in gold; bars open the week.
465. Table: PF, max PF, efficiency, top starter, average margin, close games, trades, add/drops, FAAB spent.
466. Latest week tagged.
467. Tap a row to open the week.
468. Link to the league_week data for that season.

## T. Week and matchup pages
469. Week page: breadcrumbs (Weeks › year week).
470. Week page: previous / next week links across seasons.
471. Week page: "All N weeks" link.
472. Week page: headline tiles — top score, low score, top starter, closest game.
473. Week page: games as real links with avatars, winner bold and margin.
474. Week page: your game outlined.
475. Week page: shortcut hint.
476. Matchup: breadcrumbs (Weeks › week › game).
477. Matchup: previous / next week for the same team.
478. Matchup: margin in the subtitle.
479. Matchup: score bar in the two teams' colours.
480. Matchup: "All their meetings" link to head to head.
481. Matchup: Won / Lost chips.
482. Matchup: efficiency and points left on the bench.
483. Matchup: position badges on every player.
484. Matchup: 20+ point starters in green.
485. Matchup: bench total in the bench summary.
486. Matchup: bench sorted by points.
487. Matchup: "every player that week" link now filters to that week (was the whole season).
488. Matchup: links as chips.

## U. FAAB values
489. Breadcrumbs, title, share.
490. "Rate the board" as the page's primary button.
491. Position filter as one-tap buttons (was a select).
492. Position, owner and search written to the URL; `?q=` prefills.
493. "Clear filters".
494. Position badges on the board.
495. Injury as a red chip.
496. Value with a bar.
497. Your team's players highlighted on the board.
498. Board draws 100 rows then "Show all".
499. Roster value and picks held: your team highlighted.
500. Roster value: avatars.
501. Rookie pick values: the value in bold.
502. Empty state when the board isn't published.
503. CSV named after the board's date.

## V. NFL team page
504. Breadcrumbs, title, share.
505. A bar of all 32 NFL teams to jump between them.
506. Current team marked `aria-current`.
507. Position badges in the depth chart.
508. Position badges in the players table.
509. Your team's players highlighted.

## W. Compare (new page, `#/compare?a=&b=`)
510. Pick any two players or two teams from a type-ahead list.
511. ⇄ swaps the sides.
512. Teams: avatars, fantasy names, every all-time stat side by side with the difference.
513. Teams: their head-to-head record, points and a W/L strip of every meeting.
514. Players: every career stat side by side.
515. Players: points by season side by side.
516. The higher value in each row is green (with a note that higher isn't always better).
517. Definitions on the stat names.
518. Mixed player-and-team picks explain themselves.
519. Opens with your team on side A when set.
520. Shareable URL; tab title "A vs B".

## X. Data
521. Breadcrumbs, title, share.
522. Total rows across every sheet in the intro.
523. New: find a sheet or a column by name; lists every matching column with its definition.
524. Sheets without a match are hidden while searching.
525. Browse / CSV as buttons.
526. Sheet view: the whole view (season, search, every filter, sort) is kept in the URL — copy the link to share a query.
527. New: "Filtered rows CSV ↓" — only the rows the filters keep, only the columns shown.
528. New: rows per page (50 / 100 / 250 / 500), remembered.
529. New: first / last page buttons.
530. Pager shows "rows 101–200".
531. New: find a column in the column picker.
532. The table scrolls inside its card with the header row stuck on top.
533. Header cells keyboard-sortable with `aria-sort`.
534. "No rows match these filters." row.
535. Your team's rows highlighted.
536. The details column is labelled for screen readers.

## Y. Predictions
537. Breadcrumbs, title, share.
538. A loading state while the schedule and simulations load.
539. "Sleeper unreachable" state with Try again.
540. The scenario (picked winners and roster moves) is kept in the URL — share it and others see the same odds.
541. A shared scenario's roster moves are announced when it opens.
542. Picked games: the loser greyed out as well as the winner filled.
543. Pick buttons carry `aria-pressed`.
544. New: "★ <your team> wins out".
545. New: "Pick the favorites" (each game to the higher projected scorer).
546. "Share this scenario" button.
547. Clearing picks clears both states.

## Z. Tests and docs
548. `tests/test_league_site.py::test_shell_keeps_its_basics`: skip link, search label, manifest copied and valid, every menu route exists, keyboard-sortable headers.
549. `plan/notes/LEAGUE_SITE.md`: new routes, settings, Sleeper identity, and the URL-state rule.
550. This list.

## Follow-up (2026-11-19, user: trade calculator, more Sleeper than GitHub, Share)
551. Trade calculator page (`#/calc`), linked from the menu, Trades and every team page (`g v`).
552. Calculator: tap-to-add players and future picks per side, with a filter.
553. Calculator: verdict meter in the two teams' colours, gap as rookie-pick equivalents.
554. Calculator: the five assets closest to the gap, from the team that comes out ahead.
555. Calculator: before → after roster value, value rank, QB/RB/WR/TE value, picks value, projected points a week, roster count.
556. Calculator: the deal lives in the URL; Swap sides, Clear, Share.
557. Calculator: "Title odds with this trade" opens Predictions with the players moved.
558. Sleeper colours: navy surfaces, mint accent, coral losses, dark by default.
559. Navy app bar in both themes with a mint → blue → purple strip under it.
560. Mint active tab, round search box and menu button.
561. Pill-shaped buttons and toggles.
562. Poppins for headings, tile numbers and medals.
563. Sleeper's position colours (QB pink, RB teal, WR blue, TE orange).
564. Round W/L form dots; gradient progress and value bars.
565. Theme menu: Sleeper dark (default), Light, Match the device (follows the device live).
566. Favicon, theme-color and app manifest in the new colours.
567. Share opens a dialog that always shows the link, with Copy, Share…, Text and Email.
568. "Link copied" only when the copy really happened; otherwise the link is selected to copy by hand.
569. Copy fallback works on iOS in-app browsers (selection range on a read-only field).
570. Shared links use `?to=<route>` instead of `#/…`, so Sleeper chat (and others) make them tappable.
571. Every table marks the best and worst value in each numeric column (green / coral), with a legend.
572. Lower-is-better columns (points against, busts, left on the bench, age…) are judged the right way round; identifiers and neutral counts are skipped.
573. On season-by-season tables the season still being played is left out of best / worst.
574. Trade calculator: KTC superflex value beside each asset (from a KTC snapshot the site build now saves, `data/ktc.json`).
575. Trade calculator: "Every angle" table — FAAB value, KTC value, KTC month trend, projected points a week, rest of the regular season, this season's points a week, starting-lineup change, age, picks — with the edge per row.
576. Trade calculator: season odds before → after (playoffs, final, title, projected wins) from the Predictions simulation, for both teams and everyone else.
577. Best / worst marks use an allow-list: only columns where more (or less) is clearly better; shares, counts, ages, tenure, swing, riskiness and projections stay plain.
578. Category columns (position, lineup role) are never marked.
579. Head to head: meetings are ordered oldest → newest before the streak and the strip (the file lists them newest first, which flipped the streak).
580. Head to head: "Points for / against (all meetings)" instead of a mislabelled "Avg".
581. "Roll of honour" renamed "Champions"; American spellings (favorite).
582. Home headline tiles redone, one format each: your team, the playoff line (who holds the last spot and who's within a game), title favorite, hottest and coldest team over the last three weeks.
583. Trade calculator: KTC totals use KTC's own value adjustment (ported from keeptradecut.com's live code, ALGOTOUSE=2), so a 2-for-1 gives the side with the best piece the bonus KTC's calculator gives, and the verdict says "add a player worth ~X" as KTC does.
584. Trade calculator: choose the metric that drives the verdict and the suggestions (KTC, FAAB, projected points, rest of season, this season's points); remembered.
585. Trade calculator: three- and four-team trades in the same layout ("+ Add a team"; each sent asset gets a destination).
586. Trade calculator: "Or bring in a third team" — for each other team, the swap through it that leaves every team closest to even.
587. Trade calculator: checks after every change — every team involved, active roster under the league limit, every starting spot still fillable.
588. Trade calculator: projected wins added, playoff odds and title odds as verdict / suggestion measures — each team's simulated change (Predictions model); even-it-up candidates (ten most-projected players) and third-team ideas (screened on projected points) are each simulated, and teams outside the deal that move are listed.
589. Every Sleeper and forecast request has a timeout; the calculator's simulation is dropped if it fails or takes over 30 s, errors aren't cached, and Season odds / Verdict show Try again instead of a spinner that never ends.
590. Best / worst marks are quiet: colored number with a small ▲ / ▼, no filled box. Ties at either end are all marked (unless most of the column shares the value); usage, draft value and playoff / toilet-bowl win % columns are marked too.
591. Best / worst marks drop the ▲ / ▼ (confusing): just green (best) or red (worst) numbers, with a legend.
592. Links get their own soft blue (--link), apart from the mint accent on buttons and tabs and the green of good numbers.
593. Home: the headline tiles above the standings are removed (user: they didn't add anything); the page opens on Standings & odds.
594. Predictions: pick a team and "Most likely way in" / "Most likely way out" fills every unpicked game with the result that happens most often in the simulated seasons where that team makes (misses) the playoffs; says how often that happens and the team's odds with the results set; Undo clears only the filled games.
595. Predictions: clinched / eliminated are exact — every way the open games can go (real results for games finished since the build, picks respected; up to 20 open games), not the wins-only shortcut.
596. Predictions: when no simulated season has a team missing (making) the playoffs, the way-out (way-in) button says whether it has clinched (is eliminated); if it hasn't, it fills the most likely set of results that still does it, with the team's odds under them ("all but clinched" when its points-for edge makes the tiebreak near-impossible).
597. Predictions: the 1st-seed column is exact too — 0% for a team that can't finish first however the open games go, 100% for one that can't be caught (a tie in wins counts as possibly lost on points for).
