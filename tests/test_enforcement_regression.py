import io
import unittest
from datetime import datetime, timedelta

from flask_jwt_extended import create_access_token

from backend.app import create_app
from backend.models import db
from backend.models.negotiation import Negotiation
from backend.models.negotiation_record import NegotiationRecord
from backend.models.scheduled_booking import ScheduledBooking


class EnforcementRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        self.token = create_access_token(identity="1")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.created_booking_ids = []
        self.created_negotiation_ids = []

    def tearDown(self):
        if self.created_booking_ids:
            ScheduledBooking.query.filter(
                ScheduledBooking.id.in_(self.created_booking_ids)
            ).delete(synchronize_session=False)

        if self.created_negotiation_ids:
            NegotiationRecord.query.filter(
                NegotiationRecord.negotiation_id.in_(self.created_negotiation_ids)
            ).delete(synchronize_session=False)
            Negotiation.query.filter(
                Negotiation.id.in_(self.created_negotiation_ids)
            ).delete(synchronize_session=False)

        db.session.commit()

    def test_courier_guidelines_and_sequence_and_proof_enforcement(self):
        bad_resp = self.client.post(
            "/api/bookings/courier-batch",
            json={
                "service_type": "courier",
                "community_guidelines_accepted": False,
                "pickup_lat": 0.3476,
                "pickup_lng": 32.5825,
                "pickup_address": "Kampala",
                "scheduled_at": "2026-04-18 10:00:00",
                "parcels": [
                    {
                        "destination_lat": 0.31,
                        "destination_lng": 32.58,
                        "destination_address": "Stop A",
                        "customer_proposed_price": 1500,
                    }
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(bad_resp.status_code, 400)

        ok_resp = self.client.post(
            "/api/bookings/courier-batch",
            json={
                "service_type": "courier",
                "community_guidelines_accepted": True,
                "pickup_lat": 0.3476,
                "pickup_lng": 32.5825,
                "pickup_address": "Kampala",
                "scheduled_at": "2026-04-18 10:00:00",
                "parcels": [
                    {
                        "destination_lat": 0.31,
                        "destination_lng": 32.58,
                        "destination_address": "Stop A",
                        "customer_proposed_price": 1500,
                    },
                    {
                        "destination_lat": 0.30,
                        "destination_lng": 32.57,
                        "destination_address": "Stop B",
                        "customer_proposed_price": 2000,
                    },
                ],
            },
            headers=self.headers,
        )
        self.assertEqual(ok_resp.status_code, 201)

        payload = ok_resp.get_json() or {}
        bookings = (((payload.get("data") or {}).get("bookings")) or [])
        self.assertEqual(len(bookings), 2)

        first_id = bookings[0]["id"]
        second_id = bookings[1]["id"]
        self.created_booking_ids.extend([first_id, second_id])

        first = db.session.get(ScheduledBooking, first_id)
        second = db.session.get(ScheduledBooking, second_id)
        first.status = "confirmed"
        second.status = "confirmed"
        db.session.commit()

        start_second = self.client.post(
            f"/api/bookings/{second_id}/start", headers=self.headers
        )
        self.assertEqual(start_second.status_code, 409)

        start_first = self.client.post(
            f"/api/bookings/{first_id}/start", headers=self.headers
        )
        self.assertEqual(start_first.status_code, 200)

        complete_without_proofs = self.client.post(
            f"/api/bookings/{first_id}/complete", headers=self.headers
        )
        self.assertEqual(complete_without_proofs.status_code, 400)

        pickup_resp = self.client.post(
            f"/api/bookings/{first_id}/pickup-proof",
            data={"photo": (io.BytesIO(b"fakejpeg1"), "pickup.jpg")},
            content_type="multipart/form-data",
            headers=self.headers,
        )
        self.assertEqual(pickup_resp.status_code, 200)

        dropoff_resp = self.client.post(
            f"/api/bookings/{first_id}/dropoff-proof",
            data={"photo": (io.BytesIO(b"fakejpeg2"), "dropoff.jpg")},
            content_type="multipart/form-data",
            headers=self.headers,
        )
        self.assertEqual(dropoff_resp.status_code, 200)

        complete_with_proofs = self.client.post(
            f"/api/bookings/{first_id}/complete", headers=self.headers
        )
        self.assertEqual(complete_with_proofs.status_code, 200)

        done = db.session.get(ScheduledBooking, first_id)
        self.assertEqual(done.status, "completed")
        self.assertTrue(bool(done.pickup_proof_image))
        self.assertTrue(bool(done.dropoff_proof_image))

    def test_negotiation_exposes_last_two_prices(self):
        n = Negotiation(
            customer_id=1,
            customer_name="Customer One",
            driver_id=2,
            driver_name="Driver Two",
            status="Active",
            is_active="Yes",
            customer_accepted="Accepted",
            customer_driver="Pending",
            pickup_address="Kampala",
            dropoff_address="Entebbe",
            initial_price=1000,
        )
        db.session.add(n)
        db.session.flush()

        self.created_negotiation_ids.append(n.id)

        base = datetime.utcnow()
        db.session.add(
            NegotiationRecord(
                negotiation_id=n.id,
                customer_id=1,
                driver_id=2,
                last_negotiator_id=1,
                first_negotiator_id=1,
                price=1000,
                created_at=base,
            )
        )
        db.session.add(
            NegotiationRecord(
                negotiation_id=n.id,
                customer_id=1,
                driver_id=2,
                last_negotiator_id=2,
                first_negotiator_id=1,
                price=1200,
                created_at=base + timedelta(seconds=1),
            )
        )
        db.session.add(
            NegotiationRecord(
                negotiation_id=n.id,
                customer_id=1,
                driver_id=2,
                last_negotiator_id=1,
                first_negotiator_id=1,
                price=900,
                created_at=base + timedelta(seconds=2),
            )
        )
        db.session.commit()

        data = n.to_dict()
        self.assertEqual(data.get("last_offer_price"), 900)
        self.assertEqual(data.get("second_last_offer_price"), 1200)


if __name__ == "__main__":
    unittest.main()
