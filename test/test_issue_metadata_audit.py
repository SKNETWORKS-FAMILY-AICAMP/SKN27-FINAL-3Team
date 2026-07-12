import json
from pathlib import Path

from scripts.issue_metadata_audit import (
    audit_issue,
    audit_issues,
    load_open_issues,
    main,
    make_github_requester,
    normalize_field_values,
    render_report,
)


def test_complete_open_issue_has_no_metadata_violations() -> None:
    issue = {
        "number": 180,
        "state": "open",
        "title": "[개인 일정] 이혜림 - v2 통합",
        "body": "- 기준일: 2026-07-12\n- 시작일: 2026-07-12\n- 목표일: 2026-08-04",
        "assignees": [{"login": "hi20260204-maker"}],
        "labels": [
            {"name": "wbs"},
            {"name": "phase:final"},
            {"name": "domain:qa"},
        ],
        "milestone": {"title": "2026-08-04 최종 마무리"},
        "type": {"name": "Task"},
        "issue_field_values": {
            "Priority": "Urgent",
            "Status": "In progress",
            "Start date": "2026-07-12",
            "Target date": "2026-08-04",
        },
    }

    assert audit_issue(issue) == []


def test_missing_required_metadata_reports_each_quality_gate() -> None:
    issue = {
        "number": 181,
        "state": "open",
        "title": "메타데이터가 비어 있는 실행 이슈",
        "body": "일정 정보 없음",
        "assignees": [],
        "labels": [],
        "milestone": None,
        "type": None,
        "issue_field_values": {},
    }

    assert audit_issue(issue) == [
        "missing_assignee",
        "missing_label:wbs",
        "missing_label:domain:*",
        "missing_label:phase:*",
        "missing_milestone",
        "missing_type",
        "missing_field:Priority",
        "missing_field:Status",
        "missing_field:Start date",
        "missing_field:Target date",
        "missing_body_date:기준일",
        "missing_body_date:시작일",
        "missing_body_date:목표일",
    ]


def test_rest_issue_field_values_are_normalized_by_field_name() -> None:
    raw_values = [
        {
            "issue_field_name": "Priority",
            "data_type": "single_select",
            "single_select_option": {"name": "High"},
        },
        {
            "issue_field_name": "Start date",
            "data_type": "date",
            "value": "2026-07-12",
        },
        {
            "issue_field_name": "Estimate",
            "data_type": "number",
            "value": 3,
        },
        {
            "issue_field_name": "Teams",
            "data_type": "multi_select",
            "multi_select_options": [{"name": "Backend"}, {"name": "QA"}],
        },
    ]

    assert normalize_field_values(raw_values) == {
        "Priority": "High",
        "Start date": "2026-07-12",
        "Estimate": 3,
        "Teams": ["Backend", "QA"],
    }


def test_batch_audit_ignores_closed_issues_and_pull_requests() -> None:
    missing = {
        "title": "missing",
        "body": "",
        "assignees": [],
        "labels": [],
        "milestone": None,
        "type": None,
        "issue_field_values": {},
    }
    issues = [
        {"number": 1, "state": "closed", **missing},
        {"number": 2, "state": "open", "pull_request": {"url": "https://example.test"}, **missing},
        {"number": 3, "state": "open", **missing},
    ]

    violations = audit_issues(issues)

    assert [item["number"] for item in violations] == [3]
    assert violations[0]["title"] == "missing"
    assert violations[0]["violations"][0] == "missing_assignee"


def test_open_issue_loader_attaches_rest_issue_field_values() -> None:
    calls: list[str] = []

    def request_json(path: str) -> list[dict[str, object]]:
        calls.append(path)
        if path == "/repos/acme/demo/issues?state=open&per_page=100&page=1":
            return [
                {"number": 7, "state": "open", "title": "Task"},
                {
                    "number": 8,
                    "state": "open",
                    "title": "PR",
                    "pull_request": {"url": "https://example.test/pr/8"},
                },
            ]
        if path == "/repos/acme/demo/issues/7/issue-field-values?per_page=100":
            return [
                {
                    "issue_field_name": "Priority",
                    "data_type": "single_select",
                    "single_select_option": {"name": "High"},
                }
            ]
        raise AssertionError(f"unexpected request: {path}")

    issues = load_open_issues("acme/demo", request_json)

    assert [issue["number"] for issue in issues] == [7]
    assert issues[0]["issue_field_values"] == {"Priority": "High"}
    assert calls == [
        "/repos/acme/demo/issues?state=open&per_page=100&page=1",
        "/repos/acme/demo/issues/7/issue-field-values?per_page=100",
    ]


def test_github_requester_uses_issue_fields_api_version_and_token() -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps([{"number": 7}]).encode("utf-8")

    def opener(request: object, *, timeout: int) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    request_json = make_github_requester(
        token="[MASKED]",
        api_url="https://api.github.test",
        opener=opener,
    )

    assert request_json("/repos/acme/demo/issues") == [{"number": 7}]
    request = captured["request"]
    assert getattr(request, "full_url") == "https://api.github.test/repos/acme/demo/issues"
    assert request.get_header("Authorization") == "Bearer [MASKED]"
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("X-github-api-version") == "2026-03-10"
    assert captured["timeout"] == 30


def test_failure_report_links_each_issue_and_lists_violations() -> None:
    report = render_report(
        [
            {
                "number": 3,
                "title": "메타데이터 누락",
                "violations": ["missing_assignee", "missing_field:Status"],
            }
        ],
        repository="acme/demo",
    )

    assert "❌ 1개 열린 이슈" in report
    assert "[#3](https://github.com/acme/demo/issues/3) 메타데이터 누락" in report
    assert "`missing_assignee`" in report
    assert "`missing_field:Status`" in report


def test_cli_returns_failure_and_writes_actions_summary_for_missing_metadata(
    tmp_path: Path,
) -> None:
    class Response:
        def __init__(self, payload: list[dict[str, object]]) -> None:
            self.payload = payload

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def opener(request: object, *, timeout: int) -> Response:
        assert timeout == 30
        if request.full_url.endswith("/issues?state=open&per_page=100&page=1"):
            return Response(
                [
                    {
                        "number": 9,
                        "state": "open",
                        "title": "누락 이슈",
                        "body": "",
                        "assignees": [],
                        "labels": [],
                        "milestone": None,
                        "type": None,
                    }
                ]
            )
        if request.full_url.endswith("/issues/9/issue-field-values?per_page=100"):
            return Response([])
        raise AssertionError(f"unexpected URL: {request.full_url}")

    summary = tmp_path / "summary.md"
    exit_code = main(
        ["--repository", "acme/demo"],
        environ={"GITHUB_TOKEN": "test-token", "GITHUB_STEP_SUMMARY": str(summary)},
        opener=opener,
    )

    assert exit_code == 1
    assert "[#9](https://github.com/acme/demo/issues/9)" in summary.read_text(
        encoding="utf-8"
    )


def test_metadata_audit_workflow_has_schedule_manual_run_and_read_permissions() -> None:
    workflow = Path(".github/workflows/issue-metadata-audit.yml").read_text(
        encoding="utf-8"
    )

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "issues: read" in workflow
    assert "python scripts/issue_metadata_audit.py" in workflow
