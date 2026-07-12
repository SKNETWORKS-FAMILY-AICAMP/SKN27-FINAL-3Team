"""Smoke test Google Authorization Code Flow settings and optional code exchange."""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.services.google_auth_service import create_google_code_login
from chatbot.repositories import persist_current_auth_subject

PLACEHOLDER_MARKERS = ("replace-with", "placeholder", "change-me", "example.com")


class Command(BaseCommand):
    help = "Validate Google OAuth code-flow settings and optionally exchange a real authorization code."

    def add_arguments(self, parser):
        parser.add_argument("--code", default="", help="One-time Google authorization code to exchange.")
        parser.add_argument("--redirect-uri", default="", help="Redirect URI used to obtain the code.")
        parser.add_argument("--scope", default="openid email profile", help="OAuth scopes requested for the code.")
        parser.add_argument("--session-id", default="ses_google_oauth_smoke", help="Smoke chat session id.")
        parser.add_argument("--guest-id", default="gst_google_oauth_smoke", help="Smoke guest id.")
        parser.add_argument(
            "--require-exchange",
            action="store_true",
            help="Fail if --code is missing or the real Google token exchange does not succeed.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        config = _config_status(options)
        result = {
            "contract_version": "google_oauth_code_smoke.v1",
            "status": "pass" if config["ready"] else "fail",
            "config": config,
            "exchange": None,
        }

        code = str(options["code"] or "").strip()
        if code:
            status, payload = create_google_code_login(
                {
                    "provider": "google",
                    "code": code,
                    "purpose": "LOGIN",
                    "scope": options["scope"],
                    "guest_id": options["guest_id"],
                    "session_id": options["session_id"],
                    "redirect_uri": options["redirect_uri"] or getattr(settings, "GOOGLE_POPUP_REDIRECT_URI", ""),
                },
                request_headers={"X-Requested-With": "XmlHttpRequest"},
            )
            persistence = None
            if status < 400:
                persistence = persist_current_auth_subject(payload, session_id=options["session_id"])
            payload.pop("_private_oauth_tokens", None)
            result["exchange"] = {
                "http_status": status,
                "auth_mode": payload.get("auth_mode"),
                "contract_version": payload.get("contract_version"),
                "error": payload.get("error"),
                "google": _safe_google_metadata(payload.get("google") or {}),
                "persistence": _safe_persistence_metadata(persistence or {}),
            }
            if status >= 400:
                result["status"] = "fail"
        elif options["require_exchange"]:
            result["status"] = "fail"
            result["exchange"] = {"error": {"reason": "authorization_code_required"}}

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("Google OAuth code-flow smoke failed.")


def _config_status(options: dict) -> dict:
    redirect_uri = str(options["redirect_uri"] or getattr(settings, "GOOGLE_POPUP_REDIRECT_URI", "") or "")
    required = {
        "GOOGLE_CLIENT_ID": getattr(settings, "GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": getattr(settings, "GOOGLE_CLIENT_SECRET", ""),
        "GOOGLE_POPUP_REDIRECT_URI": redirect_uri,
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    placeholders = [key for key, value in required.items() if _looks_placeholder(value)]
    return {
        "ready": not missing and not placeholders,
        "missing": missing,
        "placeholders": placeholders,
        "redirect_uri": redirect_uri,
        "token_endpoint": getattr(settings, "GOOGLE_TOKEN_ENDPOINT", ""),
        "userinfo_endpoint": getattr(settings, "GOOGLE_USERINFO_ENDPOINT", ""),
    }


def _looks_placeholder(value: object) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(marker in text for marker in PLACEHOLDER_MARKERS)


def _safe_google_metadata(google: dict) -> dict:
    return {
        "connected": bool(google.get("connected")),
        "purpose": google.get("purpose"),
        "granted_scopes": google.get("granted_scopes") or [],
        "has_refresh_token": bool(google.get("has_refresh_token")),
        "connection_policy": google.get("connection_policy"),
    }


def _safe_persistence_metadata(persistence: dict) -> dict:
    return {
        "status": persistence.get("status"),
        "tables": persistence.get("tables") or [],
        "social_account_id": persistence.get("social_account_id"),
        "oauth_connection_id": persistence.get("oauth_connection_id"),
    }


def _text_result(result: dict) -> str:
    config = result["config"]
    lines = [
        f"Google OAuth code-flow smoke: {result['status']}",
        f"- config_ready: {config['ready']}",
        f"- mock_allowed: {config['mock_allowed']}",
        f"- missing: {', '.join(config['missing']) if config['missing'] else '-'}",
        f"- placeholders: {', '.join(config.get('placeholders') or []) if config.get('placeholders') else '-'}",
    ]
    exchange = result.get("exchange")
    if exchange:
        lines.extend(
            [
                f"- exchange_http_status: {exchange.get('http_status')}",
                f"- exchange_auth_mode: {exchange.get('auth_mode')}",
                f"- persistence_status: {(exchange.get('persistence') or {}).get('status')}",
            ]
        )
    return "\n".join(lines)
