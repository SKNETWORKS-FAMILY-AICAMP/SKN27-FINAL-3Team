"""Lambda controller that starts queued Vision GPU work and stops idle workers."""

from __future__ import annotations

import os
from typing import Any

import boto3


def handler(_event: dict[str, Any], _context: Any) -> dict[str, str]:
    action = os.environ["VISION_CONTROLLER_ACTION"]
    instance_id = os.environ["VISION_WORKER_INSTANCE_ID"]
    queue_url = os.environ["AWS_VISION_QUEUE_URL"]
    ec2 = boto3.client("ec2")

    if action == "start":
        state = _instance_state(ec2, instance_id)
        if _has_queued_messages(queue_url) and state == "stopped":
            ec2.start_instances(InstanceIds=[instance_id])
            return {"status": "started"}
        return {"status": "unchanged"}

    if action == "idle_stop":
        state = _instance_state(ec2, instance_id)
        if not _has_queued_messages(queue_url) and state == "running":
            ec2.stop_instances(InstanceIds=[instance_id])
            return {"status": "stopped"}
        return {"status": "unchanged"}

    raise ValueError("invalid_controller_action")


def _instance_state(ec2: Any, instance_id: str) -> str:
    response = ec2.describe_instances(InstanceIds=[instance_id])
    reservations = response.get("Reservations") or []
    instances = reservations[0].get("Instances") if reservations else []
    instance = instances[0] if instances else {}
    return str(instance.get("State", {}).get("Name") or "")


def _has_queued_messages(queue_url: str) -> bool:
    response = boto3.client("sqs").get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )
    attributes = response.get("Attributes") or {}
    return any(
        int(attributes.get(name, "0")) > 0
        for name in (
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        )
    )
