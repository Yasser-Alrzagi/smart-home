import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.repositories.user import user_repo


def test_create_user(db_session: Session):
    user_in = {
        "username": "testrepo",
        "email": "repo@example.com",
        "password_hash": "hashedpassword",  # Service layer handles hashing, repo just saves
        "role": UserRole.student
    }
    user = user_repo.create(db_session, obj_in=user_in)
    
    assert user.username == "testrepo"
    assert user.email == "repo@example.com"
    assert user.user_id is not None
    assert user.is_active is True


def test_get_user(db_session: Session):
    user_in = {
        "username": "testget",
        "email": "get@example.com",
        "password_hash": "hashedpassword",
        "role": UserRole.student
    }
    user = user_repo.create(db_session, obj_in=user_in)
    
    user_2 = user_repo.get(db_session, id=user.user_id)
    assert user_2 is not None
    assert user_2.user_id == user.user_id
    assert user_2.email == user.email


def test_get_by_email_and_username(db_session: Session):
    user_in = {
        "username": "testlookup",
        "email": "lookup@example.com",
        "password_hash": "hashedpassword",
        "role": UserRole.student
    }
    user = user_repo.create(db_session, obj_in=user_in)
    
    user_by_email = user_repo.get_by_email(db_session, email="lookup@example.com")
    assert user_by_email is not None
    assert user_by_email.user_id == user.user_id
    
    user_by_username = user_repo.get_by_username(db_session, username="testlookup")
    assert user_by_username is not None
    assert user_by_username.user_id == user.user_id
    
    # Negative test
    assert user_repo.get_by_email(db_session, email="nonexistent@example.com") is None


def test_update_user(db_session: Session):
    user_in = {
        "username": "testupdate",
        "email": "update@example.com",
        "password_hash": "hashedpassword",
        "role": UserRole.student
    }
    user = user_repo.create(db_session, obj_in=user_in)
    
    user_update = UserUpdate(username="testupdate_new", email="updatenew@example.com")
    user_updated = user_repo.update(db_session, db_obj=user, obj_in=user_update)
    
    assert user_updated.username == "testupdate_new"
    assert user_updated.email == "updatenew@example.com"
    # Ensure other fields remain untouched
    assert user_updated.role == UserRole.student
    
    
def test_remove_user(db_session: Session):
    user_in = {
        "username": "testremove",
        "email": "remove@example.com",
        "password_hash": "hashedpassword",
        "role": UserRole.student
    }
    user = user_repo.create(db_session, obj_in=user_in)
    user_id = user.user_id
    
    removed_user = user_repo.remove(db_session, id=user_id)
    assert removed_user is not None
    assert removed_user.user_id == user_id
    
    user_2 = user_repo.get(db_session, id=user_id)
    assert user_2 is None
