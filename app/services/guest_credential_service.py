"""Signed guest credential issuance and verification for the server auth boundary."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt


GUEST_CREDENTIAL_ALGORITHM = "HS256"
GUEST_CREDENTIAL_ISSUER = "skn27-guest-credential"
GUEST_CREDENTIAL_AUDIENCE = "skn27-guest-session"
GUEST_CREDENTIAL_TYPE = "guest_credential"
GUEST_CREDENTIAL_TTL_SECONDS = 7 * 24 * 60 * 60


def issue_guest_credential(
    guest_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Issue a short-lived credential that proves one normalized guest identity."""

    normalized_guest_id = _normalize_guest_id(guest_id)
    if not normalized_guest_id:
        raise ValueError("guest_id is required")

    issued_at = now or _now()
    expires_at = issued_at + timedelta(seconds=GUEST_CREDENTIAL_TTL_SECONDS)
    claims = {
        "iss": GUEST_CREDENTIAL_ISSUER,
        "aud": GUEST_CREDENTIAL_AUDIENCE,
        "typ": GUEST_CREDENTIAL_TYPE,
        "sub": normalized_guest_id,
        "jti": f"gcr_{uuid4().hex}",
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, _guest_credential_secret(), algorithm=GUEST_CREDENTIAL_ALGORITHM), claims


def decode_guest_credential(token: str | None) -> tuple[bool, dict[str, Any]]:
    """Verify a credential without exposing the supplied token or claims on failure."""

    if not _text(token):
        return False, {"reason": "missing_guest_credential"}
    try:
        claims = jwt.decode(
            _text(token),
            _guest_credential_secret(),
            algorithms=[GUEST_CREDENTIAL_ALGORITHM],
            audience=GUEST_CREDENTIAL_AUDIENCE,
            issuer=GUEST_CREDENTIAL_ISSUER,
            options={"require": ["iss", "aud", "typ", "sub", "jti", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        return False, {"reason": "expired_guest_credential"}
    except jwt.InvalidTokenError:
        return False, {"reason": "invalid_guest_credential"}

    if claims.get("typ") != GUEST_CREDENTIAL_TYPE or not _normalize_guest_id(claims.get("sub")):
        return False, {"reason": "invalid_guest_credential"}
    return True, claims


def _guest_credential_secret() -> str:
    digest = hmac.new(
        _application_secret().encode("utf-8"),
        b"skn27-guest-credential.v1",
        hashlib.sha256,
    ).hexdigest()
    return digest


def _application_secret() -> str:
    return (
        _text(_django_setting("APP_JWT_SECRET"))
        or os.environ.get("APP_JWT_SECRET")
        or os.environ.get("DJANGO_SECRET_KEY")
        or _text(_django_setting("SECRET_KEY"))
        or "dev-only-change-before-deploy"
    )


def _django_setting(name: str, default: Any = "") -> Any:
    try:
        from django.conf import settings
    except Exception:
        return default
    if not settings.configured:
        return default
    return getattr(settings, name, default)


def _normalize_guest_id(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return text if text.startswith("gst_") else f"gst_{text}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)
