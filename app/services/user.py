from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.repositories.user import user_repo
from app.core.security import get_password_hash

class UserService:
    def create(self, db: Session, *, user_in: UserCreate) -> User:
        user_data = user_in.model_dump()
        password = user_data.pop("password")
        user_data["password_hash"] = get_password_hash(password)
        
        return user_repo.create(db, obj_in=user_data)
        
    def get(self, db: Session, *, user_id: str) -> Optional[User]:
        return user_repo.get(db, id=user_id)
        
    def get_by_email(self, db: Session, *, email: str) -> Optional[User]:
        return user_repo.get_by_email(db, email=email)
        
    def get_by_username(self, db: Session, *, username: str) -> Optional[User]:
        return user_repo.get_by_username(db, username=username)
        
    def update(self, db: Session, *, db_obj: User, obj_in: UserUpdate) -> User:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "password" in update_data:
            password = update_data.pop("password")
            update_data["password_hash"] = get_password_hash(password)
            
        return user_repo.update(db, db_obj=db_obj, obj_in=update_data)
        
    def remove(self, db: Session, *, user_id: str) -> Optional[User]:
        return user_repo.remove(db, id=user_id)

user_service = UserService()
