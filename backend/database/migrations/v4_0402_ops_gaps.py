"""
v4 · 0402 — trip/payments/notifications audit gaps.

  live_activity_tokens            iOS Live Activity push tokens (§5.1, server-driven updates)
  notification_template_overrides admin-editable notification copy (§19.1.10)
  tip_receipts                    NR-TIP-YYYY-NNNNNN documents for tips paid after the ride (§13)
  admin_users.email_bounced_at    Postmark hard bounce / spam complaint → email channel suppressed
  admin_users.email_bounce_reason
  trip_bookings.pickup_province   province of the passenger's own pickup point (tax, §13.3)
  ride_payments.settlement_status 'safety_review' while a safety-ended ride's hold awaits the admin
  ride_payments.settle_due_at     auto-release deadline for that hold (setting safety.settle_hold_h)

Additive only; amounts are INTEGER CENTS, CAD.
"""
from backend.database.schema_helpers import (TABLE_OPTS, add_columns, add_index, create_tables, drop_columns,
                                             drop_tables)

TABLES = [
    f"""CREATE TABLE live_activity_tokens (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        activity_id VARCHAR(191) NOT NULL,
        push_token VARCHAR(512) NOT NULL,
        platform VARCHAR(20) NOT NULL DEFAULT 'ios',
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        last_pushed_at DATETIME NULL,
        last_error TEXT NULL,
        ended_at DATETIME NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_lat_activity (activity_id),
        KEY ix_lat_ride (ride_type, ride_id),
        KEY ix_lat_user (user_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE notification_template_overrides (
        id INT AUTO_INCREMENT PRIMARY KEY,
        event_key VARCHAR(80) NOT NULL,
        lang VARCHAR(5) NOT NULL,
        title TEXT NULL,
        body TEXT NULL,
        updated_by INT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_nto_event_lang (event_key, lang)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE tip_receipts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        number VARCHAR(30) NOT NULL,
        ride_payment_id BIGINT NOT NULL,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        receipt_id BIGINT NULL,
        customer_id INT NOT NULL,
        driver_id INT NULL,
        currency CHAR(3) NOT NULL DEFAULT 'cad',
        amount_cents BIGINT NOT NULL,
        totals JSON NOT NULL,
        pdf_path VARCHAR(500) NULL,
        emailed_at DATETIME NULL,
        issued_at DATETIME NOT NULL,
        UNIQUE KEY uq_tip_receipts_number (number),
        UNIQUE KEY uq_tip_receipts_payment (ride_payment_id),
        KEY ix_tip_receipts_ride (ride_type, ride_id)
    ) {TABLE_OPTS}""",
]

USER_COLUMNS = [
    "email_bounced_at DATETIME NULL DEFAULT NULL",
    "email_bounce_reason VARCHAR(255) NULL DEFAULT NULL",
]
BOOKING_COLUMNS = ["pickup_province VARCHAR(4) NULL DEFAULT NULL"]
PAYMENT_COLUMNS = [
    "settlement_status VARCHAR(20) NULL DEFAULT NULL",
    "settle_due_at DATETIME NULL DEFAULT NULL",
]


def up(conn):
    create_tables(conn, TABLES)
    add_columns(conn, 'admin_users', USER_COLUMNS)
    add_columns(conn, 'trip_bookings', BOOKING_COLUMNS)
    add_columns(conn, 'ride_payments', PAYMENT_COLUMNS)
    add_index(conn, 'ride_payments', 'ix_rp_settle_due', 'settlement_status, settle_due_at')


def down(conn):
    drop_tables(conn, ['live_activity_tokens', 'notification_template_overrides', 'tip_receipts'])
    drop_columns(conn, 'admin_users', ['email_bounced_at', 'email_bounce_reason'])
    drop_columns(conn, 'trip_bookings', ['pickup_province'])
    drop_columns(conn, 'ride_payments', ['settlement_status', 'settle_due_at'])
