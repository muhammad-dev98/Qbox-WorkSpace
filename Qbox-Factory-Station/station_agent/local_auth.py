from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# Backend uses HS256 (symmetric SECRET_KEY) for operator JWTs - confirmed
# against Qbox-Backend/config/settings/base.py's SIMPLE_JWT block (no
# SIGNING_KEY/ALGORITHM override, so rest_framework_simplejwt's HS256
# default applies) and core/authentication.py's CookieJWTAuthentication.
# A symmetric secret means this Station can NEVER verify the token's
# signature locally without holding that same secret - doing so would let
# a compromised Station forge ANY operator token, which is strictly worse
# than the station-key credential this process already holds. So instead
# of local verification, every local-API call's Bearer token is checked
# against the backend's own, already-live GET /auth/profile endpoint
# (authentication/api/auth_urls.py) - the same call the Factory Panel's
# own AuthContext already makes to fetch the logged-in user's profile and
# permissions. A successful response IS the introspection result; its
# `permissions` list is what local routes gate on. Cached per-token for
# the remainder of the token's own exp (read from the JWT payload without
# verifying the signature - safe because the cache only ever *shortens*
# how long a successful backend-verified result is trusted, it never
# substitutes for that verification).
_PROFILE_PATH = "/api/v1/auth/profile"
_CACHE_SAFETY_MARGIN_S = 5


@dataclass(frozen=True)
class OperatorPrincipal:
    user_id: str
    permissions: frozenset[str]


class LocalAuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OperatorAuthenticator:
    """
    Gate for the Station's local HTTP API (127.0.0.1:<port>) - the Factory
    Panel authenticates to THIS with the operator's own existing backend
    JWT (Authorization: Bearer ...), never with the Station's own
    X-Station-Key (that header is only ever attached by backend_client.py
    on Station -> backend calls, a separate outbound connection the
    browser never sees or sends).
    """

    def __init__(self, *, backend_url: str, session: aiohttp.ClientSession):
        self._backend_url = backend_url.rstrip("/")
        self._session = session
        self._cache: dict[str, tuple[OperatorPrincipal, float]] = {}

    async def authenticate(self, request) -> OperatorPrincipal:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise LocalAuthError("LOCAL_AUTH_MISSING", "Authorization: Bearer <token> is required")
        token = auth_header[len("Bearer "):].strip()
        if not token:
            raise LocalAuthError("LOCAL_AUTH_MISSING", "Authorization: Bearer <token> is required")

        cached = self._cache.get(token)
        now = time.time()
        if cached is not None:
            principal, expires_at = cached
            if now < expires_at:
                return principal
            del self._cache[token]

        try:
            async with self._session.get(
                f"{self._backend_url}{_PROFILE_PATH}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401 or response.status == 403:
                    raise LocalAuthError("LOCAL_AUTH_INVALID", "Backend rejected this token")
                if response.status >= 400:
                    raise LocalAuthError("LOCAL_AUTH_BACKEND_ERROR", f"Unexpected backend status {response.status}")
                body = await response.json()
        except aiohttp.ClientError as exc:
            raise LocalAuthError("LOCAL_AUTH_BACKEND_UNREACHABLE", str(exc)) from exc

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise LocalAuthError("LOCAL_AUTH_BACKEND_ERROR", "Unexpected profile response shape")

        permissions = frozenset(data.get("permissions") or [])
        principal = OperatorPrincipal(user_id=str(data.get("id") or ""), permissions=permissions)

        expires_at = min(now + 300, _jwt_exp(token) - _CACHE_SAFETY_MARGIN_S) if _jwt_exp(token) else now + 60
        self._cache[token] = (principal, expires_at)
        return principal

    def require_permission(self, principal: OperatorPrincipal, permission: str) -> None:
        if permission not in principal.permissions:
            raise LocalAuthError("LOCAL_AUTH_FORBIDDEN", f"Missing required permission {permission!r}")


def _jwt_exp(token: str) -> float | None:
    """
    Reads the unverified `exp` claim purely to bound how long a
    backend-confirmed result is cached - never used to accept a token on
    its own (see module docstring: signature verification is impossible
    here by design, so every token is still checked against the backend on
    every cache miss).
    """
    try:
        _header, payload_b64, _sig = token.split(".")
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None
