"""Team-week document output."""

FILE_NAME = "team_week.csv"
PLAN_KEY = "team-week"
FRAME_KEY = "team_week"


def build_output(context):
    return context[FRAME_KEY]
