"""Audit GitHub issue metadata used by the project workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import yaml


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / ".github" / "issue-metadata-policy.yml"


def load_policy(path: Path) -> dict[str, Any]:
    """Load the versioned issue metadata policy."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("issue metadata policy must be a mapping")
    if payload.get("version") != "issue_metadata_policy.v1":
        raise ValueError("unsupported issue metadata policy version")
    return payload


DEFAULT_POLICY = load_policy(DEFAULT_POLICY_PATH)


def make_github_requester(
    *,
    token: str,
    api_version: str = str(DEFAULT_POLICY["api"]["version"]),
    api_url: str = "https://api.github.com",
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Callable[[str], list[dict[str, Any]]]:
    """Build an authenticated GitHub REST JSON requester."""
    base_url = api_url.rstrip("/")

    def request_json(path: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            f"{base_url}/{path.lstrip('/')}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": api_version,
                "User-Agent": "skn27-issue-metadata-audit",
            },
        )
        with opener(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"expected a JSON list from {path}")
        return payload

    return request_json


def normalize_field_values(raw_values: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize GitHub issue field API payloads into a name/value mapping."""
    normalized: dict[str, Any] = {}
    for item in raw_values:
        field_name = str(item.get("issue_field_name") or "").strip()
        if not field_name:
            continue
        data_type = item.get("data_type")
        if data_type == "single_select":
            option = item.get("single_select_option") or {}
            normalized[field_name] = option.get("name")
        elif data_type == "multi_select":
            normalized[field_name] = [
                option.get("name")
                for option in item.get("multi_select_options") or []
                if option.get("name")
            ]
        else:
            normalized[field_name] = item.get("value")
    return normalized


def load_open_issues(
    repository: str,
    request_json: Callable[[str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Load open issues and attach their organization issue field values."""
    issues: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = request_json(
            f"/repos/{repository}/issues?state=open&per_page=100&page={page}"
        )
        for source_issue in batch:
            if source_issue.get("pull_request"):
                continue
            issue = dict(source_issue)
            raw_fields = request_json(
                f"/repos/{repository}/issues/{issue['number']}/issue-field-values?per_page=100"
            )
            issue["issue_field_values"] = normalize_field_values(raw_fields)
            issues.append(issue)
        if len(batch) < 100:
            break
        page += 1
    return issues


def audit_issues(
    issues: list[dict[str, Any]],
    *,
    policy: dict[str, Any] = DEFAULT_POLICY,
) -> list[dict[str, Any]]:
    """Audit actionable open issues and return only failures."""
    failures: list[dict[str, Any]] = []
    scope = policy.get("scope") or {}
    included_states = {
        str(state).lower() for state in scope.get("states") or ["open"]
    }
    for issue in issues:
        if str(issue.get("state") or "").lower() not in included_states:
            continue
        if scope.get("exclude_pull_requests", True) and issue.get("pull_request"):
            continue
        violations = audit_issue(issue, policy=policy)
        if violations:
            failures.append(
                {
                    "number": issue.get("number"),
                    "title": issue.get("title") or "",
                    "violations": violations,
                }
            )
    return failures


def render_report(failures: list[dict[str, Any]], *, repository: str) -> str:
    """Render a Markdown report suitable for logs and job summaries."""
    if not failures:
        return "## 이슈 메타데이터 품질 감사\n\n✅ 열린 실행 이슈의 필수 메타데이터가 모두 설정되어 있습니다."

    lines = [
        "## 이슈 메타데이터 품질 감사",
        "",
        f"❌ {len(failures)}개 열린 이슈에서 필수 메타데이터 누락을 발견했습니다.",
        "",
    ]
    for item in failures:
        number = item["number"]
        title = str(item.get("title") or "").replace("\n", " ")
        url = f"https://github.com/{repository}/issues/{number}"
        violations = ", ".join(
            f"`{violation}`" for violation in item.get("violations") or []
        )
        lines.append(f"- [#{number}]({url}) {title}: {violations}")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> int:
    """Run the repository metadata audit command."""
    parser = argparse.ArgumentParser(
        description="Audit required metadata on all open GitHub issues."
    )
    parser.add_argument(
        "--repository",
        help="GitHub repository in owner/name form (defaults to GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--api-url",
        default="https://api.github.com",
        help="GitHub REST API base URL.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="Versioned issue metadata policy YAML file.",
    )
    args = parser.parse_args(argv)

    environment = os.environ if environ is None else environ
    repository = str(args.repository or environment.get("GITHUB_REPOSITORY") or "")
    if repository.count("/") != 1:
        parser.error("--repository or GITHUB_REPOSITORY must be owner/name")
    token = environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN") or ""
    if not token:
        parser.error("GH_TOKEN or GITHUB_TOKEN is required")

    policy = load_policy(args.policy)
    request_json = make_github_requester(
        token=token,
        api_version=str(policy["api"]["version"]),
        api_url=args.api_url,
        opener=opener,
    )
    failures = audit_issues(
        load_open_issues(repository, request_json),
        policy=policy,
    )
    report = render_report(failures, repository=repository)
    print(report)

    summary_path = environment.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(f"{report}\n")
    return 1 if failures else 0


def audit_issue(
    issue: dict[str, Any],
    *,
    policy: dict[str, Any] = DEFAULT_POLICY,
) -> list[str]:
    """Return metadata violations for one normalized issue."""
    violations: list[str] = []
    required = policy["required"]

    if len(issue.get("assignees") or []) < int(required.get("assignee_min_count", 0)):
        violations.append("missing_assignee")

    labels = {
        str(label.get("name") if isinstance(label, dict) else label).strip()
        for label in issue.get("labels") or []
    }
    for label_name in required.get("exact_labels") or []:
        if label_name not in labels:
            violations.append(f"missing_label:{label_name}")
    for prefix in required.get("label_prefixes") or []:
        if not any(label.startswith(prefix) for label in labels):
            violations.append(f"missing_label:{prefix}*")
    for prefix in required.get("exclusive_label_prefixes") or []:
        matching_labels = [label for label in labels if label.startswith(prefix)]
        if len(matching_labels) > 1:
            violations.append(f"conflicting_labels:{prefix}*")

    if required.get("milestone") and not issue.get("milestone"):
        violations.append("missing_milestone")
    if required.get("issue_type") and not issue.get("type"):
        violations.append("missing_type")

    field_values = issue.get("issue_field_values") or {}
    for field_name in required.get("issue_fields") or []:
        if not _has_value(field_values.get(field_name)):
            violations.append(f"missing_field:{field_name}")

    body = str(issue.get("body") or "")
    body_dates: dict[str, str] = {}
    for date_label in required.get("body_dates") or []:
        match = re.search(
            rf"{re.escape(date_label)}\s*:\s*(\d{{4}}-\d{{2}}-\d{{2}})",
            body,
        )
        if match is None:
            violations.append(f"missing_body_date:{date_label}")
            continue
        value = match.group(1)
        body_dates[date_label] = value
        if not _is_iso_date(value):
            violations.append(f"invalid_body_date:{date_label}")

    consistency = policy.get("consistency") or {}
    body_to_field = consistency.get("body_to_field") or {}
    date_fields = set(body_to_field.values())
    milestone_due_field = consistency.get("milestone_due_field")
    if milestone_due_field:
        date_fields.add(milestone_due_field)
    for field_name in date_fields:
        value = field_values.get(field_name)
        if _has_value(value) and not _is_iso_date(str(value)):
            violations.append(f"invalid_field_date:{field_name}")

    for body_label, field_name in body_to_field.items():
        body_value = body_dates.get(body_label)
        field_value = field_values.get(field_name)
        if (
            body_value
            and _is_iso_date(body_value)
            and _has_value(field_value)
            and _is_iso_date(str(field_value))
            and body_value != str(field_value)
        ):
            violations.append(f"date_mismatch:{body_label}:{field_name}")

    milestone = issue.get("milestone") or {}
    milestone_due_on = milestone.get("due_on") if isinstance(milestone, dict) else None
    milestone_field_value = field_values.get(milestone_due_field)
    if (
        milestone_due_field
        and milestone_due_on
        and _has_value(milestone_field_value)
        and _is_iso_date(str(milestone_field_value))
        and str(milestone_due_on)[:10] != str(milestone_field_value)
    ):
        violations.append(f"milestone_due_mismatch:{milestone_due_field}")

    return violations


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
