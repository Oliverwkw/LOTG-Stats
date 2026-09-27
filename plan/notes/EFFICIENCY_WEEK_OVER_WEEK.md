# Biggest week-over-week swings in efficiency

**Question.** "Give top and bottom 10 week over week decrease and increase in
efficiency." (Asked 2026-09-27, alongside the new team_week column "Increase in
efficiency from previous week" on branch `efficiency-change-columns`.)

**Method.** `team_week.Efficiency` (PF ÷ Max PF) from the committed exports,
each team sorted by (Year, Week), change = this week − the team's previous
week. Week 1 compares with the team's last week of the prior season, the same
rule as the new build column. 816 changes, 2020 through 2026 week 2. Changes
are in percentage points. No cross-season pair made either list.

## 10 biggest increases

| # | Team | Season, week | Previous → this week | Change | PF / Max PF |
|---|---|---|---|---|---|
| 1 | AceMatthew | 2024 wk 3→4 | 51.9% → 91.9% | +40.0 | 171.02 / 186.12 |
| 2 | plehv79 | 2022 wk 16→17 | 32.8% → 70.3% | +37.5 ⚑ | 129.28 / 184.00 |
| 3 | stevenb123 | 2023 wk 11→12 | 56.1% → 93.4% | +37.4 | 156.60 / 167.60 |
| 4 | AceMatthew | 2023 wk 4→5 | 51.4% → 85.7% | +34.3 | 178.98 / 208.86 |
| 5 | plehv79 | 2025 wk 7→8 | 65.3% → 98.5% | +33.2 | 167.64 / 170.14 |
| 6 | shmuel256 | 2021 wk 15→16 | 64.6% → 95.3% | +30.7 | 144.64 / 151.80 |
| 7 | plehv79 | 2023 wk 15→16 | 58.5% → 89.0% | +30.5 | 147.78 / 166.00 |
| 8 | AceMatthew | 2020 wk 15→16 | 57.0% → 86.5% | +29.5 | 155.22 / 179.46 |
| 9 | BROsenzweig | 2025 wk 16→17 | 54.7% → 82.5% | +27.8 | 123.12 / 149.22 |
| 10 | plehv79 | 2025 wk 11→12 | 66.1% → 92.7% | +26.6 | 71.88 / 77.58 |

## 10 biggest decreases

| # | Team | Season, week | Previous → this week | Change | PF / Max PF |
|---|---|---|---|---|---|
| 1 | plehv79 | 2022 wk 15→16 | 88.3% → 32.8% | −55.6 ⚑ | 45.36 / 138.36 |
| 2 | JacobRosenzweig | 2020 wk 1→2 | 99.1% → 59.2% | −40.0 | 96.74 / 163.54 |
| 3 | AceMatthew | 2023 wk 3→4 | 88.5% → 51.4% | −37.1 | 90.18 / 175.42 |
| 4 | JacobRosenzweig | 2023 wk 13→14 | 94.0% → 60.9% | −33.1 | 135.38 / 222.18 |
| 5 | Oliverwkw | 2020 wk 11→12 | 100.0% → 66.9% | −33.1 | 111.04 / 165.96 |
| 6 | shmuel256 | 2022 wk 2→3 | 88.3% → 56.9% | −31.5 | 74.90 / 131.74 |
| 7 | AceMatthew | 2020 wk 13→14 | 93.6% → 62.2% | −31.4 | 90.58 / 145.66 |
| 8 | AceMatthew | 2023 wk 14→15 | 88.4% → 57.2% | −31.2 | 99.12 / 173.28 |
| 9 | stevenb123 | 2020 wk 12→13 | 93.4% → 62.7% | −30.7 | 91.88 / 146.58 |
| 10 | Oliverwkw | 2025 wk 11→12 | 88.7% → 59.7% | −29.0 | 87.00 / 145.82 |

⚑ = the 2022 tankathon game, below.

## The 2022 week 16 Toilet Semis was thrown (confirmed)

plehv79 v shmuel256 in the 2022 week 16 Toilet Semis was an **intentionally
thrown tankathon matchup** (confirmed by Oliver, 2026-09-27). Through the 2024
draft, placement counted the toilet bowl, so winning a consolation game cost
draft position (see the playbook trap "Placement counted the toilet bowl").

| Team | PF | Max PF | Efficiency |
|---|---|---|---|
| plehv79 | 45.36 | 138.36 | 32.8% (league's lowest ever) |
| shmuel256 | 67.16 | 142.12 | 47.3% |

So plehv79's #1 decrease and #2 increase are the same event, and they reflect
tanking, not lineup-setting. Leaving that game out, the top decrease is
JacobRosenzweig in 2020 week 2 (−40.0) and the top increase is still
AceMatthew in 2024 week 4 (+40.0). Any "worst week", "lowest efficiency" or
"biggest drop" board will surface these two rows first; flag them rather than
dropping them quietly.

## Caveats

- **[by-design] Max PF drives most swings.** Several drops are ordinary scores
  next to a huge ceiling left on the bench (JacobRosenzweig 2023 wk 14, Max PF
  222.18). Efficiency measures lineup choices, not output.
- **[by-design] Semifinal +5 is in PF, so it is in Efficiency.** 12 team-weeks
  carry it (two per season 2020-2025, playoff-start week). None appear in
  either list above. The playbook and `inquiry.py` docstring previously said
  "eight rows across 2021-2025"; corrected to ten in 2021-2025 plus two in 2020.
- **[unverified] Build column not yet exported.** "Increase in efficiency from
  previous week" was not in the committed `exports/` when this was computed;
  the numbers use the same formula and should match once CI builds it. The
  build rounds to 4 decimal places.
