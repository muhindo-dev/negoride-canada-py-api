"""Shared helpers for the v4 models.

v4 APIs return timestamps as ISO-8601 UTC ("2026-09-27T14:03:00Z") so clients
can render them in the user's own time zone (spec §2.10). Legacy models keep
their Laravel-style "YYYY-MM-DD HH:MM:SS" strings.
"""
import json
from datetime import date, datetime
from decimal import Decimal


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%dT%H:%M:%SZ')
    if isinstance(value, date):
        return value.isoformat()
    return value


def utcnow():
    """Naive UTC datetime (MySQL DATETIME columns store UTC)."""
    return datetime.utcnow()


class SerializeMixin:
    """Column-driven to_dict(). Subclasses list private columns in `_hidden`."""

    _hidden = ()

    def to_dict(self, exclude=()):
        out = {}
        for col in self.__table__.columns:
            name = col.key
            if name in self._hidden or name in exclude:
                continue
            val = getattr(self, name)
            if isinstance(val, (datetime, date)):
                val = iso(val)
            elif isinstance(val, Decimal):
                val = float(val)
            elif isinstance(val, str) and col.type.__class__.__name__ == 'JSON':
                try:
                    val = json.loads(val)
                except ValueError:
                    pass
            out[name] = val
        return out
