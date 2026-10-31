"""Auth use cases: register, login, refresh-token rotation with reuse detection, logout."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.repository import AuthRepository

# Verifying against a dummy hash keeps login timing similar for unknown emails.
_DUMMY_HASH = hash_password("timing-equalizer-password")


@dataclass(frozen=True)
class IssuedTokens:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuthRepository(session)

    async def register(
        self, email: str, password: str, display_name: str, user_agent: str | None
    ) -> IssuedTokens:
        email = normalize_email(email)
        if await self.repo.get_user_by_email(email):
            raise ConflictError("An account with this email already exists")
        user = User(
            email=email, password_hash=hash_password(password), display_name=display_name.strip()
        )
        self.repo.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent registration with the same email
            await self.session.rollback()
            raise ConflictError("An account with this email already exists") from exc
        tokens = self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        await self.session.commit()
        return tokens

    async def login(self, email: str, password: str, user_agent: str | None) -> IssuedTokens:
        user = await self.repo.get_user_by_email(normalize_email(email))
        if user is None:
            verify_password(_DUMMY_HASH, password)
            raise UnauthorizedError("Invalid email or password")
        if not verify_password(user.password_hash, password) or not user.is_active:
            raise UnauthorizedError("Invalid email or password")
        tokens = self._issue(user, family_id=uuid.uuid4(), user_agent=user_agent)
        await self.session.commit()
        return tokens

    async def refresh(self, raw_token: str | None, user_agent: str | None) -> IssuedTokens:
        if not raw_token:
            raise UnauthorizedError("Missing refresh token")
        now = datetime.now(UTC)
        stored = await self.repo.get_refresh_token(hash_refresh_token(raw_token))
        if stored is None:
            raise UnauthorizedError("Invalid refresh token")
        if stored.revoked_at is not None:
            # A rotated token was presented again: assume theft, revoke the whole family.
            await self.repo.revoke_family(stored.family_id, now)
            await self.session.commit()
            raise UnauthorizedError("Refresh token reuse detected")
        if stored.expires_at <= now:
            raise UnauthorizedError("Refresh token expired")
        user = await self.repo.get_user(stored.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Invalid refresh token")
        stored.revoked_at = now
        tokens = self._issue(user, family_id=stored.family_id, user_agent=user_agent)
        await self.session.commit()
        return tokens

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        stored = await self.repo.get_refresh_token(hash_refresh_token(raw_token))
        if stored is not None:
            await self.repo.revoke_family(stored.family_id, datetime.now(UTC))
            await self.session.commit()

    def _issue(self, user: User, *, family_id: uuid.UUID, user_agent: str | None) -> IssuedTokens:
        settings = get_settings()
        raw = new_refresh_token()
        self.repo.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw),
                family_id=family_id,
                expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
                user_agent=(user_agent or "")[:512] or None,
            )
        )
        access, expires_in = create_access_token(user.id)
        return IssuedTokens(
            user=user, access_token=access, expires_in=expires_in, refresh_token=raw
        )
