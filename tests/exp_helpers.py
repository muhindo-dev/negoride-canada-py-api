"""Shared helpers for the experience tests (ETA, ratings, rideshare v4, car hire v4)."""
from datetime import datetime, timedelta

import pytest

from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.trip import Trip
from backend.services import settings_service as S


@pytest.fixture()
def override(monkeypatch):
    """Override settings for one test: override['ride.x'] = 5 (no DB writes)."""
    vals = {}
    orig = S.get

    def fake(key, default=None):
        k = S._normalize_key(key)
        if k in vals:
            return vals[k]
        return orig(key, default)
    monkeypatch.setattr(S, 'get', fake)
    return vals


def cleanup_experience_rows(user_ids):
    if not user_ids:
        return
    db.session.rollback()
    ids = ','.join(str(int(i)) for i in user_ids)
    conn = db.session.connection()
    conn.exec_driver_sql(
        f"DELETE FROM ride_request_offers WHERE driver_id IN ({ids}) OR request_id IN "
        f"(SELECT id FROM (SELECT id FROM ride_requests WHERE customer_id IN ({ids})) x)")
    conn.exec_driver_sql(f"DELETE FROM ride_requests WHERE customer_id IN ({ids})")
    conn.exec_driver_sql(
        f"DELETE FROM experience_marks WHERE ref_type='rideshare_trip' AND ref_id IN "
        f"(SELECT id FROM (SELECT id FROM trips WHERE driver_id IN ({ids})) x)")
    conn.exec_driver_sql(f"DELETE FROM favourite_drivers WHERE customer_id IN ({ids}) OR driver_id IN ({ids})")
    db.session.commit()


@pytest.fixture(scope='module', autouse=True)
def _experience_cleanup(_created_users):
    yield
    cleanup_experience_rows(list(_created_users))


def make_carhire(customer, driver, stage='COMPLETED', pickup=(43.6532, -79.3832), dropoff=(43.6426, -79.3871),
                 completed_ago_h=0.1, price_cents=2500, **extra):
    now = datetime.utcnow()
    n = Negotiation(customer_id=customer.id, customer_name=customer.name, driver_id=driver.id,
                    driver_name=driver.name, pickup_lat=str(pickup[0]), pickup_lng=str(pickup[1]),
                    pickup_address='Pickup', dropoff_lat=str(dropoff[0]), dropoff_lng=str(dropoff[1]),
                    dropoff_address='Dropoff', initial_price=price_cents, agreed_price=price_cents,
                    agreed_price_cents=price_cents, status='Completed' if stage == 'COMPLETED' else 'Started',
                    is_active='No', trip_stage=stage, stage_changed_at=now, service_type='car')
    if stage in ('COMPLETED', 'CLOSED'):
        n.completed_at = now - timedelta(hours=completed_ago_h)
        n.stage_changed_at = n.completed_at
    for k, v in extra.items():
        setattr(n, k, v)
    db.session.add(n)
    db.session.commit()
    return n


def make_trip(driver, slots=3, price_cents=2500, depart_in=timedelta(days=1), start=(43.6532, -79.3832),
              end=(45.4215, -75.6972), **extra):
    t = Trip(driver_id=driver.id, start_name='Toronto', end_name='Ottawa',
             start_gps=f'{start[0]},{start[1]}', end_pgs=f'{end[0]},{end[1]}',
             start_address='Union Station, Toronto', end_address='Rideau Centre, Ottawa',
             slots=slots, price=price_cents // 100, price_per_seat_cents=price_cents, status='Active',
             trip_stage='PUBLISHED', stage_changed_at=datetime.utcnow(),
             departure_at=datetime.utcnow() + depart_in, booking_mode='instant', allow_seat_negotiation=True,
             car_model='Toyota Corolla')
    for k, v in extra.items():
        setattr(t, k, v)
    db.session.add(t)
    db.session.commit()
    return t
