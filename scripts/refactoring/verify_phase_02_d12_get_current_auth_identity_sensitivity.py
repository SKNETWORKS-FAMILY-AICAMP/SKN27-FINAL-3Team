#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D12 GetCurrentAuthIdentity boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = (
    REPO_ROOT / "tmp" / "phase-02-d12-sensitivity-evidence.json"
)
TEST_MODULE: Final = "chatbot.test_phase_02_get_current_auth_identity_use_case"
TARGETS: Final = {
    "view_application_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_auth_me_delegates_to_execute_get_current_auth_identity"
    ),
    "anonymous_transport_contract_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_openapi_requires_bearer_or_signed_guest_credential"
    ),
    "guest_identity_source_mismatch_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_conflicting_header_and_query_guest_ids_fail_closed"
    ),
    "persisted_guest_state_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_existing_expired_guest_identity_fails_closed"
    ),
    "persisted_auth_session_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_application_rejects_unpersisted_jwt_before_public_projection"
    ),
    "session_binding_authorization_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_persisted_session_binding_error_maps_to_forbidden"
    ),
    "persistence_failure_mapping_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_persistence_database_error_maps_to_retryable_provider_unavailable"
    ),
    "history_event_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_successful_persistence_records_auth_me_checked_history_after_auth_event"
    ),
    "private_projection_bypass": (
        TEST_MODULE
        + ".GetCurrentAuthIdentitySecurityContractTests."
        + "test_public_response_excludes_credentials_and_raw_claims"
    ),
}


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
test_id = sys.argv[2]
mutation_name = sys.argv[3]
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.test.runner import DiscoverRunner
from django.urls import clear_url_caches


def read_source(path):
    original = path.read_bytes()
    encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    return original, encoding, original.decode(encoding).replace("\r\n", "\n")


@contextmanager
def mutate_once(path, old, new):
    original, encoding, source = read_source(path)
    if source.count(old) != 1:
        raise RuntimeError(f"mutation anchor was not unique: {path.name}")
    path.write_bytes(source.replace(old, new).encode(encoding))
    try:
        yield
    finally:
        path.write_bytes(original)


views = repo_root / "backend" / "chatbot" / "views.py"
route_specs = repo_root / "app" / "contracts" / "api_route_specs.py"
auth_service = repo_root / "app" / "services" / "auth_session_service.py"
repositories = repo_root / "backend" / "chatbot" / "repositories.py"
application = repo_root / "app" / "application" / "auth" / "get_current_identity.py"

if mutation_name == "view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_get_current_auth_identity(query)\n",
        "        from app.application.auth.get_current_identity import execute_get_current_auth_identity as _direct_execute\n        result = _direct_execute(query)\n",
    )
elif mutation_name == "anonymous_transport_contract_bypass":
    mutation = mutate_once(
        route_specs,
        '        security_requirements=(\n            {"bearerAuth": ()},\n            {"guestCredentialAuth": ()},\n        ),\n    ),\n    RouteSpec(\n        operation_id="getResumeManifest",\n',
        '        security_requirements=(\n            {"bearerAuth": ()},\n        ),\n    ),\n    RouteSpec(\n        operation_id="getResumeManifest",\n',
    )
elif mutation_name == "guest_identity_source_mismatch_bypass":
    mutation = mutate_once(
        auth_service,
        '    if (\n        normalized_header_guest_id\n        and normalized_query_guest_id\n        and normalized_header_guest_id != normalized_query_guest_id\n    ):\n        return None, "guest_identity_source_mismatch"\n',
        '    if False:\n        return None, "guest_identity_source_mismatch"\n',
    )
elif mutation_name == "persisted_guest_state_bypass":
    mutation = mutate_once(
        repositories,
        '    if guest.status == GuestIdentityStatus.EXPIRED or (\n        guest.expires_at and guest.expires_at <= timezone.now()\n    ):\n        return {\n            "guest_id": normalized_guest_id,\n            "reason": "guest_expired",\n            "status": guest.status,\n        }\n    if guest.status != GuestIdentityStatus.ACTIVE:\n        return {\n            "guest_id": normalized_guest_id,\n            "reason": "guest_inactive",\n            "status": guest.status,\n        }\n',
        '    if False:\n        return {\n            "guest_id": normalized_guest_id,\n            "reason": "guest_expired",\n            "status": guest.status,\n        }\n    if False:\n        return {\n            "guest_id": normalized_guest_id,\n            "reason": "guest_inactive",\n            "status": guest.status,\n        }\n',
    )
elif mutation_name == "persisted_auth_session_bypass":
    mutation = mutate_once(
        application,
        '    except AuthSessionStateError as error:\n        raise CurrentAuthIdentityInvalid(\n            build_auth_error("token_invalid", reason=error.reason)\n        ) from error\n',
        '    except AuthSessionStateError:\n        persistence = {"backend": "mutation", "status": "saved"}\n',
    )
elif mutation_name == "session_binding_authorization_bypass":
    mutation = mutate_once(
        application,
        '    except SessionBindingError as error:\n        raise CurrentAuthIdentityAccessDenied(\n            build_auth_error("forbidden", reason=error.reason)\n        ) from error\n',
        '    except SessionBindingError as error:\n        raise CurrentAuthIdentityInvalid(\n            build_auth_error("forbidden", reason=error.reason)\n        ) from error\n',
    )
elif mutation_name == "persistence_failure_mapping_bypass":
    mutation = mutate_once(
        application,
        '    except SessionBindingError as error:\n        raise CurrentAuthIdentityAccessDenied(\n            build_auth_error("forbidden", reason=error.reason)\n        ) from error\n    except DatabaseError as error:\n        raise CurrentAuthIdentityPersistenceUnavailable(\n            _persistence_unavailable_payload()\n        ) from error\n',
        '    except SessionBindingError as error:\n        raise CurrentAuthIdentityAccessDenied(\n            build_auth_error("forbidden", reason=error.reason)\n        ) from error\n    except DatabaseError as error:\n        raise CurrentAuthIdentityInvalid(\n            _persistence_unavailable_payload()\n        ) from error\n',
    )
elif mutation_name == "history_event_bypass":
    mutation = mutate_once(
        application,
        "    _record_history_best_effort(query, payload)\n",
        "    pass\n",
    )
elif mutation_name == "private_projection_bypass":
    mutation = mutate_once(
        application,
        "    return {field: record[field] for field in fields if field in record}\n",
        '    return {**{field: record[field] for field in fields if field in record}, "access_token": "sensitivity-private-marker"}\n',
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    import app.application.auth.get_current_identity as get_current_identity
    import app.contracts.api_route_specs as api_route_specs
    import app.contracts.openapi_v1 as openapi_v1
    import app.services.auth_session_service as auth_session_service
    import chatbot.repositories as chatbot_repositories
    import chatbot.urls as chatbot_urls
    import chatbot.views as chat_views
    import config.urls as config_urls

    importlib.reload(auth_session_service)
    importlib.reload(chatbot_repositories)
    importlib.reload(api_route_specs)
    importlib.reload(openapi_v1)
    importlib.reload(get_current_identity)
    importlib.reload(chat_views)
    importlib.reload(chatbot_urls)
    importlib.reload(config_urls)
    clear_url_caches()
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests([test_id])
raise SystemExit(0 if failures == 0 else 1)
'''


class SensitivityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MutationOutcome:
    name: str
    exit_code: int
    failure_kind: str


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _git(*args: str) -> str:
    result = _run(["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *args])
    if result.returncode:
        raise SensitivityError(f"git {' '.join(args)} failed")
    return result.stdout


def failure_kind(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in result.stdout:
        raise SensitivityError("assertion mismatch: mutation did not fail by assertion")
    return "assertion"


def _run_mutation(name: str, target: str) -> MutationOutcome:
    result = _run(
        [sys.executable, "-c", MUTATION_CHILD_SCRIPT, str(REPO_ROOT), target, name]
    )
    return MutationOutcome(name, result.returncode, failure_kind(result))


def build_evidence(
    *,
    head: str,
    actual_head: str,
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    source_restored: bool,
    working_tree_unchanged: bool,
    residual_diff_zero: bool,
) -> dict[str, Any]:
    passed = (
        bool(head)
        and head == actual_head
        and original_exit_code == 0
        and tuple(item.name for item in mutations) == tuple(TARGETS)
        and all(
            item.exit_code != 0 and item.failure_kind == "assertion"
            for item in mutations
        )
        and source_restored
        and working_tree_unchanged
        and residual_diff_zero
    )
    return {
        "contract_version": "phase_02_d12_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "actual_head": actual_head,
        "original": {"exit_code": original_exit_code},
        "mutations": [item.__dict__ for item in mutations],
        "source_restored": source_restored,
        "working_tree_unchanged": working_tree_unchanged,
        "residual_diff_zero": residual_diff_zero,
    }


def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    actual_head = _git("rev-parse", "HEAD").strip()
    requested_head = os.environ.get("PHASE_02_D12_SENSITIVITY_HEAD", "").strip()
    head = requested_head or actual_head
    try:
        if requested_head and requested_head != actual_head:
            raise SensitivityError(
                "stale D12 sensitivity head: requested evidence head does not match checkout"
            )
        original_exit_code = _run(
            [sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]
        ).returncode
        if original_exit_code:
            raise SensitivityError(
                f"original D12 characterization suite failed: {original_exit_code}"
            )
        outcomes = tuple(
            _run_mutation(name, target) for name, target in TARGETS.items()
        )
    except (OSError, SensitivityError) as exc:
        error = str(exc)
    after = _git("status", "--porcelain")
    residual_diff_zero = (
        _run(
            [
                "git",
                "-c",
                f"safe.directory={REPO_ROOT.as_posix()}",
                "diff",
                "--no-ext-diff",
                "--exit-code",
            ]
        ).returncode
        == 0
    )
    evidence = build_evidence(
        head=head,
        actual_head=actual_head,
        original_exit_code=original_exit_code,
        mutations=outcomes,
        source_restored=before == after,
        working_tree_unchanged=before == after,
        residual_diff_zero=residual_diff_zero,
    )
    if error:
        evidence["error"] = error
    path = Path(
        os.environ.get(
            "PHASE_02_D12_SENSITIVITY_EVIDENCE_PATH",
            DEFAULT_EVIDENCE_PATH,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

