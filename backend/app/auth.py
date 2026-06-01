import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import Settings, get_settings

_bearer = HTTPBearer()
_ALGORITHM = "HS256"


def create_token(username: str, settings: Settings) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.token_expire_days)
    return jwt.encode({"sub": username, "exp": expire}, settings.secret_key, algorithm=_ALGORITHM)


def check_credentials(username: str, password: str, settings: Settings) -> bool:
    return secrets.compare_digest(username, settings.app_username) and secrets.compare_digest(
        password, settings.app_password
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[_ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise exc
    except JWTError:
        raise exc
    return username
