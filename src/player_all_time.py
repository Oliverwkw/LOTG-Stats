"""Player-all-time document output."""

FILE_NAME = "player_all_time.csv"
PLAN_KEY = "Player-all-time"
FRAME_KEY = "player_all_time"


def build_output(context):
    return context[FRAME_KEY]
