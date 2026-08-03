import { createEmptyConsultationIntake } from "./consultationIntake.js";

const CONTRACT_VERSION = "resume_manifest.v1";
const ATTACHMENT_FIELDS = ["attachment_id", "purpose", "filename", "status", "scan_status"];
const REPORT_FIELDS = [
  "report_id",
  "report_type",
  "status",
  "title",
  "content_summary",
  "created_at",
  "updated_at",
];
const ANALYSIS_FIELDS = [
  "contract_version",
  "job_id",
  "session_id",
  "message_id",
  "status",
  "active_node",
  "progress_message",
  "assistant_message",
  "assistant_message_payload",
  "cards",
  "pending_questions",
  "conversation_messages",
  "attachments",
  "attachment_workflows",
  "attachment_processing",
  "analysis_progress",
  "progress_state",
  "report_links",
  "limitations",
  "reporting_payload",
  "supervisor_state",
  "supervisor_execution",
  "reports",
  "report_count",
  "latest_report_id",
  "latest_report_status",
  "last_event_at",
  "created_at",
  "updated_at",
];
const INTAKE_FIELD_BY_SERVER_KEY = {
  attachment_available: "attachmentAvailable",
  collision_location: "collisionLocation",
  document_disposition_type: "documentDispositionType",
  fine_question: "fineQuestion",
  issuing_authority: "issuingAuthority",
  response_deadline: "responseDeadline",
  road_layout: "roadLayout",
  signal_priority: "signalPriority",
  vehicle_actions: "vehicleActions",
};

export function hydrateResumeManifest(manifest) {
  if (
    !manifest ||
    manifest.contract_version !== CONTRACT_VERSION ||
    manifest.has_resume !== true ||
    !String(manifest.session?.session_id || "").trim()
  ) {
    return emptyResumeState();
  }

  const sessionId = String(manifest.session.session_id).trim();
  const pendingQuestions = projectPendingQuestions(manifest.pending_questions);
  const chatMessages = projectMessages(manifest.conversation_messages, pendingQuestions);
  const registeredAttachments = projectList(manifest.attachments, ATTACHMENT_FIELDS, "attachment_id");
  const reportList = projectList(manifest.reports, REPORT_FIELDS, "report_id");
  const analysis = projectObject(manifest.latest_analysis, ANALYSIS_FIELDS);
  const analysisResponse = analysis.job_id
    ? {
        ...analysis,
        pending_questions: Array.isArray(analysis.pending_questions)
          ? analysis.pending_questions
          : pendingQuestions,
        persistence: {
          conversation_save_state: "saved",
          job_id: analysis.job_id,
          session_id: analysis.session_id || sessionId,
        },
      }
    : null;

  return {
    hasResume: true,
    sessionId,
    chatMessages,
    consultationIntake: buildConsultationIntake(manifest),
    registeredAttachments,
    analysisResponse,
    reportList,
    currentReport: reportList.length ? toCurrentReport(reportList[0], analysisResponse) : null,
  };
}

function emptyResumeState() {
  return {
    hasResume: false,
    sessionId: "",
    chatMessages: [],
    consultationIntake: createEmptyConsultationIntake(),
    registeredAttachments: [],
    analysisResponse: null,
    reportList: [],
    currentReport: null,
  };
}

function projectMessages(value, pendingQuestions) {
  const messages = Array.isArray(value)
    ? value.flatMap((item) => {
        const role = item?.role === "assistant" ? "assistant" : item?.role === "user" ? "user" : "";
        const content = String(item?.content || "").trim();
        return role && content ? [{ role, content, status: "saved" }] : [];
      })
    : [];
  const lastAssistantIndex = messages.findLastIndex((message) => message.role === "assistant");
  if (lastAssistantIndex >= 0 && pendingQuestions.length) {
    messages[lastAssistantIndex] = {
      ...messages[lastAssistantIndex],
      pending_questions: pendingQuestions,
    };
  }
  return messages;
}

function projectPendingQuestions(value) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const field = String(item?.field || "").trim();
    const question = String(item?.question || "").trim();
    return field && question ? [{ field, question }] : [];
  });
}

function buildConsultationIntake(manifest) {
  const intake = createEmptyConsultationIntake();
  const facts = isRecord(manifest.facts) ? manifest.facts : {};
  const slots = isRecord(manifest.fine_notice_intake?.slots)
    ? manifest.fine_notice_intake.slots
    : {};
  for (const [serverKey, stateKey] of Object.entries(INTAKE_FIELD_BY_SERVER_KEY)) {
    const value = slots[serverKey] ?? facts[serverKey];
    if (["string", "number", "boolean"].includes(typeof value)) {
      intake[stateKey] = String(value);
    }
  }
  if (Object.keys(slots).length || intake.issuingAuthority || intake.responseDeadline) {
    intake.consultationType = "fine_notice";
  }
  return intake;
}

function toCurrentReport(report, analysisResponse) {
  return {
    ...report,
    persistence: { status: report.status || "saved" },
    metadata: {
      case_id: analysisResponse?.job_id || "",
      title: report.title || "저장된 상담 리포트",
      updated_at: report.updated_at || report.created_at || "",
      report_count: 1,
    },
  };
}

function projectList(value, fields, requiredField) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => projectObject(item, fields))
    .filter((item) => String(item[requiredField] || "").trim());
}

function projectObject(value, fields) {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    fields
      .filter((field) => Object.hasOwn(value, field))
      .map((field) => [field, cloneJsonValue(value[field])])
      .filter(([, item]) => item !== undefined)
  );
}

function cloneJsonValue(value) {
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return value;
  if (Array.isArray(value)) {
    return value.map(cloneJsonValue).filter((item) => item !== undefined);
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value)
        .map(([key, item]) => [key, cloneJsonValue(item)])
        .filter(([, item]) => item !== undefined)
    );
  }
  return undefined;
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
