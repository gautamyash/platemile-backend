
from jose import jwt

from app.config import settings
from app.security import create_access_token, decode_access_token


def test_token_roundtrip():
    assert decode_access_token(create_access_token("user-1")) == "user-1"


def test_garbage_and_wrong_secret_rejected():
    assert decode_access_token("not-a-token") is None
    forged = jwt.encode({"sub": "user-1"}, "other-secret", algorithm=settings.jwt_algorithm)
    assert decode_access_token(forged) is None


def test_expired_rejected(monkeypatch):
    monkeypatch.setattr(settings, "jwt_expire_minutes", -5)
    assert decode_access_token(create_access_token("user-1")) is None
