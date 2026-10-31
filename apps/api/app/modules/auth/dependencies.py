from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise UnauthorizedError("Invalid or expired access token")
    user = await AuthRepository(session).get_user(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired access token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
