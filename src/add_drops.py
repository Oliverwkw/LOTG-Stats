"""Add/Drop document output (formerly 'transactions').

An add/drop is a waiver claim, free-agency pickup, pure drop, or commissioner
roster move — every non-trade roster change. Trades live in their own sheet.
"""

FILE_NAME = "add_drops.csv"
PLAN_KEY = "add_drops"
FRAME_KEY = "add_drops"


def build_output(context):
    return context[FRAME_KEY]
