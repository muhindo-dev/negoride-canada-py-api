"""Notification engine (spec §5). Public API: notify(), notify_admins(), mark_opened()."""
from backend.services.notify.dispatcher import mark_opened, notify, notify_admins  # noqa: F401
