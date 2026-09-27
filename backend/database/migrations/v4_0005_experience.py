"""
v4 · P5 Experience (spec §16, §17, §18, §21.3) + analytics

Tables: ride_ratings, favourite_drivers, referrals, analytics_events.
(The legacy `driver_ratings` table belongs to the older flow and is left untouched.)
"""
from backend.database.schema_helpers import create_tables, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE ride_ratings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        rater_id INT NOT NULL,
        ratee_id INT NOT NULL,
        role VARCHAR(20) NOT NULL,
        stars TINYINT NOT NULL,
        tags JSON NULL,
        comment TEXT NULL,
        tip_cents BIGINT NOT NULL DEFAULT 0,
        tip_payment_id BIGINT NULL,
        visible_at DATETIME NULL,
        hidden_by_admin TINYINT(1) NOT NULL DEFAULT 0,
        hidden_by INT NULL,
        hidden_reason VARCHAR(500) NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_rating (ride_type, ride_id, rater_id),
        KEY ix_rating_ratee (ratee_id, created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE favourite_drivers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        customer_id INT NOT NULL,
        driver_id INT NOT NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_fav (customer_id, driver_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE referrals (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        referrer_id INT NOT NULL,
        referred_id INT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        bonus_cents BIGINT NOT NULL DEFAULT 0,
        paid_at DATETIME NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_referred (referred_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE analytics_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        name VARCHAR(80) NOT NULL,
        value_num DECIMAL(14,3) NULL,
        props JSON NULL,
        created_at DATETIME NOT NULL,
        KEY ix_analytics_name (name, created_at)
    ) {TABLE_OPTS}""",
]


def up(conn):
    create_tables(conn, TABLES)


def down(conn):
    drop_tables(conn, ['analytics_events', 'referrals', 'favourite_drivers', 'ride_ratings'])
