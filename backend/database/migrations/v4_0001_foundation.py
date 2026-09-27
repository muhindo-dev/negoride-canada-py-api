"""
v4 · P1 Foundation (spec §2, §4, §5)

Tables: app_settings, audit_logs, webhook_events, trip_events, notifications,
notification_deliveries, notification_preferences, device_tokens,
idempotency_keys.
Columns: trip_stage + lifecycle timestamps on negotiations, trips, trip_bookings,
scheduled_bookings.

Additive only — no existing column is renamed or dropped.
"""
from backend.database.schema_helpers import (
    add_columns, add_index, create_tables, drop_columns, drop_tables, TABLE_OPTS)

TABLES = [
    f"""CREATE TABLE app_settings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        `key` VARCHAR(120) NOT NULL,
        value TEXT NULL,
        value_type VARCHAR(20) NOT NULL DEFAULT 'string',
        category VARCHAR(40) NOT NULL DEFAULT 'general',
        description VARCHAR(500) NULL,
        is_public TINYINT(1) NOT NULL DEFAULT 0,
        updated_by INT NULL,
        created_at DATETIME NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_app_settings_key (`key`)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE audit_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        actor_id INT NULL,
        actor_type VARCHAR(20) NOT NULL DEFAULT 'admin',
        action VARCHAR(120) NOT NULL,
        entity_type VARCHAR(60) NULL,
        entity_id VARCHAR(64) NULL,
        before_json JSON NULL,
        after_json JSON NULL,
        meta JSON NULL,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(500) NULL,
        created_at DATETIME NOT NULL,
        KEY ix_audit_entity (entity_type, entity_id),
        KEY ix_audit_actor (actor_id),
        KEY ix_audit_action (action),
        KEY ix_audit_created (created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE webhook_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        provider VARCHAR(20) NOT NULL,
        event_id VARCHAR(191) NOT NULL,
        event_type VARCHAR(120) NULL,
        payload LONGTEXT NOT NULL,
        signature_valid TINYINT(1) NOT NULL DEFAULT 1,
        status VARCHAR(20) NOT NULL DEFAULT 'received',
        attempts INT NOT NULL DEFAULT 0,
        error TEXT NULL,
        received_at DATETIME NOT NULL,
        processed_at DATETIME NULL,
        UNIQUE KEY uq_webhook_provider_event (provider, event_id),
        KEY ix_webhook_status (status)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE trip_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        from_stage VARCHAR(40) NULL,
        to_stage VARCHAR(40) NOT NULL,
        actor_type VARCHAR(20) NOT NULL,
        actor_id INT NULL,
        lat DECIMAL(10,7) NULL,
        lng DECIMAL(10,7) NULL,
        meta JSON NULL,
        created_at DATETIME NOT NULL,
        KEY ix_trip_events_ride (ride_type, ride_id),
        KEY ix_trip_events_stage (to_stage),
        KEY ix_trip_events_created (created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE notifications (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        event_key VARCHAR(80) NOT NULL,
        event_group VARCHAR(30) NOT NULL DEFAULT 'general',
        title VARCHAR(255) NOT NULL,
        body TEXT NULL,
        data JSON NULL,
        deep_link VARCHAR(255) NULL,
        is_critical TINYINT(1) NOT NULL DEFAULT 0,
        read_at DATETIME NULL,
        opened_at DATETIME NULL,
        created_at DATETIME NOT NULL,
        KEY ix_notifications_user (user_id, created_at),
        KEY ix_notifications_event (event_key)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE notification_deliveries (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        notification_id BIGINT NOT NULL,
        channel VARCHAR(20) NOT NULL,
        provider_message_id VARCHAR(191) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        error TEXT NULL,
        attempts INT NOT NULL DEFAULT 0,
        queued_at DATETIME NOT NULL,
        sent_at DATETIME NULL,
        delivered_at DATETIME NULL,
        opened_at DATETIME NULL,
        failed_at DATETIME NULL,
        next_attempt_at DATETIME NULL,
        KEY ix_nd_notification (notification_id),
        KEY ix_nd_status (status),
        KEY ix_nd_provider (provider_message_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE notification_preferences (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        event_group VARCHAR(30) NOT NULL,
        push TINYINT(1) NOT NULL DEFAULT 1,
        sms TINYINT(1) NOT NULL DEFAULT 1,
        email TINYINT(1) NOT NULL DEFAULT 1,
        quiet_start CHAR(5) NULL,
        quiet_end CHAR(5) NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_np_user_group (user_id, event_group)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE device_tokens (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        onesignal_subscription_id VARCHAR(191) NULL,
        device_id VARCHAR(191) NULL,
        platform VARCHAR(20) NULL,
        app_version VARCHAR(30) NULL,
        os_version VARCHAR(60) NULL,
        locale VARCHAR(10) NULL,
        timezone VARCHAR(60) NULL,
        last_seen_at DATETIME NULL,
        created_at DATETIME NULL,
        UNIQUE KEY uq_device_user (user_id, device_id),
        KEY ix_device_sub (onesignal_subscription_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE idempotency_keys (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        idem_key VARCHAR(120) NOT NULL,
        endpoint VARCHAR(191) NOT NULL,
        status_code INT NULL,
        response_json LONGTEXT NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_idem (user_id, endpoint, idem_key)
    ) {TABLE_OPTS}""",
]

_RIDE_COLUMNS = [
    "trip_stage VARCHAR(40) NULL DEFAULT NULL",
    "stage_changed_at DATETIME NULL DEFAULT NULL",
]

NEGOTIATION_COLUMNS = _RIDE_COLUMNS + [
    "agreed_price_cents BIGINT NULL DEFAULT NULL",
    "ride_pin VARCHAR(8) NULL DEFAULT NULL",
    "confirmed_at DATETIME NULL DEFAULT NULL",
    "en_route_at DATETIME NULL DEFAULT NULL",
    "arriving_at DATETIME NULL DEFAULT NULL",
    "closed_at DATETIME NULL DEFAULT NULL",
    "cancelled_at DATETIME NULL DEFAULT NULL",
    "cancel_reason_code VARCHAR(40) NULL DEFAULT NULL",
    "awaiting_payment_since DATETIME NULL DEFAULT NULL",
    "eta_seconds INT NULL DEFAULT NULL",
    "eta_distance_m INT NULL DEFAULT NULL",
    "eta_target VARCHAR(10) NULL DEFAULT NULL",
    "eta_updated_at DATETIME NULL DEFAULT NULL",
    "initial_eta_at DATETIME NULL DEFAULT NULL",
    "disputed_at DATETIME NULL DEFAULT NULL",
    "dispute_reason TEXT NULL",
    "request_mode VARCHAR(20) NULL DEFAULT NULL",
    "service_type VARCHAR(40) NULL DEFAULT NULL",
    "tip_cents BIGINT NULL DEFAULT NULL",
    "final_fare_cents BIGINT NULL DEFAULT NULL",
    "waiting_fee_cents BIGINT NULL DEFAULT NULL",
    "distance_m INT NULL DEFAULT NULL",
    "duration_s INT NULL DEFAULT NULL",
    "pickup_province VARCHAR(4) NULL DEFAULT NULL",
]

TRIP_COLUMNS = _RIDE_COLUMNS + [
    "departure_at DATETIME NULL DEFAULT NULL",
    "booking_mode VARCHAR(20) NOT NULL DEFAULT 'instant'",
    "allow_seat_negotiation TINYINT(1) NOT NULL DEFAULT 1",
    "price_per_seat_cents BIGINT NULL DEFAULT NULL",
    "min_seat_price_cents BIGINT NULL DEFAULT NULL",
    "pets_ok TINYINT(1) NOT NULL DEFAULT 0",
    "luggage_size VARCHAR(20) NULL DEFAULT NULL",
    "boarding_at DATETIME NULL DEFAULT NULL",
    "started_at DATETIME NULL DEFAULT NULL",
    "completed_at DATETIME NULL DEFAULT NULL",
    "closed_at DATETIME NULL DEFAULT NULL",
    "cancelled_at DATETIME NULL DEFAULT NULL",
    "cancel_reason_code VARCHAR(40) NULL DEFAULT NULL",
    "published_at DATETIME NULL DEFAULT NULL",
    "pickup_province VARCHAR(4) NULL DEFAULT NULL",
]

TRIP_BOOKING_COLUMNS = _RIDE_COLUMNS + [
    "ride_pin VARCHAR(8) NULL DEFAULT NULL",
    "price_per_seat_cents BIGINT NULL DEFAULT NULL",
    "offered_price_per_seat_cents BIGINT NULL DEFAULT NULL",
    "total_cents BIGINT NULL DEFAULT NULL",
    "request_status VARCHAR(20) NULL DEFAULT NULL",
    "request_expires_at DATETIME NULL DEFAULT NULL",
    "pickup_order INT NULL DEFAULT NULL",
    "pickup_lat DECIMAL(10,7) NULL DEFAULT NULL",
    "pickup_lng DECIMAL(10,7) NULL DEFAULT NULL",
    "pickup_address VARCHAR(500) NULL DEFAULT NULL",
    "confirmed_at DATETIME NULL DEFAULT NULL",
    "driver_arrived_at DATETIME NULL DEFAULT NULL",
    "checked_in_at DATETIME NULL DEFAULT NULL",
    "dropped_off_at DATETIME NULL DEFAULT NULL",
    "closed_at DATETIME NULL DEFAULT NULL",
    "cancelled_at DATETIME NULL DEFAULT NULL",
    "cancel_reason_code VARCHAR(40) NULL DEFAULT NULL",
    "awaiting_payment_since DATETIME NULL DEFAULT NULL",
    "disputed_at DATETIME NULL DEFAULT NULL",
]

SCHEDULED_BOOKING_COLUMNS = _RIDE_COLUMNS + [
    "ride_pin VARCHAR(8) NULL DEFAULT NULL",
]


def up(conn):
    create_tables(conn, TABLES)
    add_columns(conn, 'negotiations', NEGOTIATION_COLUMNS)
    add_columns(conn, 'trips', TRIP_COLUMNS)
    add_columns(conn, 'trip_bookings', TRIP_BOOKING_COLUMNS)
    add_columns(conn, 'scheduled_bookings', SCHEDULED_BOOKING_COLUMNS)
    add_index(conn, 'negotiations', 'ix_negotiations_trip_stage', 'trip_stage')
    add_index(conn, 'trips', 'ix_trips_trip_stage', 'trip_stage')
    add_index(conn, 'trip_bookings', 'ix_trip_bookings_trip_stage', 'trip_stage')
    add_index(conn, 'scheduled_bookings', 'ix_sched_trip_stage', 'trip_stage')


def _names(cols):
    return [c.split()[0] for c in cols]


def down(conn):
    drop_columns(conn, 'negotiations', _names(NEGOTIATION_COLUMNS))
    drop_columns(conn, 'trips', _names(TRIP_COLUMNS))
    drop_columns(conn, 'trip_bookings', _names(TRIP_BOOKING_COLUMNS))
    drop_columns(conn, 'scheduled_bookings', _names(SCHEDULED_BOOKING_COLUMNS))
    drop_tables(conn, ['idempotency_keys', 'device_tokens', 'notification_preferences',
                       'notification_deliveries', 'notifications', 'trip_events',
                       'webhook_events', 'audit_logs', 'app_settings'])
