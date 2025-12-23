# LOTG Cloud Tracker (no code on your Mac)

This project runs **entirely in the cloud** on **GitHub Actions (free)** and exports your league’s history into
CSV + Excel tabs, using the column schema in:

- `plan/LOTG Plan - Sheet1.csv`

## What you need

- A free GitHub account (you can sign up with Gmail)
- A web browser on your Mac
- Microsoft Excel (optional, but helpful)

## Setup (once)

1. Create a new GitHub repository (public or private).
2. Upload everything in this folder to that repo (drag/drop on github.com is fine).
3. In the repo, open `config/league.yaml` and set:
   - `league_id` to your Sleeper league id (keep it in quotes).
4. Go to **Actions** and enable GitHub Actions if prompted.

## Run it (one click)

- GitHub repo → **Actions** → **Build LOTG Stats** → **Run workflow**

When it finishes, download the artifact named **LOTG_outputs**.

It contains:
- `exports/LOTG_Stats.xlsx` (one tab per output table)
- `exports/LOTG_Exports.zip` (all CSVs)
- the individual CSVs (so you can import to Sheets/Excel/PowerBI later)

## Outputs

These tables match the column lists in your plan:

- `player_week.csv`
- `player_year.csv`
- `player_all_time.csv`
- `team_week.csv`
- `team_year.csv`
- `team_all_time.csv`
- `league_week.csv`
- `league_year.csv`
- `league_all_time.csv`
- `transactions.csv`
- `trades.csv`
- `pick_history.csv`

## Notes on custom / league-flavor stats

A few columns in your plan look like custom league awards or inside jokes (e.g., `Brosenzweig`, `Sisenzweig`).
This build defines them deterministically so they’re always reproducible:

- `UPST`: 1 if you won while your **Max PF** was lower than your opponent’s Max PF (i.e., an upset by “optimal lineup” strength).
- `Hardship`: (injury + suspension + bye counts) / starter count (best-effort, using public injury + schedule data).
- `Brosenzweig`: `UPST == 1` AND `Hardship > 0`
- `Sisenzweig`: `UPST == 0` AND `Hardship > 0` AND `Win? == 1`

If you want different definitions, edit them in `src/lotg/build.py` (search for the metric names).
