"""Smoke test Google Authorization Code Flow settings and optional code exchange."""

from __future__ import annotations

import json
import os
from getpass import getpass

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.services.google_auth_service import (
    create_google_code_login,
    is_official_google_token_endpoint,
    is_official_google_userinfo_endpoint,
    is_google_web_client_id,
    normalize_google_web_origin,
)
from chatbot.repositories import persist_current_auth_subject

PLACEHOLDER_MARKERS = ("replace-with", "placeholder", "change-me", "example.com")


class Command(BaseCommand):
    help = "Validate Google OAuth code-flow settings and optionally exchange a real authorization code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prompt-code",
            action="store_true",
            help="Read a one-time Google authorization code from a hidden terminal prompt.",
        )
        parser.add_argument("--redirect-uri", default="", help="Redirect URI used to obtain the code.")
        parser.add_argument("--scope", default="openid email profile", help="OAuth scopes requested for the code.")
        parser.add_argument("--session-id", default="ses_google_oauth_smoke", help="Smoke chat session id.")
        parser.add_argument("--guest-id", default="gst_google_oauth_smoke", help="Smoke guest id.")
        parser.add_argument(
            "--require-exchange",
            action="store_true",
            help=(
                "Fail if no code is supplied through the hidden prompt or "
                "GOOGLE_OAUTH_SMOKE_CODE environment variable."
            ),
        )
        parser.add_argument(
            "--verify-replay-rejection",
            action="store_true",
            help="Exchange the same code twice and fail unless the second exchange is rejected.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        config = _config_status(options)
        result = {
            "contract_version": "google_oauth_code_smoke.v1",
            "status": "pass" if config["ready"] else "fail",
            "config": config,
            "exchange": None,
            "replay_check": None,
        }

        code = _authorization_code(options)
        if code:
            login_payload = {
                "provider": "google",
                "client_id": getattr(settings, "GOOGLE_CLIENT_ID", ""),
                "code": code,
                "purpose": "LOGIN",
                "scope": options["scope"],
                "guest_id": options["guest_id"],
                "session_id": options["session_id"],
                "redirect_uri": options["redirect_uri"] or getattr(settings, "GOOGLE_POPUP_REDIRECT_URI", ""),
            }
            request_headers = {
                "X-Requested-With": "XmlHttpRequest",
                "Origin": options["redirect_uri"]
                or getattr(settings, "GOOGLE_POPUP_REDIRECT_URI", ""),
            }
            status, payload = create_google_code_login(
                login_payload,
                request_headers=request_headers,
            )
            payload.pop("_private_oauth_tokens", None)
            persistence = None
            if status < 400:
                persistence = persist_current_auth_subject(payload, session_id=options["session_id"])
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
            elif options["verify_replay_rejection"]:
                replay_status, replay_payload = create_google_code_login(
                    login_payload,
                    request_headers=request_headers,
                )
                result["replay_check"] = _safe_replay_metadata(replay_status, replay_payload)
                if result["replay_check"]["status"] != "rejected":
                    result["status"] = "fail"
        elif options["require_exchange"]:
            result["status"] = "fail"
            result["exchange"] = {"error": {"reason": "authorization_code_required"}}
        elif options["verify_replay_rejection"]:
            result["status"] = "fail"
            result["replay_check"] = {
                "status": "not_run",
                "error": {"reason": "authorization_code_required"},
            }

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
    invalid = []
    if required["GOOGLE_CLIENT_ID"] and not is_google_web_client_id(required["GOOGLE_CLIENT_ID"]):
        invalid.append("GOOGLE_CLIENT_ID")
    if required["GOOGLE_POPUP_REDIRECT_URI"] and not normalize_google_web_origin(
        required["GOOGLE_POPUP_REDIRECT_URI"]
    ):
        invalid.append("GOOGLE_POPUP_REDIRECT_URI")
    token_endpoint = getattr(settings, "GOOGLE_TOKEN_ENDPOINT", "")
    userinfo_endpoint = getattr(settings, "GOOGLE_USERINFO_ENDPOINT", "")
    if not is_official_google_token_endpoint(token_endpoint):
        invalid.append("GOOGLE_TOKEN_ENDPOINT")
    if not is_official_google_userinfo_endpoint(userinfo_endpoint):
        invalid.append("GOOGLE_USERINFO_ENDPOINT")
    return {
        "ready": not missing and not placeholders and not invalid,
        "missing": missing,
        "placeholders": placeholders,
        "invalid": invalid,
        "redirect_uri": redirect_uri,
        "token_endpoint": token_endpoint,
        "userinfo_endpoint": userinfo_endpoint,
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


def _authorization_code(options: dict) -> str:
    code = str(os.environ.get("GOOGLE_OAUTH_SMOKE_CODE") or "").strip()
    if not code and options.get("prompt_code"):
        code = getpass("One-time Google authorization code: ").strip()
    return code


def _safe_replay_metadata(status: int, payload: dict) -> dict:
    error = payload.get("error") or {}
    auth_error = error.get("auth") or {}
    reason = auth_error.get("reason") or error.get("reason")
    verified_rejection = status == 401 and reason == "google_token_exchange_failed:400"
    replay_status = "accepted" if status < 400 else "rejected" if verified_rejection else "inconclusive"
    return {
        "status": replay_status,
        "http_status": status,
        "error": {
            "code": error.get("code"),
            "reason": reason,
        },
    }


def _text_result(result: dict) -> str:
    config = result["config"]
    lines = [
        f"Google OAuth code-flow smoke: {result['status']}",
        f"- config_ready: {config['ready']}",
        f"- missing: {', '.join(config['missing']) if config['missing'] else '-'}",
        f"- placeholders: {', '.join(config.get('placeholders') or []) if config.get('placeholders') else '-'}",
        f"- invalid: {', '.join(config.get('invalid') or []) if config.get('invalid') else '-'}",
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
    replay_check = result.get("replay_check")
    if replay_check:
        lines.extend(
            [
                f"- replay_status: {replay_check.get('status')}",
                f"- replay_http_status: {replay_check.get('http_status')}",
            ]
        )
    return "\n".join(lines)
