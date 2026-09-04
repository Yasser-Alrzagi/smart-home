from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.user import user_service
from app.core.security import verify_password

class AuthService:
    def authenticate(self, db: Session, *, username: str, password: str) -> Optional[User]:
        user = user_service.get_by_username(db, username=username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

auth_service = AuthService()
