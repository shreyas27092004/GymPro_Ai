# app/auth/router.py
from typing import Any
from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from .deps import SessionContext, get_session
from .service import (
    AdminActivateBody,
    ForgotPasswordBody,
    LoginBody,
    RefreshBody,
    RegisterBody,
    ResetPasswordBody,
    activate_admin,
    forgot_password,
    login,
    logout,
    refresh,
    register,
    reset_password,
    verify_email,
)

router = APIRouter(tags=["Auth"])


@router.post("/register", status_code=status.HTTP_200_OK)
async def api_register(
    body: RegisterBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "127.0.0.1"
    return await register(db, body, ip)


from pydantic import BaseModel


class VerifyEmailBody(BaseModel):
    token: str


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def api_verify_email(
    body: VerifyEmailBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "127.0.0.1"
    return await verify_email(db, body.token, ip)


@router.post("/login", status_code=status.HTTP_200_OK)
async def api_login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "127.0.0.1"
    tokens = await login(db, body.email, body.password, ip)
    # Set refresh token in httpOnly SameSite=Strict cookie
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="strict",
        secure=False,  # Set true in production over HTTPS
        max_age=7 * 24 * 3600,
    )
    return tokens


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def api_refresh(
    request: Request,
    response: Response,
    body: RefreshBody | None = None,
    refresh_token_cookie: str | None = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    raw_token = (body.refresh_token if body and body.refresh_token else None) or refresh_token_cookie
    if not raw_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Missing refresh token")
    ip = request.client.host if request.client else "127.0.0.1"
    tokens = await refresh(db, raw_token, ip)
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=7 * 24 * 3600,
    )
    return tokens


@router.post("/logout", status_code=status.HTTP_200_OK)
async def api_logout(
    response: Response,
    s: SessionContext = Depends(get_session),
    refresh_token_cookie: str | None = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = await logout(db, s.user_id, refresh_token_cookie)
    response.delete_cookie(key="refresh_token")
    return res


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def api_forgot_password(
    body: ForgotPasswordBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "127.0.0.1"
    return await forgot_password(db, body.email, ip)


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def api_reset_password(
    body: ResetPasswordBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await reset_password(db, body.token, body.new_password)


@router.post("/activate-admin", status_code=status.HTTP_200_OK)
async def api_activate_admin(
    body: AdminActivateBody,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "127.0.0.1"
    tokens = await activate_admin(db, body.email, body.password, body.code, ip)
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=7 * 24 * 3600,
    )
    return tokens


@router.get("/me", status_code=status.HTTP_200_OK)
async def api_me(s: SessionContext = Depends(get_session)) -> dict[str, Any]:
    """Return caller's role, status, plan, consent, and profile metadata."""
    return s.public()
