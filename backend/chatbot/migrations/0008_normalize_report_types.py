from __future__ import annotations

from django.db import migrations, models


REPORT_TYPE_ALIASES = {
    "objection_draft": "fine_notice_objection",
    "fault_analysis": "fault_ratio_analysis",
    "generic_supervisor": "general",
}


def normalize_report_types(apps, schema_editor) -> None:
    report_model = apps.get_model("chatbot", "Report")
    for legacy_value, canonical_value in REPORT_TYPE_ALIASES.items():
        report_model.objects.filter(report_type=legacy_value).update(report_type=canonical_value)


def remove_legacy_auth_material(apps, schema_editor) -> None:
    oauth_connection = apps.get_model("chatbot", "OAuthConnection")
    social_account = apps.get_model("chatbot", "SocialAccount")

    oauth_connection.objects.all().delete()
    social_account.objects.filter(provider_user_id__startswith="mock-").delete()
    social_account.objects.filter(email__endswith="@example.local").delete()


class Migration(migrations.Migration):
    dependencies = [("chatbot", "0007_report_type_contract_choices")]

    operations = [
        migrations.RunPython(normalize_report_types, migrations.RunPython.noop),
        migrations.RunPython(remove_legacy_auth_material, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="report",
            name="report_type",
            field=models.CharField(
                choices=[
                    ("fine_notice_objection", "Fine notice objection"),
                    ("fault_ratio_analysis", "Fault ratio analysis"),
                    ("general", "General"),
                ],
                default="fine_notice_objection",
                max_length=64,
            ),
        ),
    ]
