"""JWT authentication with HTTP-only cookies."""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from jose import JWTError, jwt

from config import (
    ADMIN_PASSWORD,
    ADMIN_USER,
    COOKIE_NAME,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    SECRET_KEY,
)
from db import models


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": username, "exp": expire},
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def init_admin() -> None:
    models.ensure_admin(ADMIN_USER, hash_password(ADMIN_PASSWORD))


def authenticate(username: str, password: str) -> bool:
    admin = models.get_admin(username)
    if admin:
        return verify_password(password, admin["password_hash"])
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        return True
    return False


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_MINUTES * 60,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


async def get_current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = decode_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username


async def optional_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_token(token)
