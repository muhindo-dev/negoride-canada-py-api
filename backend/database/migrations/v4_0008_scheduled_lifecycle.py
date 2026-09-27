"""
v4 · Lifecycle columns on scheduled_bookings so scheduled car hire / airport /
courier rides get the same arrival, wait-window, ETA and dispute handling as
on-demand car hire.
"""
from backend.database.schema_helpers import add_columns, drop_columns

COLUMNS = [
    "en_route_at DATETIME NULL DEFAULT NULL",
    "arriving_at DATETIME NULL DEFAULT NULL",
    "driver_arrived_at DATETIME NULL DEFAULT NULL",
    "closed_at DATETIME NULL DEFAULT NULL",
    "awaiting_payment_since DATETIME NULL DEFAULT NULL",
    "cancel_reason_code VARCHAR(40) NULL DEFAULT NULL",
    "eta_seconds INT NULL DEFAULT NULL",
    "eta_distance_m INT NULL DEFAULT NULL",
    "eta_target VARCHAR(10) NULL DEFAULT NULL",
    "eta_updated_at DATETIME NULL DEFAULT NULL",
    "initial_eta_at DATETIME NULL DEFAULT NULL",
    "disputed_at DATETIME NULL DEFAULT NULL",
    "dispute_reason TEXT NULL",
    "pickup_province VARCHAR(4) NULL DEFAULT NULL",
    "tip_cents BIGINT NULL DEFAULT NULL",
]


def up(conn):
    add_columns(conn, 'scheduled_bookings', COLUMNS)


def down(conn):
    drop_columns(conn, 'scheduled_bookings', [c.split()[0] for c in COLUMNS])
