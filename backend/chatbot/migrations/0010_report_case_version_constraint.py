from django.db import migrations, models


def normalize_case_report_versions(apps, schema_editor):
    case_model = apps.get_model("chatbot", "Case")
    report_model = apps.get_model("chatbot", "Report")

    for case in case_model.objects.all().iterator():
        reports = list(
            report_model.objects.filter(case_id=case.id).order_by("created_at", "id")
        )
        used_versions = set()
        next_version = max(
            (report.version_no for report in reports if report.version_no > 0),
            default=0,
        ) + 1
        for report in reports:
            old_version = report.version_no
            if old_version > 0 and old_version not in used_versions:
                used_versions.add(old_version)
                continue
            while next_version in used_versions:
                next_version += 1
            metadata = dict(report.metadata or {})
            metadata["version_migration_0010"] = {
                "old_version": old_version,
                "new_version": next_version,
            }
            report.version_no = next_version
            report.metadata = metadata
            report.save(update_fields=["version_no", "metadata"])
            used_versions.add(next_version)
            next_version += 1
        latest_version = max(used_versions, default=0)
        if case.current_report_version != latest_version:
            case.current_report_version = latest_version
            case.save(update_fields=["current_report_version"])


def restore_case_report_versions(apps, schema_editor):
    case_model = apps.get_model("chatbot", "Case")
    report_model = apps.get_model("chatbot", "Report")

    for report in report_model.objects.all().iterator():
        metadata = dict(report.metadata or {})
        audit = metadata.get("version_migration_0010")
        if not isinstance(audit, dict) or "old_version" not in audit:
            continue
        report.version_no = audit["old_version"]
        metadata.pop("version_migration_0010", None)
        report.metadata = metadata
        report.save(update_fields=["version_no", "metadata"])

    for case in case_model.objects.all().iterator():
        latest_version = (
            report_model.objects.filter(case_id=case.id)
            .order_by("-version_no")
            .values_list("version_no", flat=True)
            .first()
            or 0
        )
        if case.current_report_version != latest_version:
            case.current_report_version = latest_version
            case.save(update_fields=["current_report_version"])


class Migration(migrations.Migration):
    dependencies = [
        ("chatbot", "0009_consultation_case_v2"),
    ]

    operations = [
        migrations.RunPython(
            normalize_case_report_versions,
            restore_case_report_versions,
        ),
        migrations.AddConstraint(
            model_name="report",
            constraint=models.UniqueConstraint(
                fields=("case", "version_no"),
                name="report_case_version_uniq",
            ),
        ),
    ]
