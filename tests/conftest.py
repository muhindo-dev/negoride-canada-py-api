"""Test harness for the v4 backend.

Runs against the local MySQL `negoride` database (same as production schema).
Everything a test creates belongs to throw-away users (username prefix
`v4test_`) and is deleted at the end of the session.

External providers are never called:
  JOB_MODE=eager            jobs run synchronously
  PAYMENTS_GATEWAY=fake     in-memory Stripe simulation
  EMAIL_PROVIDER=memory     emails captured in email_provider.OUTBOX
  NOTIFY_PUSH_DRY_RUN=1     OneSignal payloads captured in channels.PUSH_LOG
  TWILIO_* unset            SMS captured in twilio_client.SENT
"""
import hashlib
import hmac
import json
import os
import time
import uuid

os.environ['JOB_MODE'] = 'eager'
os.environ['PAYMENTS_GATEWAY'] = 'fake'
os.environ['EMAIL_PROVIDER'] = 'memory'
os.environ['NOTIFY_PUSH_DRY_RUN'] = '1'
os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_test_v4'
os.environ['FLASK_ENV'] = 'testing'
os.environ['RUN_SCHEDULER'] = '0'
for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'REDIS_URL', 'CERTN_API_KEY', 'GOOGLE_MAPS_SERVER_KEY'):
    os.environ[k] = ''

import pytest  # noqa: E402

from backend import jobs  # noqa: E402
jobs.set_mode('eager')

from backend.app import app as flask_app  # noqa: E402
from backend.models import db  # noqa: E402
from backend.models.user import AdminUser  # noqa: E402
from backend.services import realtime  # noqa: E402
from backend.services.payments.gateway import FakeGateway, set_gateway  # noqa: E402

realtime.RECORD = True

# Tables with a user/ride reference that tests may populate: (table, column)
_USER_TABLES = [
    ('notification_deliveries', None), ('notifications', 'user_id'), ('notification_preferences', 'user_id'),
    ('device_tokens', 'user_id'), ('idempotency_keys', 'user_id'), ('ride_payments', 'customer_id'),
    ('refunds', 'customer_id'), ('receipts', 'customer_id'), ('credit_notes', 'customer_id'),
    ('driver_strikes', 'driver_id'), ('safety_incidents', 'user_id'), ('trusted_contacts', 'user_id'),
    ('safety_reports', 'reporter_id'), ('safety_settings', 'user_id'), ('safety_checks', 'user_id'),
    ('ride_locations', 'user_id'), ('ride_share_links', 'user_id'), ('recordings', 'user_id'),
    ('phone_verifications', 'user_id'), ('user_devices', 'user_id'), ('legal_acceptances', 'user_id'),
    ('driver_documents', 'user_id'), ('background_checks', 'user_id'), ('driver_applications', 'user_id'),
    ('support_tickets', 'user_id'), ('ride_ratings', 'rater_id'), ('favourite_drivers', 'customer_id'),
    ('referrals', 'referrer_id'), ('analytics_events', 'user_id'), ('transactions', 'user_id'),
    ('user_wallets', 'user_id'), ('audit_logs', 'actor_id'), ('marketing_consents', 'user_id'),
    ('live_activity_tokens', 'user_id'), ('tip_receipts', 'customer_id'),
]


def _cleanup(user_ids):
    if not user_ids:
        return
    ids = ','.join(str(int(i)) for i in user_ids)
    conn = db.session.connection()
    ex = lambda sql: conn.exec_driver_sql(sql)  # noqa: E731
    neg = f"SELECT id FROM negotiations WHERE customer_id IN ({ids}) OR driver_id IN ({ids})"
    sched = f"SELECT id FROM scheduled_bookings WHERE customer_id IN ({ids}) OR driver_id IN ({ids})"
    trips = f"SELECT id FROM trips WHERE driver_id IN ({ids})"
    books = f"SELECT id FROM trip_bookings WHERE customer_id IN ({ids}) OR driver_id IN ({ids}) OR trip_id IN ({trips})"
    for rt, sub in (('carhire', neg), ('scheduled', sched), ('rideshare_trip', trips), ('rideshare_booking', books)):
        for table in ('trip_events', 'ride_payments', 'refunds', 'receipts', 'ride_locations', 'ride_share_links',
                      'ride_ratings', 'safety_checks', 'ride_routes', 'ride_pin_failures'):
            ex(f"DELETE FROM {table} WHERE ride_type='{rt}' AND ride_id IN (SELECT id FROM ({sub}) x)")
    ex(f"DELETE FROM payments WHERE negotiation_id IN (SELECT id FROM ({neg}) x)")
    ex(f"DELETE FROM negotiation_records WHERE negotiation_id IN (SELECT id FROM ({neg}) x)")
    ex(f"DELETE FROM negotiations WHERE customer_id IN ({ids}) OR driver_id IN ({ids})")
    ex(f"DELETE FROM scheduled_bookings WHERE customer_id IN ({ids}) OR driver_id IN ({ids})")
    ex(f"DELETE FROM trip_bookings WHERE customer_id IN ({ids}) OR driver_id IN ({ids}) OR trip_id IN (SELECT id FROM ({trips}) x)")
    ex(f"DELETE FROM trips WHERE driver_id IN ({ids})")
    ex(f"DELETE FROM notification_deliveries WHERE notification_id IN (SELECT id FROM (SELECT id FROM notifications WHERE user_id IN ({ids})) x)")
    ex(f"DELETE FROM safety_incident_locations WHERE incident_id IN (SELECT id FROM (SELECT id FROM safety_incidents WHERE user_id IN ({ids})) x)")
    ex(f"DELETE FROM recording_chunks WHERE recording_id IN (SELECT id FROM (SELECT id FROM recordings WHERE user_id IN ({ids})) x)")
    ex(f"DELETE FROM support_ticket_messages WHERE ticket_id IN (SELECT id FROM (SELECT id FROM support_tickets WHERE user_id IN ({ids})) x)")
    for table, col in _USER_TABLES:
        if col:
            ex(f"DELETE FROM {table} WHERE {col} IN ({ids})")
    ex(f"DELETE FROM ride_ratings WHERE ratee_id IN ({ids})")
    ex(f"DELETE FROM favourite_drivers WHERE driver_id IN ({ids})")
    ex(f"DELETE FROM payout_requests WHERE user_id IN ({ids})")
    ex(f"DELETE FROM admin_users WHERE id IN ({ids})")
    db.session.commit()


@pytest.fixture(scope='session')
def app():
    ctx = flask_app.app_context()
    ctx.push()
    yield flask_app
    ctx.pop()


@pytest.fixture(scope='session')
def _created_users(app):
    created = []
    yield created
    db.session.rollback()
    _cleanup(created)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _fresh(app):
    set_gateway(FakeGateway())
    FakeGateway.reset()
    realtime.SENT.clear()
    jobs.set_mode('eager')
    from backend.services import settings_service as S
    S.invalidate()
    yield
    db.session.rollback()
    db.session.remove()


@pytest.fixture()
def make_user(app, _created_users):
    def _make(role='customer', **overrides):
        tag = uuid.uuid4().hex[:10]
        u = AdminUser(username=f'v4test_{role}_{tag}', name=f'V4 {role.title()} {tag[:4]}',
                      first_name=f'{role.title()}{tag[:3]}', last_name='Test',
                      email=f'v4test_{role}_{tag}@negoride.test', phone_number=f'+1416555{int(tag[:4], 16) % 10000:04d}',
                      user_type={'customer': 'Customer', 'driver': 'Driver', 'admin': 'Admin'}[role], status=1,
                      max_passengers=4, rating=0)
        u.set_password('Test1234!')
        if role == 'driver':
            u.is_car = 'Yes'
            u.is_car_approved = 'Yes'
            u.ready_for_trip = 'Yes'
            u.current_latitude, u.current_longitude = 43.6532, -79.3832
        for k, v in overrides.items():
            setattr(u, k, v)
        db.session.add(u)
        db.session.commit()
        _created_users.append(u.id)
        return u
    return _make


@pytest.fixture()
def auth():
    from backend.utils.auth import issue_token

    def _h(user, **extra):
        h = {'Authorization': f'Bearer {issue_token(user)}'}
        h.update(extra)
        return h
    return _h


def stripe_signature(payload, secret='whsec_test_v4'):
    t = int(time.time())
    sig = hmac.new(secret.encode(), f'{t}.{payload}'.encode(), hashlib.sha256).hexdigest()
    return f't={t},v1={sig}'


@pytest.fixture()
def sign_stripe():
    return stripe_signature


def body(resp):
    return resp.get_json() or {}
