"""
v4 · 0403 — counter-offer marketplace (spec §21.2.2).

ride_request_offers gets the back-and-forth state of one driver's offer:
  counter_by              'driver' | 'customer' — whose counter is on the table
  customer_counter_cents  the customer's counter to that driver
  counter_expires_at      the live counter's expiry (setting carhire.counter_offer_ttl_s)
  counter_round           number of counters exchanged
Offer statuses: offered | countered (driver countered, customer's turn) |
customer_countered (driver's turn) | accepted | declined | withdrawn | expired.
"""
from backend.database.schema_helpers import add_columns, drop_columns

COLUMNS = [
    "counter_by VARCHAR(10) NULL DEFAULT NULL",
    "customer_counter_cents BIGINT NULL DEFAULT NULL",
    "counter_expires_at DATETIME NULL DEFAULT NULL",
    "counter_round INT NOT NULL DEFAULT 0",
]


def up(conn):
    add_columns(conn, 'ride_request_offers', COLUMNS)


def down(conn):
    drop_columns(conn, 'ride_request_offers', ['counter_by', 'customer_counter_cents', 'counter_expires_at',
                                               'counter_round'])
