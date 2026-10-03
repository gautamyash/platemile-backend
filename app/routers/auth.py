from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import credits
from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.google_auth import InvalidGoogleToken, verify_google_id_token
from app.models import DeletedIdentity, User
from app.ratelimit import limit
from app.routers.account import sub_hash
from app.security import create_access_token

router = APIRouter(tags=["auth"])


class GoogleLoginIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    credits: int
    is_new: bool = False


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _clean_name(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    return " ".join(raw.split())[:120] or None


@router.post("/auth/google", response_model=LoginOut, dependencies=[limit("login", 20, 60)])
async def google_login(body: GoogleLoginIn, session: AsyncSession = Depends(get_session)) -> LoginOut:
    try:
        claims = await verify_google_id_token(body.id_token)
    except InvalidGoogleToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google sign-in could not be verified")

    sub, email = claims["sub"], claims["email"]
    name = _clean_name(claims.get("name"))
    is_new = False
    user = (await session.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is not None and user.deleted_at is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account was deleted")
    if user is None:
        user = User(google_sub=sub, email=email, name=name)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:  # two first-time logins raced; use the row that won
            await session.rollback()
            user = (await session.execute(select(User).where(User.google_sub == sub))).scalar_one()
        else:
            previously_deleted = await session.get(DeletedIdentity, sub_hash(sub)) is not None
            if not previously_deleted:
                await credits.grant(session, user.id, settings.welcome_credits, "welcome")
            is_new = True
    else:
        if user.email != email:
            user.email = email
        if name and user.name != name:
            user.name = name
    await session.commit()

    bal = await credits.balance(session, user.id)
    return LoginOut(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, email=user.email, name=user.name, credits=bal, is_new=is_new),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, credits=await credits.balance(session, user.id))


class DevLoginIn(BaseModel):
    email: str = Field(default="dev@example.com", max_length=120)


@router.post("/auth/dev", response_model=LoginOut, include_in_schema=False)
async def dev_login(body: DevLoginIn, session: AsyncSession = Depends(get_session)) -> LoginOut:
    """Testing-only login for Expo Go (no Google). Disabled unless DEV_LOGIN_ENABLED=true."""
    if not settings.dev_login_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    sub = f"dev:{body.email.lower()}"
    is_new = False
    user = (await session.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is None:
        user = User(google_sub=sub, email=body.email)
        session.add(user)
        await session.flush()
        await credits.grant(session, user.id, settings.welcome_credits, "welcome")
        is_new = True
    await session.commit()
    bal = await credits.balance(session, user.id)
    return LoginOut(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, email=user.email, name=user.name, credits=bal, is_new=is_new),
    )
