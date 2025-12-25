# LOTG-Stats

Pipeline to generate a complete LOTG_Stats Excel workbook:

- Fully populated sheets
- Restored Record / Win% vs each team
- First four columns pinned on every sheet

## Usage

1. Put raw game logs under `./data/` (CSV or Excel).
2. Edit `config.yaml` to map your columns to the normalized names.
3. Run:
   ```bash
   python -m lotg_stats.cli --config config.yaml
   ```

Output: `./LOTG_outputs/LOTG_Stats.xlsx`

## Notes

- Config-driven column mapping allows your existing file headers to vary.
- If player stats are missing, the Players sheet is skipped gracefully.
