from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.services.runpod_vision_client import (
    RunPodVisionClient,
    RunPodVisionConfig,
    RunPodVisionError,
)


SIGNED_URL = "https://private-bucket.s3.ap-northeast-2.amazonaws.com/video.mp4?X-Amz-Signature=private"
API_KEY = "runpod-private-key"


def _request() -> dict[str, str]:
    return {
        "schema_version": "vision-runpod-request-v1",
        "execution_id": "exec_vision_1",
        "attachment_id": "att_video_1",
        "video_url": SIGNED_URL,
        "content_type": "video/mp4",
    }


def _handoff() -> dict[str, Any]:
    return {
        "vision_supervisor_handoff": {
            "schema_version": "vision-supervisor-handoff-v1",
            "status": "partial",
        }
    }


def _config(**overrides: Any) -> RunPodVisionConfig:
    values = {
        "endpoint_id": "endpoint_123",
        "api_key": API_KEY,
        "timeout_seconds": 30.0,
        "poll_interval_seconds": 0.01,
        "http_timeout_seconds": 5.0,
        "max_response_bytes": 32_768,
    }
    values.update(overrides)
    return RunPodVisionConfig(**values)


def _sequenced_transport(
    *responses: dict[str, Any] | Exception,
) -> tuple[Callable[..., dict[str, Any]], list[dict[str, Any]]]:
    remaining = list(responses)
    calls: list[dict[str, Any]] = []

    def transport(
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> dict[str, Any]:
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        response = remaining.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    return transport, calls


def test_submit_then_poll_returns_completed_handoff() -> None:
    transport, calls = _sequenced_transport(
        {"id": "job_1"},
        {"id": "job_1", "status": "IN_QUEUE"},
        {"id": "job_1", "status": "IN_PROGRESS"},
        {"id": "job_1", "status": "COMPLETED", "output": _handoff()},
    )
    client = RunPodVisionClient(
        _config(),
        transport=transport,
        sleep=lambda _seconds: None,
    )

    result = client.run(_request())

    assert result.job_id == "job_1"
    assert result.output == _handoff()
    assert [call["method"] for call in calls] == ["POST", "GET", "GET", "GET"]
    assert calls[0]["url"] == "https://api.runpod.ai/v2/endpoint_123/run"
    assert calls[0]["payload"] == {"input": _request()}
    assert calls[0]["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert calls[-1]["url"].endswith("/status/job_1")


def test_existing_job_id_skips_submit_and_only_polls() -> None:
    transport, calls = _sequenced_transport(
        {"id": "job_existing", "status": "COMPLETED", "output": _handoff()},
    )
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    result = client.run(_request(), existing_job_id="job_existing")

    assert result.job_id == "job_existing"
    assert [call["method"] for call in calls] == ["GET"]


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        ("FAILED", "vision_remote_execution_failed"),
        ("CANCELLED", "vision_remote_cancelled"),
        ("TIMED_OUT", "vision_remote_timeout"),
    ],
)
def test_terminal_failure_statuses_use_stable_codes(
    status: str,
    expected_code: str,
) -> None:
    transport, _calls = _sequenced_transport(
        {"id": "job_failure"},
        {
            "id": "job_failure",
            "status": status,
            "error": f"{SIGNED_URL} {API_KEY} private provider detail",
        },
    )
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == expected_code
    assert str(raised.value) == expected_code
    assert API_KEY not in repr(raised.value)
    assert "X-Amz-Signature" not in repr(raised.value)


def test_worker_error_output_maps_to_remote_execution_failed() -> None:
    transport, _calls = _sequenced_transport(
        {"id": "job_worker_error"},
        {
            "id": "job_worker_error",
            "status": "COMPLETED",
            "output": {
                "vision_worker_error": {
                    "error_code": "vision_worker_execution_failed",
                    "detail": SIGNED_URL,
                }
            },
        },
    )
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == "vision_remote_execution_failed"
    assert SIGNED_URL not in repr(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"id": ""},
        {"id": "../unsafe"},
    ],
)
def test_invalid_submit_response_uses_stable_invalid_response(
    response: dict[str, Any],
) -> None:
    transport, _calls = _sequenced_transport(response)
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == "vision_remote_invalid_response"


@pytest.mark.parametrize(
    "status_response",
    [
        {"id": "job_1"},
        {"id": "other_job", "status": "COMPLETED", "output": _handoff()},
        {"id": "job_1", "status": "UNKNOWN"},
        {"id": "job_1", "status": "COMPLETED", "output": []},
        {"id": "job_1", "status": "COMPLETED", "output": {}},
        {
            "id": "job_1",
            "status": "COMPLETED",
            "output": {"vision_supervisor_handoff": []},
        },
    ],
)
def test_invalid_status_or_output_uses_stable_invalid_response(
    status_response: dict[str, Any],
) -> None:
    transport, _calls = _sequenced_transport({"id": "job_1"}, status_response)
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == "vision_remote_invalid_response"


def test_polling_deadline_uses_stable_timeout() -> None:
    clock_values = iter((0.0, 0.0, 31.0))
    transport, _calls = _sequenced_transport(
        {"id": "job_timeout"},
        {"id": "job_timeout", "status": "IN_PROGRESS"},
    )
    client = RunPodVisionClient(
        _config(timeout_seconds=30.0),
        transport=transport,
        sleep=lambda _: None,
        clock=lambda: next(clock_values),
    )

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == "vision_remote_timeout"


def test_transport_failure_never_retries_submit_or_exposes_secrets() -> None:
    transport, calls = _sequenced_transport(
        OSError(f"provider failed for {SIGNED_URL} using {API_KEY}"),
    )
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(RunPodVisionError) as raised:
        client.run(_request())

    assert raised.value.code == "vision_remote_unavailable"
    assert len(calls) == 1
    assert API_KEY not in repr(raised.value)
    assert "X-Amz-Signature" not in repr(raised.value)


def test_poll_network_failure_is_retried_without_resubmitting() -> None:
    transport, calls = _sequenced_transport(
        {"id": "job_poll_retry"},
        OSError("temporary status failure"),
        {
            "id": "job_poll_retry",
            "status": "COMPLETED",
            "output": _handoff(),
        },
    )
    client = RunPodVisionClient(_config(), transport=transport, sleep=lambda _: None)

    result = client.run(_request())

    assert result.job_id == "job_poll_retry"
    assert [call["method"] for call in calls] == ["POST", "GET", "GET"]


def test_configuration_from_environment_requires_key_and_safe_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNPOD_API_KEY", API_KEY)
    monkeypatch.setenv("RUNPOD_VISION_ENDPOINT_ID", "endpoint-safe_123")
    monkeypatch.setenv("RUNPOD_VISION_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("RUNPOD_VISION_POLL_INTERVAL_SECONDS", "0.5")

    config = RunPodVisionConfig.from_environment()

    assert config.endpoint_id == "endpoint-safe_123"
    assert config.api_key == API_KEY
    assert config.timeout_seconds == 45.0
    assert config.poll_interval_seconds == 0.5
    assert API_KEY not in repr(config)


@pytest.mark.parametrize(
    ("endpoint_id", "api_key"),
    [
        ("", API_KEY),
        ("../unsafe", API_KEY),
        ("endpoint_1", ""),
    ],
)
def test_invalid_configuration_uses_remote_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_id: str,
    api_key: str,
) -> None:
    monkeypatch.setenv("RUNPOD_VISION_ENDPOINT_ID", endpoint_id)
    monkeypatch.setenv("RUNPOD_API_KEY", api_key)

    with pytest.raises(RunPodVisionError) as raised:
        RunPodVisionConfig.from_environment()

    assert raised.value.code == "vision_remote_unavailable"
