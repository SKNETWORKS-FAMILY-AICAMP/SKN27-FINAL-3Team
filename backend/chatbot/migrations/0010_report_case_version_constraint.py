from django.db import migrations, models


def normalize_case_report_versions(apps, schema_editor):
    case_model = apps.get_model("chatbot", "Case")
    report_model = apps.get_model("chatbot", "Report")

    for case in case_model.objects.all().iterator():
        reports = report_model.objects.filter(case_id=case.id).order_by("created_at", "id")
        latest_version = 0
        for latest_version, report in enumerate(reports.iterator(), start=1):
            if report.version_no != latest_version:
                report.version_no = latest_version
                report.save(update_fields=["version_no"])
        if case.current_report_version != latest_version:
            case.current_report_version = latest_version
            case.save(update_fields=["current_report_version"])


class Migration(migrations.Migration):
    dependencies = [
        ("chatbot", "0009_consultation_case_v2"),
    ]

    operations = [
        migrations.RunPython(normalize_case_report_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="report",
            constraint=models.UniqueConstraint(
                fields=("case", "version_no"),
                name="report_case_version_uniq",
            ),
        ),
    ]
