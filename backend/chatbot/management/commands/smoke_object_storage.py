"""Smoke test the object storage adapter envelope."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from chatbot.object_storage import (
    build_report_storage_reference,
    build_upload_storage_reference,
    copy_object,
    delete_object,
    object_exists,
    object_storage_policy,
    write_object,
)


class Command(BaseCommand):
    help = "Validate object storage metadata envelope and optionally require binary write support."

    def add_arguments(self, parser):
        parser.add_argument("--owner-id", default="usr_object_storage_smoke", help="Owner id for key generation.")
        parser.add_argument("--session-id", default="ses_object_storage_smoke", help="Session id for key generation.")
        parser.add_argument("--require-binary", action="store_true", help="Fail unless the adapter writes binary objects.")
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        policy = object_storage_policy()
        upload_ref = build_upload_storage_reference(
            {
                "attachment_id": "att_object_storage_smoke",
                "session_id": options["session_id"],
                "filename": "smoke.txt",
                "content_type": "text/plain",
                "size_bytes": 12,
                "storage_uri": "mock://uploads/att_object_storage_smoke/smoke.txt",
            },
            owner_id=options["owner_id"],
        )
        report_ref = build_report_storage_reference(
            report_id="rep_object_storage_smoke",
            owner_id=options["owner_id"],
            session_id=options["session_id"],
            source_uri="mock://reports/rep_object_storage_smoke",
        )
        upload_write = {
            "status": "skipped",
            "reason": "scanner_only_clean_upload",
            "writes_binary": False,
        }
        report_staging_ref = _staging_reference(report_ref)
        report_staging_write = write_object(
            report_staging_ref,
            "smoke report\n",
            metadata={"source": "smoke_object_storage", "resource_type": "report"},
        )
        if report_staging_write.get("writes_binary"):
            report_write = copy_object(report_staging_ref, report_ref)
            report_staging_cleanup = delete_object(report_staging_ref)
        else:
            report_write = {
                "status": "skipped",
                "reason": "report_staging_write_failed",
                "writes_binary": False,
            }
            report_staging_cleanup = {"status": "not_required"}
        result = {
            "contract_version": "object_storage_smoke.v1",
            "status": "pass",
            "scope": "api_report_write",
            "policy": policy,
            "upload_reference": _safe_reference(upload_ref),
            "report_reference": _safe_reference(report_ref),
            "upload_write": upload_write,
            "report_staging_write": report_staging_write,
            "report_write": report_write,
            "report_staging_cleanup": report_staging_cleanup,
        }
        binary_failure_reason = _binary_failure_reason(
            policy=policy,
            report_ref=report_ref,
            report_write=report_write,
            report_staging_cleanup=report_staging_cleanup,
        )
        if options["require_binary"] and binary_failure_reason:
            result["status"] = "fail"
            result["error"] = {
                "reason": binary_failure_reason,
                "message": "Object storage adapter did not write binary objects.",
                "upload_reason": upload_write.get("reason"),
                "report_reason": report_write.get("reason"),
                "staging_cleanup_reason": report_staging_cleanup.get("reason"),
            }

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("Object storage smoke failed.")


def _safe_reference(reference: dict) -> dict:
    return {
        "policy_version": reference.get("policy_version"),
        "backend": reference.get("backend"),
        "provider": reference.get("provider"),
        "bucket": reference.get("bucket"),
        "key": reference.get("key"),
        "storage_uri": reference.get("storage_uri"),
        "resource_type": reference.get("resource_type"),
        "status": reference.get("status"),
        "writes_binary": reference.get("writes_binary"),
        "persistence_state": reference.get("persistence_state"),
    }


def _staging_reference(reference: dict) -> dict:
    staging = dict(reference)
    key = str(reference.get("key") or "")
    staging_key = f"staging/{key}"
    bucket = str(reference.get("bucket") or "")
    staging["key"] = staging_key
    staging["storage_uri"] = f"s3://{bucket}/{staging_key}"
    staging["resource_id"] = f"{reference.get('resource_id')}:staging"
    return staging


def _binary_failure_reason(
    *,
    policy: dict,
    report_ref: dict,
    report_write: dict,
    report_staging_cleanup: dict,
) -> str:
    if not policy.get("writes_binary"):
        return "binary_adapter_missing"
    if not report_write.get("writes_binary"):
        return str(report_write.get("reason") or "report_write_failed")
    if not object_exists(report_ref):
        return "report_object_missing_after_write"
    if report_staging_cleanup.get("status") not in {"deleted", "not_found"}:
        return "report_staging_cleanup_failed"
    if policy.get("provider") == "s3" and not report_staging_cleanup.get(
        "permanent"
    ):
        return "report_staging_cleanup_not_verified"
    return ""


def _text_result(result: dict) -> str:
    policy = result["policy"]
    lines = [
        f"Object storage smoke: {result['status']}",
        f"- provider: {policy.get('provider')}",
        f"- bucket: {policy.get('bucket')}",
        f"- persistence_state: {policy.get('persistence_state')}",
        f"- writes_binary: {policy.get('writes_binary')}",
        f"- upload_write: {result['upload_write'].get('status')}",
        f"- report_staging_write: {result['report_staging_write'].get('status')}",
        f"- report_write: {result['report_write'].get('status')}",
        f"- report_staging_cleanup: {result['report_staging_cleanup'].get('status')}",
        f"- upload_uri: {result['upload_reference'].get('storage_uri')}",
        f"- report_uri: {result['report_reference'].get('storage_uri')}",
    ]
    if result.get("error"):
        lines.append(f"- error: {result['error'].get('reason')}")
        if result["error"].get("upload_reason"):
            lines.append(f"- upload_reason: {result['error'].get('upload_reason')}")
        if result["error"].get("report_reason"):
            lines.append(f"- report_reason: {result['error'].get('report_reason')}")
        if result["error"].get("staging_cleanup_reason"):
            lines.append(
                "- staging_cleanup_reason: "
                f"{result['error'].get('staging_cleanup_reason')}"
            )
    return "\n".join(lines)
