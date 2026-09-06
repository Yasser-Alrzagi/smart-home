import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_user, RoleChecker
from app.core.security import create_access_token
from app.core.errors import AppError
from app.services.sessions import issue_session
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.user import user_service


def test_get_current_user_valid_token(db_session: Session):
    user_in = UserCreate(
        username="deps_user",
        email="deps@example.com",
        password="secretpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    
    token = issue_session(db_session, user)
    
    current_user = get_current_user(db=db_session, token=token)
    assert current_user.user_id == user.user_id


def test_get_current_user_invalid_token(db_session: Session):
    with pytest.raises(AppError) as exc_info:
        get_current_user(db=db_session, token="invalid.token.here")
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_nonexistent(db_session: Session):
    token = create_access_token(subject="nonexistent_uuid", role=UserRole.student)
    with pytest.raises(AppError) as exc_info:
        get_current_user(db=db_session, token=token)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_active_user(db_session: Session):
    user_in = UserCreate(
        username="active_user",
        email="active@example.com",
        password="secretpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    
    # Should pass
    active_user = get_current_active_user(current_user=user)
    assert active_user.user_id == user.user_id
    
    # Deactivate
    update_in = UserUpdate(is_active=False)
    user = user_service.update(db_session, db_obj=user, obj_in=update_in)
    
    # Should fail
    with pytest.raises(HTTPException) as exc_info:
        get_current_active_user(current_user=user)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Could not validate credentials"


def test_role_checker():
    # Mock user object
    class MockUser:
        def __init__(self, role):
            self.role = role

    student_user = MockUser(role=UserRole.student)
    admin_user = MockUser(role=UserRole.system_administrator)
    
    require_admin = RoleChecker(allowed_roles=[UserRole.system_administrator])
    
    # Admin passes
    result = require_admin(user=admin_user)
    assert result == admin_user
    
    # Student fails
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=student_user)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
