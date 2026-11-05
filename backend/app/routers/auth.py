"""Registration, login and profile endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_user_settings
from ..models import User, UsageEvent, UserSettings
from ..schemas import ChangePasswordRequest, LoginRequest, ProfileUpdate, RegisterRequest
from ..security import create_access_token, hash_password, verify_password
from ..serializers import settings_out, user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User, settings_row: UserSettings) -> dict:
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_out(user),
        "settings": settings_out(settings_row),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册，请直接登录")
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip()[:120] or email.split("@")[0],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    settings_row = UserSettings(user_id=user.id)
    db.add(settings_row)
    db.add(UsageEvent(user_id=user.id, kind="signup"))
    db.commit()
    return _token_response(user, settings_row)


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码不正确")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return _token_response(user, get_user_settings(db, user))


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"user": user_out(user), "settings": settings_out(get_user_settings(db, user))}


@router.patch("/profile")
def update_profile(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if payload.display_name is not None:
        name = payload.display_name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "昵称不能为空")
        user.display_name = name[:120]
    if payload.affiliation is not None:
        user.affiliation = payload.affiliation.strip()[:255] or None
    if payload.avatar_color is not None:
        user.avatar_color = payload.avatar_color[:16]
    db.commit()
    return {"user": user_out(user)}


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    if len(payload.new_password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "新密码至少 8 位")
    user.password_hash = hash_password(payload.new_password)
    db.add(UsageEvent(user_id=user.id, kind="password_changed"))
    db.commit()
    return {"ok": True}
