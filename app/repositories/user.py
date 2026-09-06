from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.repositories.base import BaseRepository
from app.core.errors import HardDeleteDisabled


class UserRepository(BaseRepository[User, UserCreate, UserUpdate]):
    def remove(self, db: Session, *, id):
        raise HardDeleteDisabled()

    def get_by_email(self, db: Session, *, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        return db.scalar(stmt)
        
    def get_by_username(self, db: Session, *, username: str) -> Optional[User]:
        stmt = select(User).where(User.username == username)
        return db.scalar(stmt)

user_repo = UserRepository(User)
