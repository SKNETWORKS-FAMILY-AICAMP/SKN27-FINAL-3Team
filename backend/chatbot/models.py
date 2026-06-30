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


class UserAccountStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    DELETED = "deleted", "Deleted"


class GuestIdentityStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MERGED = "merged", "Merged"
    EXPIRED = "expired", "Expired"


class AuthSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


class SubscriptionStatus(models.TextChoices):
    FREE = "free", "Free"
    TRIAL = "trial", "Trial"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELED = "canceled", "Canceled"


class AgentInvocationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    RETRYING = "retrying", "Retrying"


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


class UserAccount(TimestampedModel):
    user_id = models.CharField(max_length=64, unique=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    display_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=32,
        choices=UserAccountStatus.choices,
        default=UserAccountStatus.ACTIVE,
        db_index=True,
    )
    auth_provider = models.CharField(max_length=64, blank=True)
    provider_subject = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="users_status_idx"),
            models.Index(fields=["email"], name="users_email_idx"),
        ]

    def __str__(self) -> str:
        return self.user_id


class GuestIdentity(TimestampedModel):
    guest_id = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=GuestIdentityStatus.choices,
        default=GuestIdentityStatus.ACTIVE,
        db_index=True,
    )
    merged_user = models.ForeignKey(
        UserAccount,
        related_name="merged_guest_identities",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    merge_confirmed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "guest_identities"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"], name="guest_status_idx"),
            models.Index(fields=["merged_user", "status"], name="guest_user_status_idx"),
        ]

    def __str__(self) -> str:
        return self.guest_id


class AuthSession(TimestampedModel):
    auth_session_id = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        UserAccount,
        related_name="auth_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    guest = models.ForeignKey(
        GuestIdentity,
        related_name="auth_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    subject_type = models.CharField(max_length=32, db_index=True)
    subject_id = models.CharField(max_length=128, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=AuthSessionStatus.choices,
        default=AuthSessionStatus.ACTIVE,
        db_index=True,
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "auth_sessions"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["subject_id", "status"], name="auth_subject_status_idx"),
            models.Index(fields=["user", "status"], name="auth_user_status_idx"),
        ]

    def __str__(self) -> str:
        return self.auth_session_id


class AuthEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        UserAccount,
        related_name="auth_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    guest = models.ForeignKey(
        GuestIdentity,
        related_name="auth_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    auth_session = models.ForeignKey(
        AuthSession,
        related_name="events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    event_type = models.CharField(max_length=64, db_index=True)
    subject_id = models.CharField(max_length=128, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["subject_id", "created_at"], name="auth_evt_subject_idx"),
            models.Index(fields=["event_type"], name="auth_evt_type_idx"),
        ]

    def __str__(self) -> str:
        return self.event_id


class Subscription(TimestampedModel):
    subscription_id = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        UserAccount,
        related_name="subscriptions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    plan_code = models.CharField(max_length=64, default="free", db_index=True)
    status = models.CharField(
        max_length=32,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.FREE,
        db_index=True,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "subscriptions"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "status"], name="sub_user_status_idx"),
            models.Index(fields=["plan_code", "status"], name="sub_plan_status_idx"),
        ]

    def __str__(self) -> str:
        return self.subscription_id


class UsageQuota(TimestampedModel):
    quota_id = models.CharField(max_length=64, unique=True, db_index=True)
    subject_id = models.CharField(max_length=128, db_index=True)
    scope = models.CharField(max_length=64, db_index=True)
    limit_count = models.PositiveIntegerField(default=0)
    used_count = models.PositiveIntegerField(default=0)
    reset_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "usage_quotas"
        ordering = ["subject_id", "scope"]
        indexes = [
            models.Index(fields=["subject_id", "scope"], name="quota_subject_scope_idx"),
            models.Index(fields=["reset_at"], name="quota_reset_idx"),
        ]

    def __str__(self) -> str:
        return self.quota_id


class UsageEvent(models.Model):
    usage_event_id = models.CharField(max_length=64, unique=True, db_index=True)
    subject_id = models.CharField(max_length=128, db_index=True)
    scope = models.CharField(max_length=64, db_index=True)
    amount = models.PositiveIntegerField(default=1)
    quota_key = models.CharField(max_length=160, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "usage_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["subject_id", "scope"], name="usage_subject_scope_idx"),
            models.Index(fields=["quota_key"], name="usage_quota_key_idx"),
        ]

    def __str__(self) -> str:
        return self.usage_event_id


class HistoryEvent(models.Model):
    event_id = models.CharField(max_length=64, unique=True, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    event_version = models.CharField(max_length=64, default="history_event.v1")
    occurred_at = models.DateTimeField(db_index=True)
    actor_user_id = models.CharField(max_length=128, blank=True, db_index=True)
    actor_guest_id = models.CharField(max_length=128, blank=True, db_index=True)
    actor_auth_session_id = models.CharField(max_length=128, blank=True, db_index=True)
    actor_auth_state = models.CharField(max_length=32, blank=True)
    subject_session_id = models.CharField(max_length=128, blank=True, db_index=True)
    subject_message_id = models.CharField(max_length=128, blank=True, db_index=True)
    subject_job_id = models.CharField(max_length=128, blank=True, db_index=True)
    subject_report_id = models.CharField(max_length=128, blank=True, db_index=True)
    source_surface = models.CharField(max_length=64, blank=True)
    source_api_path = models.CharField(max_length=256, blank=True, db_index=True)
    source_execution_mode = models.CharField(max_length=64, blank=True, db_index=True)
    source_node_code = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(max_length=32, default="success", db_index=True)
    summary = models.TextField(blank=True)
    actor = models.JSONField(default=dict, blank=True)
    subject = models.JSONField(default=dict, blank=True)
    source = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    privacy = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "history_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["subject_session_id", "occurred_at"], name="hist_evt_session_time_idx"),
            models.Index(fields=["actor_user_id", "occurred_at"], name="hist_evt_user_time_idx"),
            models.Index(fields=["actor_guest_id", "occurred_at"], name="hist_evt_guest_time_idx"),
            models.Index(fields=["subject_job_id", "event_type"], name="hist_evt_job_type_idx"),
            models.Index(fields=["event_type", "status"], name="hist_evt_type_status_idx"),
        ]

    def __str__(self) -> str:
        return self.event_id


class CodeGroup(TimestampedModel):
    group_code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "code_groups"
        ordering = ["group_code"]
        indexes = [
            models.Index(fields=["is_active"], name="code_groups_active_idx"),
        ]

    def __str__(self) -> str:
        return self.group_code


class CodeItem(TimestampedModel):
    group = models.ForeignKey(CodeGroup, related_name="items", on_delete=models.CASCADE)
    code = models.CharField(max_length=64)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "code_items"
        ordering = ["group", "sort_order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["group", "code"], name="code_items_group_code_uniq"),
        ]
        indexes = [
            models.Index(fields=["group", "is_active"], name="code_items_group_active_idx"),
            models.Index(fields=["group", "sort_order"], name="code_items_group_sort_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.group.group_code}:{self.code}"


class AgentNodeDefinition(TimestampedModel):
    node_code = models.CharField(max_length=64, unique=True, db_index=True)
    node_name = models.CharField(max_length=200)
    node_type = models.CharField(max_length=64, default="agent", db_index=True)
    owner = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=64, default="planned", db_index=True)
    contract_version = models.CharField(max_length=64, blank=True)
    adapter_key = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "agent_nodes"
        ordering = ["node_code"]
        indexes = [
            models.Index(fields=["status"], name="agent_nodes_status_idx"),
            models.Index(fields=["owner", "status"], name="agent_nodes_owner_idx"),
        ]

    def __str__(self) -> str:
        return self.node_code


class AiSession(TimestampedModel):
    ai_session_id = models.CharField(max_length=64, unique=True, db_index=True)
    session = models.ForeignKey(
        ChatSession,
        related_name="ai_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    user = models.ForeignKey(
        UserAccount,
        related_name="ai_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    guest = models.ForeignKey(
        GuestIdentity,
        related_name="ai_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    owner_id = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=32, default="active", db_index=True)
    routing_intent = models.CharField(max_length=64, blank=True, db_index=True)
    quota_key = models.CharField(max_length=160, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_sessions"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner_id", "status"], name="ai_sess_owner_status_idx"),
            models.Index(fields=["session", "status"], name="ai_sess_session_idx"),
        ]

    def __str__(self) -> str:
        return self.ai_session_id


class AgentInvocation(models.Model):
    invocation_id = models.CharField(max_length=64, unique=True, db_index=True)
    ai_session = models.ForeignKey(
        AiSession,
        related_name="agent_invocations",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    job = models.ForeignKey(
        AnalysisJob,
        related_name="agent_invocations",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    agent_node = models.ForeignKey(
        AgentNodeDefinition,
        related_name="invocations",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    node_code = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=AgentInvocationStatus.choices,
        default=AgentInvocationStatus.QUEUED,
        db_index=True,
    )
    attempt_no = models.PositiveIntegerField(default=1)
    execution_mode = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    token_count = models.PositiveIntegerField(null=True, blank=True)
    cost_estimate = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    evidence_count = models.PositiveIntegerField(default=0)
    limitation_count = models.PositiveIntegerField(default=0)
    retryable = models.BooleanField(default=False)
    error_code = models.CharField(max_length=120, blank=True, db_index=True)
    quota_key = models.CharField(max_length=160, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_invocations"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["job", "node_code"], name="agent_inv_job_node_idx"),
            models.Index(fields=["ai_session", "status"], name="agent_inv_session_idx"),
            models.Index(fields=["status"], name="agent_inv_status_idx"),
        ]

    def __str__(self) -> str:
        return self.invocation_id


class AgentFeedbackEvent(models.Model):
    feedback_id = models.CharField(max_length=64, unique=True, db_index=True)
    invocation = models.ForeignKey(
        AgentInvocation,
        related_name="feedback_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    agent_result = models.ForeignKey(
        AgentResult,
        related_name="feedback_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    feedback_type = models.CharField(max_length=64, db_index=True)
    rating = models.IntegerField(null=True, blank=True)
    comment = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_feedback_events"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["invocation", "created_at"], name="agent_fb_inv_idx"),
            models.Index(fields=["feedback_type"], name="agent_fb_type_idx"),
        ]

    def __str__(self) -> str:
        return self.feedback_id
