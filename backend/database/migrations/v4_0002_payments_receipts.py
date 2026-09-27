"""
v4 · P2 Money & trust (spec §6, §7, §13)

All new money columns are INTEGER CENTS, CAD.
Tables: ride_payments, refunds, receipts, credit_notes, document_sequences,
tax_rates, driver_strikes.
"""
from backend.database.schema_helpers import create_tables, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE ride_payments (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        customer_id INT NOT NULL,
        driver_id INT NULL,
        purpose VARCHAR(30) NOT NULL DEFAULT 'ride',
        provider VARCHAR(20) NOT NULL DEFAULT 'stripe',
        checkout_session_id VARCHAR(191) NULL,
        checkout_url TEXT NULL,
        intent_id VARCHAR(191) NULL,
        capture_method VARCHAR(20) NOT NULL DEFAULT 'manual',
        currency CHAR(3) NOT NULL DEFAULT 'cad',
        fare_cents BIGINT NOT NULL DEFAULT 0,
        fees_cents BIGINT NOT NULL DEFAULT 0,
        tax_cents BIGINT NOT NULL DEFAULT 0,
        amount_authorized_cents BIGINT NOT NULL DEFAULT 0,
        amount_captured_cents BIGINT NOT NULL DEFAULT 0,
        amount_refunded_cents BIGINT NOT NULL DEFAULT 0,
        tip_cents BIGINT NOT NULL DEFAULT 0,
        capture_status VARCHAR(30) NOT NULL DEFAULT 'pending',
        payment_method_brand VARCHAR(30) NULL,
        payment_method_last4 VARCHAR(4) NULL,
        authorized_at DATETIME NULL,
        auth_expires_at DATETIME NULL,
        captured_at DATETIME NULL,
        canceled_at DATETIME NULL,
        failure_reason TEXT NULL,
        idempotency_key VARCHAR(120) NULL,
        meta JSON NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_ride_payments_intent (intent_id),
        UNIQUE KEY uq_ride_payments_session (checkout_session_id),
        KEY ix_ride_payments_ride (ride_type, ride_id),
        KEY ix_ride_payments_status (capture_status)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE refunds (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_payment_id BIGINT NOT NULL,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        customer_id INT NOT NULL,
        amount_cents BIGINT NOT NULL,
        kind VARCHAR(20) NOT NULL DEFAULT 'refund',
        rule_id VARCHAR(60) NULL,
        reason TEXT NULL,
        provider_refund_id VARCHAR(191) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        initiated_by INT NULL,
        initiated_by_type VARCHAR(20) NOT NULL DEFAULT 'system',
        idempotency_key VARCHAR(160) NOT NULL,
        credit_note_id BIGINT NULL,
        created_at DATETIME NOT NULL,
        processed_at DATETIME NULL,
        UNIQUE KEY uq_refunds_idem (idempotency_key),
        KEY ix_refunds_ride (ride_type, ride_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE document_sequences (
        id INT AUTO_INCREMENT PRIMARY KEY,
        doc_type VARCHAR(20) NOT NULL,
        year INT NOT NULL,
        last_value INT NOT NULL DEFAULT 0,
        UNIQUE KEY uq_docseq (doc_type, year)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE receipts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        number VARCHAR(30) NOT NULL,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        ride_payment_id BIGINT NULL,
        customer_id INT NOT NULL,
        driver_id INT NULL,
        currency CHAR(3) NOT NULL DEFAULT 'cad',
        total_cents BIGINT NOT NULL DEFAULT 0,
        totals JSON NOT NULL,
        pdf_path VARCHAR(500) NULL,
        emailed_at DATETIME NULL,
        email_count INT NOT NULL DEFAULT 0,
        issued_at DATETIME NOT NULL,
        voided_at DATETIME NULL,
        UNIQUE KEY uq_receipts_number (number),
        UNIQUE KEY uq_receipts_ride (ride_type, ride_id),
        KEY ix_receipts_customer (customer_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE credit_notes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        number VARCHAR(30) NOT NULL,
        receipt_id BIGINT NOT NULL,
        refund_id BIGINT NULL,
        customer_id INT NOT NULL,
        amount_cents BIGINT NOT NULL,
        tax_cents BIGINT NOT NULL DEFAULT 0,
        reason TEXT NULL,
        totals JSON NULL,
        pdf_path VARCHAR(500) NULL,
        emailed_at DATETIME NULL,
        issued_at DATETIME NOT NULL,
        UNIQUE KEY uq_credit_notes_number (number),
        UNIQUE KEY uq_credit_notes_refund (refund_id),
        KEY ix_credit_notes_receipt (receipt_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE tax_rates (
        id INT AUTO_INCREMENT PRIMARY KEY,
        province CHAR(2) NOT NULL,
        name VARCHAR(60) NOT NULL,
        gst_bp INT NOT NULL DEFAULT 0,
        pst_bp INT NOT NULL DEFAULT 0,
        hst_bp INT NOT NULL DEFAULT 0,
        qst_bp INT NOT NULL DEFAULT 0,
        effective_from DATE NOT NULL,
        effective_to DATE NULL,
        UNIQUE KEY uq_tax_rates (province, effective_from)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE driver_strikes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        driver_id INT NOT NULL,
        reason VARCHAR(40) NOT NULL,
        ride_type VARCHAR(30) NULL,
        ride_id BIGINT NULL,
        note VARCHAR(500) NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_strike_ride (driver_id, reason, ride_type, ride_id),
        KEY ix_strikes_driver (driver_id, created_at)
    ) {TABLE_OPTS}""",
]

# Rates in basis points (1 bp = 0.01 %). Seeded defaults as of 2026 —
# [CONFIRM WITH CLIENT's accountant]; editable in the admin.
TAX_SEED = [
    ('AB', 'Alberta', 500, 0, 0, 0), ('BC', 'British Columbia', 500, 0, 0, 0),
    ('MB', 'Manitoba', 500, 0, 0, 0), ('NB', 'New Brunswick', 0, 0, 1500, 0),
    ('NL', 'Newfoundland and Labrador', 0, 0, 1500, 0),
    ('NS', 'Nova Scotia', 0, 0, 1400, 0), ('NT', 'Northwest Territories', 500, 0, 0, 0),
    ('NU', 'Nunavut', 500, 0, 0, 0), ('ON', 'Ontario', 0, 0, 1300, 0),
    ('PE', 'Prince Edward Island', 0, 0, 1500, 0), ('QC', 'Quebec', 500, 0, 0, 998),
    ('SK', 'Saskatchewan', 500, 0, 0, 0), ('YT', 'Yukon', 500, 0, 0, 0),
]


def up(conn):
    create_tables(conn, TABLES)
    with conn.cursor() as cur:
        for prov, name, gst, pst, hst, qst in TAX_SEED:
            cur.execute(
                "INSERT IGNORE INTO tax_rates (province, name, gst_bp, pst_bp, hst_bp, qst_bp, effective_from)"
                " VALUES (%s,%s,%s,%s,%s,%s,'2025-04-01')", (prov, name, gst, pst, hst, qst))
    conn.commit()


def down(conn):
    drop_tables(conn, ['driver_strikes', 'tax_rates', 'credit_notes', 'receipts',
                       'document_sequences', 'refunds', 'ride_payments'])
