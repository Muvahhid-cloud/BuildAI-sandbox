import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct-horse-battery")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct-horse-battery")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")


def test_access_token_roundtrip() -> None:
    uid = uuid.uuid4()
    token, ttl = create_access_token(uid)
    assert ttl == 15 * 60
    assert decode_access_token(token) == uid


def test_expired_access_token_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), now=datetime.now(UTC) - timedelta(hours=1))
    assert decode_access_token(token) is None


def test_token_with_wrong_type_rejected() -> None:
    s = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )
    assert decode_access_token(token) is None


def test_refresh_hash_is_deterministic() -> None:
    assert hash_refresh_token("abc") == hash_refresh_token("abc")
    assert len(hash_refresh_token("abc")) == 64
