from __future__ import annotations

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from chatbot.object_storage import delete_object


@override_settings(
    OBJECT_STORAGE_PROVIDER="s3",
    OBJECT_STORAGE_BUCKET="versioned-object-bucket",
    OBJECT_STORAGE_PREFIX="canonical",
)
class VersionedObjectDeletionTests(SimpleTestCase):
    def _versioned_client(self, *, key: str) -> Mock:
        client = Mock()
        client.list_object_versions.side_effect = [
            {
                "Versions": [
                    {"Key": key, "VersionId": "version-current"},
                    {"Key": key, "VersionId": "version-old"},
                ],
                "DeleteMarkers": [
                    {"Key": key, "VersionId": "delete-marker"},
                ],
                "IsTruncated": False,
            },
            {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
        ]
        client.delete_objects.return_value = {"Deleted": []}
        return client

    def test_clean_upload_delete_removes_and_verifies_every_s3_version(self) -> None:
        key = "canonical/uploads/usr/session/attachment/evidence.txt"
        reference = {
            "provider": "s3",
            "bucket": "versioned-object-bucket",
            "key": key,
            "resource_type": "uploaded_file",
            "resource_id": "att-versioned-clean",
        }
        client = self._versioned_client(key=key)

        with patch("chatbot.object_storage._boto3_client", return_value=client):
            result = delete_object(reference)

        self.assertEqual(result["status"], "deleted")
        self.assertTrue(result["permanent"])
        self.assertEqual(result["versions_deleted"], 3)
        client.delete_objects.assert_called_once_with(
            Bucket="versioned-object-bucket",
            Delete={
                "Objects": [
                    {"Key": key, "VersionId": "version-current"},
                    {"Key": key, "VersionId": "version-old"},
                    {"Key": key, "VersionId": "delete-marker"},
                ],
                "Quiet": True,
            },
        )
        client.delete_object.assert_not_called()
        self.assertEqual(client.list_object_versions.call_count, 2)

    def test_report_staging_delete_is_permanent_on_versioned_bucket(self) -> None:
        key = "staging/canonical/reports/usr/scope/report.txt"
        reference = {
            "provider": "s3",
            "bucket": "versioned-object-bucket",
            "key": key,
            "resource_type": "report",
            "resource_id": "rep-versioned:staging",
        }
        client = self._versioned_client(key=key)

        with patch("chatbot.object_storage._boto3_client", return_value=client):
            result = delete_object(reference)

        self.assertEqual(result["status"], "deleted")
        self.assertTrue(result["permanent"])
        client.delete_object.assert_not_called()

    def test_versioned_delete_is_not_success_until_recheck_is_empty(self) -> None:
        key = "canonical/uploads/usr/session/attachment/evidence.txt"
        reference = {
            "provider": "s3",
            "bucket": "versioned-object-bucket",
            "key": key,
            "resource_type": "uploaded_file",
            "resource_id": "att-versioned-still-present",
        }
        remaining = {
            "Versions": [{"Key": key, "VersionId": "version-still-present"}],
            "DeleteMarkers": [],
            "IsTruncated": False,
        }
        client = Mock()
        client.list_object_versions.side_effect = [remaining, remaining]
        client.delete_objects.return_value = {"Deleted": []}

        with patch("chatbot.object_storage._boto3_client", return_value=client):
            result = delete_object(reference)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "versioned_delete_verification_failed")

    def test_final_report_delete_keeps_standard_versioned_delete_semantics(self) -> None:
        key = "canonical/reports/usr/scope/report.txt"
        reference = {
            "provider": "s3",
            "bucket": "versioned-object-bucket",
            "key": key,
            "resource_type": "report",
            "resource_id": "rep-versioned",
        }
        client = Mock()

        with patch("chatbot.object_storage._boto3_client", return_value=client):
            result = delete_object(reference)

        self.assertEqual(result["status"], "deleted")
        self.assertNotIn("permanent", result)
        client.delete_object.assert_called_once_with(
            Bucket="versioned-object-bucket",
            Key=key,
        )
        client.list_object_versions.assert_not_called()
