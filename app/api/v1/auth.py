"""Authentication API — JWT login and current-user identity."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.user import Token, UserResponse
from app.services.auth import auth_service

# Mounted under settings.API_V1_STR in main.py, so /login/access-token resolves to
# the tokenUrl declared by OAuth2PasswordBearer in app/api/deps.py.
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    """OAuth2 password flow — exchange username and password for a JWT access token."""
    user = auth_service.authenticate(
        db, username=form_data.username, password=form_data.password
    )
    # Wrong username and wrong password are reported identically on purpose.
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    access_token = create_access_token(
        subject=user.user_id,
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/users/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(get_current_active_user)) -> User:
    """Return the authenticated user described by the bearer token."""
    return current_user
