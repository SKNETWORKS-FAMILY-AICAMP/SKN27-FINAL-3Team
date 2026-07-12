"""Audit GitHub issue metadata used by the project workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = ("Priority", "Status", "Start date", "Target date")
REQUIRED_BODY_DATES = ("기준일", "시작일", "목표일")


def make_github_requester(
    *,
    token: str,
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
                "X-GitHub-Api-Version": "2026-03-10",
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


def audit_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Audit actionable open issues and return only failures."""
    failures: list[dict[str, Any]] = []
    for issue in issues:
        if str(issue.get("state") or "").lower() != "open":
            continue
        if issue.get("pull_request"):
            continue
        violations = audit_issue(issue)
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
    args = parser.parse_args(argv)

    environment = os.environ if environ is None else environ
    repository = str(args.repository or environment.get("GITHUB_REPOSITORY") or "")
    if repository.count("/") != 1:
        parser.error("--repository or GITHUB_REPOSITORY must be owner/name")
    token = environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN") or ""
    if not token:
        parser.error("GH_TOKEN or GITHUB_TOKEN is required")

    request_json = make_github_requester(
        token=token,
        api_url=args.api_url,
        opener=opener,
    )
    failures = audit_issues(load_open_issues(repository, request_json))
    report = render_report(failures, repository=repository)
    print(report)

    summary_path = environment.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(f"{report}\n")
    return 1 if failures else 0


def audit_issue(issue: dict[str, Any]) -> list[str]:
    """Return metadata violations for one normalized issue."""
    violations: list[str] = []

    if not issue.get("assignees"):
        violations.append("missing_assignee")

    labels = {
        str(label.get("name") if isinstance(label, dict) else label).strip()
        for label in issue.get("labels") or []
    }
    if "wbs" not in labels:
        violations.append("missing_label:wbs")
    if not any(label.startswith("domain:") for label in labels):
        violations.append("missing_label:domain:*")
    if not any(label.startswith("phase:") for label in labels):
        violations.append("missing_label:phase:*")

    if not issue.get("milestone"):
        violations.append("missing_milestone")
    if not issue.get("type"):
        violations.append("missing_type")

    field_values = issue.get("issue_field_values") or {}
    for field_name in REQUIRED_FIELDS:
        if not _has_value(field_values.get(field_name)):
            violations.append(f"missing_field:{field_name}")

    body = str(issue.get("body") or "")
    for date_label in REQUIRED_BODY_DATES:
        if not re.search(rf"{re.escape(date_label)}\s*:\s*\d{{4}}-\d{{2}}-\d{{2}}", body):
            violations.append(f"missing_body_date:{date_label}")

    return violations


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
