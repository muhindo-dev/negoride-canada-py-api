"""Weekly driver earnings statements (spec §13.3). INTEGER CENTS, CAD."""
from backend.models import db
from backend.models.base import SerializeMixin, utcnow


class DriverStatement(SerializeMixin, db.Model):
    __tablename__ = 'driver_statements'
    __table_args__ = (db.UniqueConstraint('driver_id', 'period_start', name='uq_driver_statements_week'),)
    _hidden = ('pdf_path',)

    id = db.Column(db.BigInteger, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True)
    driver_id = db.Column(db.Integer, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)       # exclusive (next Monday)
    currency = db.Column(db.String(3), nullable=False, default='cad')
    gross_cents = db.Column(db.BigInteger, nullable=False, default=0)
    commission_cents = db.Column(db.BigInteger, nullable=False, default=0)
    fees_cents = db.Column(db.BigInteger, nullable=False, default=0)
    net_cents = db.Column(db.BigInteger, nullable=False, default=0)
    payouts_cents = db.Column(db.BigInteger, nullable=False, default=0)
    totals = db.Column(db.JSON, nullable=False)
    pdf_path = db.Column(db.String(500))
    emailed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
