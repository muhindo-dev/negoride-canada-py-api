"""
v4 · P5 Experience — pick-a-driver / favourite-first / broadcast matching
(spec §18.2), once-only reminder markers and supply snapshots (§19.1.13).

Tables:
  ride_requests            one customer car-hire request (direct | favourite_first | broadcast)
  ride_request_offers      the request offered to one driver (first acceptor wins)
  experience_marks         "sent once" markers (departure reminders, …)
  driver_supply_snapshots  online-driver count every 10 min (supply vs demand report)

The Negotiation model stays single-driver: a negotiation is created only when a
driver accepts / counters (or immediately for `direct`).
"""
from backend.database.schema_helpers import create_tables, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE ride_requests (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT NOT NULL,
        mode VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL,
        service_type VARCHAR(40) NOT NULL DEFAULT 'car',
        pickup_lat DECIMAL(10,7) NOT NULL,
        pickup_lng DECIMAL(10,7) NOT NULL,
        pickup_address VARCHAR(500) NULL,
        dropoff_lat DECIMAL(10,7) NULL,
        dropoff_lng DECIMAL(10,7) NULL,
        dropoff_address VARCHAR(500) NULL,
        offer_cents BIGINT NOT NULL,
        note VARCHAR(500) NULL,
        favourite_driver_id INT NULL,
        favourite_until DATETIME NULL,
        broadcast_at DATETIME NULL,
        expires_at DATETIME NULL,
        negotiation_id BIGINT NULL,
        matched_driver_id INT NULL,
        matched_at DATETIME NULL,
        distance_m INT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NULL,
        KEY ix_rr_status_fav (status, favourite_until),
        KEY ix_rr_status_exp (status, expires_at),
        KEY ix_rr_customer (customer_id, created_at),
        KEY ix_rr_created (created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE ride_request_offers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        request_id BIGINT NOT NULL,
        driver_id INT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'offered',
        is_favourite TINYINT(1) NOT NULL DEFAULT 0,
        distance_m INT NULL,
        eta_s INT NULL,
        counter_cents BIGINT NULL,
        offered_at DATETIME NOT NULL,
        responded_at DATETIME NULL,
        UNIQUE KEY uq_rro (request_id, driver_id),
        KEY ix_rro_driver (driver_id, status)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE experience_marks (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        kind VARCHAR(40) NOT NULL,
        ref_type VARCHAR(30) NOT NULL,
        ref_id BIGINT NOT NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_exp_mark (kind, ref_type, ref_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE driver_supply_snapshots (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        bucket_at DATETIME NOT NULL,
        online_drivers INT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_supply_bucket (bucket_at)
    ) {TABLE_OPTS}""",
]


def up(conn):
    create_tables(conn, TABLES)


def down(conn):
    drop_tables(conn, ['driver_supply_snapshots', 'experience_marks', 'ride_request_offers', 'ride_requests'])
