from __future__ import annotations

from etl.fault_cases.src.review_case.embedding import run_embedding


def test_zero_target_embedding_job_is_finished_successfully(monkeypatch) -> None:
    finished_jobs: list[tuple[str, int, int, int, str]] = []
    reports: list[dict] = []

    monkeypatch.setattr(run_embedding, "count_embeddings", lambda _settings: 904)
    monkeypatch.setattr(run_embedding, "fetch_pending_chunks", lambda _settings, limit: [])
    monkeypatch.setattr(run_embedding, "count_chunks", lambda: 904)
    monkeypatch.setattr(
        run_embedding,
        "create_embedding_job",
        lambda _settings, target_count, dry_run: "job-zero-target",
    )
    monkeypatch.setattr(
        run_embedding,
        "finish_embedding_job",
        lambda job_id, success, failed, skipped, status: finished_jobs.append(
            (job_id, success, failed, skipped, status)
        ),
    )
    monkeypatch.setattr(run_embedding, "write_report", lambda report: reports.append(report))

    result = run_embedding.create_embeddings(dry_run=False)

    assert finished_jobs == [("job-zero-target", 0, 0, 0, "success")]
    assert result["embedding_count_after"] == 904
    assert reports == [result]
