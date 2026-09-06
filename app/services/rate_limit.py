"""Persistent atomic fixed windows. Limits survive failed request rollbacks.

IP-wide and account+IP buckets deliberately avoid globally locking a victim's
account from another IP. Not protection against every distributed attack.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import time

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import session_scope
from app.core.errors import AppError
from app.models import LoginRateBucket
from app.services.audit import record_event


def opaque_key(scope, value):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        (scope + ":" + value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def consume(key, *, limit, seconds, now=None):
    now = time.time() if now is None else now
    start = int(now // seconds) * seconds
    expires = datetime.fromtimestamp(start + seconds, timezone.utc).replace(tzinfo=None)
    try:
        with session_scope() as db:
            stmt = insert(LoginRateBucket).values(
                bucket_key=key, window_start=start, attempts=1, expires_at=expires
            )
            db.execute(
                stmt.on_duplicate_key_update(
                    attempts=func.least(LoginRateBucket.attempts + 1, limit + 1)
                )
            )
            count = db.scalar(
                select(LoginRateBucket.attempts).where(
                    LoginRateBucket.bucket_key == key,
                    LoginRateBucket.window_start == start,
                )
            )
        # Raise only AFTER the independent counter transaction has committed.
        if count > limit:
            raise AppError(
                429,
                "Too many attempts; try again later.",
                {"Retry-After": str(max(1, int(start + seconds - now) + 1))},
            )
    except SQLAlchemyError:
        raise AppError(503, "Authentication temporarily unavailable.") from None


def limit_ip(source):
    consume(
        opaque_key("login_ip", source),
        limit=settings.LOGIN_IP_LIMIT,
        seconds=settings.LOGIN_IP_WINDOW_SECONDS,
    )


def limit_account(source, account_id):
    consume(
        opaque_key(
            "login_pair", json.dumps([source, account_id], separators=(",", ":"))
        ),
        limit=settings.LOGIN_ACCOUNT_IP_LIMIT,
        seconds=settings.LOGIN_ACCOUNT_WINDOW_SECONDS,
    )


def record_failed_login(source, account_id):
    try:
        with session_scope() as db:
            record_event(
                db,
                "login.failure",
                details={
                    "source_key": opaque_key("source", source),
                    "account_key": opaque_key("account", account_id),
                },
            )
    except SQLAlchemyError:
        raise AppError(503, "Authentication temporarily unavailable.") from None
