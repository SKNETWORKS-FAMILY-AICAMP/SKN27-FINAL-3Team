from __future__ import annotations

import importlib
import json
import os
from io import StringIO

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.core.management import call_command
from django.core.management.base import CommandError


SEED_VERSION = (
    "sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db"
)


def _run_command(name: str, *args: str) -> tuple[dict, str]:
    output = StringIO()
    call_command(name, *args, stdout=output)
    raw = output.getvalue()
    return json.loads(raw), raw


def _assert_credential_safe(payload: dict, raw: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "password" not in serialized
    assert "dsn" not in serialized
    assert "password" not in raw.lower()
    assert "dsn" not in raw.lower()


def test_stage_command_emits_credential_safe_json(monkeypatch) -> None:
    module = importlib.import_module(
        "chatbot.management.commands.stage_precedent_newplusplus_seed"
    )
    captured = {}

    def fake_stage_seed(**kwargs):
        captured.update(kwargs)
        return {
            "contract_version": "precedent_newplusplus_seed.v1",
            "status": "staged",
            "seed_version": SEED_VERSION,
            "block_count": 3339,
            "case_count": 825,
            "embedding_dimension": 2560,
        }

    monkeypatch.setattr(module, "stage_seed", fake_stage_seed)

    payload, raw = _run_command("stage_precedent_newplusplus_seed")

    assert payload["contract_version"] == "precedent_newplusplus_seed.v1"
    assert payload["status"] == "staged"
    assert captured["embeddings_path"] == module.DEFAULT_EMBEDDINGS
    assert captured["metadata_path"] == module.DEFAULT_METADATA
    assert captured["connection_factory"] is module.connect_database
    _assert_credential_safe(payload, raw)


def test_stage_command_redacts_unexpected_runtime_errors(monkeypatch) -> None:
    module = importlib.import_module(
        "chatbot.management.commands.stage_precedent_newplusplus_seed"
    )

    def fail(**_kwargs):
        raise RuntimeError("password=private dsn=postgresql://private")

    monkeypatch.setattr(module, "stage_seed", fail)

    with pytest.raises(CommandError) as exc_info:
        _run_command("stage_precedent_newplusplus_seed")

    message = str(exc_info.value).lower()
    assert "password" not in message
    assert "dsn" not in message
    assert "password=private" not in message
    assert "postgresql://private" not in message


def test_promote_command_requires_both_versions() -> None:
    importlib.import_module(
        "chatbot.management.commands.promote_precedent_newplusplus_seed"
    )
    with pytest.raises(CommandError):
        _run_command("promote_precedent_newplusplus_seed")
    with pytest.raises(CommandError):
        _run_command(
            "promote_precedent_newplusplus_seed",
            "--seed-version",
            SEED_VERSION,
        )


def test_promote_command_accepts_explicit_none_for_initial_activation(
    monkeypatch,
) -> None:
    module = importlib.import_module(
        "chatbot.management.commands.promote_precedent_newplusplus_seed"
    )
    captured = {}

    def fake_promote_seed(**kwargs):
        captured.update(kwargs)
        return {
            "contract_version": "precedent_newplusplus_seed.v1",
            "status": "promoted",
            "active_seed_version": SEED_VERSION,
            "previous_seed_version": None,
        }

    monkeypatch.setattr(module, "promote_seed", fake_promote_seed)

    payload, raw = _run_command(
        "promote_precedent_newplusplus_seed",
        "--seed-version",
        SEED_VERSION,
        "--expected-active-seed-version",
        "none",
    )

    assert captured["seed_version"] == SEED_VERSION
    assert captured["expected_active_seed_version"] is None
    assert captured["connection_factory"] is module.connect_database
    assert payload["status"] == "promoted"
    _assert_credential_safe(payload, raw)


def test_rollback_command_requires_expected_active_version() -> None:
    importlib.import_module(
        "chatbot.management.commands.rollback_precedent_newplusplus_seed"
    )
    with pytest.raises(CommandError):
        _run_command("rollback_precedent_newplusplus_seed")


def test_rollback_command_emits_credential_safe_json(monkeypatch) -> None:
    module = importlib.import_module(
        "chatbot.management.commands.rollback_precedent_newplusplus_seed"
    )

    def fake_rollback_seed(**kwargs):
        assert kwargs["expected_active_seed_version"] == SEED_VERSION
        assert kwargs["connection_factory"] is module.connect_database
        return {
            "contract_version": "precedent_newplusplus_seed.v1",
            "status": "rolled_back",
            "active_seed_version": "sha256:" + "b" * 64,
            "previous_seed_version": SEED_VERSION,
        }

    monkeypatch.setattr(module, "rollback_seed", fake_rollback_seed)

    payload, raw = _run_command(
        "rollback_precedent_newplusplus_seed",
        "--expected-active-seed-version",
        SEED_VERSION,
    )

    assert payload["status"] == "rolled_back"
    _assert_credential_safe(payload, raw)


def test_verify_command_is_read_only_and_credential_safe(monkeypatch) -> None:
    module = importlib.import_module(
        "chatbot.management.commands.verify_precedent_newplusplus_seed"
    )
    calls = []

    def fake_verify_seed(**kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "precedent_newplusplus_seed.v1",
            "status": "verified",
            "seed_version": SEED_VERSION,
            "release_status": "active",
            "block_count": 3339,
            "case_count": 825,
            "embedding_dimension": 2560,
        }

    monkeypatch.setattr(module, "verify_seed", fake_verify_seed)

    payload, raw = _run_command(
        "verify_precedent_newplusplus_seed",
        "--expected-seed-version",
        SEED_VERSION,
    )

    assert calls == [
        {
            "expected_seed_version": SEED_VERSION,
            "connection_factory": module.connect_database,
        }
    ]
    assert payload["status"] == "verified"
    _assert_credential_safe(payload, raw)


def test_verify_command_requires_expected_seed_version() -> None:
    importlib.import_module(
        "chatbot.management.commands.verify_precedent_newplusplus_seed"
    )
    with pytest.raises(CommandError):
        _run_command("verify_precedent_newplusplus_seed")
