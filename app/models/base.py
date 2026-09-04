"""Shared declarative base and helpers for all ORM models.

All DateTime columns are naive and hold UTC. ``utcnow`` exists so no model writes a
timezone-aware value into a naive column — PyMySQL would silently drop the offset and
the value would read back as naive, breaking any later comparison.
"""
from datetime import datetime, timezone

from app.core.database import Base

__all__ = ["Base", "utcnow"]


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching the naive DATETIME columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
