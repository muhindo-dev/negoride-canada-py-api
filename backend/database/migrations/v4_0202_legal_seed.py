"""
v4 · Seed the published v1.0 legal documents in English and French (spec §12):
terms, privacy, community_guidelines, driver_agreement, cancellation_policy,
safety_policy, recording_notice, background_check_consent.

Content lives in backend/services/legal_content.py. Numbers (fees, windows,
retention days…) are Jinja placeholders rendered from app_settings at read
time. Rows that already exist (same type + version + language) are left
untouched, so edits made in the admin Legal editor are never overwritten.
"""
from datetime import datetime


def up(conn):
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from backend.services.legal_service import seed_rows
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with conn.cursor() as cur:
        for doc_type, version, lang, title, summary, body, audience in seed_rows():
            cur.execute("SELECT id FROM legal_documents WHERE type=%s AND version=%s AND language=%s",
                        (doc_type, version, lang))
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO legal_documents (type, version, title, summary_markdown, what_changed, body_markdown, "
                "language, audience, status, requires_reacceptance, effective_at, published_at, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,'published',0,%s,%s,%s,%s)",
                (doc_type, version, title, summary, body, lang, audience, now, now, now, now))
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM legal_documents WHERE version='1.0' AND published_by IS NULL "
                    "AND id NOT IN (SELECT document_id FROM (SELECT DISTINCT document_id FROM legal_acceptances) x)")
    conn.commit()
