import pytest
from datetime import datetime
from pydantic import ValidationError

from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.models.enums import UserRole

def test_create_valid_user():
    user = UserCreate(
        username="testuser",
        email="test@example.com",
        password="securepassword123",
        role=UserRole.student
    )
    assert user.username == "testuser"
    assert user.email == "test@example.com"
    assert user.password == "securepassword123"
    assert user.role == UserRole.student
    assert user.is_active is True

def test_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(
            username="testuser",
            email="invalid-email",
            password="securepassword123",
            role=UserRole.student
        )

def test_invalid_role():
    with pytest.raises(ValidationError):
        UserCreate(
            username="testuser",
            email="test@example.com",
            password="securepassword123",
            role="NotARole"
        )

def test_from_attributes():
    class MockUser:
        user_id = "test-uuid"
        username = "mockuser"
        email = "mock@example.com"
        role = UserRole.student
        is_active = True
        created_at = datetime.now()
        updated_at = datetime.now()

    mock_user = MockUser()
    response = UserResponse.model_validate(mock_user)
    
    assert response.user_id == mock_user.user_id
    assert response.username == mock_user.username
    assert response.email == mock_user.email
    assert response.role == mock_user.role
