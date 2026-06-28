"""Persistence models for production storage integration.

These models are intentionally not wired into the mock services yet. They define
the durable storage boundary that will replace local sidecar JSON files in later
branches.
"""

from __future__ import annotations

from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ChatSessionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    SYSTEM = "system", "System"


class UploadedFileStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADED = "uploaded", "Uploaded"
    SCANNING = "scanning", "Scanning"
    READY = "ready", "Ready"
    REJECTED = "rejected", "Rejected"
    DELETED = "deleted", "Deleted"


class AnalysisJobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


class AgentResultStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


class ReportStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    GENERATING = "generating", "Generating"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    DELETED = "deleted", "Deleted"


class ReportType(models.TextChoices):
    OBJECTION_DRAFT = "objection_draft", "Objection draft"
    FAULT_ANALYSIS = "fault_analysis", "Fault analysis"
    GENERAL = "general", "General"


class ChatSession(TimestampedModel):
    session_id = models.CharField(max_length=64, unique=True, db_index=True)
    owner_id = models.CharField(max_length=128, blank=True, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=32,
        choices=ChatSessionStatus.choices,
        default=ChatSessionStatus.DRAFT,
    )
    current_intent = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "chat_sessions"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(
                fields=["owner_id", "status"],
                name="chat_sessions_owner_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.session_id


class ChatMessage(models.Model):
    message_id = models.CharField(max_length=64, unique=True, db_index=True)
    session = models.ForeignKey(ChatSession, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=MessageRole.choices)
    content = models.TextField(blank=True)
    routing_intent = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["session", "created_at"],
                name="chat_msg_session_created_idx",
            ),
            models.Index(
                fields=["routing_intent"],
                name="chat_msg_routing_intent_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.message_id


class UploadedFile(TimestampedModel):
    attachment_id = models.CharField(max_length=64, unique=True, db_index=True)
    owner_id = models.CharField(max_length=128, blank=True, db_index=True)
    session = models.ForeignKey(
        ChatSession,
        related_name="uploaded_files",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    purpose = models.CharField(max_length=64, default="unknown", db_index=True)
    file_type = models.CharField(max_length=32, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    storage_uri = models.CharField(max_length=512, blank=True)
    privacy_risk = models.BooleanField(default=True)
    status = models.CharField(
        max_length=32,
        choices=UploadedFileStatus.choices,
        default=UploadedFileStatus.UPLOADED,
    )
    scan_status = models.CharField(max_length=32, default="not_started")
    agent_handoff = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "uploaded_files"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["owner_id", "session"],
                name="upl_files_owner_session_idx",
            ),
            models.Index(
                fields=["status", "purpose"],
                name="upl_files_status_purpose_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.attachment_id


class AnalysisJob(TimestampedModel):
    job_id = models.CharField(max_length=64, unique=True, db_index=True)
    session = models.ForeignKey(ChatSession, related_name="analysis_jobs", on_delete=models.CASCADE)
    message = models.ForeignKey(
        ChatMessage,
        related_name="analysis_jobs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    owner_id = models.CharField(max_length=128, blank=True, db_index=True)
    routing_intent = models.CharField(max_length=64, blank=True, db_index=True)
    mock_scenario = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=32,
        choices=AnalysisJobStatus.choices,
        default=AnalysisJobStatus.QUEUED,
        db_index=True,
    )
    active_node = models.CharField(max_length=64, blank=True)
    progress_message = models.TextField(blank=True)
    analysis_plan_id = models.CharField(max_length=64, blank=True)
    status_counts = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "analysis_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["owner_id", "status"],
                name="analysis_jobs_owner_status_idx",
            ),
            models.Index(
                fields=["session", "status"],
                name="ana_jobs_session_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.job_id


class AnalysisJobEvent(models.Model):
    job = models.ForeignKey(AnalysisJob, related_name="events", on_delete=models.CASCADE)
    status = models.CharField(max_length=32, choices=AnalysisJobStatus.choices)
    active_node = models.CharField(max_length=64, blank=True)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analysis_job_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["job", "created_at"],
                name="ana_job_events_job_created_idx",
            ),
            models.Index(
                fields=["status"],
                name="ana_job_events_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job.job_id}:{self.status}"


class AgentResult(models.Model):
    result_id = models.CharField(max_length=64, unique=True, db_index=True)
    job = models.ForeignKey(AnalysisJob, related_name="agent_results", on_delete=models.CASCADE)
    node_code = models.CharField(max_length=64, db_index=True)
    node_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=32,
        choices=AgentResultStatus.choices,
        default=AgentResultStatus.SUCCESS,
        db_index=True,
    )
    summary = models.TextField(blank=True)
    structured_result = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    next_actions = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    raw_output = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_results"
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["job", "node_code"],
                name="agent_results_job_node_idx",
            ),
            models.Index(
                fields=["job", "status"],
                name="agent_results_job_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.result_id


class AnalysisDisplayResult(TimestampedModel):
    display_result_id = models.CharField(max_length=64, unique=True, db_index=True)
    job = models.OneToOneField(
        AnalysisJob,
        related_name="display_result",
        on_delete=models.CASCADE,
    )
    assistant_message = models.JSONField(default=dict, blank=True)
    progress = models.JSONField(default=list, blank=True)
    cards = models.JSONField(default=list, blank=True)
    pending_questions = models.JSONField(default=list, blank=True)
    attachments = models.JSONField(default=list, blank=True)
    report_links = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "analysis_display_results"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.display_result_id


class Report(TimestampedModel):
    report_id = models.CharField(max_length=64, unique=True, db_index=True)
    owner_id = models.CharField(max_length=128, blank=True, db_index=True)
    session = models.ForeignKey(
        ChatSession,
        related_name="reports",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    job = models.ForeignKey(
        AnalysisJob,
        related_name="reports",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    display_result = models.ForeignKey(
        AnalysisDisplayResult,
        related_name="reports",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    report_type = models.CharField(
        max_length=64,
        choices=ReportType.choices,
        default=ReportType.OBJECTION_DRAFT,
    )
    status = models.CharField(
        max_length=32,
        choices=ReportStatus.choices,
        default=ReportStatus.DRAFT,
        db_index=True,
    )
    title = models.CharField(max_length=200, blank=True)
    storage_uri = models.CharField(max_length=512, blank=True)
    content_summary = models.TextField(blank=True)
    content = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "reports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["owner_id", "status"],
                name="reports_owner_status_idx",
            ),
            models.Index(
                fields=["report_type", "status"],
                name="reports_type_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.report_id
