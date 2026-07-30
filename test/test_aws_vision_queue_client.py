from __future__ import annotations

from app.services.aws_vision_queue_client import (
    AwsVisionQueueClient,
    AwsVisionQueueConfig,
)


def test_submit_deduplicates_execution_and_returns_safe_handoff() -> None:
    submitted: list[dict] = []
    polls = [None, {"vision_supervisor_handoff": {"status": "partial"}}]

    def submit(**kwargs):
        submitted.append(kwargs)
        return {"MessageId": "message-1"}

    def read_result(**_kwargs):
        return polls.pop(0)

    client = AwsVisionQueueClient(
        AwsVisionQueueConfig(
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/vision.fifo",
            result_bucket="skn27-vision-results",
            poll_interval_seconds=0.01,
            timeout_seconds=1,
        ),
        submit=submit,
        read_result=read_result,
        sleep=lambda _seconds: None,
    )

    result = client.run(
        {
            "schema_version": "vision-runpod-request-v1",
            "execution_id": "exec_1",
            "attachment_id": "att_1",
            "video_url": "https://private-bucket.s3.ap-northeast-2.amazonaws.com/video.mp4",
            "content_type": "video/mp4",
        }
    )

    assert result.output == {"vision_supervisor_handoff": {"status": "partial"}}
    assert submitted[0]["MessageDeduplicationId"] == "exec_1"
    assert submitted[0]["MessageGroupId"] == "vision"
    assert submitted[0]["QueueUrl"].endswith(".fifo")
