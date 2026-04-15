from datetime import datetime
from backend.models import db


class CallLog(db.Model):
    __tablename__ = 'call_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Participants
    caller_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False, index=True)
    callee_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True, index=True)
    negotiation_id = db.Column(db.Integer, db.ForeignKey('negotiations.id'), nullable=True, index=True)

    # Call details
    call_type = db.Column(db.String(20), nullable=False, default='voice')  # voice | video
    status = db.Column(db.String(20), default='initiated')
    # status flow: initiated → ringing → active → ended
    #              initiated → missed   (45s timeout)
    #              initiated → rejected (callee declined)

    # Timestamps
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    # Metrics
    duration = db.Column(db.Integer, default=0)  # seconds
    end_reason = db.Column(db.String(30), nullable=True)
    # end_reason: normal | no_answer | rejected | error | network_timeout | busy
    quality_score = db.Column(db.Integer, nullable=True)  # 1-5

    def to_dict(self):
        return {
            'id': self.id,
            'caller_id': self.caller_id,
            'callee_id': self.callee_id,
            'negotiation_id': self.negotiation_id,
            'call_type': self.call_type,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'answered_at': self.answered_at.isoformat() if self.answered_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration': self.duration,
            'end_reason': self.end_reason,
            'quality_score': self.quality_score,
        }
