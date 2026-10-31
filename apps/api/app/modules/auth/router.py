from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.core.config import get_settings
from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.modules.auth.service import AuthService, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "buildai_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _token_response(response: Response, tokens: IssuedTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserOut.model_validate(tokens.user),
    )


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    tokens = await AuthService(session).register(
        body.email, body.password, body.display_name, request.headers.get("user-agent")
    )
    return _token_response(response, tokens)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    tokens = await AuthService(session).login(
        body.email, body.password, request.headers.get("user-agent")
    )
    return _token_response(response, tokens)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, session: SessionDep, refresh_token: RefreshCookie = None
) -> TokenResponse:
    tokens = await AuthService(session).refresh(refresh_token, request.headers.get("user-agent"))
    return _token_response(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response, session: SessionDep, refresh_token: RefreshCookie = None
) -> None:
    await AuthService(session).logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
