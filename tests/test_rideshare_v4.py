"""Rideshare self-booking (spec §18.1): search, book, request-to-book,
negotiation bounds, last-seat race, manifest, departure reminders."""
import threading
from datetime import datetime, timedelta

from backend.models import db
from backend.models.notification import Notification
from backend.models.trip import Trip
from backend.models.trip_booking import TripBooking
from backend.services import experience_jobs, ride_jobs
from tests.conftest import body
from tests.exp_helpers import _experience_cleanup, make_trip  # noqa: F401

TORONTO = (43.6532, -79.3832)
OTTAWA = (45.4215, -75.6972)


def search(client, auth, user, **params):
    q = {'from_lat': TORONTO[0] + 0.01, 'from_lng': TORONTO[1], 'to_lat': OTTAWA[0], 'to_lng': OTTAWA[1] + 0.01}
    q.update(params)
    return client.get('/api/rideshare/search', headers=auth(user), query_string=q)


def book(client, auth, user, trip_id, **data):
    return client.post(f'/api/rideshare/trips/{trip_id}/book', headers=auth(user), json={'seats': 1, **data})


def test_search_cards_and_filters(client, auth, make_user):
    d, c = make_user('driver'), make_user('customer')
    trip = make_trip(d, slots=2, pets_ok=True, luggage_size='medium')
    r = body(search(client, auth, c))
    card = next(t for t in r['data']['trips'] if t['trip_id'] == trip.id)
    assert card['seats_left'] == 2 and card['price_per_seat_cents'] == 2500
    assert card['driver']['first_name'] == d.first_name and 'phone_number' not in card['driver']
    assert card['badges'] == {'verified': True, 'background_checked': False, 'pets_ok': True, 'luggage_size': 'medium'}
    assert card['negotiation']['allowed'] is True and card['booking_mode'] == 'instant'
    assert card['car']['model'] == 'Toyota Corolla'

    # wrong direction / too many seats / other day → not listed
    rev = body(client.get('/api/rideshare/search', headers=auth(c), query_string={
        'from_lat': OTTAWA[0], 'from_lng': OTTAWA[1], 'to_lat': TORONTO[0], 'to_lng': TORONTO[1]}))
    assert all(t['trip_id'] != trip.id for t in rev['data']['trips'])
    assert all(t['trip_id'] != trip.id for t in body(search(client, auth, c, seats=3))['data']['trips'])
    other_day = (datetime.utcnow() + timedelta(days=5)).strftime('%Y-%m-%d')
    assert all(t['trip_id'] != trip.id for t in body(search(client, auth, c, date=other_day))['data']['trips'])
    # driver doesn't see their own trip
    assert all(t['trip_id'] != trip.id for t in body(search(client, auth, d))['data']['trips'])

    detail = body(client.get(f'/api/rideshare/trips/{trip.id}', headers=auth(c)))['data']
    assert detail['is_bookable'] is True and detail['my_booking'] is None


def test_instant_book_then_pay_next(client, auth, make_user):
    d, c = make_user('driver'), make_user('customer')
    trip = make_trip(d)
    r = book(client, auth, c, trip.id, seats=2, pickup={'lat': 43.66, 'lng': -79.39, 'address': 'Bloor St'},
             note='Small bag')
    assert r.status_code == 201, r.get_json()
    data = body(r)['data']
    assert data['booking']['stage'] == 'PENDING_PAYMENT' and data['booking']['total_cents'] == 5000
    assert data['next_action']['action'] == 'pay'
    assert data['next_action']['endpoint'].endswith(f"/rideshare_booking/{data['booking']['id']}/pay")
    again = book(client, auth, c, trip.id)
    assert again.status_code == 409 and body(again)['data']['error_code'] == 'duplicate'
    mine = body(client.get('/api/rideshare/my-bookings?scope=upcoming', headers=auth(c)))['data']
    assert mine['total'] == 1 and mine['items'][0]['trip']['trip_id'] == trip.id


def test_request_to_book_approve_decline_timeout(client, auth, make_user):
    d = make_user('driver')
    trip = make_trip(d)
    r = client.put(f'/api/rideshare/trips/{trip.id}/settings', headers=auth(d),
                   json={'booking_mode': 'request', 'pets_ok': True, 'luggage_size': 'small'})
    assert body(r)['code'] == 1 and body(r)['data']['booking_mode'] == 'request'
    stranger = make_user('driver')
    assert client.put(f'/api/rideshare/trips/{trip.id}/settings', headers=auth(stranger),
                      json={'pets_ok': False}).status_code == 403
    bad = client.put(f'/api/rideshare/trips/{trip.id}/settings', headers=auth(d), json={'luggage_size': 'huge'})
    assert body(bad)['data']['error_code'] == 'bad_luggage'

    c1, c2, c3 = make_user('customer'), make_user('customer'), make_user('customer')
    b1 = body(book(client, auth, c1, trip.id))['data']
    assert b1['booking']['stage'] == 'REQUESTED' and b1['next_action']['action'] == 'wait_for_approval'
    assert Notification.query.filter_by(user_id=d.id, event_key='rideshare.booking_requested').count() == 1
    b2 = body(book(client, auth, c2, trip.id))['data']
    b3 = body(book(client, auth, c3, trip.id))['data']

    # only the driver can respond
    assert client.post(f"/api/rideshare/bookings/{b1['booking']['id']}/respond", headers=auth(c1),
                       json={'approve': True}).status_code == 403
    ok = body(client.post(f"/api/rideshare/bookings/{b1['booking']['id']}/respond", headers=auth(d),
                          json={'approve': True}))
    assert ok['code'] == 1 and ok['data']['booking']['stage'] == 'PENDING_PAYMENT'
    no = body(client.post(f"/api/rideshare/bookings/{b2['booking']['id']}/respond", headers=auth(d),
                          json={'approve': False, 'reason': 'Car full of luggage'}))
    assert no['code'] == 1 and no['data']['booking']['stage'] == 'DECLINED'
    twice = client.post(f"/api/rideshare/bookings/{b2['booking']['id']}/respond", headers=auth(d),
                        json={'approve': True})
    assert twice.status_code == 409

    # unanswered request → auto-declined (EXPIRED, seat released) by the lifecycle job
    db.session.rollback()
    row = db.session.get(TripBooking, b3['booking']['id'])
    row.request_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    ride_jobs.tick_lifecycle()
    db.session.rollback()
    assert db.session.get(TripBooking, b3['booking']['id']).trip_stage == 'EXPIRED'


def test_seat_negotiation_bounds(client, auth, make_user):
    d, c = make_user('driver'), make_user('customer')
    trip = make_trip(d, min_seat_price_cents=2000)
    low = book(client, auth, c, trip.id, offered_price_per_seat_cents=1500)
    assert body(low)['data']['error_code'] == 'offer_out_of_bounds'
    high = book(client, auth, c, trip.id, offered_price_per_seat_cents=2600)
    assert body(high)['data']['error_code'] == 'offer_out_of_bounds'
    ok = body(book(client, auth, c, trip.id, offered_price_per_seat_cents=2200))['data']['booking']
    assert ok['stage'] == 'REQUESTED' and ok['total_cents'] == 2200     # negotiated → driver approves

    fixed = make_trip(d, allow_seat_negotiation=False)
    c2 = make_user('customer')
    r = book(client, auth, c2, fixed.id, offered_price_per_seat_cents=2200)
    assert body(r)['data']['error_code'] == 'no_negotiation'


def test_last_seat_race_exactly_one_wins(app, client, auth, make_user):
    d = make_user('driver')
    trip = make_trip(d, slots=1)
    trip_id = trip.id
    customers = [make_user('customer') for _ in range(2)]
    headers = [auth(c) for c in customers]
    barrier = threading.Barrier(2)
    results = [None, None]

    def worker(i):
        with app.test_client() as tc:
            barrier.wait()
            r = tc.post(f'/api/rideshare/trips/{trip_id}/book', headers=headers[i], json={'seats': 1})
            results[i] = (r.status_code, (r.get_json() or {}).get('data') or {})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    codes = sorted(r[0] for r in results)
    assert codes == [201, 409], results
    loser = next(r for r in results if r[0] == 409)
    assert loser[1]['error_code'] == 'sold_out'
    db.session.rollback()
    assert TripBooking.query.filter_by(trip_id=trip_id).count() == 1


def test_manifest_and_departure_reminder(client, auth, make_user):
    d, c1, c2 = make_user('driver'), make_user('customer'), make_user('customer')
    trip = make_trip(d, depart_in=timedelta(minutes=30))
    for c in (c1, c2):
        assert book(client, auth, c, trip.id).status_code == 201
    db.session.rollback()
    first = TripBooking.query.filter_by(trip_id=trip.id, customer_id=c1.id).one()
    first.trip_stage = 'CONFIRMED'     # (payment flow covered elsewhere)
    db.session.commit()

    m = body(client.get(f'/api/rideshare/trips/{trip.id}/manifest', headers=auth(d)))['data']
    assert [p['pickup_order'] for p in m['passengers']] == sorted(p['pickup_order'] for p in m['passengers'])
    p1 = next(p for p in m['passengers'] if p['booking_id'] == first.id)
    acts = {a['action']: a['endpoint'] for a in p1['actions']}
    assert acts['arrived'] == f'/api/rides/rideshare_booking/{first.id}/arrived'
    assert 'start' in acts and 'no-show' not in acts        # no-show only after departure
    assert 'phone_number' not in p1['customer']
    assert client.get(f'/api/rideshare/trips/{trip.id}/manifest', headers=auth(c1)).status_code == 403

    sent = experience_jobs.departure_reminders(datetime.utcnow())
    assert sent >= 1
    assert Notification.query.filter_by(user_id=c1.id, event_key='rideshare.departure_reminder').count() == 1
    assert Notification.query.filter_by(user_id=d.id, event_key='rideshare.departure_reminder').count() == 1
    # unpaid passenger is not reminded; second run sends nothing new
    assert Notification.query.filter_by(user_id=c2.id, event_key='rideshare.departure_reminder').count() == 0
    experience_jobs.departure_reminders(datetime.utcnow())
    assert Notification.query.filter_by(user_id=c1.id, event_key='rideshare.departure_reminder').count() == 1
    db.session.rollback()
    assert db.session.get(Trip, trip.id) is not None
