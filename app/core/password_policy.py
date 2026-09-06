"""Shared password bounds; never strip, normalize, or truncate a password."""
MAX_PASSWORD_CHARS = 256
MAX_PASSWORD_BYTES = 1024
MIN_NEW_PASSWORD_CHARS = 12


def validate_password_bounds(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PASSWORD_CHARS:
        raise ValueError("Password must contain 1 to 256 characters.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Password must be valid UTF-8 text.") from exc
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Password exceeds the UTF-8 byte limit.")
    return value
