"""
WebSocket authentication with SimpleJWT access tokens.

Browsers cannot set headers on a WebSocket, so the token is read from (in order):
  1. the query string:            ws://host/ws/chat/room/?token=<access>
  2. an ``Authorization: Bearer`` header (non-browser clients)
Falls back to the Django session user (e.g. when logged into /admin/).
"""
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


@database_sync_to_async
def get_user_from_token(raw_token: str):
    auth = JWTAuthentication()
    try:
        validated = auth.get_validated_token(raw_token)
        user = auth.get_user(validated)
    except (InvalidToken, TokenError, AuthenticationFailed):
        return None
    return user if user.is_active else None


def _extract_token(scope) -> str | None:
    query = parse_qs(scope.get("query_string", b"").decode())
    if query.get("token"):
        return query["token"][0]
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            parts = value.decode().split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]
    return None


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = _extract_token(scope)
        if token:
            user = await get_user_from_token(token)
            scope["user"] = user or AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):  # noqa: N802 - mirrors channels' AuthMiddlewareStack
    # Session auth runs first; a JWT, when present, overrides it.
    return AuthMiddlewareStack(JWTAuthMiddleware(inner))
