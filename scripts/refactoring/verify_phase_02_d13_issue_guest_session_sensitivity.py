#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D13 IssueGuestSession boundary."""

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
    REPO_ROOT / "tmp" / "phase-02-d13-sensitivity-evidence.json"
)
TEST_MODULE: Final = "chatbot.test_phase_02_issue_guest_session_use_case"
TEST_CASE: Final = TEST_MODULE + ".IssueGuestSessionSecurityContractTests."
TARGETS: Final = {
    "view_application_bypass": (
        TEST_CASE + "test_guest_session_delegates_to_issue_guest_session_application"
    ),
    "expired_guest_reactivation_bypass": (
        TEST_CASE + "test_expired_persisted_guest_is_not_reactivated"
    ),
    "merged_guest_reactivation_bypass": (
        TEST_CASE + "test_merged_persisted_guest_is_not_reactivated"
    ),
    "raw_audit_payload_bypass": (
        TEST_CASE + "test_guest_session_does_not_persist_request_secret_markers"
    ),
    "non_object_transport_normalization_bypass": (
        TEST_CASE + "test_truthy_non_object_json_normalizes_to_a_new_unbound_guest"
    ),
    "invalid_credential_unbound_contract_bypass": (
        TEST_CASE
        + "test_invalid_credential_issues_a_new_unbound_guest_without_adopting_body_identity"
    ),
    "foreign_session_binding_authorization_bypass": (
        TEST_CASE + "test_foreign_guest_session_binding_remains_forbidden"
    ),
    "guest_state_401_mapping_bypass": (
        TEST_CASE + "test_expired_persisted_guest_is_not_reactivated"
    ),
    "session_binding_403_mapping_bypass": (
        TEST_CASE + "test_foreign_guest_session_binding_remains_forbidden"
    ),
    "persistence_503_mapping_bypass": (
        "chatbot.test_guest_session_runtime_contract.GuestSessionRuntimeContractTests."
        "test_guest_session_returns_structured_503_when_persistence_store_is_unavailable"
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
repositories = repo_root / "backend" / "chatbot" / "repositories.py"
auth_service = repo_root / "app" / "services" / "auth_session_service.py"
application = repo_root / "app" / "application" / "auth" / "issue_guest_session.py"

if mutation_name == "view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_issue_guest_session(\n",
        "        from app.application.auth.issue_guest_session import execute_issue_guest_session as _direct_issue_guest_session\n        result = _direct_issue_guest_session(\n",
    )
elif mutation_name == "expired_guest_reactivation_bypass":
    mutation = mutate_once(
        repositories,
        """def _require_issuable_guest_identity(guest: GuestIdentity) -> None:
    \"\"\"Block terminal or expired persisted identities from being reissued.\"\"\"

    if guest.status == GuestIdentityStatus.EXPIRED or (
        guest.expires_at and guest.expires_at <= timezone.now()
    ):
""",
        """def _require_issuable_guest_identity(guest: GuestIdentity) -> None:
    \"\"\"Block terminal or expired persisted identities from being reissued.\"\"\"

    if False:
""",
    )
elif mutation_name == "merged_guest_reactivation_bypass":
    mutation = mutate_once(
        repositories,
        "    if guest.status != GuestIdentityStatus.ACTIVE:\n        raise GuestIdentityStateError(\"guest_inactive\")\n",
        "    if False:\n        raise GuestIdentityStateError(\"guest_inactive\")\n",
    )
elif mutation_name == "raw_audit_payload_bypass":
    mutation = mutate_once(
        repositories,
        """            metadata={
                \"source\": \"auth_guest_session\",
                \"chat_session_id\": chat_session.session_id if chat_session else None,
            },
""",
        """            metadata={
                \"source\": \"auth_guest_session\",
                \"chat_session_id\": chat_session.session_id if chat_session else None,
                \"raw_payload\": {\"access_token\": \"d13-access-token-marker\"},
            },
""",
    )
elif mutation_name == "non_object_transport_normalization_bypass":
    mutation = mutate_once(
        views,
        "    if not isinstance(body, dict):\n        body = {}\n",
        "    if False:\n        body = {}\n",
    )
elif mutation_name == "invalid_credential_unbound_contract_bypass":
    mutation = mutate_once(
        auth_service,
        "    session_id = _text(payload.get(\"session_id\")) if credential_valid else \"\"\n",
        "    session_id = _text(payload.get(\"session_id\"))\n",
    )
elif mutation_name == "foreign_session_binding_authorization_bypass":
    mutation = mutate_once(
        repositories,
        """        if existing_guest_id:
            if not normalized_guest_id or existing_guest_id != normalized_guest_id:
                raise SessionBindingError(\"guest_session_binding_mismatch\")
            return session
""",
        """        if existing_guest_id:
            if not normalized_guest_id or existing_guest_id != normalized_guest_id:
                return session
            return session
""",
    )
elif mutation_name == "guest_state_401_mapping_bypass":
    mutation = mutate_once(
        application,
        """    except GuestIdentityStateError as error:
        raise IssueGuestSessionInvalid(
""",
        """    except GuestIdentityStateError as error:
        raise IssueGuestSessionPersistenceUnavailable(
""",
    )
elif mutation_name == "session_binding_403_mapping_bypass":
    mutation = mutate_once(
        application,
        """    except SessionBindingError as error:
        raise IssueGuestSessionAccessDenied(
""",
        """    except SessionBindingError as error:
        raise IssueGuestSessionInvalid(
""",
    )
elif mutation_name == "persistence_503_mapping_bypass":
    mutation = mutate_once(
        application,
        """    except DatabaseError as error:
        raise IssueGuestSessionPersistenceUnavailable(
""",
        """    except DatabaseError as error:
        raise IssueGuestSessionInvalid(
""",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    import app.application.auth.issue_guest_session as issue_guest_session
    import app.services.auth_session_service as auth_session_service
    import chatbot.repositories as chatbot_repositories
    import chatbot.urls as chatbot_urls
    import chatbot.views as chat_views
    import config.urls as config_urls

    importlib.reload(auth_session_service)
    importlib.reload(chatbot_repositories)
    importlib.reload(issue_guest_session)
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
        and len(mutations) == 10
        and all(
            item.exit_code != 0 and item.failure_kind == "assertion"
            for item in mutations
        )
        and source_restored
        and working_tree_unchanged
        and residual_diff_zero
    )
    return {
        "contract_version": "phase_02_d13_sensitivity.v1",
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
    requested_head = os.environ.get("PHASE_02_D13_SENSITIVITY_HEAD", "").strip()
    head = requested_head or actual_head
    try:
        if requested_head and requested_head != actual_head:
            raise SensitivityError(
                "stale D13 sensitivity head: requested evidence head does not match checkout"
            )
        original_exit_code = _run(
            [sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]
        ).returncode
        if original_exit_code:
            raise SensitivityError(
                f"original D13 characterization suite failed: {original_exit_code}"
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
            "PHASE_02_D13_SENSITIVITY_EVIDENCE_PATH",
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
