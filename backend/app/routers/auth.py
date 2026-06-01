from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import check_credentials, create_token, get_current_user
from ..config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    if not check_credentials(body.username, body.password, settings):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_token(body.username, settings))


@router.get("/me")
def me(username: Annotated[str, Depends(get_current_user)]) -> dict[str, str]:
    return {"username": username}
