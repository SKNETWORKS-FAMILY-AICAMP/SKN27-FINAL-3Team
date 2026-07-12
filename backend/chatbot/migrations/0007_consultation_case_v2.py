# Generated for the additive AI traffic-dispute consultation v2 rollout.

import hashlib

import django.db.models.deletion
from django.db import migrations, models


def backfill_authenticated_fault_cases(apps, schema_editor):
    Case = apps.get_model("chatbot", "Case")
    ChatSession = apps.get_model("chatbot", "ChatSession")

    sessions = ChatSession.objects.filter(current_intent="fault_ratio").exclude(owner_id="")
    for session in sessions.iterator():
        digest = hashlib.sha256(session.session_id.encode("utf-8")).hexdigest()[:32]
        case, _ = Case.objects.get_or_create(
            case_id=f"case_{digest}",
            defaults={
                "owner_id": session.owner_id,
                "title": session.title or "교통사고 과실 초기상담",
                "case_type": "fault_ratio",
                "status": "ready",
                "metadata": {
                    "backfill_source": "authenticated_fault_ratio_session",
                    "source_session_id": session.session_id,
                },
            },
        )
        session.case_id = case.id
        session.save(update_fields=["case"])
        session.analysis_jobs.update(case_id=case.id)
        session.uploaded_files.update(case_id=case.id)
        session.reports.update(case_id=case.id)


def reverse_fault_case_backfill(apps, schema_editor):
    Case = apps.get_model("chatbot", "Case")
    Case.objects.filter(
        metadata__backfill_source="authenticated_fault_ratio_session"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("chatbot", "0006_agent_work_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="version_no",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="uploadedfile",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="uploadedfile",
            name="retention_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="report",
            name="report_type",
            field=models.CharField(
                choices=[
                    ("objection_draft", "Objection draft"),
                    ("fault_analysis", "Fault analysis"),
                    ("general", "General"),
                    ("initial_consultation", "Initial consultation"),
                    ("expert_handoff", "Expert handoff"),
                ],
                default="objection_draft",
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name="Case",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("case_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("owner_id", models.CharField(db_index=True, max_length=128)),
                ("title", models.CharField(blank=True, max_length=200)),
                ("case_type", models.CharField(db_index=True, default="fault_ratio", max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("intake", "Intake"),
                            ("awaiting_fact_confirmation", "Awaiting fact confirmation"),
                            ("queued", "Queued"),
                            ("analyzing", "Analyzing"),
                            ("needs_input", "Needs input"),
                            ("ready", "Ready"),
                            ("high_risk_handoff", "High risk handoff"),
                            ("closed", "Closed"),
                            ("deleted", "Deleted"),
                        ],
                        db_index=True,
                        default="intake",
                        max_length=40,
                    ),
                ),
                ("risk_level", models.CharField(db_index=True, default="standard", max_length=32)),
                ("location", models.JSONField(blank=True, default=dict)),
                ("current_fact_version", models.PositiveIntegerField(default=0)),
                ("current_report_version", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "cases",
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(fields=["owner_id", "status"], name="cases_owner_status_idx"),
                    models.Index(fields=["case_type", "status"], name="cases_type_status_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="analysisjob",
            name="case",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="analysis_jobs", to="chatbot.case"),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="case",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="chat_sessions", to="chatbot.case"),
        ),
        migrations.AddField(
            model_name="report",
            name="case",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reports", to="chatbot.case"),
        ),
        migrations.AddField(
            model_name="uploadedfile",
            name="case",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_files", to="chatbot.case"),
        ),
        migrations.RunPython(backfill_authenticated_fault_cases, reverse_fault_case_backfill),
        migrations.CreateModel(
            name="CaseNotificationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email_enabled", models.BooleanField(default=False)),
                ("email_address", models.EmailField(blank=True, max_length=254)),
                ("consented_at", models.DateTimeField(blank=True, null=True)),
                ("case", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="notification_preference", to="chatbot.case")),
            ],
            options={"db_table": "case_notification_preferences"},
        ),
        migrations.CreateModel(
            name="ConfirmedFactVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("fact_version_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("version_no", models.PositiveIntegerField()),
                ("status", models.CharField(db_index=True, default="confirmed", max_length=32)),
                ("facts", models.JSONField(blank=True, default=dict)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("conflicts", models.JSONField(blank=True, default=list)),
                ("user_edit_history", models.JSONField(blank=True, default=list)),
                ("confirmed_by", models.CharField(blank=True, max_length=128)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fact_versions", to="chatbot.case")),
            ],
            options={"db_table": "confirmed_fact_versions", "ordering": ["case", "-version_no"]},
        ),
        migrations.AddField(
            model_name="report",
            name="source_fact_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reports", to="chatbot.confirmedfactversion"),
        ),
        migrations.CreateModel(
            name="MediaArtifact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("artifact_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("artifact_type", models.CharField(db_index=True, max_length=64)),
                ("storage_uri", models.CharField(blank=True, max_length=512)),
                ("source_timestamp_ms", models.PositiveBigIntegerField(blank=True, null=True)),
                ("checksum", models.CharField(blank=True, max_length=128)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("retention_expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="media_artifacts", to="chatbot.case")),
                ("job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="media_artifacts", to="chatbot.analysisjob")),
                ("uploaded_file", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="media_artifacts", to="chatbot.uploadedfile")),
            ],
            options={"db_table": "media_artifacts", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("delivery_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("channel", models.CharField(default="email", max_length=32)),
                ("status", models.CharField(db_index=True, default="queued", max_length=32)),
                ("recipient_masked", models.CharField(blank=True, max_length=255)),
                ("provider_message_id", models.CharField(blank=True, max_length=255)),
                ("error_code", models.CharField(blank=True, max_length=128)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_deliveries", to="chatbot.case")),
                ("report", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notification_deliveries", to="chatbot.report")),
            ],
            options={"db_table": "notification_deliveries", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="confirmedfactversion",
            constraint=models.UniqueConstraint(fields=("case", "version_no"), name="confirmed_fact_case_version_uniq"),
        ),
        migrations.AddIndex(
            model_name="mediaartifact",
            index=models.Index(fields=["case", "artifact_type"], name="media_case_type_idx"),
        ),
        migrations.AddIndex(
            model_name="mediaartifact",
            index=models.Index(fields=["retention_expires_at", "deleted_at"], name="media_retention_idx"),
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(fields=["case", "status"], name="notify_case_status_idx"),
        ),
    ]
