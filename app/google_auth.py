import anyio
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from app.config import settings


class InvalidGoogleToken(Exception):
    pass


def _verify_sync(token: str) -> dict:
    audiences = settings.google_audiences
    if not audiences:
        raise InvalidGoogleToken("server not configured")
    request = g_requests.Request()
    try:
        info = id_token.verify_oauth2_token(token, request, audience=audiences)
    except ValueError as exc:
        raise InvalidGoogleToken(str(exc)) from exc
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidGoogleToken("bad issuer")
    if not info.get("email") or not info.get("email_verified"):
        raise InvalidGoogleToken("email not verified")
    return info


async def verify_google_id_token(token: str) -> dict:
    """Verifies signature, expiry, issuer and audience. Returns the claims (sub, email, ...)."""
    return await anyio.to_thread.run_sync(_verify_sync, token)
