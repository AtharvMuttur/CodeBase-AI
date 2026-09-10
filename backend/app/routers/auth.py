"""Registration, login, and current-user endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import AuthRequest, AuthResponse, UserResponse
from ..services.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _response(user: User) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse(id=user.id, email=user.email),
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: AuthRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    return _response(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)) -> AuthResponse:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _response(user)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email)


__all__ = ["router"]
