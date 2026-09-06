"""Credential verification; request and rate-limit orchestration live in the API."""

import secrets
from sqlalchemy import select

from app.models import User
from app.core.security import get_password_hash, password_needs_rehash, verify_password

# One dummy Argon2id hash per process, not a real/default account credential.
_DUMMY_HASH = get_password_hash(secrets.token_hex(24))


class AuthService:
    def authenticate(self, db, *, username: str, password: str):
        # Lock before password verification so concurrent reset/disable cannot
        # issue a session based on stale credentials. Refresh any identity-map row.
        user = db.scalar(
            select(User)
            .where(User.username == username)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        if not valid or user is None:
            return None
        if user.is_active and password_needs_rehash(user.password_hash):
            user.password_hash = get_password_hash(password)
            db.flush()
        return user


auth_service = AuthService()
