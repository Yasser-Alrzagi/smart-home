from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
import uuid
import jwt
import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.password_policy import validate_password_bounds
from app.core.config import settings

# Explicit Argon2id settings (64 MiB, 3 iterations, 4 lanes).
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify full Argon2id passwords; support bounded legacy bcrypt without truncation."""
    try:
        validate_password_bounds(plain_password)
        if not isinstance(hashed_password, str):
            return False
        if hashed_password.startswith("$argon2id$"):
            return password_hasher.verify(hashed_password, plain_password)
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
            encoded = plain_password.encode("utf-8")
            # Old hashes cannot establish the ignored suffix. Require reset for
            # those legacy passwords rather than silently accepting a prefix.
            if len(encoded) > 72:
                return False
            return bcrypt.checkpw(encoded, hashed_password.encode("ascii"))
        return False
    except (VerificationError, InvalidHashError, ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """New hashes always use Argon2id; password text is never normalized or cut."""
    return password_hasher.hash(validate_password_bounds(password))


def password_needs_rehash(hashed_password: str) -> bool:
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        return True
    return password_hasher.check_needs_rehash(hashed_password)


def create_access_token(
    subject: Union[str, Any],
    role: str,
    expires_delta: Optional[timedelta] = None,
    *,
    session_id: str | None = None,
    token_version: int = 0,
    expires_at: datetime | None = None,
) -> str:
    """Sign claims only. HTTP authentication ALSO requires a persisted AuthSession."""
    now = datetime.now(timezone.utc)
    expire = (
        expires_at
        if expires_at is not None
        else now
        + (
            expires_delta
            if expires_delta is not None
            else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
    )
    return jwt.encode(
        {
            "exp": expire,
            "iat": now,
            "sub": str(subject),
            "role": role,
            "jti": session_id or str(uuid.uuid4()),
            "ver": token_version,
            "type": "access",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> Optional[dict]:
    if not isinstance(token, str) or len(token) > 4096:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "strict_aud": True,
                "require": ["exp", "iat", "sub", "jti", "ver", "iss", "aud", "type"],
            },
        )
        if (
            payload.get("type") != "access"
            or not payload["sub"]
            or type(payload["ver"]) is not int
            or payload["ver"] < 0
            or type(payload["exp"]) is not int
            or type(payload["iat"]) is not int
            or payload["exp"] <= payload["iat"]
        ):
            return None
        if str(uuid.UUID(payload["jti"])) != payload["jti"]:
            return None
        return payload
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        return None
