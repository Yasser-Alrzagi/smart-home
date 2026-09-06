from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.user import user_service
from app.core.security import verify_password


def test_create_user_hashes_password(db_session: Session):
    user_in = UserCreate(
        username="test_service",
        email="test_service@example.com",
        password="secretpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    
    assert user.username == "test_service"
    assert user.email == "test_service@example.com"
    # Ensure raw password is NOT stored
    assert user.password_hash != "secretpassword"
    # Ensure it's correctly hashed
    assert verify_password("secretpassword", user.password_hash)


def test_get_user(db_session: Session):
    user_in = UserCreate(
        username="test_service2",
        email="test_service2@example.com",
        password="secretpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    
    fetched = user_service.get(db_session, user_id=user.user_id)
    assert fetched is not None
    assert fetched.user_id == user.user_id
    
    by_email = user_service.get_by_email(db_session, email="test_service2@example.com")
    assert by_email is not None
    assert by_email.user_id == user.user_id
    
    by_username = user_service.get_by_username(db_session, username="test_service2")
    assert by_username is not None
    assert by_username.user_id == user.user_id


def test_update_user_password(db_session: Session):
    user_in = UserCreate(
        username="test_service3",
        email="test_service3@example.com",
        password="secretpassword",
        role=UserRole.student
    )
    user = user_service.create(db_session, user_in=user_in)
    old_hash = user.password_hash
    
    update_in = UserUpdate(password="newsecretpassword")
    user_updated = user_service.update(db_session, db_obj=user, obj_in=update_in)
    
    assert user_updated.password_hash != old_hash
    assert verify_password("newsecretpassword", user_updated.password_hash)


def test_remove_user(db_session: Session):
    from app.core.errors import HardDeleteDisabled
    from app.models import User
    from app.services.user import user_service
    from app.schemas.user import UserCreate
    import pytest
    user = user_service.create(db_session, user_in=UserCreate(
        username="retained_user", email="retained@example.com", password="safe-password", role=UserRole.student))
    with pytest.raises(HardDeleteDisabled):
        user_service.remove(db_session, user_id=user.user_id)
    assert db_session.get(User, user.user_id) is not None
