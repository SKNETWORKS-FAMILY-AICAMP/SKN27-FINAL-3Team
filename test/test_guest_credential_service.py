"""Unit tests for the signed guest credential boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import google_auth_service
from app.services.google_auth_service import decode_access_token
from app.services.guest_credential_service import (
    GUEST_CREDENTIAL_AUDIENCE,
    GUEST_CREDENTIAL_TYPE,
    decode_guest_credential,
    issue_guest_credential,
)


def test_issued_guest_credential_has_guest_only_claims() -> None:
    token, claims = issue_guest_credential("owner")

    valid, decoded = decode_guest_credential(token)

    assert valid is True
    assert claims["sub"] == "gst_owner"
    assert decoded["sub"] == "gst_owner"
    assert decoded["aud"] == GUEST_CREDENTIAL_AUDIENCE
    assert decoded["typ"] == GUEST_CREDENTIAL_TYPE


def test_guest_credential_is_not_accepted_as_an_app_jwt(monkeypatch) -> None:
    monkeypatch.setattr(
        google_auth_service,
        "_jwt_secret",
        lambda: "test-app-jwt-secret-at-least-32-characters",
    )
    token, _claims = issue_guest_credential("owner")

    app_jwt_valid, _decoded = decode_access_token(token)

    assert app_jwt_valid is False


def test_expired_or_tampered_guest_credential_returns_only_safe_reason() -> None:
    expired_at = datetime.now(timezone.utc) - timedelta(days=8)
    expired_token, _claims = issue_guest_credential("owner", now=expired_at)

    assert decode_guest_credential(expired_token) == (
        False,
        {"reason": "expired_guest_credential"},
    )
    assert decode_guest_credential(f"{expired_token}tampered") == (
        False,
        {"reason": "invalid_guest_credential"},
    )
