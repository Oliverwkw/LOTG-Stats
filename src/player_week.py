"""Player-week document output."""

FILE_NAME = "player_week.csv"
PLAN_KEY = "Player-Week"
FRAME_KEY = "player_week"


def build_output(context):
    return context[FRAME_KEY]
