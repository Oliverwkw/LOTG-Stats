"""Team-week document output."""

from lotg_support.matchup import add_combined_columns

FILE_NAME = "team_week.csv"
PLAN_KEY = "team-week"
FRAME_KEY = "team_week"


def build_output(context):
    # The combined-matchup block reads the finished per-team columns (injuries,
    # hardship and boom/bust are filled in late), so it is added here, last.
    return add_combined_columns(context[FRAME_KEY])
