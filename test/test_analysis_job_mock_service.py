from app.services.analysis_job_mock_service import (
    create_analysis_job,
    get_analysis_job,
    list_analysis_jobs,
)
from app.services.attachment_mock_service import register_attachment


def test_create_analysis_job_stores_chat_plan_and_node_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("MOCK_ANALYSIS_JOB_ROOT", str(tmp_path / "jobs"))
    attachment = register_attachment(
        {
            "session_id": "ses_job",
            "filename": "notice.jpg",
            "content_type": "image/jpeg",
            "purpose": "fine_notice",
            "size_bytes": 2048,
        }
    )

    job = create_analysis_job(
        {
            "session_id": "ses_job",
            "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
            "attachments": [{"attachment_id": attachment["attachment_id"]}],
            "mock_scenario": "fine_notice",
            "mock_status": "success",
        }
    )

    assert job["job_id"].startswith("job_")
    assert job["status"] == "success"
    assert job["session_id"] == "ses_job"
    assert job["analysis_plan"]["input_summary"]["attachment_purposes"] == ["fine_notice"]
    assert job["node_execution"]["job_id"] == job["job_id"]
    assert job["node_execution"]["executions"][0]["agent_input"]["job_id"] == job["job_id"]
    assert job["node_execution"]["executions"][0]["agent_output"]["job_id"] == job["job_id"]

    stored = get_analysis_job(job["job_id"])
    assert stored["job_id"] == job["job_id"]
    assert stored["chat_response"]["message_id"] == job["message_id"]


def test_list_analysis_jobs_filters_by_session(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("MOCK_ANALYSIS_JOB_ROOT", str(tmp_path / "jobs"))
    first = create_analysis_job(
        {
            "session_id": "ses_one",
            "user_text": "고지서 분석해줘",
            "mock_scenario": "fine_notice",
            "mock_status": "success",
        }
    )
    create_analysis_job(
        {
            "session_id": "ses_two",
            "user_text": "사고 과실비율 봐줘",
            "mock_scenario": "fault_ratio",
            "mock_status": "partial",
        }
    )

    jobs = list_analysis_jobs(session_id="ses_one")

    assert [job["job_id"] for job in jobs] == [first["job_id"]]
    assert jobs[0]["status"] == "success"


def test_analysis_job_status_can_represent_running_and_partial(monkeypatch, tmp_path):
    monkeypatch.setenv("MOCK_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("MOCK_ANALYSIS_JOB_ROOT", str(tmp_path / "jobs"))

    running_job = create_analysis_job(
        {
            "session_id": "ses_running",
            "user_text": "고지서 분석해줘",
            "mock_scenario": "fine_notice",
            "mock_status": "pending",
        }
    )
    partial_job = create_analysis_job(
        {
            "session_id": "ses_partial",
            "user_text": "사고 과실비율 봐줘",
            "mock_scenario": "fault_ratio",
            "mock_status": "partial",
        }
    )

    assert running_job["status"] == "running"
    assert partial_job["status"] == "partial"
    assert running_job["history"][0]["status"] == "queued"
    assert running_job["history"][-1]["status"] == "running"
