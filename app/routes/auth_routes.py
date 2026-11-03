"""Authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.auth import (
    authenticate,
    clear_auth_cookie,
    create_token,
    get_current_user,
    set_auth_cookie,
)

auth_router = APIRouter(prefix="/auth")


class LoginRequest(BaseModel):
    username: str
    password: str


@auth_router.post("/login")
async def login(body: LoginRequest, response: Response):
    if not authenticate(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(body.username)
    set_auth_cookie(response, token)
    return {"success": True, "username": body.username}


@auth_router.post("/logout")
async def logout(response: Response):
    clear_auth_cookie(response)
    return {"success": True}


@auth_router.get("/me")
async def me(user: str = Depends(get_current_user)):
    return {"username": user}
