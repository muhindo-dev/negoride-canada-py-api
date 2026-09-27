"""
v4 · Lifecycle timestamp columns on negotiations.

These columns already exist in databases where the Truckeroo backend ran its own
migrations (it shares the local `negoride` schema), but NOT in NegoRide
production. Add them where missing. `down()` deliberately does NOT drop them,
because another application may own them.
"""
from backend.database.schema_helpers import add_columns

COLUMNS = [
    "driver_arrived_at DATETIME NULL DEFAULT NULL",
    "started_at DATETIME NULL DEFAULT NULL",
    "completed_at DATETIME NULL DEFAULT NULL",
    "cancelled_by VARCHAR(20) NULL DEFAULT NULL",
    "cancel_reason TEXT NULL",
]


def up(conn):
    add_columns(conn, 'negotiations', COLUMNS)


def down(conn):
    pass  # shared columns — never dropped
