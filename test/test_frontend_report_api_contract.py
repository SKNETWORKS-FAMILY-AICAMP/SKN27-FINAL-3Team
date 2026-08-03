from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_report_client_declares_canonical_read_detail_and_pdf_routes() -> None:
    client = (ROOT / "app" / "web" / "apiClient.js").read_text(encoding="utf-8")

    for required in (
        "listReports({ identity } = {})",
        'joinApiPath(apiBase, "reports/")',
        "getReportDetail({ reportId, sessionId, identity } = {})",
        '`reports/${encodeURIComponent(reportId || "")}/`',
        "downloadReport({ reportId, sessionId, identity, documentType } = {})",
        '`reports/${encodeURIComponent(reportId || "")}/download/`',
        "document_type: documentType",
        "return getBlob(url, identity);",
        "Authorization: `Bearer ${authToken}`",
    ):
        assert required in client

    list_method = client.split("listReports", maxsplit=1)[1].split(
        "getReportDetail", maxsplit=1
    )[0]
    assert "session_id" not in list_method


def test_frontend_report_views_consume_only_public_report_detail_fields() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    for required in (
        "api.listReports({",
        "api.getReportDetail({",
        "api.downloadReport({",
        "currentReport?.report_id",
        "currentReport?.session_id",
        "currentReport?.job_id",
        "currentReport?.content?.reporting_payload",
        "currentReport?.metadata?.report_quality",
    ):
        assert required in shell

    for internal_header in (
        "X-Report-Storage-URI",
        "X-Report-Object-Key",
        "X-Report-Access-Decision",
    ):
        assert internal_header not in shell


def test_frontend_report_views_consume_public_quality_summary_only() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    assert "public_quality_summary" in shell
    assert "reportQuality?.public_quality_summary" in shell
    assert "reportQualitySummary?.retrieval?.embedding" not in shell
    assert "reportQualitySummary?.retrieval?.backend" not in shell
    assert "reportQualitySummary?.retrieval?.attempted_backends" not in shell
    assert "data_provenance" not in shell


def test_frontend_report_limitations_use_the_public_quality_summary() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    assert "reportQualitySummary?.limitations" in shell
    assert "reportQuality?.limitations" not in shell
