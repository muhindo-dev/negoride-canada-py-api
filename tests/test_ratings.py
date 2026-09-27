"""Ratings, reviews and tips (spec §17) + admin ratings explorer (§19.1.9)."""
import json
from datetime import datetime, timedelta

from backend.models import db
from backend.models.experience import RideRating
from backend.models.money import RidePayment
from backend.models.negotiation import Negotiation
from backend.models.platform import AuditLog
from backend.models.transaction import Transaction
from backend.models.user import AdminUser
from backend.services import ratings_service as RSV
from backend.services.payments.gateway import get_gateway
from tests.conftest import body
from tests.exp_helpers import _experience_cleanup, make_carhire, override  # noqa: F401


def rate(client, auth, user, ride_id, stars=5, **kw):
    return client.post(f'/api/rides/carhire/{ride_id}/rating', headers=auth(user), json={'stars': stars, **kw})


# ── math ────────────────────────────────────────────────────────────────────

def test_bayesian_average_math():
    assert RSV.bayesian([5, 5, 5], 4.8, 5) == (4.8 * 5 + 15) / 8
    assert RSV.bayesian([], 4.8, 5) == 4.8
    # many ratings → converges to the raw mean
    assert abs(RSV.bayesian([3] * 1000, 4.8, 5) - 3) < 0.01


def test_score_uses_rolling_window(client, auth, make_user, override):
    override['rating.window'] = 3
    driver = make_user('driver')
    for stars in (1, 1, 5, 5, 5):   # oldest first → window keeps the last three 5s
        c = make_user('customer')
        ride = make_carhire(c, driver)
        assert body(rate(client, auth, c, ride.id, stars))['code'] == 1
    db.session.rollback()
    d = db.session.get(AdminUser, driver.id)
    assert float(d.rating) == round((4.8 * 5 + 15) / 8, 2)
    assert d.rating_count == 5
    assert float(d.rating_avg_raw) == 5.0


# ── rules ───────────────────────────────────────────────────────────────────

def test_rate_visibility_duplicate_and_close(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d)
    r = rate(client, auth, c, ride.id, 4, tags=['Clean car', 'on_time'], comment='Nice')
    assert r.status_code == 201, r.get_json()
    assert body(r)['data']['rating']['tags'] == ['clean_car', 'on_time']
    assert body(r)['data']['ask_what_went_wrong'] is False

    # duplicate
    dup = rate(client, auth, c, ride.id, 5)
    assert dup.status_code == 409 and body(dup)['data']['error_code'] == 'duplicate'

    # driver sees that the customer rated, but not the rating (hidden until both / 72 h)
    st = body(client.get(f'/api/rides/carhire/{ride.id}/rating', headers=auth(d)))['data']
    assert st['other_party_rated'] is True and st['other_rating'] is None and st['can_rate'] is True

    r = rate(client, auth, d, ride.id, 5, tags=['respectful'])
    assert r.status_code == 201, r.get_json()
    st = body(client.get(f'/api/rides/carhire/{ride.id}/rating', headers=auth(d)))['data']
    assert st['other_rating']['stars'] == 4 and st['can_rate'] is False
    # customers never see an individual rating attributed to them
    st_c = body(client.get(f'/api/rides/carhire/{ride.id}/rating', headers=auth(c)))['data']
    assert st_c['other_party_rated'] is True and st_c['other_rating'] is None
    assert st_c['my_rating']['stars'] == 4

    # both rated → ride CLOSED
    db.session.rollback()
    assert db.session.get(Negotiation, ride.id).trip_stage == 'CLOSED'


def test_visible_after_72h_only(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d, completed_ago_h=71)
    assert rate(client, auth, c, ride.id, 3).status_code == 201
    st = body(client.get(f'/api/rides/carhire/{ride.id}/rating', headers=auth(d)))['data']
    assert st['other_rating'] is None
    db.session.rollback()
    row = RideRating.query.filter_by(ride_type='carhire', ride_id=ride.id, rater_id=c.id).first()
    assert row.visible_at > datetime.utcnow()
    row.visible_at = datetime.utcnow() - timedelta(seconds=1)   # the 72 h passed
    db.session.commit()
    st = body(client.get(f'/api/rides/carhire/{ride.id}/rating', headers=auth(d)))['data']
    assert st['other_rating']['stars'] == 3


def test_window_expiry_and_stage_rules(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    old = make_carhire(c, d, completed_ago_h=73)
    r = rate(client, auth, c, old.id, 5)
    assert r.status_code == 410 and body(r)['data']['error_code'] == 'rating_window_closed'

    live = make_carhire(c, d, stage='IN_PROGRESS')
    r = rate(client, auth, c, live.id, 5)
    assert r.status_code == 409 and body(r)['data']['error_code'] == 'not_completed'

    ok = make_carhire(c, d)
    assert body(rate(client, auth, c, ok.id, 6))['data']['error_code'] == 'bad_stars'
    assert body(rate(client, auth, c, ok.id, 5, tags=['Great vibes']))['data']['error_code'] == 'bad_tags'
    stranger = make_user('customer')
    assert rate(client, auth, stranger, ok.id, 5).status_code == 403
    assert body(rate(client, auth, d, ok.id, 5, tip_cents=500))['data']['error_code'] == 'tip_not_allowed'


def test_low_rating_asks_what_went_wrong(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d)
    r = body(rate(client, auth, c, ride.id, 2, tags=['unsafe_driving']))
    assert r['data']['ask_what_went_wrong'] is True
    assert r['data']['safety_report']['endpoint'] == '/api/safety/reports'


def test_tip_checkout_credits_100_percent_to_driver(client, auth, make_user, sign_stripe):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d)
    r = rate(client, auth, c, ride.id, 5, tip_cents=350)
    assert r.status_code == 201, r.get_json()
    tip = body(r)['data']['tip']
    assert tip['checkout_url'] and tip['amount_cents'] == 350
    rp = db.session.get(RidePayment, tip['ride_payment_id'])
    assert rp.purpose == 'tip' and rp.driver_id == d.id and rp.capture_method == 'automatic'

    event = get_gateway().simulate_customer_pays(rp.checkout_session_id)
    payload = json.dumps(event)
    w = client.post('/api/webhooks/stripe', data=payload, content_type='application/json',
                    headers={'Stripe-Signature': sign_stripe(payload)})
    assert w.status_code == 200
    db.session.rollback()
    tx = Transaction.query.filter_by(user_id=d.id, category='tip').all()
    assert len(tx) == 1 and float(tx[0].amount) == 3.50
    row = RideRating.query.filter_by(ride_type='carhire', ride_id=ride.id, rater_id=c.id).first()
    assert row.tip_payment_id == rp.id and row.tip_cents == 350


def test_profile_card_first_name_only(client, auth, make_user):
    c, d = make_user('customer'), make_user('driver')
    ride = make_carhire(c, d)
    rate(client, auth, c, ride.id, 5, tags=['clean_car', 'safe_driving'])
    card = body(client.get(f'/api/drivers/{d.id}/profile-card', headers=auth(c)))['data']
    assert card['first_name'] == d.first_name and 'last_name' not in card and 'phone_number' not in card
    assert card['total_trips'] >= 1 and card['rating_count'] == 1
    assert {t['key'] for t in card['top_compliments']} == {'clean_car', 'safe_driving'}
    assert card['badges']['verified'] is True and card['badges']['background_checked'] is False
    assert client.get(f'/api/drivers/{c.id}/profile-card', headers=auth(c)).status_code == 404
    tags = body(client.get('/api/ratings/tags', headers=auth(c)))['data']
    assert any(t['key'] == 'price_changed' for t in tags['customer']['negative'])


# ── admin ───────────────────────────────────────────────────────────────────

def test_admin_hide_rating_recomputes_and_audits(client, auth, make_user):
    admin, d = make_user('admin'), make_user('driver')
    c1, c2 = make_user('customer'), make_user('customer')
    r1, r2 = make_carhire(c1, d), make_carhire(c2, d)
    rate(client, auth, c1, r1.id, 1, comment='abusive words')
    rate(client, auth, c2, r2.id, 5)
    db.session.rollback()
    before = float(db.session.get(AdminUser, d.id).rating)
    assert before == round((4.8 * 5 + 6) / 7, 2)
    bad = RideRating.query.filter_by(ride_type='carhire', ride_id=r1.id).first()

    assert client.post(f'/api/admin/ratings/{bad.id}/hide', headers=auth(c1), json={'reason': 'abusive'}).status_code == 403
    r = client.post(f'/api/admin/ratings/{bad.id}/hide', headers=auth(admin), json={'reason': ''})
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/ratings/{bad.id}/hide', headers=auth(admin), json={'reason': 'Abusive comment'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    d2 = db.session.get(AdminUser, d.id)
    assert float(d2.rating) == round((4.8 * 5 + 5) / 6, 2) and d2.rating_count == 1
    assert AuditLog.query.filter_by(action='rating.hidden', entity_id=str(bad.id)).count() == 1

    lst = body(client.get(f'/api/admin/ratings?driver_id={d.id}&hidden=1', headers=auth(admin)))['data']
    assert lst['total'] == 1 and lst['items'][0]['hidden_reason'] == 'Abusive comment'
    low = body(client.get('/api/admin/ratings/lowest-drivers?min_count=1&limit=500', headers=auth(admin)))['data']
    assert any(x['driver_id'] == d.id for x in low['drivers'])


def test_admin_trend_alerts(client, auth, make_user):
    admin, d, c = make_user('admin'), make_user('driver'), make_user('customer')
    now = datetime.utcnow()
    rows = [(20, 5)] * 4 + [(2, 3)] * 3      # (days ago, stars): 5.0 before → 3.0 last week
    for i, (ago, stars) in enumerate(rows):
        db.session.add(RideRating(ride_type='carhire', ride_id=900000000 + d.id * 10 + i, rater_id=c.id,
                                  ratee_id=d.id, role='customer', stars=stars, tags=[],
                                  created_at=now - timedelta(days=ago)))
    db.session.commit()
    alerts = body(client.get('/api/admin/ratings/trend-alerts', headers=auth(admin)))['data']['alerts']
    mine = [a for a in alerts if a['driver_id'] == d.id]
    assert mine and mine[0]['drop'] == 2.0 and mine[0]['recent_count'] == 3
