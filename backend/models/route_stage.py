from backend.models import db
from backend.utils.helpers import my_date_time


class RouteStage(db.Model):
    __tablename__ = 'route_stages'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=True)
    latitute = db.Column(db.String(255), nullable=True, default='')
    longitude = db.Column(db.String(255), nullable=True, default='')
    details = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitute': self.latitute,
            'longitude': self.longitude,
            'details': self.details,
        }
