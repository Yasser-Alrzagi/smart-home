import pytest
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.schemas.user import UserCreate
from app.services.user import user_service
from app.services.auth import auth_service


def test_authenticate_valid_credentials(db_session: Session):
    user_in = UserCreate(
        username="auth_user",
        email="auth_user@example.com",
        password="authpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    
    authenticated_user = auth_service.authenticate(db_session, username="auth_user", password="authpassword")
    assert authenticated_user is not None
    assert authenticated_user.user_id == user.user_id


def test_authenticate_invalid_password(db_session: Session):
    user_in = UserCreate(
        username="auth_user_2",
        email="auth_user_2@example.com",
        password="authpassword",
        role=UserRole.student
    )
    user_service.create(db_session, user_in=user_in)
    
    authenticated_user = auth_service.authenticate(db_session, username="auth_user_2", password="wrongpassword")
    assert authenticated_user is None


def test_authenticate_nonexistent_user(db_session: Session):
    authenticated_user = auth_service.authenticate(db_session, username="nonexistent", password="anypassword")
    assert authenticated_user is None
