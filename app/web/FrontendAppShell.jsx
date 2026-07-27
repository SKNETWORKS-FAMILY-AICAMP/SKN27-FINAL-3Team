import { useEffect, useMemo, useRef, useState } from "react";

import { createFrontendApi } from "./apiClient.js";
import {
  buildAuthContext,
  buildGoogleLoginPayload,
  clearStoredAuthSession,
  persistAuthSession,
  readStoredGoogleProfile,
  readStoredAuthSession,
  readStoredAuthToken,
  scheduleAppJwtRefresh,
} from "./authSession.js";
import {
  CONSULTATION_FACT_FIELDS,
  CONSULTATION_TYPE_OPTIONS,
  buildStructuredConsultationMessage,
  createEmptyConsultationIntake,
  hasConsultationIntakeData,
  listConsultationIntakeMissingFields,
} from "./consultationIntake.js";

const TAB_ROUTES = [
  { id: "chatbot", label: "사고·과태료 상담" },
  { id: "mypage", label: "마이페이지" },
  { id: "reporting", label: "리포트" },
];

const FALLBACK_ANALYSIS_CARDS = [
  {
    card_type: "상담 접수",
    title: "입력 내용을 확인했습니다",
    status: "partial",
    summary: "상담 입력을 접수했습니다. 자료 분석은 로그인 후 이어서 진행할 수 있습니다.",
  },
];
const EXECUTION_MODE = "async_worker";
const WORKER_POLL_INTERVAL_MS = 500;
const WORKER_POLL_MAX_ATTEMPTS = 60;
const WORKER_PENDING_JOB_STATUSES = new Set(["queued", "running", "retrying"]);
const FINE_NOTICE_DEADLINE_DAYS = 60;
const ATTACHMENT_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf,video/mp4,video/quicktime";
const VIDEO_MIME_TYPES = new Set(["video/mp4", "video/quicktime"]);
const DOCUMENT_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);
const ATTACHMENT_PURPOSE_LABELS = {
  fine_notice: "고지서",
  supporting_evidence: "보조 자료",
  blackbox_video: "블랙박스 영상",
  accident_scene: "사고 현장 자료",
  evidence: "증거 자료",
  traffic_accident_confirmation: "교통사고 사실확인원",
};
const CHAT_ATTACHMENT_OPTIONS = [
  {
    label: "고지서·문서",
    description: "고지서, 사실확인원 또는 보조 문서",
    purpose: "fine_notice",
    accept: "image/jpeg,image/png,image/webp,application/pdf",
  },
  {
    label: "사고 현장 사진",
    description: "사고 현장, 차량 파손 또는 도로 사진",
    purpose: "accident_scene",
    accept: "image/jpeg,image/png,image/webp",
  },
  {
    label: "블랙박스 영상",
    description: "MP4 또는 MOV 영상",
    purpose: "blackbox_video",
    accept: "video/mp4,video/quicktime",
  },
];
const OCR_CONFIRMATION_FIELDS = [
  "fine_type",
  "notice_stage",
  "law_code",
  "violation_text",
  "opinion_deadline",
  "issuing_authority",
];
const OCR_CONFIRMATION_FIELD_LABELS = {
  fine_type: "처분 유형",
  notice_stage: "고지 단계",
  law_code: "법령 코드",
  violation_text: "위반 내용",
  opinion_deadline: "의견제출 기한",
  issuing_authority: "발급 기관",
};
const DEADLINE_GUIDANCE_STATUSES = new Set(["overdue", "due_soon", "normal", "needs_confirmation"]);
const SERVICE_INFORMATION_NOTICE = "이 서비스는 법률 자문이나 개별 사건의 확정 판단을 대신하지 않으며, 확인할 사실과 근거를 정리합니다.";
const USER_FACING_NEXT_ACTION_LABELS = {
  answer_pending_question: "추가 질문에 답변해 주세요.",
  review_verified_results: "확인된 결과와 근거를 검토해 주세요.",
};

function upcomingDeadlineSummary(cases, windowDays = 7) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const upcoming = cases
    .map((item) => {
      if (!isFineNoticeCase(item)) return null;
      const raw = item?.notice_received_at || item?.notice_received_date;
      if (!raw || item?.notice_received_source !== "user") return null;
      const receivedAt = parseISODateOnly(raw);
      if (!receivedAt) return null;
      const deadline = new Date(receivedAt);
      deadline.setDate(deadline.getDate() + FINE_NOTICE_DEADLINE_DAYS);
      const days = Math.ceil((deadline.getTime() - today.getTime()) / 86400000);
      return { days, deadline };
    })
    .filter((item) => item && item.days >= 0 && item.days <= windowDays)
    .sort((left, right) => left.days - right.days);
  return {
    count: upcoming.length,
    nearestLabel: upcoming.length
      ? (upcoming[0].days === 0 ? "과태료 이의제기 오늘 마감" : `과태료 이의제기 마감 D-${upcoming[0].days}`)
      : "7일 이내 과태료 이의제기 마감 없음",
  };
}

function parseISODateOnly(value) {
  const normalized = String(value || "").trim().slice(0, 10);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(normalized);
  if (!match) return null;
  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const parsed = new Date(year, month - 1, day);
  parsed.setHours(0, 0, 0, 0);
  if (
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
  ) {
    return null;
  }
  return parsed;
}

function isFineNoticeCase(item) {
  const caseType = [
    item?.type,
    item?.report_type,
    item?.case_type,
  ]
    .filter(Boolean)
    .join(" ");
  return /과태료|fine_notice/.test(caseType);
}

function waitForWorkerPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, WORKER_POLL_INTERVAL_MS));
}

function waitForAssistantToken() {
  return new Promise((resolve) => window.setTimeout(resolve, 20));
}

function assistantMessageText(value, fallback = "") {
  if (typeof value === "string") {
    return value.trim() || fallback;
  }
  if (value && typeof value === "object") {
    return String(value.answer || value.summary || "").trim() || fallback;
  }
  return fallback;
}

function stringList(value) {
  return Array.isArray(value)
    ? value.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
}

function userFacingNextActions(value) {
  return stringList(value).flatMap((action) => {
    const mappedAction = USER_FACING_NEXT_ACTION_LABELS[action];
    if (mappedAction) {
      return [mappedAction];
    }
    return /^[a-z][a-z0-9_]*$/i.test(action) ? [] : [action];
  });
}

function userFacingLimitations(value) {
  const normalized = stringList(value).flatMap((item) => {
    if (/lexical|token coverage|검색 토큰/i.test(item)) {
      return ["검색 결과의 일치도가 낮아 추가 확인이 필요합니다."];
    }
    if (/sync adapter|supervisor|postgres|execution mode|adapter/i.test(item)) {
      return [];
    }
    return [item];
  });
  return [...new Set(normalized)];
}

function isDeadlineGuidance(value) {
  return Boolean(
    value &&
      value.contract_version === "deadline_guidance.v1" &&
      DEADLINE_GUIDANCE_STATUSES.has(value.status)
  );
}

function buildSafetyGuidance({ serviceScope = null, limitations = [], nextActions = [] } = {}) {
  if (serviceScope) {
    return {
      title: serviceScope.decision === "expert_handoff" ? "전문가 확인이 필요한 요청입니다" : "서비스 범위 안내",
      reason: String(serviceScope.reason || "").trim(),
      limitations: userFacingLimitations(serviceScope.limitations),
      nextActions: userFacingNextActions(serviceScope.next_actions),
    };
  }
  const safeLimitations = userFacingLimitations(limitations);
  const safeNextActions = userFacingNextActions(nextActions);
  if (!safeLimitations.length && !safeNextActions.length) {
    return null;
  }
  return {
    title: "추가 확인이 필요한 안내",
    reason: "현재 결과의 한계와 다음 확인 사항을 함께 검토해 주세요.",
    limitations: safeLimitations,
    nextActions: safeNextActions,
  };
}

function analysisCardKey(card, index) {
  return `${card?.card_type || "analysis"}-${card?.title || "card"}-${index}`;
}

function ocrConfirmationFieldsFrom(result) {
  return OCR_CONFIRMATION_FIELDS.reduce((fields, field) => {
    fields[field] = String(result?.[field] || "");
    return fields;
  }, {});
}

export default function FrontendAppShell({
  apiBase = "/api",
  googleClientId = "",
}) {
  const api = useMemo(() => createFrontendApi({ apiBase }), [apiBase]);
  const storedAuthSession = useMemo(() => readStoredAuthSession(), []);
  const [activeRoute, setActiveRoute] = useState("chatbot");
  const [sessionId, setSessionId] = useState(() => storedAuthSession.session_id || "");
  const [guestId, setGuestId] = useState(() => storedAuthSession.guest_id || "");
  const [guestCredential, setGuestCredential] = useState(() => storedAuthSession.guest_credential || "");
  const [authSessionId, setAuthSessionId] = useState(() => storedAuthSession.auth_session_id || "");
  const [mypageSummary, setMypageSummary] = useState(null);
  const [historyEvents, setHistoryEvents] = useState(null);
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [consultationIntake, setConsultationIntake] = useState(() => createEmptyConsultationIntake());
  const [analysisResponse, setAnalysisResponse] = useState(null);
  const [activeAuthToken, setActiveAuthToken] = useState(() => readStoredAuthToken());
  const [savePromptVisible, setSavePromptVisible] = useState(false);
  const [saveDecision, setSaveDecision] = useState("undecided");
  const [statusMessage, setStatusMessage] = useState("");
  const [capabilityCatalog, setCapabilityCatalog] = useState(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSavingConversation, setIsSavingConversation] = useState(false);
  const [attachmentPurpose, setAttachmentPurpose] = useState("fine_notice");
  const executionMode = EXECUTION_MODE;
  const [selectedUploadFile, setSelectedUploadFile] = useState(null);
  const [uploadInputResetKey, setUploadInputResetKey] = useState(0);
  const [registeredAttachments, setRegisteredAttachments] = useState([]);
  const [isRegisteringAttachment, setIsRegisteringAttachment] = useState(false);
  const [ocrConfirmationFields, setOcrConfirmationFields] = useState({});
  const [pendingOcrConfirmation, setPendingOcrConfirmation] = useState(null);
  const [reportActionStatus, setReportActionStatus] = useState("");
  const [currentReport, setCurrentReport] = useState(null);
  const [reportList, setReportList] = useState([]);
  const [pendingAuthAction, setPendingAuthAction] = useState(null);
  const [guestDetailedReportUsed, setGuestDetailedReportUsed] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const isMountedRef = useRef(false);
  const authRefreshContextRef = useRef({ guestId, guestCredential, sessionId });
  authRefreshContextRef.current = { guestId, guestCredential, sessionId };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const effectiveAuthToken = activeAuthToken || "";
  const identity = {
    authToken: effectiveAuthToken,
    guestId,
    guestCredential,
    authSessionId,
  };
  const authContext = buildAuthContext({
    authState: authSessionId ? "authenticated" : guestId ? "guest" : "anonymous",
    guestId,
    authSessionId,
    sessionId,
    userId: null,
  });
  const isGuestReady = Boolean(guestId && guestCredential);
  const sessionLabel = authSessionId
    ? "Google 계정 상담"
    : isGuestReady
      ? "비회원 상담"
      : "상담 준비";
  const cases = mypageSummary?.cases?.length ? mypageSummary.cases : [];
  const effectiveReportList = reportList;
  const effectiveCurrentReport = currentReport || effectiveReportList[0] || null;
  const effectiveMypageSummary = mypageSummary;
  const history = historyEvents?.events || [];
  const analysisCards = analysisResponse?.cards?.length
    ? normalizeAnalysisCards(analysisResponse.cards)
    : [];
  const assistantAnswer =
    analysisResponse?.assistant_message?.core_answer ||
    assistantMessageText(analysisResponse?.assistant_message);
  const assistantFollowUp = analysisResponse?.assistant_message?.follow_up || null;
  const serviceScope = analysisResponse?.service_scope || null;
  const responseLimitations = stringList(analysisResponse?.limitations);
  const responseNextActions = stringList(analysisResponse?.next_actions);
  const chatSafetyGuidance = buildSafetyGuidance({
    serviceScope,
    limitations: responseLimitations,
    nextActions: responseNextActions,
  });
  const resultSafetyGuidance = serviceScope
    ? null
    : buildSafetyGuidance({ limitations: responseLimitations, nextActions: responseNextActions });
  const deadlineGuidance = isDeadlineGuidance(analysisResponse?.deadline_guidance)
    ? analysisResponse.deadline_guidance
    : null;
  const ocrResult = analysisResponse?.structured_results?.fine_notice_analysis || null;
  const attachmentClassificationResult =
    analysisResponse?.structured_results?.attachment_document_classification || null;
  const supervisorState = analysisResponse?.supervisor_state || null;
  const reportingPayload = analysisResponse?.reporting_payload || null;
  const supervisorExecution = analysisResponse?.supervisor_execution || null;
  const caseType = detectCaseType({ analysisCards, analysisResponse, currentReport });
  const isLiveReportingReady = isReportingPayloadReady(reportingPayload, supervisorState);
  const visibleReportingPayload = isLiveReportingReady ? reportingPayload : null;
  const visibleAnalysisCards = isLiveReportingReady
    ? analysisCards
    : analysisCards.filter((card) => card?.card_type !== "reporting_preview");
  const attachmentOptions = Array.from(
    new Set([
      ...(capabilityCatalog?.capabilities || []).flatMap(
        (capability) => capability.attachment_purposes || []
      ),
      ...CHAT_ATTACHMENT_OPTIONS.map((option) => option.purpose),
    ])
  ).map((purpose) => {
    const configured = CHAT_ATTACHMENT_OPTIONS.find((option) => option.purpose === purpose);
    return configured || {
      label: ATTACHMENT_PURPOSE_LABELS[purpose] || purpose,
      description: "상담 근거로 사용할 지원 자료",
      purpose,
      accept: ATTACHMENT_ACCEPT,
    };
  });
  useEffect(() => {
    if (ocrResult?.requires_confirmation === true) {
      setOcrConfirmationFields(ocrConfirmationFieldsFrom(ocrResult));
      return;
    }
    setOcrConfirmationFields({});
    setPendingOcrConfirmation(null);
  }, [ocrResult]);

  useEffect(() => {
    let active = true;
    api.getCapabilities()
      .then((catalog) => {
        if (!active) return;
        setCapabilityCatalog(catalog);
        setCapabilityError("");
      })
      .catch(() => {
        if (!active) return;
        setCapabilityCatalog(null);
        setCapabilityError("현재 지원 기능을 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.");
      });
    return () => {
      active = false;
    };
  }, [api]);

  useEffect(() => {
    if (!activeAuthToken || !authSessionId) {
      return undefined;
    }

    let refreshEffectActive = true;
    const cleanupRefreshTimer = scheduleAppJwtRefresh({
      token: activeAuthToken,
      refresh: async () => {
        const refreshContext = authRefreshContextRef.current;
        try {
          const refreshResult = await api.refreshAuthToken(
            {
              guest_id: refreshContext.guestId || undefined,
              session_id: refreshContext.sessionId || undefined,
            },
            {
              authToken: activeAuthToken,
              authSessionId,
              guestId: refreshContext.guestId,
              guestCredential: refreshContext.guestCredential,
            }
          );
          if (!refreshEffectActive) {
            return;
          }
          const nextToken = refreshResult?.access_token || "";
          const nextAuthSessionId = refreshResult?.subject?.auth_session_id || "";
          if (!nextToken || !nextAuthSessionId) {
            throw new Error("Auth refresh response is incomplete.");
          }
          const nextGuestId = refreshResult?.subject?.guest_id || refreshContext.guestId || "";
          const nextUserId = refreshResult?.subject?.user_id || readStoredAuthSession().user_id || "";
          setActiveAuthToken(nextToken);
          setAuthSessionId(nextAuthSessionId);
          setGuestId(nextGuestId);
          persistAuthSession({
            accessToken: nextToken,
            authSessionId: nextAuthSessionId,
            guestId: nextGuestId,
            guestCredential: refreshContext.guestCredential,
            googleProfile: readStoredGoogleProfile(),
            sessionId: refreshContext.sessionId,
            userId: nextUserId,
          });
        } catch (_error) {
          if (!refreshEffectActive) {
            return;
          }
          clearStoredAuthSession();
          persistAuthSession({
            guestId: refreshContext.guestId || "",
            guestCredential: refreshContext.guestCredential || "",
            sessionId: refreshContext.sessionId || "",
          });
          setActiveAuthToken("");
          setAuthSessionId("");
          setGuestId(refreshContext.guestId || "");
          setGuestCredential(refreshContext.guestCredential || "");
          setSessionId(refreshContext.sessionId || "");
          setMypageSummary(null);
          setHistoryEvents(null);
          setCurrentReport(null);
          setReportList([]);
          setPendingAuthAction(null);
          setStatusMessage("로그인이 만료되었습니다. Google 계정으로 다시 로그인해 주세요.");
        }
      },
    });

    return () => {
      refreshEffectActive = false;
      cleanupRefreshTimer();
    };
  }, [api, activeAuthToken, authSessionId]);

  async function bootstrapGuestSession(nextRoute = "chatbot") {
    setStatusMessage("로그인 없이 바로 상담을 시작할 수 있도록 준비하고 있습니다.");
    try {
      const initialGuest = await api.createGuestSession(
        {
          guest_id: guestId || undefined,
          session_id: sessionId || undefined,
        },
        { guestId, guestCredential }
      );
      const initialGuestId = initialGuest?.guest?.guest_id || guestId;
      const initialGuestCredential = initialGuest?.guest_credential || "";
      const ensuredSessionId = initialGuest?.session_binding?.session_id || sessionId || `ses_web_${Date.now()}`;
      if (!initialGuestId || !initialGuestCredential) {
        throw new Error("Guest session response is incomplete.");
      }
      const reboundGuest = await api.createGuestSession(
        {
          guest_id: initialGuestId,
          session_id: ensuredSessionId,
        },
        { guestId: initialGuestId, guestCredential: initialGuestCredential }
      );
      const nextGuestId = reboundGuest?.guest?.guest_id || initialGuestId;
      const nextGuestCredential = reboundGuest?.guest_credential || initialGuestCredential;
      const nextSessionId = reboundGuest?.session_binding?.session_id || ensuredSessionId;
      setGuestId(nextGuestId);
      setGuestCredential(nextGuestCredential);
      setSessionId(nextSessionId);
      persistAuthSession({
        guestId: nextGuestId,
        guestCredential: nextGuestCredential,
        sessionId: nextSessionId,
      });
      setStatusMessage("임시 상담을 시작했습니다. 상세 분석이나 이력 저장이 필요해질 때 Google 로그인을 안내합니다.");
      setActiveRoute(nextRoute);
      return {
        guestCredential: nextGuestCredential,
        guestId: nextGuestId,
        sessionId: nextSessionId,
      };
    } catch (error) {
      setStatusMessage("상담 준비에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      return null;
    }
  }

  async function ensureGuestSession(nextRoute = "chatbot") {
    if (sessionId && guestId && guestCredential) {
      setActiveRoute(nextRoute);
      return { guestCredential, guestId, sessionId };
    }
    const guestSessionResult = await bootstrapGuestSession(nextRoute);
    if (guestSessionResult?.sessionId) {
      return guestSessionResult;
    }
    return null;
  }

  async function loginAndBindCurrentSession({ source = "manual_login", nextRoute = "chatbot" } = {}) {
    const activeGuestSession = await ensureGuestSession(nextRoute);
    if (!activeGuestSession?.sessionId || !activeGuestSession?.guestCredential) {
      throw new Error("Guest session is required before Google login.");
    }
    const activeSessionId = activeGuestSession.sessionId || sessionId || `ses_web_${Date.now()}`;
    const activeGuestId = activeGuestSession.guestId || guestId || "";
    const activeGuestCredential = activeGuestSession.guestCredential;
    const loginPayload = {
      guest_id: activeGuestId,
      session_id: activeSessionId,
      ...(await buildGoogleLoginPayload({ googleClientId, guestId: activeGuestId })),
    };
    const loginResult = await api.loginWithGoogleCode(loginPayload, {
      guestId: activeGuestId,
      guestCredential: activeGuestCredential,
    });
    const nextToken = loginResult?.access_token || "";
    const subject = loginResult?.subject || {};
    const nextAuthSessionId = subject.auth_session_id || "";
    const nextGuestId = subject.guest_id || activeGuestId;
    const nextUserId = subject.user_id || loginResult?.user?.user_id || null;

    setActiveAuthToken(nextToken);
    setAuthSessionId(nextAuthSessionId);
    setGuestId(nextGuestId);
    setGuestCredential("");
    setSessionId(activeSessionId);
    persistAuthSession({
      accessToken: nextToken,
      googleProfile: loginResult?.user || null,
      authSessionId: nextAuthSessionId,
      guestId: nextGuestId,
      guestCredential: "",
      sessionId: activeSessionId,
      userId: nextUserId,
    });

    const nextIdentity = {
      authToken: nextToken,
      authSessionId: nextAuthSessionId,
      guestId: nextGuestId,
      guestCredential: "",
    };
    return {
      authSessionId: nextAuthSessionId,
      authToken: nextToken,
      guestId: nextGuestId,
      guestCredential: "",
      identity: nextIdentity,
      loginResult,
      sessionId: activeSessionId,
      source,
      userId: nextUserId,
    };
  }

  async function logoutAndResetSession() {
    setStatusMessage("로그아웃하고 새 계정으로 시작할 준비를 하고 있습니다.");
    const logoutIdentity = identity;
    try {
      if (authSessionId || effectiveAuthToken) {
        await api.logoutAuthSession(
          {
            auth_session_id: authSessionId || undefined,
            session_id: sessionId || undefined,
          },
          logoutIdentity
        );
      }
    } catch (_error) {
      // Local session reset is still required so another account can sign in cleanly.
    }
    clearStoredAuthSession();
    setActiveAuthToken("");
    setAuthSessionId("");
    setGuestId("");
    setGuestCredential("");
    setSessionId("");
    setMypageSummary(null);
    setHistoryEvents(null);
    setChatMessages([]);
    setAnalysisResponse(null);
    setCurrentReport(null);
    setReportList([]);
    setPendingAuthAction(null);
    setReportActionStatus("");
    setSavePromptVisible(false);
    setSaveDecision("undecided");
    setGuestDetailedReportUsed(false);
    setSubmittedQuestion("");
    setQuestion("");
    setConsultationIntake(createEmptyConsultationIntake());
    setActiveRoute("entry");
    setStatusMessage("로그아웃했습니다. 새 Google 계정으로 다시 진행할 수 있습니다.");
  }

  async function registerAttachmentMetadata() {
    setIsRegisteringAttachment(true);
    setStatusMessage(selectedUploadFile ? "첨부 파일을 업로드하고 있습니다." : "첨부 metadata를 등록하고 있습니다.");
    try {
      let activeSession = sessionId;
      let activeGuestId = guestId;
      let nextIdentity = identity;
      if (!authSessionId) {
        setPendingAuthAction({
          type: "upload",
          filename: selectedUploadFile?.name || `${attachmentPurpose}-sample.txt`,
          purpose: attachmentPurpose,
        });
        setStatusMessage("자료 업로드를 위해 Google 로그인 후 지금 하던 상담에 이어서 연결합니다.");
        const loginState = await loginAndBindCurrentSession({
          source: "attachment_upload",
          nextRoute: "chatbot",
        });
        activeSession = loginState.sessionId;
        activeGuestId = loginState.guestId;
        nextIdentity = loginState.identity;
        setPendingAuthAction(null);
      } else {
        const guestSessionResult = sessionId ? null : await bootstrapGuestSession("chatbot");
        activeSession = sessionId || guestSessionResult?.sessionId || `ses_web_${Date.now()}`;
        activeGuestId = guestId || guestSessionResult?.guestId || "";
        nextIdentity = {
          ...identity,
          guestId: activeGuestId,
          authSessionId,
        };
      }
      const result = selectedUploadFile
        ? await api.uploadFile(
            {
              file: selectedUploadFile,
              session_id: activeSession,
              purpose: attachmentPurpose,
            },
            nextIdentity
          )
        : await api.registerFileMetadata(
            {
              session_id: activeSession,
              purpose: attachmentPurpose,
              filename: `${attachmentPurpose}-sample.txt`,
              content_type: "text/plain",
              size_bytes: 0,
            },
            nextIdentity
          );
      let attachment = result?.attachment;
      if (attachment) {
        attachment = {
          ...attachment,
          scan_status: attachment.scan_status || "scan_pending",
        };
        setRegisteredAttachments((items) => [...items, attachment]);
        setSelectedUploadFile(null);
        setUploadInputResetKey((value) => value + 1);
        setStatusMessage(`${attachment.original_filename || attachment.filename || attachment.purpose} 자료를 상담 입력에 연결했습니다. scan=${attachment.scan_status || attachment.status}`);
      } else {
        setStatusMessage("첨부 등록 응답을 확인하지 못했습니다.");
      }
    } catch (_error) {
      const publicMessage = _error?.publicMessage;
      setStatusMessage(publicMessage || "첨부 등록에 실패했습니다. 다시 시도해 주세요.");
      setPendingAuthAction(null);
    } finally {
      setIsRegisteringAttachment(false);
    }
  }

  function handleAttachmentFile(file) {
    if (!file) {
      setSelectedUploadFile(null);
      setUploadInputResetKey((value) => value + 1);
      return;
    }
    const contentType = String(file.type || "").toLowerCase();
    if (!VIDEO_MIME_TYPES.has(contentType) && !DOCUMENT_MIME_TYPES.has(contentType)) {
      setSelectedUploadFile(null);
      setUploadInputResetKey((value) => value + 1);
      setStatusMessage("이미지(JPEG/PNG/WebP), PDF, MP4 또는 MOV 파일만 첨부할 수 있습니다.");
      return;
    }
    if (VIDEO_MIME_TYPES.has(contentType)) {
      setAttachmentPurpose("blackbox_video");
      setStatusMessage(`${file.name} 영상을 Vision 분석 대기열에 연결했습니다.`);
    } else {
      setStatusMessage(`${file.name} 파일을 OCR 분류 대기열에 연결했습니다.`);
    }
    setSelectedUploadFile(file);
  }

  function handleAttachmentDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleAttachmentDrop(event) {
    event.preventDefault();
    handleAttachmentFile(event.dataTransfer.files?.[0] || null);
  }

  async function runCurrentReportAction(action = "download_objection") {
    const jobId = currentReport?.job_id || analysisResponse?.persistence?.job_id || analysisResponse?.supervisor_execution?.job_id || "";
    const documentType = "objection_form";
    const reportAction = action === "save" ? "save" : "download";
    const activeReportingPayload = currentReport?.content?.reporting_payload || visibleReportingPayload;
    const appealGate = activeReportingPayload?.appeal_gate || null;
    const actionDefinition = Array.isArray(activeReportingPayload?.report_actions)
      ? activeReportingPayload.report_actions.find((item) => item?.type === action)
      : null;
    if (reportAction === "download") {
      if (appealGate?.blocked === true) {
        setReportActionStatus(appealGate.reason || "이의신청 가능 여부를 확인한 뒤 문서를 다운로드할 수 있습니다.");
        return;
      }
      if (actionDefinition && actionDefinition.document_format !== "docx") {
        setReportActionStatus("DOCX 형식으로 준비된 문서만 다운로드할 수 있습니다.");
        return;
      }
      if (
        activeReportingPayload?.document_confirmation?.required === true &&
        activeReportingPayload.document_confirmation.confirmed !== true
      ) {
        setReportActionStatus(
          activeReportingPayload.document_confirmation.stale
            ? "문서 내용이 바뀌었습니다. 네 가지 항목을 다시 확인해 주세요."
            : "이의신청서 다운로드 전 네 가지 최종 확인을 완료해 주세요."
        );
        return;
      }
    }
    const persistedReportId = persistedAnalysisReportId(analysisResponse, currentReport);
    if ((!analysisResponse || !jobId) && currentReport?.report_id && reportAction === "download") {
      try {
        let nextIdentity = identity;
        let activeSessionId = currentReport?.session_id || sessionId;
        if (!authSessionId) {
          setPendingAuthAction({ type: `report_${action}`, reportId: currentReport.report_id });
          const loginState = await loginAndBindCurrentSession({
            source: `report_${action}`,
            nextRoute: "reporting",
          });
          nextIdentity = loginState.identity;
          activeSessionId = activeSessionId || loginState.sessionId;
          setPendingAuthAction(null);
        }
        const downloadedFilename = await triggerReportDownload({
          reportId: currentReport.report_id,
          sessionId: activeSessionId,
          requestIdentity: nextIdentity,
          documentType,
        });
        setReportActionStatus(`다운로드 완료: ${downloadedFilename || currentReport.report_id}`);
      } catch (_error) {
        setPendingAuthAction(null);
        setReportActionStatus(`다운로드에 실패했습니다. ${_error?.message || ""}`.trim());
      }
      return;
    }
    if (!analysisResponse || !jobId) {
      setReportActionStatus("리포트 action을 실행할 상담 결과가 아직 없습니다.");
      return;
    }
    if (!currentReport && !activeReportingPayload) {
      setReportActionStatus("역질문이 끝난 뒤 리포트와 제출 문서를 만들 수 있습니다.");
      setStatusMessage("필수 확인 질문에 답하면 리포트 다운로드가 열립니다.");
      setActiveRoute("chatbot");
      return;
    }
    if (!persistedReportId) {
      setReportActionStatus(
        hasReportGenerationNode(supervisorState)
          ? "분석 워커가 리포트를 저장할 때까지 기다린 뒤 다시 시도해 주세요."
          : "이번 상담 유형은 별도 리포트 문서를 만들지 않습니다."
      );
      return;
    }
    setReportActionStatus(
      reportAction === "download"
        ? "이의신청서 DOCX를 준비하고 있습니다."
        : "리포트를 저장하고 있습니다."
    );
    try {
      let activeSessionId = currentReport?.session_id || analysisResponse?.session_id || sessionId;
      let nextIdentity = identity;
      if (!authSessionId) {
        setPendingAuthAction({ type: `report_${action}`, jobId });
        setReportActionStatus("리포트 작업을 위해 Google 로그인 후 같은 상담으로 이어갑니다.");
        const loginState = await loginAndBindCurrentSession({
          source: `report_${action}`,
          nextRoute: "chatbot",
        });
        activeSessionId = activeSessionId || loginState.sessionId;
        nextIdentity = loginState.identity;
        setPendingAuthAction(null);
      }
      if (persistedReportId) {
        const detailResult = await api.getReportDetail({
          reportId: persistedReportId,
          sessionId: activeSessionId,
          identity: nextIdentity,
        });
        const persistedReport = detailResult?.report || currentReport || {
          report_id: persistedReportId,
          session_id: activeSessionId,
          content: { reporting_payload: activeReportingPayload },
        };
        setCurrentReport(persistedReport);
        let downloadedFilename = "";
        if (reportAction === "download") {
          const confirmation = persistedReport?.content?.reporting_payload?.document_confirmation;
          if (confirmation?.required === true && confirmation.confirmed !== true) {
            setReportActionStatus(
              confirmation.stale
                ? "문서 내용이 바뀌었습니다. 네 가지 항목을 다시 확인해 주세요."
                : "이의신청서 다운로드 전 네 가지 최종 확인을 완료해 주세요."
            );
            return;
          }
          downloadedFilename = await triggerReportDownload({
            reportId: persistedReportId,
            sessionId: activeSessionId,
            requestIdentity: nextIdentity,
            documentType,
          });
        } else {
          await api.updateConversationSaveState(
            {
              session_id: activeSessionId,
              conversation_save_state: "saved",
              conversation_save_source: "worker_report_save_action",
            },
            nextIdentity
          );
        }
        setReportActionStatus(
          reportAction === "download"
            ? `다운로드 완료: ${downloadedFilename || persistedReportId}`
            : `리포트 저장 완료: ${persistedReportId}`
        );
        if (nextIdentity.authSessionId) {
          await loadMyPageSummary({ identity: nextIdentity, sessionId: activeSessionId });
          await loadHistoryEvents({ identity: nextIdentity, sessionId: activeSessionId });
          await loadReports({ identity: nextIdentity, sessionId: activeSessionId });
        }
        setActiveRoute("reporting");
        return;
      }
    } catch (_error) {
      setPendingAuthAction(null);
      setReportActionStatus(`리포트 action 실행에 실패했습니다. ${_error?.message || ""}`.trim());
    }
  }

  async function confirmCurrentReportDocument(confirmation) {
    const reportId = persistedAnalysisReportId(analysisResponse, currentReport);
    if (!reportId) {
      setReportActionStatus("최종 확인을 저장할 이의신청서가 아직 준비되지 않았습니다.");
      return;
    }
    try {
      let activeSessionId = currentReport?.session_id || analysisResponse?.session_id || sessionId;
      let nextIdentity = identity;
      if (!authSessionId) {
        setPendingAuthAction({ type: "report_document_confirmation", reportId });
        const loginState = await loginAndBindCurrentSession({
          source: "report_document_confirmation",
          nextRoute: "reporting",
        });
        activeSessionId = activeSessionId || loginState.sessionId;
        nextIdentity = loginState.identity;
        setPendingAuthAction(null);
      }
      await api.confirmReportDocument({
        reportId,
        sessionId: activeSessionId,
        identity: nextIdentity,
        confirmation,
      });
      const detailResult = await api.getReportDetail({
        reportId,
        sessionId: activeSessionId,
        identity: nextIdentity,
      });
      setCurrentReport(detailResult?.report || currentReport);
      setReportActionStatus("최종 확인이 저장되었습니다. 이의신청서 DOCX를 다운로드할 수 있습니다.");
    } catch (_error) {
      setPendingAuthAction(null);
      setReportActionStatus(`최종 확인 저장에 실패했습니다. ${_error?.message || ""}`.trim());
    }
  }

  async function copyReportDocumentCard(copyText, title) {
    if (!copyText) {
      setReportActionStatus("복사할 문서 내용이 아직 준비되지 않았습니다.");
      return;
    }
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      setReportActionStatus("이 브라우저에서는 문서 내용을 자동으로 복사할 수 없습니다.");
      return;
    }
    try {
      await navigator.clipboard.writeText(copyText);
      setReportActionStatus(`${title || "문서"} 내용을 클립보드에 복사했습니다.`);
    } catch (_error) {
      setReportActionStatus("문서 내용을 복사하지 못했습니다. 다시 시도해 주세요.");
    }
  }

  async function triggerReportDownload({ reportId, sessionId: activeSessionId, requestIdentity, documentType = "objection_form" }) {
    const file = await api.downloadReport({
      reportId,
      sessionId: activeSessionId,
      identity: requestIdentity,
      documentType,
    });
    const filename = file.filename || `${reportId}.docx`;
    if (typeof document === "undefined" || typeof URL === "undefined") {
      return filename;
    }

    const url = URL.createObjectURL(file.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    return filename;
  }

  function prepareMissingEvidenceUpload() {
    setAttachmentPurpose("fine_notice");
    setStatusMessage("누락 자료를 추가할 수 있도록 상담 입력으로 이동했습니다. 고지서 원본이나 보조 문서를 선택해 주세요.");
    setActiveRoute("chatbot");
  }

  function prepareDraftRegeneration() {
    setQuestion("추가 자료를 반영해 이의신청서 초안과 제출 가이드라인을 다시 정리해줘");
    setStatusMessage("초안 재생성 요청 문구를 입력창에 준비했습니다. 추가 자료가 있으면 먼저 첨부한 뒤 전송해 주세요.");
    setActiveRoute("chatbot");
  }

  async function pollQueuedWorkerResult(chatResult, requestIdentity) {
    const workItem = chatResult?.work_item || chatResult?.supervisor_execution?.work_item || null;
    if (chatResult?.execution_mode !== "async_worker" || !workItem?.work_item_id) {
      return chatResult;
    }
    let latestResult = chatResult;
    logDeveloperDiagnostic("worker.status", {
      status: "polling",
      authenticated: Boolean(requestIdentity?.authToken),
    });
    try {
      for (let attempt = 0; attempt < WORKER_POLL_MAX_ATTEMPTS; attempt += 1) {
        const jobDetailResult = await api.getAnalysisResult({
          jobId: workItem.job_id,
          identity: requestIdentity,
        });
        const jobDetail = jobDetailResult?.result || jobDetailResult?.job || {};
        const processedItem = jobDetail.work_item || {};
        const progressState = jobDetail.progress_state || processedItem.progress_state || {};
        const jobStatus = jobDetail.status || progressState.job_status || latestResult.status;
        const nextWorkItem = {
          ...workItem,
          ...processedItem,
          status: processedItem.status || workItem.status,
          job_status: progressState.job_status || jobStatus || workItem.job_status,
          progress_state: progressState,
        };
        latestResult = {
          ...latestResult,
          ...jobDetail,
          execution_mode: chatResult.execution_mode,
          persistence: chatResult.persistence,
          status: jobStatus,
          job_detail: jobDetail,
          supervisor_execution: {
            ...(latestResult.supervisor_execution || {}),
            ...(jobDetail.supervisor_execution || {}),
            work_item: nextWorkItem,
            worker_poll: {
              contract_version: "worker_progress_polling.v1",
              status: processedItem.status || null,
              job_status: jobStatus || null,
              progress_state: progressState,
            },
          },
          work_item: nextWorkItem,
        };
        logDeveloperDiagnostic("worker.status", {
          attempt: attempt + 1,
          jobStatus: jobStatus || null,
          status: processedItem.status || "waiting",
        });
        if (!WORKER_PENDING_JOB_STATUSES.has(jobStatus)) {
          return latestResult;
        }
        if (attempt < WORKER_POLL_MAX_ATTEMPTS - 1) {
          await waitForWorkerPoll();
        }
      }
      return latestResult;
    } catch (_error) {
      logDeveloperDiagnostic("worker.error", { message: _error?.message || "progress polling failed" });
      return latestResult;
    }
  }

  function updateOcrConfirmationField(field, value) {
    if (!OCR_CONFIRMATION_FIELDS.includes(field)) return;
    setOcrConfirmationFields((fields) => ({ ...fields, [field]: value }));
  }

  function submitOcrConfirmation() {
    const fields = OCR_CONFIRMATION_FIELDS.reduce((confirmed, field) => {
      const value = String(ocrConfirmationFields[field] || "").trim();
      if (value) confirmed[field] = value;
      return confirmed;
    }, {});
    const confirmation = { confirmed: true, fields };
    const followUpMessage = "OCR 추출값을 확인했습니다. 후속 절차를 진행해 주세요.";
    setPendingOcrConfirmation(confirmation);
    setQuestion(followUpMessage);
    void submitServiceMessage({
      userText: followUpMessage,
      ocrConfirmation: confirmation,
    });
  }

  function submitAttachmentClassificationConfirmation() {
    const attachmentId = String(attachmentClassificationResult?.attachment_id || "").trim();
    if (!attachmentId) {
      setStatusMessage("확인할 자료 분류를 찾지 못했습니다. 자료를 다시 첨부해 주세요.");
      return;
    }
    const followUpMessage = "자료 분류를 확인했습니다. 다음 분석을 진행해 주세요.";
    setQuestion(followUpMessage);
    void submitServiceMessage({
      userText: followUpMessage,
      attachmentClassificationConfirmation: {
        confirmed: true,
        attachment_id: attachmentId,
      },
    });
  }

  async function submitServiceMessage({
    userText,
    ocrConfirmation,
    attachmentClassificationConfirmation,
  } = {}) {
    const trimmedQuestion = String(userText ?? question).trim();
    const composedQuestion = buildStructuredConsultationMessage({
      freeText: trimmedQuestion,
      intake: consultationIntake,
    });
    const confirmationForRequest = ocrConfirmation || pendingOcrConfirmation;
    if (!composedQuestion) {
      setStatusMessage("상담 내용을 입력하거나 구조화 입력 항목을 작성해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setStatusMessage("상담 내용을 정리하고 있습니다.");
    setSubmittedQuestion(composedQuestion);

    let followupLoginState = null;
    if (!authSessionId && guestDetailedReportUsed) {
      setStatusMessage("비로그인 상담은 1회 리포팅까지 제공됩니다. 추가 질문은 Google 로그인 후 이어갑니다.");
      followupLoginState = await saveConversationWithGoogle({
        routeAfterSave: "chatbot",
        source: "guest_followup_question",
        statusMessage: "추가 질문을 위해 Google 로그인 후 기존 상담을 내 사건으로 저장하고 있습니다.",
      });
      if (!followupLoginState?.authSessionId) {
        setIsSubmitting(false);
        return;
      }
    }

    const effectiveAuthSessionId = followupLoginState?.authSessionId || authSessionId;
    const effectiveIdentity = followupLoginState?.identity || identity;
    const guestSessionResult = followupLoginState?.sessionId || sessionId ? null : await bootstrapGuestSession("chatbot");
    const activeSession = followupLoginState?.sessionId || sessionId || guestSessionResult?.sessionId || `ses_web_${Date.now()}`;
    const activeGuestId = followupLoginState?.guestId || guestId || guestSessionResult?.guestId || "";
    const activeGuestCredential = followupLoginState
      ? followupLoginState.guestCredential || ""
      : guestCredential || guestSessionResult?.guestCredential || "";
    const nextUserMessage = { role: "user", content: composedQuestion };
    const conversationHistory = [...chatMessages, nextUserMessage].map((message) => ({
      role: message.role,
      content: message.content,
    }));
    const activeAuthContext = buildAuthContext({
      authState: effectiveAuthSessionId ? "authenticated" : activeGuestId ? "guest" : "anonymous",
      guestId: activeGuestId,
      authSessionId: effectiveAuthSessionId,
      sessionId: activeSession,
      userId: followupLoginState?.userId || null,
    });
    setChatMessages(conversationHistory);
    setCurrentReport(null);
    setReportActionStatus("");

    try {
      const submitIdentity = {
        ...effectiveIdentity,
        guestId: activeGuestId,
        guestCredential: activeGuestCredential,
        authSessionId: effectiveAuthSessionId,
      };
      logDeveloperDiagnostic("chat.submit", {
        attachmentCount: registeredAttachments.length,
        authenticated: Boolean(effectiveAuthSessionId),
        executionMode,
        sessionId: activeSession,
      });
      const result = await api.submitChatMessage(
        {
          session_id: activeSession,
          auth_context: activeAuthContext,
          conversation_save_state: effectiveAuthSessionId ? "saved" : "pending",
          user_text: composedQuestion,
          ocr_confirmation: confirmationForRequest || undefined,
          attachment_classification_confirmation:
            attachmentClassificationConfirmation || undefined,
          execution_mode: executionMode,
          conversation_history: conversationHistory,
          attachments: registeredAttachments.map((attachment) => ({
            attachment_id: attachment.attachment_id,
            purpose: attachment.purpose,
            type: attachment.type,
            storage_uri: attachment.storage_uri,
          })),
        },
        submitIdentity
      );
      const workerResult = await pollQueuedWorkerResult(result, submitIdentity);
      logDeveloperDiagnostic("chat.result", buildDeveloperDiagnostic(workerResult));
      const assistantMessage = {
        role: "assistant",
        content:
          workerResult?.assistant_message?.core_answer ||
          assistantMessageText(workerResult?.assistant_message, "상담 내용을 접수했습니다."),
        status: workerResult?.status || "partial",
        pending_questions: workerResult?.pending_questions || [],
        followUp: workerResult?.assistant_message?.follow_up || null,
      };
      await streamAssistantMessage(conversationHistory, assistantMessage);
      setAnalysisResponse(workerResult);
      setQuestion("");
      setConsultationIntake(createEmptyConsultationIntake());
      const canSaveGuestConversation = !effectiveAuthSessionId && Boolean(
        workerResult?.persistence?.job_id || workerResult?.session_id || workerResult?.message_id
      );
      setSavePromptVisible(canSaveGuestConversation);
      setGuestDetailedReportUsed(canSaveGuestConversation);
      setSaveDecision(effectiveAuthSessionId ? "saved" : "undecided");
      setStatusMessage(
        effectiveAuthSessionId
          ? ""
          : canSaveGuestConversation
            ? workerResult?.status === "success"
              ? "상담 응답을 받았습니다. 저장 여부를 선택할 수 있습니다."
              : "상담 응답을 받았습니다. 현재 상태로 저장하거나 답변을 이어갈 수 있습니다."
            : "추가 정보가 필요합니다. 답변을 이어서 입력해 주세요."
      );
    } catch (_error) {
      logDeveloperDiagnostic("chat.error", {
        message: _error?.message || "unknown error",
      });
      const isRateLimitExceeded = _error?.status === 429 || _error?.code === "rate_limit_exceeded";
      const requiresLogin =
        _error?.requiredAction === "login" ||
        ["auth_required", "token_invalid", "token_expired", "login_required"].includes(_error?.code);
      const requiresGuestSessionRefresh =
        _error?.requiredAction === "refresh_guest_session" || _error?.code === "guest_session_invalid";
      let errorMessage = "응답을 불러오지 못해 접수 상태만 표시합니다.";
      if (isRateLimitExceeded) {
        errorMessage = effectiveAuthSessionId
          ? "오늘의 상담 가능 횟수를 모두 사용했습니다. 잠시 후 다시 시도해 주세요."
          : "비회원 상담 가능 횟수를 모두 사용했습니다. 계속 상담하려면 Google 로그인해 주세요.";
      } else if (requiresGuestSessionRefresh) {
        clearStoredAuthSession();
        setActiveAuthToken("");
        setAuthSessionId("");
        setGuestId("");
        setGuestCredential("");
        setSessionId("");
        errorMessage = _error?.publicMessage || "임시 상담 세션이 만료되었습니다. 다시 시작해 주세요.";
      } else if (requiresLogin) {
        clearStoredAuthSession();
        persistAuthSession({
          guestId: guestId || "",
          guestCredential: guestCredential || "",
          sessionId: activeSession || sessionId || "",
        });
        setActiveAuthToken("");
        setAuthSessionId("");
        errorMessage = effectiveAuthSessionId
          ? _error?.publicMessage || "로그인이 만료되었습니다. 다시 로그인한 뒤 같은 상담을 이어가 주세요."
          : _error?.publicMessage || "로그인이 필요합니다. Google 로그인 후 같은 상담을 이어가 주세요.";
      }
      setChatMessages([
        ...conversationHistory,
        {
          role: "assistant",
          content: errorMessage,
          status: "partial",
          pending_questions: [],
        },
      ]);
      setAnalysisResponse(isRateLimitExceeded ? null : { cards: FALLBACK_ANALYSIS_CARDS });
      setSavePromptVisible(!isRateLimitExceeded && !authSessionId);
      setStatusMessage(errorMessage);
    } finally {
      setIsSubmitting(false);
      if (confirmationForRequest) {
        setPendingOcrConfirmation(null);
      }
    }
  }

  async function streamAssistantMessage(conversationHistory, assistantMessage) {
    const tokens = String(assistantMessage.content || "").match(/\S+\s*/g) || [];
    const batchSize = Math.max(1, Math.ceil(tokens.length / 160));
    let renderedContent = "";

    if (!isMountedRef.current) return;
    if (!tokens.length) {
      setChatMessages([
        ...conversationHistory,
        { ...assistantMessage, content: "", streaming: false },
      ]);
      return;
    }

    setChatMessages([
      ...conversationHistory,
      { ...assistantMessage, content: "", streaming: true },
    ]);

    for (let index = 0; index < tokens.length; index += batchSize) {
      if (!isMountedRef.current) return;
      renderedContent += tokens.slice(index, index + batchSize).join("");
      setChatMessages([
        ...conversationHistory,
        {
          ...assistantMessage,
          content: renderedContent,
          streaming: index + batchSize < tokens.length,
        },
      ]);
      if (index + batchSize < tokens.length) {
        await waitForAssistantToken();
      }
    }
  }

  async function saveConversationWithGoogle({
    routeAfterSave = "mypage",
    source = "google_login_save_prompt",
    statusMessage = "Google 로그인 후 현재 상담을 내 사건 이력에 연결하고 있습니다.",
  } = {}) {
    setIsSavingConversation(true);
    setStatusMessage(statusMessage);
    try {
      const loginState = await loginAndBindCurrentSession({
        source,
        nextRoute: "chatbot",
      });
      await api.updateConversationSaveState(
        {
          session_id: loginState.sessionId,
          conversation_save_state: "saved",
          conversation_save_source: source,
        },
        loginState.identity
      );
      const summary = await api.getMyPageSummary({ identity: loginState.identity, sessionId: loginState.sessionId });
      setMypageSummary(summary);
      const events = await api.listHistoryEvents({ identity: loginState.identity, sessionId: loginState.sessionId });
      setHistoryEvents(events);
      setActiveRoute(routeAfterSave);

      setSaveDecision("saved");
      setSavePromptVisible(false);
      setGuestDetailedReportUsed(false);
      setStatusMessage("현재 상담을 Google 계정 기준 내 사건 이력에 저장했습니다.");
      return loginState;
    } catch (_error) {
      setStatusMessage("로그인 또는 저장 연결에 실패했습니다. 상담은 지금 상태로 계속 진행할 수 있습니다.");
      return null;
    } finally {
      setIsSavingConversation(false);
    }
  }

  async function saveConversationAfterLogin() {
    await saveConversationWithGoogle({
      routeAfterSave: "mypage",
      source: "google_login_save_prompt",
    });
  }


  async function keepConversationTemporary() {
    setSaveDecision("session_only");
    setSavePromptVisible(false);
    if (sessionId) {
      try {
        await api.updateConversationSaveState(
          {
            session_id: sessionId,
            conversation_save_state: "session_only",
            conversation_save_source: "user_declined_save_prompt",
          },
          identity
        );
      } catch (_error) {
        // Local UI state still reflects the user's choice if the API update is unavailable.
      }
    }
    setStatusMessage(
      "이번 상담은 임시로만 계속 진행합니다. 저장하지 않으면 내 사건 이력에는 표시하지 않습니다."
    );
  }

  function startNewConversation() {
    setQuestion("");
    setSubmittedQuestion("");
    setChatMessages([]);
    setConsultationIntake(createEmptyConsultationIntake());
    setAnalysisResponse(null);
    setCurrentReport(null);
    setReportActionStatus("");
    setSaveDecision("undecided");
    setSavePromptVisible(false);
    setGuestDetailedReportUsed(false);
    setSessionId("");
    setStatusMessage("새 상담을 시작할 수 있습니다.");
    setActiveRoute("chatbot");
  }

  async function loadMyPageSummary(options = {}) {
    const requestIdentity = options?.identity || identity;
    const requestSessionId = options?.sessionId || sessionId;
    setStatusMessage("내 사건을 불러오고 있습니다.");
    try {
      const summary = await api.getMyPageSummary({ sessionId: requestSessionId, identity: requestIdentity });
      setMypageSummary(summary);
      setStatusMessage("내 사건 현황을 업데이트했습니다.");
      return summary;
    } catch (_error) {
      setStatusMessage("저장된 사건을 찾지 못했습니다.");
      return null;
    }
  }

  async function loadHistoryEvents(options = {}) {
    const requestIdentity = options?.identity || identity;
    const requestSessionId = options?.sessionId || sessionId;
    setStatusMessage("과거 이력을 불러오고 있습니다.");
    try {
      const events = await api.listHistoryEvents({ sessionId: requestSessionId, identity: requestIdentity });
      setHistoryEvents(events);
      setStatusMessage("과거 이력을 업데이트했습니다.");
      return events;
    } catch (_error) {
      setStatusMessage("저장된 이력을 찾지 못했습니다.");
      return null;
    }
  }

  async function loadReports(options = {}) {
    const requestIdentity = options?.identity || identity;
    const requestSessionId = options?.sessionId || sessionId;
    if (!requestIdentity?.authToken && !requestIdentity?.authSessionId) {
      setReportList([]);
      setStatusMessage("저장 리포트 목록은 로그인 후 확인할 수 있습니다.");
      return { reports: [] };
    }
    setStatusMessage("리포트 목록을 불러오고 있습니다.");
    try {
      const result = await api.listReports({ sessionId: requestSessionId, identity: requestIdentity });
      const reports = Array.isArray(result?.reports) ? result.reports : [];
      setReportList(reports);
      if (!currentReport && reports[0]) {
        setCurrentReport(reports[0]);
      }
      setStatusMessage("리포트 목록을 업데이트했습니다.");
      return result;
    } catch (_error) {
      setReportList([]);
      setStatusMessage(
        _error?.message?.includes("login_required")
          ? "저장 리포트 목록은 로그인 후 확인할 수 있습니다."
          : "리포트 목록을 불러오지 못했습니다."
      );
      return null;
    }
  }

  async function openReportDetail(report) {
    const reportId = report?.report_id || "";
    if (!reportId) {
      return;
    }
    const requestSessionId = report?.session_id || sessionId;
    if (!identity?.authToken && !identity?.authSessionId) {
      setCurrentReport(report);
      setReportActionStatus("로그인 후 리포트 상세를 다시 불러올 수 있습니다.");
      setStatusMessage("리포트 상세는 로그인 후 확인할 수 있습니다.");
      return;
    }
    setStatusMessage("리포트 상세를 불러오고 있습니다.");
    try {
      const result = await api.getReportDetail({
        reportId,
        sessionId: requestSessionId,
        identity,
      });
      const detail = result?.report || report;
      setCurrentReport(detail);
      setReportActionStatus(`선택한 리포트: ${detail.report_id || reportId}`);
      setStatusMessage("리포트 상세를 미리보기에 반영했습니다.");
    } catch (_error) {
      setCurrentReport(report);
      setReportActionStatus("리포트 상세를 불러오지 못해 목록 요약만 표시합니다.");
      setStatusMessage("리포트 상세를 불러오지 못했습니다.");
    }
  }

  async function openSavedCase(item) {
    const jobId = item?.job_id || item?.case_id || "";
    if (jobId) {
      setStatusMessage("저장된 상담과 리포트를 불러오고 있습니다.");
      try {
        const detail = await api.getAnalysisJobDetail({ jobId, identity });
        const job = detail?.job || {};
        const restoredMessages = restoreConversationMessages(job, item);
        const restoredResponse = restoreAnalysisResponse(job, item);
        const restoredReport = restoreCurrentReport(job, item);
        const firstUserMessage = restoredMessages.find((message) => message.role === "user");

        setSessionId(job.session_id || item?.session_id || sessionId);
        setSubmittedQuestion(firstUserMessage?.content || item?.title || job.progress_message || "");
        setChatMessages(restoredMessages);
        setAnalysisResponse(restoredResponse);
        setCurrentReport(restoredReport);
        setReportActionStatus(
          restoredReport
            ? "내 사건에서 저장된 상담과 리포트를 불러왔습니다."
            : "내 사건에서 저장된 상담을 불러왔습니다. 리포트는 상담 결과 아래에서 다시 생성할 수 있습니다."
        );
        setSaveDecision("saved");
        setSavePromptVisible(false);
        setGuestDetailedReportUsed(false);
        setStatusMessage("저장된 상담을 현재 대화로 다시 열었습니다.");
        setActiveRoute("chatbot");
        return;
      } catch (_error) {
        setStatusMessage("상담 상세를 불러오지 못해 저장 리포트 정보만 표시합니다.");
      }
    }

    const reportId = item?.latest_report_id || item?.report_id || "";
    if (!reportId) {
      setCurrentReport(null);
      setReportActionStatus("선택한 사건에는 아직 저장된 리포트가 없습니다. 상담 화면에서 이어갈 수 있습니다.");
      setActiveRoute("chatbot");
      return;
    }

    const reportStatus = item?.latest_report_status || item?.status || "saved";
    setCurrentReport({
      report_id: reportId,
      status: reportStatus,
      persistence: { status: reportStatus },
      metadata: {
        case_id: item?.case_id || item?.job_id || "",
        title: item?.title || item?.case_id || "저장된 상담 리포트",
        updated_at: item?.updated_at || item?.last_event_at || item?.created_at || "",
        report_count: item?.report_count || 1,
      },
    });
    setReportActionStatus("내 사건에서 저장된 리포트를 열었습니다.");
    setActiveRoute("reporting");
  }

  const showSidebar = activeRoute !== "entry" && activeRoute !== "mypage" && activeRoute !== "reporting";

  return (
    <div className="app-shell" data-auth-state={authContext.auth_state}>
      <AppIconRail
        activeRoute={activeRoute}
        onNavigate={setActiveRoute}
        onOpenChat={() => bootstrapGuestSession("chatbot")}
      />
      <div className="app-shell__body">
      {(authSessionId || !["chatbot", "history"].includes(activeRoute)) && (
        <div className="top-float-actions" aria-label="주요 메뉴">
          {authSessionId ? (
            <button className="button ghost small" type="button" onClick={logoutAndResetSession}>
              로그아웃
            </button>
          ) : (
            <button
              className="button primary small"
              type="button"
              onClick={saveConversationAfterLogin}
              disabled={isSavingConversation}
            >
              {isSavingConversation ? "연결 중" : "Google 로그인"}
            </button>
          )}
        </div>
      )}

      <div
        className={
          !showSidebar
            ? "layout is-entry"
            : isSidebarCollapsed
              ? "layout sidebar-collapsed"
              : "layout"
        }
      >
        {showSidebar && (
          <ConversationSidebar
            activeRoute={activeRoute}
            cases={cases}
            currentTitle={submittedQuestion}
            isAuthenticated={Boolean(authSessionId)}
            isCollapsed={isSidebarCollapsed}
            isGuestReady={isGuestReady}
            isSavingConversation={isSavingConversation}
            onLogin={saveConversationAfterLogin}
            onLogout={logoutAndResetSession}
            onNavigate={setActiveRoute}
            onNewChat={startNewConversation}
            onOpenCase={openSavedCase}
            onToggleCollapse={() => setIsSidebarCollapsed((value) => !value)}
            savePromptVisible={savePromptVisible}
            sessionLabel={sessionLabel}
            statusMessage={statusMessage}
          />
        )}

        <main className="workspace" aria-live="polite">
          {activeRoute === "entry" && (
            <EntryScreenV2
              isAuthenticated={Boolean(authSessionId)}
              onGuestStart={() => bootstrapGuestSession("chatbot")}
              onOpenChat={() => bootstrapGuestSession("chatbot")}
              onNavigate={setActiveRoute}
            />
          )}

          {activeRoute === "chatbot" && (
            <ChatScreenV2
              analysisCards={visibleAnalysisCards}
              attachmentOptions={attachmentOptions}
              assistantAnswer={assistantAnswer}
              assistantFollowUp={assistantFollowUp}
              chatSafetyGuidance={chatSafetyGuidance}
              authSessionId={authSessionId}
              chatMessages={chatMessages}
              currentReport={currentReport}
              onOpenCaseResult={(route) => setActiveRoute(route)}
              isRegisteringAttachment={isRegisteringAttachment}
              isSubmitting={isSubmitting}
              isSavingConversation={isSavingConversation}
              onAttachmentDragOver={handleAttachmentDragOver}
              onAttachmentDrop={handleAttachmentDrop}
              onAttachmentFile={handleAttachmentFile}
              onConfirmOcr={submitOcrConfirmation}
              onConfirmAttachmentClassification={submitAttachmentClassificationConfirmation}
              onOcrFieldChange={updateOcrConfirmationField}
              onKeepTemporary={keepConversationTemporary}
              onRegisterAttachment={registerAttachmentMetadata}
              onOpenReporting={() => setActiveRoute("reporting")}
              onConfirmReportDocument={confirmCurrentReportDocument}
              onRunReportAction={runCurrentReportAction}
              onSaveConversation={saveConversationAfterLogin}
              onSubmit={submitServiceMessage}
              pendingAuthAction={pendingAuthAction}
              ocrConfirmationFields={ocrConfirmationFields}
              ocrResult={ocrResult}
              attachmentClassificationResult={attachmentClassificationResult}
              question={question}
              registeredAttachments={registeredAttachments}
              reportActionStatus={reportActionStatus}
              saveDecision={saveDecision}
              savePromptVisible={savePromptVisible}
              selectedUploadFile={selectedUploadFile}
              reportingPayload={reportingPayload}
              consultationIntake={consultationIntake}
              setAttachmentPurpose={setAttachmentPurpose}
              setConsultationIntake={setConsultationIntake}
              setQuestion={setQuestion}
              capabilityError={capabilityError}
              submittedQuestion={submittedQuestion}
              supervisorExecution={supervisorExecution}
              supervisorState={supervisorState}
              uploadInputResetKey={uploadInputResetKey}
            />
          )}

          {(activeRoute === "fineResult" || activeRoute === "faultResult") && (
            <CaseResultScreen
              analysisCards={analysisCards}
              caseType={activeRoute === "faultResult" ? "fault" : caseType}
              currentReport={currentReport}
              deadlineGuidance={deadlineGuidance}
              resultSafetyGuidance={resultSafetyGuidance}
              isAuthenticated={Boolean(authSessionId)}
              onOpenChat={() => setActiveRoute("chatbot")}
              onOpenReport={() => setActiveRoute("reporting")}
              onPrepareDraftRegeneration={prepareDraftRegeneration}
              onPrepareMissingEvidence={prepareMissingEvidenceUpload}
              onConfirmDocument={confirmCurrentReportDocument}
              onRunReportAction={runCurrentReportAction}
              registeredAttachments={registeredAttachments}
              reportingPayload={reportingPayload}
              reportActionStatus={reportActionStatus}
              supervisorExecution={supervisorExecution}
              supervisorState={supervisorState}
              userClaims={analysisResponse?.user_claims || []}
            />
          )}

          {activeRoute === "mypage" && (
            <MyPageScreen
              cases={cases}
              onOpenChat={() => setActiveRoute("chatbot")}
              onOpenCase={openSavedCase}
              onRefresh={loadMyPageSummary}
              summary={effectiveMypageSummary}
            />
          )}

          {activeRoute === "history" && (
            <HistoryScreen events={history} onRefresh={loadHistoryEvents} />
          )}

          {activeRoute === "reporting" && (
            <ReportingScreen
              analysisCards={visibleAnalysisCards}
              currentReport={effectiveCurrentReport}
              isAuthenticated={Boolean(authSessionId)}
              onOpenChat={() => setActiveRoute("chatbot")}
              onOpenReport={openReportDetail}
              onRefresh={async () => {
                await loadMyPageSummary();
                await loadHistoryEvents();
                await loadReports();
              }}
              onPrepareDraftRegeneration={prepareDraftRegeneration}
              onPrepareMissingEvidence={prepareMissingEvidenceUpload}
              onCopyDocumentCard={copyReportDocumentCard}
              onRunReportAction={runCurrentReportAction}
              reportActionStatus={reportActionStatus}
              reportList={effectiveReportList}
              reportingPayload={visibleReportingPayload}
              supervisorExecution={supervisorExecution}
              supervisorState={supervisorState}
            />
          )}

        </main>
      </div>
      </div>
    </div>
  );
}

function persistedAnalysisReportId(analysisResponse, currentReport) {
  const reportLinks = Array.isArray(analysisResponse?.report_links) ? analysisResponse.report_links : [];
  const analysisReportId = reportLinks.find((link) => link?.report_id)?.report_id || "";
  return currentReport?.report_id || analysisReportId || "";
}

function EntryScreen({ onGuestStart, onOpenChat }) {
  return (
    <section className="entry-screen">
      <div className="entry-copy">
        <span className="eyebrow">로그인 후 바로 상담 시작</span>
        <h1>사고와 과태료 자료를 올리면 AI가 필요한 다음 행동을 정리합니다.</h1>
        <p className="lead">
          고지서와 사고 상황을 입력하면 과태료 이의제기 가능성, 과실비율 쟁점,
          관련 근거와 작성 초안을 한 화면에서 확인할 수 있습니다.
        </p>
        <div className="entry-actions">
          <button className="button primary" type="button" onClick={onOpenChat}>
            Google로 계속하기
          </button>
          <button className="button" type="button" onClick={onGuestStart}>
            비회원 상담 시작
          </button>
        </div>
        <div className="trust-row">
          <div className="trust-item">
            <strong>자료 기반 분석</strong>
            <p>사진, 고지서, 상황 설명을 함께 확인합니다.</p>
          </div>
          <div className="trust-item">
            <strong>근거 확인</strong>
            <p>관련 법령, 판례, 보험 기준을 결과와 함께 보여줍니다.</p>
          </div>
          <div className="trust-item">
            <strong>문서 초안</strong>
            <p>의견제출서와 이의신청서 초안을 이어서 작성합니다.</p>
          </div>
        </div>
      </div>
      <div className="entry-preview" aria-label="상담 미리보기">
        <div className="phone-frame">
          <div className="phone-head">
            <strong>AI 교통 상담</strong>
            <span className="tag green">대기 중</span>
          </div>
          <div className="phone-body">
            <div className="preview-bubble">새 상담이 준비되었습니다.</div>
            <div className="preview-bubble answer">질문 입력 전</div>
            <div className="preview-result">
              <strong>자료 분석 대기</strong>
              <p>로그인 후 고지서와 보조 문서를 연결합니다.</p>
              <button className="button primary" type="button" onClick={onOpenChat}>
                상담 화면 열기
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ChatScreen({
  analysisCards,
  isSubmitting,
  onSubmit,
  question,
  setQuestion,
  statusMessage,
  submittedQuestion,
}) {
  const hasConversation = Boolean(submittedQuestion);

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>AI 교통 상담</h2>
          <p>회원은 명령문과 자료를 함께 제출하고, 비회원은 단순 교통 질문부터 시작합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button">
            내 사건 보기
          </button>
          <button className="button primary" type="button">
            회원 자료 추가
          </button>
        </div>
      </div>

      <div className="chat-shell">
        <div className="conversation-list">
          <div className="section-label">최근 상담</div>
          <div className="empty-panel">
            <strong>아직 상담 이력이 없습니다.</strong>
            <p>질문을 입력하면 이 영역에 상담 목록이 쌓입니다.</p>
          </div>
        </div>

        <div className="chat-main">
          <div className="messages">
            {!hasConversation && (
              <section className="chat-empty-state" aria-label="새 상담 시작">
                <span className="eyebrow">새 상담</span>
                <h3>어떤 교통 문제를 확인할까요?</h3>
                <p>
                  사고 상황, 고지서, 보험사 주장처럼 확인하고 싶은 내용을 먼저 문장으로 적어 주세요.
                  자료 첨부 분석은 로그인 후 이어서 진행합니다.
                </p>
                <div className="policy-grid">
                  <div className="policy-card">
                    <span>회원</span>
                    <strong>명령문 + 자료 분석</strong>
                    <p>고지서와 보조 문서를 분석 목적과 함께 제출합니다.</p>
                  </div>
                  <div className="policy-card is-disabled">
                    <span>비회원</span>
                    <strong>단순 질문부터 가능</strong>
                    <p>개인 자료가 필요한 OCR·영상 분석은 로그인 후 진행합니다.</p>
                  </div>
                </div>
              </section>
            )}

            {hasConversation && (
              <>
                <article className="message user">
                  <span className="message-avatar">나</span>
                  <div className="bubble">
                    <p>{submittedQuestion}</p>
                  </div>
                </article>

                <article className="message">
                  <span className="message-avatar">AI</span>
                  <div className="bubble wide">
                    <strong>상담 내용을 확인했습니다.</strong>
                    <p>
                      입력 기준으로 확인 가능한 항목을 정리합니다. 최종 판단은 추가 자료와 기관 확인에
                      따라 달라질 수 있습니다.
                    </p>
                    {analysisCards.length > 0 && (
                      <div className="result-cards">
                        {analysisCards.map((card, index) => (
                          <div className="result-card" key={analysisCardKey(card, index)}>
                            <span className={card.status === "success" ? "tag green" : "tag amber"}>
                              {card.card_type}
                            </span>
                            <strong>{card.title}</strong>
                            <p>{card.summary}</p>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="chatbot-actions">
                      <button className="button primary" type="button">
                        리포트로 이어가기
                      </button>
                      <button className="button" type="button">
                        추가 질문하기
                      </button>
                    </div>
                  </div>
                </article>
              </>
            )}
          </div>

          <div className="quick-row" aria-label="빠른 질문">
            <button className="quick-chip" type="button">고지서 분석하기</button>
            <button className="quick-chip" type="button">사고 분석 준비</button>
            <button className="quick-chip" type="button">의견제출서 초안</button>
            <button className="quick-chip" type="button">단순 법령 질문</button>
          </div>

          <div className="chat-input">
            <div className="input-stack">
              <div className="attachment-strip">
                <span>파일 첨부 분석은 로그인 후 이용할 수 있습니다.</span>
              </div>
              <textarea
                aria-label="상담 메시지 입력"
                placeholder="교통사고, 고지서, 보험 분쟁 등 확인할 내용을 입력해 주세요."
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
            </div>
            <button className="button primary" type="button" onClick={onSubmit} disabled={isSubmitting}>
              {isSubmitting ? "정리 중" : "전송"}
            </button>
          </div>

          {statusMessage && (
            <p className="status-message inside" role="status">
              {statusMessage}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function Reveal({ children, className = "", as = "div", ...rest }) {
  const Tag = as;
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag ref={ref} className={`reveal${visible ? " reveal--visible" : ""}${className ? ` ${className}` : ""}`} {...rest}>
      {children}
    </Tag>
  );
}

const RAIL_ITEMS = [
  {
    id: "entry",
    label: "홈",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 11.5 12 4l8 7.5" />
        <path d="M6 10v9h12v-9" />
      </svg>
    ),
  },
  {
    id: "chatbot",
    label: "AI 상담",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 5h16v11H8l-4 4V5z" />
      </svg>
    ),
  },
  {
    id: "reporting",
    label: "리포트",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 3h9l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
        <path d="M14 3v5h5" />
      </svg>
    ),
  },
  {
    id: "mypage",
    label: "마이페이지",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="8" r="3.4" />
        <path d="M5 20c1.4-3.6 4.2-5.5 7-5.5s5.6 1.9 7 5.5" />
      </svg>
    ),
  },
];

function AppIconRail({ activeRoute, onNavigate, onOpenChat }) {
  const handleClick = (routeId) => {
    if (routeId === "chatbot" && typeof onOpenChat === "function") {
      onOpenChat();
      return;
    }
    if (typeof onNavigate === "function") {
      onNavigate(routeId);
    }
  };

  return (
    <aside className="app-rail" aria-label="빠른 이동">
      {RAIL_ITEMS.map((item) => (
        <button
          key={item.id}
          className={activeRoute === item.id ? "rail-icon active" : "rail-icon"}
          type="button"
          onClick={() => handleClick(item.id)}
          title={item.label}
          aria-label={item.label}
          aria-current={activeRoute === item.id ? "page" : undefined}
        >
          {item.icon}
        </button>
      ))}
      <button
        className={activeRoute === "history" ? "rail-icon rail-icon--bottom active" : "rail-icon rail-icon--bottom"}
        type="button"
        onClick={() => handleClick("history")}
        title="과거 이력"
        aria-label="과거 이력"
        aria-current={activeRoute === "history" ? "page" : undefined}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7.5V12l3 2" />
        </svg>
      </button>
    </aside>
  );
}

function EntryScreenV2({ isAuthenticated, onGuestStart, onOpenChat, onNavigate }) {
  const [activeCard, setActiveCard] = useState(0);
  const lastWheelAt = useRef(0);
  const touchStartRef = useRef(null);
  const wheelCards = ["상황과 자료", "서비스 안내", "진행 순서", "주요 기능"];
  const goToRoute = (route) => {
    if (typeof onNavigate === "function") {
      onNavigate(route);
    }
  };
  const rotateWheel = (direction) => {
    setActiveCard((current) => (current + direction + 4) % 4);
  };
  const handleWheel = (event) => {
    const now = Date.now();
    if (now - lastWheelAt.current < 420 || Math.abs(event.deltaY) < 8) return;
    lastWheelAt.current = now;
    rotateWheel(event.deltaY > 0 ? 1 : -1);
  };

  return (
    <section className="entry-screen insurance-layout entry-dashboard entry-wheel">
      <div className="entry-wheel__shell">
        <div
          className="entry-wheel__viewport"
          tabIndex={0}
          onWheel={handleWheel}
          onTouchStart={(event) => {
            const touch = event.touches[0];
            touchStartRef.current = { x: touch.clientX, y: touch.clientY };
          }}
          onTouchEnd={(event) => {
            const start = touchStartRef.current;
            const touch = event.changedTouches[0];
            touchStartRef.current = null;
            if (!start || !touch) return;
            const deltaX = touch.clientX - start.x;
            const deltaY = touch.clientY - start.y;
            const primaryDelta = Math.abs(deltaY) >= Math.abs(deltaX) ? deltaY : deltaX;
            if (Math.abs(primaryDelta) < 46) return;
            rotateWheel(primaryDelta < 0 ? 1 : -1);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") rotateWheel(-1);
            if (event.key === "ArrowRight") rotateWheel(1);
          }}
          aria-label="홈 화면 기능 카드 캐러셀"
        >
          <nav className="entry-wheel__radial-nav" aria-label="홈 화면 카드 선택">
            <div className="entry-wheel__orbit" aria-hidden="true" />
            {wheelCards.map((label, index) => {
              let offset = (index - activeCard + wheelCards.length) % wheelCards.length;
              if (offset > 1) offset -= wheelCards.length;
              const radialPosition = {
                "-2": { x: 6, y: -205 },
                "-1": { x: 74, y: -112 },
                "0": { x: 118, y: 0 },
                "1": { x: 78, y: 132 },
              }[String(offset)];
              return (
                <button
                  className={activeCard === index ? "entry-wheel__radial-item is-active" : "entry-wheel__radial-item"}
                  type="button"
                  key={label}
                  style={{
                    "--radial-x": `${radialPosition.x}px`,
                    "--radial-y": `${radialPosition.y}px`,
                  }}
                  onClick={() => setActiveCard(index)}
                  aria-current={activeCard === index ? "true" : undefined}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{label}</strong>
                </button>
              );
            })}
          </nav>
          <div
            className="entry-wheel__rotor"
          >
          <article
            className={`entry-card entry-card--photo entry-wheel__card ${activeCard === 0 ? "is-active" : ""}`}
            style={{ "--wheel-index": 0 }}
            onClick={() => setActiveCard(0)}
          >
            <img
              src="/design-references/02-consultation-desk.jpg"
              alt="차량 관련 서류를 검토하는 상담 장면"
              loading="lazy"
            />
            <div className="entry-wheel__photo-label">
              <span>01</span>
              <strong>당신의 편리한 교통사고 서포트 앱</strong>
            </div>
          </article>

          <article
            className={`entry-card entry-card--intro entry-wheel__card ${activeCard === 1 ? "is-active" : ""}`}
            style={{ "--wheel-index": 1 }}
            onClick={() => setActiveCard(1)}
          >
            <span className="entry-wheel__number">02 · 서비스 안내</span>
            <p>
              과실비율 예측과 과태료 이의신청 지원까지, 상황과 자료를 바탕으로
              쟁점과 다음 행동을 정리해 드리는 서비스입니다.
            </p>
            <div className="entry-card__actions">
              <button className="button primary" type="button" onClick={onOpenChat}>
                바로 상담 시작
              </button>
              {isAuthenticated && (
                <button className="button on-dark" type="button" onClick={() => goToRoute("reporting")}>
                  지난 리포트
                </button>
              )}
            </div>
          </article>

          <article
            className={`entry-card entry-card--steps entry-wheel__card ${activeCard === 2 ? "is-active" : ""}`}
            style={{ "--wheel-index": 2 }}
            onClick={() => setActiveCard(2)}
          >
            <div className="entry-card__head">
              <span className="entry-wheel__number">03 · 이용 과정</span>
              <strong>진행 순서</strong>
              <p>이렇게 도와드립니다</p>
            </div>
            <div className="entry-step-list">
              <div className="entry-step-row">
                <strong className="index index--brand">01</strong>
                <div>
                  <strong>상황 요약</strong>
                  <p>입력한 내용을 핵심 사실 중심으로 정리합니다.</p>
                  <span className="entry-step-icon entry-step-icon--brand">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6 4h9l3 3v13H6V4z" />
                      <path d="M9 10h6M9 13.5h6M9 17h4" />
                    </svg>
                  </span>
                </div>
              </div>
              <div className="entry-step-row">
                <strong className="index index--info">02</strong>
                <div>
                  <strong>쟁점 확인</strong>
                  <p>판단에 중요한 기준과 빠진 자료를 알려드립니다.</p>
                  <span className="entry-step-icon entry-step-icon--info">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="6.5" />
                      <path d="M16 16l4.5 4.5" />
                    </svg>
                  </span>
                </div>
              </div>
              <div className="entry-step-row">
                <strong className="index index--green">03</strong>
                <div>
                  <strong>근거 조회</strong>
                  <p>관련 법령과 판례를 확인할 수 있습니다.</p>
                  <span className="entry-step-icon entry-step-icon--green">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 5c-2-1.2-4.6-1.5-7-1v13c2.4-.5 5 -.2 7 1 2-1.2 4.6-1.5 7-1V4c-2.4-.5-5-.2-7 1z" />
                      <path d="M12 5v13" />
                    </svg>
                  </span>
                </div>
              </div>
              <div className="entry-step-row">
                <strong className="index index--amber">04</strong>
                <div>
                  <strong>다음 행동</strong>
                  <p>준비할 자료와 처리 순서를 제안합니다.</p>
                  <span className="entry-step-icon entry-step-icon--amber">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h13" />
                      <path d="M13 6l6 6-6 6" />
                    </svg>
                  </span>
                </div>
              </div>
            </div>
          </article>

          <article
            className={`entry-card entry-card--features entry-wheel__card ${activeCard === 3 ? "is-active" : ""}`}
            style={{ "--wheel-index": 3 }}
            onClick={() => setActiveCard(3)}
          >
            <div className="entry-card__head">
              <span className="entry-wheel__number">04 · 주요 기능</span>
              <strong>우리 기능들</strong>
            </div>
            <div className="entry-quick-list entry-quick-list--light">
              <button className="entry-quick-item" type="button" onClick={onOpenChat}>
                <span className="entry-quick-icon entry-quick-icon--info">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 4v2" />
                    <path d="M4 6h16" />
                    <path d="M4 6L2 11a2.2 2.2 0 0 0 4.4 0z" />
                    <path d="M20 6l-2 5a2.2 2.2 0 0 0 4.4 0z" />
                    <path d="M12 6v14" />
                    <path d="M8.5 20h7" />
                  </svg>
                </span>
                <span>
                  <strong>법률·판례 조회</strong>
                  <small>관련 법령과 판례를 확인합니다</small>
                </span>
              </button>
              <button className="entry-quick-item" type="button" onClick={onOpenChat}>
                <span className="entry-quick-icon entry-quick-icon--green">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 16l1.1-4.5A2 2 0 0 1 8 10h8a2 2 0 0 1 1.9 1.5L20 16" />
                    <path d="M4 16h16v2a1 1 0 0 1-1 1h-1.3a1 1 0 0 1-1-1v-.3H7.3v.3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-2z" />
                    <circle cx="7.5" cy="16" r="1.3" />
                    <circle cx="16.5" cy="16" r="1.3" />
                  </svg>
                </span>
                <span>
                  <strong>사고 과실비율 예측</strong>
                  <small>사고 상황과 자료를 정리합니다</small>
                </span>
              </button>
              <button className="entry-quick-item" type="button" onClick={onOpenChat}>
                <span className="entry-quick-icon entry-quick-icon--amber">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 3.5h7l3 3v14H7z" />
                    <path d="M14 3.5v3h3" />
                    <path d="M9.5 16.8l5-5 2 2-5 5H9.5v-2z" />
                  </svg>
                </span>
                <span>
                  <strong>과태료 이의신청 지원</strong>
                  <small>신청서 초안 작성을 돕습니다</small>
                </span>
              </button>
            </div>
          </article>
          </div>
        </div>

      </div>
    </section>
  );
}

function ConversationSidebar({
  activeRoute,
  cases,
  currentTitle,
  isAuthenticated,
  isCollapsed = false,
  isGuestReady,
  isSavingConversation,
  onLogin,
  onLogout,
  onNavigate,
  onNewChat,
  onOpenCase,
  onToggleCollapse,
  savePromptVisible,
  sessionLabel,
  statusMessage,
}) {
  const hasCases = cases.length > 0;
  const currentConversationTitle = currentTitle || "새 상담";

  return (
    <>
      <aside
        className={isCollapsed ? "sidebar chat-sidebar collapsed" : "sidebar chat-sidebar"}
        aria-label="대화 목록과 계정"
      >
        <div className="sidebar-brand">
          <button
            className="sidebar-collapse-toggle"
            type="button"
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? "사이드바 펼치기" : "사이드바 접기"}
            title={isCollapsed ? "사이드바 펼치기" : "사이드바 접기"}
          >
            {isCollapsed ? "»" : "«"}
          </button>
          {!isCollapsed && <span className="sidebar-collapse-label">접기</span>}
        </div>

      {!isCollapsed && (
      <>
      <div className="sidebar-actions">
        <button className="nav-item primary-action" type="button" onClick={onNewChat}>
          <span>+</span>
          <span>새 상담</span>
        </button>
        <button className="nav-item" type="button" onClick={() => onNavigate("history")}>
          <span>상담 검색</span>
        </button>
      </div>

      <section className="conversation-section" aria-label="현재 대화">
        <div className="section-label">현재</div>
        <button
          className="conversation-card active"
          type="button"
          onClick={() => onNavigate("chatbot")}
        >
          <strong>{currentConversationTitle}</strong>
          <span>{isAuthenticated ? "저장됨 · 추가 질문 가능" : savePromptVisible ? "게스트 리포트 생성됨" : "게스트 상담"}</span>
        </button>
      </section>

      <section className="conversation-section grow" aria-label="내 사건 대화">
        <div className="section-label">내 사건</div>
        {!hasCases ? (
          <div className="empty-panel compact">
            <p>{isAuthenticated ? "저장된 상담이 아직 없습니다." : "로그인하면 저장한 상담과 리포트 상태가 표시됩니다."}</p>
          </div>
        ) : (
          cases.slice(0, 8).map((item) => (
            <button
              className="conversation-card compact"
              key={item.case_id || item.job_id || item.title}
              type="button"
              onClick={() => onOpenCase(item)}
            >
              <strong>{item.title || item.case_id}</strong>
            </button>
          ))
        )}
      </section>

        <section className="sidebar-auth" aria-label="계정 상태">
          <div className="profile-row">
            <span className="avatar">{isAuthenticated ? "G" : isGuestReady ? "비" : "AI"}</span>
            <div>
              <div className="profile-name">{sessionLabel}</div>
              <div className="profile-meta">{isAuthenticated ? "대화 저장 및 후속 질문 가능" : "비회원 1회 리포팅 가능"}</div>
            </div>
          </div>
          {!isAuthenticated && (
            <button className="button primary full" type="button" onClick={onLogin} disabled={isSavingConversation}>
              {isSavingConversation ? "연결 중" : "Google 로그인"}
            </button>
          )}

          {statusMessage && <p className="sidebar-status">{statusMessage}</p>}
        </section>
      </>
      )}
      </aside>
      <nav className="mobile-bottom-nav" aria-label="모바일 주요 메뉴">
        <button className="mobile-bottom-nav__item" type="button" onClick={onNewChat}>
          <span aria-hidden="true">＋</span>
          <strong>새 상담</strong>
        </button>
        <button
          className={activeRoute === "mypage" ? "mobile-bottom-nav__item active" : "mobile-bottom-nav__item"}
          type="button"
          onClick={() => onNavigate("mypage")}
        >
          <span aria-hidden="true">▣</span>
          <strong>내 사건</strong>
        </button>
        <button
          className={activeRoute === "reporting" || activeRoute === "fineResult" || activeRoute === "faultResult" ? "mobile-bottom-nav__item active" : "mobile-bottom-nav__item"}
          type="button"
          onClick={() => onNavigate("reporting")}
        >
          <span aria-hidden="true">▤</span>
          <strong>리포트</strong>
        </button>
      </nav>
    </>
  );
}

function ChatScreenV2({
  analysisCards,
  attachmentClassificationResult,
  attachmentOptions,
  assistantAnswer,
  assistantFollowUp,
  capabilityError,
  chatSafetyGuidance,
  authSessionId,
  chatMessages,
  currentReport,
  onAttachmentDragOver,
  onAttachmentDrop,
  onAttachmentFile,
  onConfirmAttachmentClassification,
  onConfirmOcr,
  onOcrFieldChange,
  onOpenCaseResult,
  isRegisteringAttachment,
  isSavingConversation,
  isSubmitting,
  onKeepTemporary,
  onRegisterAttachment,
  onOpenReporting,
  onConfirmReportDocument,
  onRunReportAction,
  onSaveConversation,
  onSubmit,
  pendingAuthAction,
  ocrConfirmationFields,
  ocrResult,
  question,
  registeredAttachments,
  reportActionStatus,
  saveDecision,
  savePromptVisible,
  selectedUploadFile,
  reportingPayload,
  consultationIntake,
  setAttachmentPurpose,
  setConsultationIntake,
  setQuestion,
  submittedQuestion,
  supervisorExecution,
  supervisorState,
  uploadInputResetKey,
}) {
  const attachmentInputRef = useRef(null);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const missingIntakeFields = listConsultationIntakeMissingFields(consultationIntake);
  const hasStructuredIntake = hasConsultationIntakeData(consultationIntake);
  const visibleMessages = chatMessages.length
    ? chatMessages
    : submittedQuestion
      ? [
          { role: "user", content: submittedQuestion },
          {
            role: "assistant",
            content: assistantAnswer || "상담 내용을 기준으로 확인 가능한 항목을 정리했습니다.",
            followUp: assistantFollowUp,
          },
        ]
      : [];
  const hasConversation = visibleMessages.length > 0;
  const latestAssistantIndex = latestMessageIndex(visibleMessages, "assistant");
  const isAuthenticated = Boolean(authSessionId);
  const visibleReportingPayload = isReportingPayloadReady(reportingPayload, supervisorState) ? reportingPayload : null;
  const canGenerateReport = hasReportGenerationNode(supervisorState);
  const openAttachmentPicker = (option) => {
    setAttachmentPurpose(option.purpose);
    setAttachmentMenuOpen(false);
    if (attachmentInputRef.current) {
      attachmentInputRef.current.accept = option.accept;
      attachmentInputRef.current.click();
    }
  };
  const quickQuestionGroups = [
    {
      title: "과태료·범칙금",
      questions: [
        "과태료 고지서를 받았는데 어떻게 해야 하는지 봐줘",
        "6월 24일 오후 3시 초등학교 앞에서 아이가 아파 잠깐 정차했어",
        "과태료와 범칙금은 어떤 차이가 있고 벌점은 언제 붙어?",
        "무인 단속 고지서를 받았는데 실제 운전자가 내가 아니면 어떻게 해야 해?",
        "과태료 의견제출 기한이 지났는데 이의를 제기할 방법이 있을까?",
        "어린이보호구역에서 응급상황 때문에 잠깐 정차한 경우도 단속 대상이야?",
      ],
    },
    {
      title: "과실비율",
      questions: [
        "신호 없는 교차로에서 나는 직진, 상대는 우측 진입 중 사고가 났어",
        "보험사 접수 내역을 바탕으로 과실 쟁점을 정리해줘",
        "차선을 바꾸던 중 뒤차와 부딪혔는데 과실비율은 무엇을 기준으로 정해?",
        "앞차가 갑자기 급정거해서 추돌했는데 뒤차가 항상 100% 책임이야?",
        "불법 주정차 차량 때문에 시야가 가려져 사고가 나면 그 차량에도 책임이 있어?",
        "보험사가 제시한 과실비율에 동의하지 않을 때 어떤 자료를 준비해야 해?",
      ],
    },
    {
      title: "법령 관련 질문",
      questions: [
        "황색 신호에 교차로에 진입했다가 사고가 났는데 신호위반으로 볼 수 있어?",
        "교통사고 사실확인원과 경찰 조사 결과는 과실비율 판단에 어떤 영향을 줘?",
      ],
    },
  ];
  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>AI 교통 상담</h2>
        </div>
      </div>

      <div className="chat-shell">
        <div className="conversation-list">
          <div className="section-label">현재 상담</div>
          <div className="empty-panel">
            <strong>{hasConversation ? "게스트 상담 진행 중" : "아직 대화가 없습니다."}</strong>
            <p>
              {hasConversation
                ? "저장 선택 전까지는 임시 상담으로 다룹니다."
                : "질문을 입력하면 이 영역에 상담 맥락이 쌓입니다."}
            </p>
          </div>
        </div>
        <div className="chat-main">
          <div className="messages">
            {!hasConversation && (
              <section className="chat-empty-state" aria-label="상담 시작">
                <span className="chat-session-status">비회원으로 상담 중</span>
                <h3>지금 가장 급한 상황부터 적어 주세요.</h3>
                <p>
                  사고 직후라면 장소, 시간, 상대방 주장, 고지서 내용처럼 기억나는 것만 적어도 됩니다.
                  로그인과 자료 업로드는 상담이 진행된 뒤 필요한 시점에 안내합니다.
                </p>
              </section>
            )}

            {hasConversation && (
              <>
                {visibleMessages.map((message, index) => {
                  const isUser = message.role === "user";
                  const isLatestAssistant = !isUser && index === latestAssistantIndex;
                  return (
                    <article className={isUser ? "message user" : "message"} key={`${message.role}-${index}`}>
                      <span className="message-avatar">{isUser ? "나" : "AI"}</span>
                      <div className={`${isUser ? "bubble" : "bubble wide"}${message.streaming ? " is-streaming" : ""}`}>
                        <p>{message.content}</p>
                        {!isUser && !message.streaming && message.followUp && <FollowUpNote followUp={message.followUp} />}
                        {!isUser && !message.streaming && isLatestAssistant && (
                          <>
                            {chatSafetyGuidance && <SafetyGuidancePanel guidance={chatSafetyGuidance} />}
                            <MissingFieldsPrompt supervisorState={supervisorState} />
                            {canGenerateReport && (reportingPayload || analysisCards.length > 0) && (
                              <ReportActionPanel
                                currentReport={currentReport}
                                isAuthenticated={Boolean(authSessionId)}
                                onConfirmDocument={onConfirmReportDocument}
                                onRunReportAction={onRunReportAction}
                                reportingPayload={visibleReportingPayload}
                                reportActionStatus={reportActionStatus}
                              />
                            )}
                            {canGenerateReport && visibleReportingPayload && (
                              <ReportReadyNotice
                                isAuthenticated={Boolean(authSessionId)}
                                onOpenReporting={onOpenReporting}
                                onRunReportAction={onRunReportAction}
                                reportingPayload={visibleReportingPayload}
                                reportActionStatus={reportActionStatus}
                              />
                            )}
                          </>
                        )}
                      </div>
                    </article>
                  );
                })}
                {isSubmitting && visibleMessages[visibleMessages.length - 1]?.role !== "assistant" && (
                  <article className="message" aria-live="polite">
                    <span className="message-avatar">AI</span>
                    <div className="bubble wide bubble-loading">
                      <span className="typing-dots"><span></span><span></span><span></span></span>
                      <span>AI가 답변을 정리하고 있어요</span>
                    </div>
                  </article>
                )}
              </>
            )}
          </div>

          {savePromptVisible && (
            <section className="save-choice-panel" aria-label="상담 저장 선택">
              <div>
                <span className="save-choice-label">상담 저장</span>
                <strong>이 상담을 내 상담 기록에 저장하시겠어요?</strong>
                <p>로그인하면 나중에 다시 확인할 수 있습니다. 저장하지 않은 상담은 현재 접속 중에만 유지됩니다.</p>
              </div>
              <div className="save-choice-actions">
                <button className="button" type="button" onClick={onKeepTemporary}>
                  저장하지 않기
                </button>
                <button className="button primary" type="button" onClick={onSaveConversation} disabled={isSavingConversation}>
                  {isSavingConversation ? "저장 중" : "로그인 후 저장"}
                </button>
              </div>
            </section>
          )}

          {saveDecision === "session_only" && (
            <section className="save-choice-panel is-muted" aria-label="임시 상담 유지">
              <strong>이번 상담은 임시로 유지합니다.</strong>
              <p>나중에 저장이 필요해지면 Google 로그인 후 다시 연결할 수 있습니다.</p>
            </section>
          )}

          {ocrResult?.requires_confirmation === true && (
            <OcrConfirmationCard
              fields={ocrConfirmationFields}
              isSubmitting={isSubmitting}
              onChange={onOcrFieldChange}
              onConfirm={onConfirmOcr}
            />
          )}

          {attachmentClassificationResult?.requires_confirmation === true && (
            <AttachmentClassificationConfirmationCard
              classification={attachmentClassificationResult?.classification}
              confidenceBand={attachmentClassificationResult?.confidence_band}
              isSubmitting={isSubmitting}
              onConfirm={onConfirmAttachmentClassification}
            />
          )}

          <details className="quick-examples">
            <summary className="quick-examples-header">
              <span>
                <strong>서비스 예시 작동 방식</strong>
                <small>궁금한 상황을 선택하면 질문이 입력창에 담깁니다.</small>
              </span>
            </summary>
            <div className="quick-example-groups">
              {quickQuestionGroups.map((group) => (
                <section className="quick-example-group" aria-label={group.title} key={group.title}>
                  <h4>{group.title}</h4>
                  <div className="quick-row">
                    {group.questions.map((item) => (
                      <button className="quick-chip" type="button" key={item} onClick={() => setQuestion(item)}>
                        {item}
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </details>

          <div className="chat-input">
            <div className="input-stack">
              <ConsultationIntakePanel
                hasStructuredIntake={hasStructuredIntake}
                missingFields={missingIntakeFields}
                registeredAttachments={registeredAttachments}
                value={consultationIntake}
                onChange={(field, nextValue) =>
                  setConsultationIntake((current) => ({ ...current, [field]: nextValue }))
                }
                onReset={() => setConsultationIntake(createEmptyConsultationIntake())}
              />
              <textarea
                aria-label="상담 메시지 입력"
                placeholder="사고 상황, 고지서 내용, 보험사 설명처럼 지금 기억나는 내용을 입력해 주세요."
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
              <div className="chat-attachment-bar">
              <div
                className="attachment-dropzone"
                onDragOver={onAttachmentDragOver}
                onDrop={onAttachmentDrop}
              >
                <strong>파일을 끌어 놓거나 + 메뉴에서 선택하세요.</strong>
                <span>영상은 Vision 분석, 이미지와 PDF는 OCR 분류로 전달됩니다.</span>
              <div className="composer-toolbar">
                <div className="attachment-menu-wrap">
                  <button
                    className="attachment-plus"
                    type="button"
                    aria-label="자료 첨부"
                    aria-expanded={attachmentMenuOpen}
                    onClick={() => setAttachmentMenuOpen((open) => !open)}
                  >
                    +
                  </button>
                  {attachmentMenuOpen && (
                    <div className="attachment-menu" role="menu">
                      {attachmentOptions.map((option) => (
                        <button type="button" role="menuitem" key={option.label} onClick={() => openAttachmentPicker(option)}>
                          <strong>{option.label}</strong>
                          <span>{option.description}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <input
                    ref={attachmentInputRef}
                    key={uploadInputResetKey}
                    className="attachment-file-input"
                    type="file"
                    accept={ATTACHMENT_ACCEPT}
                    onChange={(event) => onAttachmentFile(event.target.files?.[0] || null)}
                  />
                </div>

                {selectedUploadFile && (
                  <div className="selected-attachment">
                    <span>{selectedUploadFile.name}</span>
                    <button
                      type="button"
                      onClick={onRegisterAttachment}
                      disabled={isRegisteringAttachment || Boolean(capabilityError)}
                    >
                      {isRegisteringAttachment ? "첨부 중" : isAuthenticated ? "첨부" : "로그인 후 첨부"}
                    </button>
                    <button type="button" aria-label="선택한 파일 제거" onClick={() => onAttachmentFile(null)}>×</button>
                  </div>
                )}

                {!selectedUploadFile && registeredAttachments.length > 0 && (
                  <span className="attachment-count">첨부 {registeredAttachments.length}개</span>
                )}

                <button className="button primary composer-send" type="button" onClick={onSubmit} disabled={isSubmitting}>
                  {isSubmitting ? "정리 중" : "전송"}
                </button>
              </div>
                <span role="status">
                  {selectedUploadFile
                    ? `${selectedUploadFile.name} 선택됨 · ${VIDEO_MIME_TYPES.has(selectedUploadFile.type) ? "Vision" : "OCR"} 대기`
                    : "첨부할 파일을 하나 선택하세요."}
                </span>
              </div>

              {capabilityError && <p className="attachment-help" role="alert">{capabilityError}</p>}
              {!isAuthenticated && selectedUploadFile && !pendingAuthAction && (
                <p className="attachment-help" role="status">자료 첨부는 Google 로그인 후 현재 상담에 연결됩니다.</p>
              )}
              {pendingAuthAction && <p className="attachment-help" role="status">로그인 후 같은 상담에서 첨부를 이어갑니다.</p>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function OcrConfirmationCard({ fields, isSubmitting, onChange, onConfirm }) {
  return (
    <section className="ocr-confirmation-card" aria-label="OCR 추출값 확인">
      <div>
        <span className="eyebrow">OCR 확인</span>
        <strong>추출된 고지서 정보를 확인하거나 수정해 주세요.</strong>
        <p>확인한 값만 후속 법령 검색과 이의절차 검토에 사용됩니다.</p>
      </div>
      <div className="ocr-confirmation-fields">
        {OCR_CONFIRMATION_FIELDS.map((field) => (
          <label key={field}>
            <span>{OCR_CONFIRMATION_FIELD_LABELS[field]}</span>
            <input
              type="text"
              value={fields[field] || ""}
              onChange={(event) => onChange(field, event.target.value)}
            />
          </label>
        ))}
      </div>
      <button className="button primary" type="button" onClick={onConfirm} disabled={isSubmitting}>
        OCR 추출값 확인 후 후속 절차 진행
      </button>
    </section>
  );
}

function AttachmentClassificationConfirmationCard({
  classification,
  confidenceBand,
  isSubmitting,
  onConfirm,
}) {
  const classificationLabel =
    classification === "fine_notice" ? "고지서·행정 문서" : "사고 현장·증거 사진";
  const confidenceLabel = confidenceBand === "high" ? "높음" : "보통";
  return (
    <section className="ocr-confirmation-card" aria-label="자료 분류 확인">
      <div>
        <span className="eyebrow">자료 분류 확인</span>
        <strong>{classificationLabel}(으)로 분류했습니다.</strong>
        <p>
          분류 신뢰도 {confidenceLabel} · 확인 후에만 자료 종류에 맞는 OCR 또는 근거 검색을
          진행합니다.
        </p>
      </div>
      <button className="button primary" type="button" onClick={onConfirm} disabled={isSubmitting}>
        자료 분류 확인 후 다음 분석 진행
      </button>
    </section>
  );
}

function MissingFieldsPrompt({ supervisorState }) {
  const questions = Array.isArray(supervisorState?.next_questions) ? supervisorState.next_questions : [];
  if (!questions.length) {
    return null;
  }
  return (
    <div className="missing-fields-prompt" role="status">
      <strong>지금 분석에 필요한 정보예요</strong>
      <ul>
        {questions.map((item, index) => (
          <li key={item.field || index}>{item.question}</li>
        ))}
      </ul>
      <p>위 항목을 알고 계신 만큼만 이어서 입력해 주세요.</p>
    </div>
  );
}

function ConsultationIntakePanel({
  hasStructuredIntake,
  missingFields,
  onChange,
  onReset,
  registeredAttachments,
  value,
}) {
  const selectedType = value?.consultationType || "";
  const isFineNotice = selectedType === "fine_notice";
  return (
    <section className="consultation-intake-card" aria-label="구조화 입력 단계">
      <div className="consultation-intake-card__head">
        <div>
          <span className="eyebrow">입력 단계</span>
          <strong>사고 내용을 사실과 주장으로 나눠 적을 수 있습니다.</strong>
          <p>여기 적은 내용은 전송 시 현재 메시지와 함께 상담 입력으로 정리됩니다.</p>
        </div>
        {hasStructuredIntake && (
          <button className="button" type="button" onClick={onReset}>
            입력 초기화
          </button>
        )}
      </div>

      <div className="consultation-intake-grid">
        <label className="consultation-intake-field consultation-intake-field--wide">
          <span>사건 유형</span>
          <select
            value={selectedType}
            onChange={(event) => onChange("consultationType", event.target.value)}
          >
            {CONSULTATION_TYPE_OPTIONS.map((option) => (
              <option key={option.value || "empty"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {CONSULTATION_FACT_FIELDS.map((field) => (
          <label className="consultation-intake-field" key={field.key}>
            <span>{field.label}</span>
            <input
              type="text"
              value={value?.[field.key] || ""}
              onChange={(event) => onChange(field.key, event.target.value)}
              placeholder={field.question}
            />
          </label>
        ))}

        <label className="consultation-intake-field consultation-intake-field--wide">
          <span>확인된 사실</span>
          <textarea
            rows={3}
            value={value?.confirmedFacts || ""}
            onChange={(event) => onChange("confirmedFacts", event.target.value)}
            placeholder="사고 시각, 장소, 첨부자료로 확인된 내용처럼 검증 가능한 사실을 적어 주세요."
          />
        </label>

        <label className="consultation-intake-field consultation-intake-field--wide">
          <span>사용자 주장·상대방 주장</span>
          <textarea
            rows={3}
            value={value?.userClaims || ""}
            onChange={(event) => onChange("userClaims", event.target.value)}
            placeholder="상대가 주장하는 내용이나 아직 확인되지 않은 진술을 따로 적어 주세요."
          />
        </label>

        <label className="consultation-intake-field consultation-intake-field--wide">
          <span>추가 확인이 필요한 점</span>
          <textarea
            rows={2}
            value={value?.missingDetails || ""}
            onChange={(event) => onChange("missingDetails", event.target.value)}
            placeholder="목격자 연락처, 블랙박스 확보 여부처럼 아직 모르는 항목을 적어 주세요."
          />
        </label>
      </div>

      <div className="consultation-intake-footer">
        {registeredAttachments.length > 0 && (
          <span className="consultation-intake-badge">첨부 자료 {registeredAttachments.length}개 연결됨</span>
        )}
        {isFineNotice ? (
          <p className="consultation-intake-help">
            과태료·범칙금 상담은 고지서 OCR 확인 카드와 자유 입력을 함께 사용하면 됩니다.
          </p>
        ) : missingFields.length > 0 ? (
          <div className="consultation-intake-missing" role="status">
            <strong>아직 비어 있는 핵심 사실</strong>
            <div className="consultation-intake-chip-list">
              {missingFields.map((field) => (
                <span className="consultation-intake-chip" key={field.key}>
                  {field.label}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <p className="consultation-intake-help">
            핵심 사실 4개가 채워졌습니다. 자유 입력에는 추가 상황이나 질문만 적어도 됩니다.
          </p>
        )}
      </div>
    </section>
  );
}

function FollowUpNote({ followUp }) {
  const message = String(followUp?.message || "").trim();
  const items = Array.isArray(followUp?.items) ? followUp.items : [];
  if (!message) {
    return null;
  }
  const requiredItems = items.filter((item) => item?.required);
  const optionalItems = items.filter((item) => !item?.required);
  return (
    <div className="follow-up-note" role="status">
      <p>{message}</p>
      {requiredItems.length > 0 && (
        <div className="follow-up-group follow-up-group-required">
          <span className="follow-up-group-label">꼭 필요해요</span>
          <ul>
            {requiredItems.map((item, index) => (
              <li key={item.label || index}>
                {item.label}
                {item.reason && <small>{item.reason}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {optionalItems.length > 0 && (
        <div className="follow-up-group follow-up-group-optional">
          <span className="follow-up-group-label">알려주시면 더 좋아요</span>
          <ul>
            {optionalItems.map((item, index) => (
              <li key={item.label || index}>
                {item.label}
                {item.reason && <small>{item.reason}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function FaultRatioInsightPanel({ node, compact = false }) {
  const structuredResult = node?.structured_result || {};
  const retrieval = structuredResult.retrieval || {};
  const sourceSummary = retrieval.source_summary || structuredResult.source_summary || {};
  const sourceCounts = sourceSummary.source_counts || {};
  const similarCases = Array.isArray(structuredResult.similar_cases)
    ? structuredResult.similar_cases
    : Array.isArray(structuredResult.top_cases)
      ? structuredResult.top_cases
      : [];
  const recommendedEvidence = Array.isArray(structuredResult.recommended_evidence)
    ? structuredResult.recommended_evidence
    : [];
  const limitations = Array.isArray(node?.limitations)
    ? node.limitations
    : Array.isArray(structuredResult.limitations)
      ? structuredResult.limitations
      : [];
  const ratioRangeLabel = structuredResult.ratio_range_label || "pending review";
  const sourceCount = Object.values(sourceCounts).reduce((total, count) => total + Number(count || 0), 0);

  if (!node || node.node_code !== "text_ml_case_search") {
    return null;
  }

  return (
    <article className={compact ? "agent-insight-panel compact" : "agent-insight-panel"}>
      <div className="agent-insight-head">
        <span className="tag">과실 쟁점</span>
        <strong>유사 사례와 제출 자료 검토</strong>
      </div>
      <div className="agent-insight-grid">
        <p>
          <span>검토 범위</span>
          <strong>{compactValue(ratioRangeLabel)}</strong>
        </p>
        <p>
          <span>참고 자료</span>
          <strong>{sourceCount || similarCases.length}건</strong>
        </p>
        <p>
          <span>추가하면 좋은 자료</span>
          <strong>{recommendedEvidence.length}건</strong>
        </p>
      </div>
      {similarCases.length > 0 && (
        <div className="agent-insight-section">
          <strong>참고한 유사 사례</strong>
          {similarCases.slice(0, compact ? 2 : 3).map((item, index) => (
            <p key={item.source_ref || item.source_reference || item.case_id || `similar-case-${index}`}>
              {compactValue(item)}
            </p>
          ))}
        </div>
      )}
      {recommendedEvidence.length > 0 && (
        <div className="agent-insight-section">
          <strong>추가하면 좋은 자료</strong>
          <p>{compactValue(recommendedEvidence)}</p>
        </div>
      )}
      {limitations.length > 0 && (
        <div className="agent-insight-section">
          <strong>검토 시 확인할 한계</strong>
          <ul>
            {limitations.slice(0, compact ? 2 : 3).map((item, index) => (
              <li key={`fault-ratio-limitation-${index}`}>{compactValue(item)}</li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function LawGroundInsightPanel({ node, compact = false }) {
  const structuredResult = node?.structured_result || {};
  const qualitySummary = structuredResult.public_quality_summary || null;
  const shouldShowQualityDetails =
    qualitySummary?.partial_result ||
    qualitySummary?.review_required ||
    ["partial", "blocked", "failed", "empty", "stale", "fallback", "limited"].includes(String(qualitySummary?.status || "").toLowerCase()) ||
    qualitySummary?.retrieval?.used_fallback ||
    (qualitySummary?.limitation_count || 0) > 0 ||
    qualitySummary?.freshness?.limitation;
  const matchedLaws = Array.isArray(structuredResult.matched_laws)
    ? structuredResult.matched_laws
    : Array.isArray(structuredResult.law_provisions)
      ? structuredResult.law_provisions
      : [];
  const limitations = Array.isArray(qualitySummary?.limitations) ? qualitySummary.limitations : [];

  if (!node || node?.node_code !== "law_ground_search") {
    return null;
  }

  return (
    <article className={compact ? "agent-insight-panel compact" : "agent-insight-panel"}>
      <div className="agent-insight-head">
        <span className="tag">법령 근거</span>
        <strong>검색 출처와 적용 후보</strong>
      </div>
      <div className="agent-insight-grid">
        <p>
          <span>검색 상태</span>
          <strong>{compactValue(qualitySummary?.status || "unavailable")}</strong>
        </p>
        <p>
          <span>검색 저장소</span>
          <strong>{compactValue(qualitySummary?.retrieval?.backend_label || "unavailable")}</strong>
        </p>
        <p>
          <span>확인된 근거</span>
          <strong>{matchedLaws.length}건</strong>
        </p>
      </div>
      {(qualitySummary?.freshness?.retrieved_at || qualitySummary?.freshness?.effective_at) && (
        <p className="agent-insight-timestamp">
          {qualitySummary?.freshness?.retrieved_at
            ? `조회 시각: ${formatDateTime(qualitySummary.freshness.retrieved_at)}`
            : ""}
          {qualitySummary?.freshness?.effective_at
            ? ` · 적용 기준일: ${formatDate(qualitySummary.freshness.effective_at)}`
            : ""}
        </p>
      )}
      {shouldShowQualityDetails && qualitySummary?.freshness?.limitation && (
        <p className="agent-insight-timestamp">
          최신성 안내: {compactValue(qualitySummary.freshness.limitation)}
        </p>
      )}
      {matchedLaws.length > 0 && (
        <div className="agent-insight-section">
          <strong>관련 법령 후보</strong>
          {matchedLaws.slice(0, compact ? 2 : 4).map((item, index) => (
            <p key={item.source_reference || `law-ground-${index}`}>
              <strong>
                {compactValue(
                  [
                    item.law_name || item.source_name || item.title || item.article_title,
                    item.article || item.article_no,
                  ]
                    .filter(Boolean)
                    .join(" ")
                )}
              </strong>
              {(item.summary || item.provision_text) && (
                <span>{compactValue(item.summary || item.provision_text)}</span>
              )}
              <small>출처: {compactValue(item.source_reference)}</small>
              {(item.effective_date || item.enforce_date) && (
                <small>시행 기준일: {formatDate(item.effective_date || item.enforce_date)}</small>
              )}
            </p>
          ))}
        </div>
      )}
      {shouldShowQualityDetails && limitations.length > 0 && (
        <div className="agent-insight-section">
          <strong>적용 전 확인사항</strong>
          <ul>
            {limitations.slice(0, compact ? 2 : 3).map((item, index) => (
              <li key={`law-ground-limitation-${index}`}>{compactValue(item)}</li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function ReportingPreviewPanel({ reportingPayload }) {
  const sections = Array.isArray(reportingPayload?.sections) ? reportingPayload.sections : [];
  const documentSections = sections.filter(isSubmissionDocumentSection);
  const supportingSections = sections.filter((section) => !isSubmissionDocumentSection(section));

  return (
    <section className="reporting-preview" aria-label="리포팅 미리보기">
      <div className="flow-panel-head">
        <div>
          <span className="report-document-label">리포트 미리보기</span>
          <strong>{reportingPayload.title || "상담 분석 리포트"}</strong>
          <p>{reportingPayload.summary}</p>
        </div>
        <span className={reportingPayload.stage === "agent_execution_ready" ? "tag green" : "tag amber"}>
          {reportStatusLabel(reportingPayload.stage)}
        </span>
      </div>
      {documentSections.length > 0 && (
        <div className="report-document-highlights" aria-label="제출 문서 미리보기">
          {documentSections.map((section) => (
            <article key={`document-${section.title}`}>
              <span className="tag green">제출 문서</span>
              <strong>{section.title}</strong>
              {(section.items || []).slice(0, 6).map((item, index) => (
                <p key={`${section.title}-document-${index}`}>{compactValue(item)}</p>
              ))}
            </article>
          ))}
        </div>
      )}
      <div className="report-section-list">
        {supportingSections.map((section) => (
          <article key={section.title}>
            <strong>{section.title}</strong>
            {(section.items || []).slice(0, 4).map((item, index) => (
              <p key={`${section.title}-${index}`}>{compactValue(item)}</p>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}

function isSubmissionDocumentSection(section) {
  const title = String(section?.title || "");
  return /이의신청서|의견제출서|제출 가이드라인|제출 가이드|초안/.test(title);
}

function shouldShowDocumentConfirmation({
  documentConfirmation,
  isAuthenticated,
}) {
  if (!isAuthenticated) return false;
  return documentConfirmation?.required === true;
}

function ReportReadyNotice({ isAuthenticated, onOpenReporting, onRunReportAction, reportingPayload, reportActionStatus }) {
  const appealDownloadBlocked = reportingPayload?.appeal_gate?.blocked === true;
  const confirmationReady = reportingPayload?.document_confirmation?.confirmed === true;
  const hasOfficialDocument =
    reportingPayload?.document_confirmation?.required === true ||
    ["fine_notice", "traffic_accident"].includes(reportingPayload?.document_variant) ||
    ["fine_notice_objection", "fault_ratio_analysis"].includes(reportingPayload?.report_type);
  return (
    <section className="report-ready-strip" aria-label="리포트 준비 완료">
      <div>
        <span className="tag green">리포트 준비 완료</span>
        {reportActionStatus && <p>{reportActionStatus}</p>}
      </div>
      <div className="report-ready-actions">
        <button className="button" type="button" onClick={onOpenReporting}>
          작업대
        </button>
        {hasOfficialDocument && (
          <button
            className="button primary"
            type="button"
            onClick={() => onRunReportAction("download_objection")}
            disabled={appealDownloadBlocked || !confirmationReady}
          >
            {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 DOCX"}
          </button>
        )}
      </div>
    </section>
  );
}

function DocumentConfirmationPanel({ confirmation, isAuthenticated, onConfirm }) {
  const [checks, setChecks] = useState({
    facts_confirmed: false,
    agency_confirmed: false,
    deadline_confirmed: false,
    attachments_confirmed: false,
  });
  useEffect(() => {
    setChecks({
      facts_confirmed: false,
      agency_confirmed: false,
      deadline_confirmed: false,
      attachments_confirmed: false,
    });
  }, [confirmation?.reportId, confirmation?.confirmed, confirmation?.stale]);
  const allChecked = Object.values(checks).every(Boolean);
  const appealBlocked = confirmation?.appealBlocked === true;
  if (confirmation?.required !== true) {
    return null;
  }
  if (confirmation.confirmed === true) {
    return <p className="document-confirmation-status">최종 확인이 완료되었습니다.</p>;
  }
  return (
    <fieldset className="document-confirmation-panel" disabled={appealBlocked}>
      <legend>이의신청서 최종 확인</legend>
      <p>{confirmation.stale ? "문서 내용이 변경되어 다시 확인해야 합니다." : "다운로드 전 아래 항목을 확인해 주세요."}</p>
      {[
        ["facts_confirmed", "사실관계를 확인했습니다."],
        ["agency_confirmed", "관할 기관을 확인했습니다."],
        ["deadline_confirmed", "제출 기한을 확인했습니다."],
        ["attachments_confirmed", "첨부 자료를 확인했습니다."],
      ].map(([key, label]) => (
        <label key={key} className="document-confirmation-check">
          <input
            type="checkbox"
            checked={checks[key]}
            onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))}
          />
          {label}
        </label>
      ))}
      <button
        className="button"
        type="button"
        onClick={() => onConfirm?.(checks)}
        disabled={!isAuthenticated || appealBlocked || !allChecked}
      >
        {isAuthenticated ? "최종 확인 저장" : "로그인 후 최종 확인"}
      </button>
    </fieldset>
  );
}

function ReportActionPanel({ currentReport, isAuthenticated, onConfirmDocument, onRunReportAction, reportingPayload, reportActionStatus }) {
  const activeReportingPayload = currentReport?.content?.reporting_payload || reportingPayload;
  const appealDownloadBlocked = activeReportingPayload?.appeal_gate?.blocked === true;
  const documentConfirmation = activeReportingPayload?.document_confirmation || null;
  const hasOfficialDocument =
    documentConfirmation?.required === true ||
    ["fine_notice", "traffic_accident"].includes(activeReportingPayload?.document_variant) ||
    ["fine_notice_objection", "fault_ratio_analysis"].includes(activeReportingPayload?.report_type);
  const confirmation = {
    required: shouldShowDocumentConfirmation({
      documentConfirmation,
      isAuthenticated,
    }),
    confirmed: documentConfirmation?.confirmed === true,
    stale: documentConfirmation?.stale === true,
    appealBlocked: appealDownloadBlocked,
    reportId: currentReport?.report_id || activeReportingPayload?.report_id || null,
  };
  const reportQuality =
    currentReport?.persistence?.report_quality ||
    currentReport?.report_quality ||
    currentReport?.metadata?.report_quality ||
    null;
  const reportQualitySummary = reportQuality?.public_quality_summary || null;
  const hasReportQuality = Boolean(reportQualitySummary);
  const shouldShowReportQualityDetails =
    reportQualitySummary?.partial_result ||
    reportQualitySummary?.review_required ||
    ["partial", "blocked", "failed", "empty", "stale", "fallback", "limited"].includes(String(reportQualitySummary?.status || "").toLowerCase()) ||
    reportQualitySummary?.retrieval?.used_fallback ||
    (reportQualitySummary?.limitation_count || 0) > 0 ||
    reportQualitySummary?.freshness?.limitation;
  const reportLimitations = Array.isArray(reportQualitySummary?.limitations) ? reportQualitySummary.limitations.slice(0, 3) : [];
  const reportQualityTitle = reportQualitySummary?.partial_result ? "일부 자료가 부족한 리포트" : "검토 준비가 완료된 리포트";
  const helperText = isAuthenticated
    ? reportActionStatus || activeReportingPayload?.appeal_gate?.reason || "상담 결과를 저장하거나 제출용 이의신청서 DOCX를 준비할 수 있습니다."
    : reportActionStatus || "리포트 저장과 DOCX 다운로드는 Google 로그인 후 사용할 수 있습니다.";

  return (
    <section className="report-action-panel" aria-label="리포트 저장과 다운로드">
      <div>
        <span className="eyebrow">리포트 상태</span>
        <strong>{currentReport?.report_id || "리포트 준비 중"}</strong>
        <p>{helperText}</p>
        {hasReportQuality && (
          <div className="report-quality-panel" data-partial-report={String(Boolean(reportQualitySummary.partial_result))}>
            <span className={reportQualitySummary.partial_result ? "tag amber" : "tag green"}>
              {reportQualitySummary.partial_result ? "일부 자료 부족" : "검토 준비 완료"}
            </span>
            <strong className="report-quality-title">{reportQualityTitle}</strong>
            <span className="tag">분석 상태 · {caseStatusLabel(reportQualitySummary.status)}</span>
            <span className="tag">확인할 한계 · {reportQualitySummary.limitation_count ?? 0}건</span>
            {reportQualitySummary?.freshness?.effective_at && (
              <span className="tag">기준일 {formatDate(reportQualitySummary.freshness.effective_at)}</span>
            )}
            {reportQualitySummary?.freshness?.retrieved_at && (
              <span className="tag">조회 시각 {formatDateTime(reportQualitySummary.freshness.retrieved_at)}</span>
            )}
            {shouldShowReportQualityDetails && reportQualitySummary.partial_result && (
              <p className="report-quality-warning">최종 제출 전에 부족한 자료와 사실관계를 확인해 주세요.</p>
            )}
            {shouldShowReportQualityDetails && reportLimitations.length > 0 && (
              <ul className="report-quality-limitations" aria-label="report quality limitations">
                {reportLimitations.map((item, index) => (
                  <li key={`report-quality-limitation-${index}`}>{compactValue(item)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <DocumentConfirmationPanel
        confirmation={confirmation}
        isAuthenticated={isAuthenticated}
        onConfirm={onConfirmDocument}
      />
      <div className="report-action-buttons">
        <button className="button" type="button" onClick={() => onRunReportAction("save")}>
          {isAuthenticated ? "저장" : "로그인 후 저장"}
        </button>
        {hasOfficialDocument && (
          <button
          className="button primary"
          type="button"
          onClick={() => onRunReportAction("download_objection")}
          disabled={appealDownloadBlocked || !confirmation.confirmed}
        >
          {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 이의신청서 DOCX"}
        </button>
        )}
      </div>
    </section>
  );
}

function MyPageScreen({ cases, onOpenCase, onOpenChat, onRefresh, summary }) {
  const pageSize = 5;
  const activeCases = summary?.active_cases ?? cases.length;
  const savedReports = summary?.saved_reports ?? 0;
  const recentCount = summary?.recent_analysis_count ?? cases.length;
  const deadlineSummary = upcomingDeadlineSummary(cases);
  const hasCases = cases.length > 0;
  const [showActionableOnly, setShowActionableOnly] = useState(false);
  const [selectedCaseKey, setSelectedCaseKey] = useState(null);
  const [historyPage, setHistoryPage] = useState(1);
  const visibleCases = showActionableOnly
    ? cases.filter((item) => {
        const status = String(item.case_status || item.status || "").toLowerCase();
        return /partial|pending|queued|running|draft|review|기한|추가|확인|대기|진행|작성/.test(status);
      })
    : cases;
  const pageCount = Math.max(1, Math.ceil(visibleCases.length / pageSize));
  const currentPage = Math.min(historyPage, pageCount);
  const pagedCases = visibleCases.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const caseKey = (item) => item.case_id || item.job_id || item.title;
  const selectedCase =
    pagedCases.find((item) => caseKey(item) === selectedCaseKey) || pagedCases[0] || null;

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>내 사건</h2>
          <p>진행 중인 상담, 저장한 리포트, 기한이 임박한 사건을 관리합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onOpenChat}>새 상담</button>
          <button className="button primary" type="button" onClick={onRefresh}>
            현황 새로고침
          </button>
        </div>
      </div>

      <div className="dashboard">
        <div className="summary-grid">
          <MetricCard label="등록 사건" value={`${activeCases}건`} detail="최근 30일 기준" />
          <MetricCard label="과태료 이의제기 기한 임박" value={`${deadlineSummary.count}건`} detail={deadlineSummary.nearestLabel} />
          <MetricCard label="저장 리포트" value={`${savedReports}건`} detail="DOCX 다운로드 가능" />
          <MetricCard label="최근 분석" value={`${recentCount}건`} detail="상담/리포트 포함" />
        </div>

        <div className="mypage-split">
          <article className="table-panel">
            <div className="panel-head">
              <strong>최근 분석 이력</strong>
              <button
                className={showActionableOnly ? "button active" : "button"}
                type="button"
                disabled={!hasCases}
                aria-pressed={showActionableOnly}
                onClick={() => {
                  setShowActionableOnly((value) => !value);
                  setHistoryPage(1);
                }}
              >
                {showActionableOnly ? "✓ 조치가 필요한 항목들 표시 중" : "조치가 필요한 항목들 보기"}
              </button>
            </div>
            <div className="table-scroll">
              <table className="history-table">
                <thead>
                  <tr>
                    <th>유형</th>
                    <th>사건명</th>
                    <th>상태</th>
                    <th>최근 작업</th>
                    <th>이동</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleCases.length === 0 ? (
                    <tr>
                      <td colSpan="5">
                        <div className="table-empty">
                          <strong>아직 저장된 사건이 없습니다.</strong>
                          <p>상담을 시작하거나 리포트를 저장하면 이곳에 표시됩니다.</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    pagedCases.map((item) => (
                      <tr
                        key={caseKey(item)}
                        className={selectedCase && caseKey(item) === caseKey(selectedCase) ? "is-selected" : undefined}
                        onClick={() => setSelectedCaseKey(caseKey(item))}
                      >
                        <td><span className="tag">{item.type || "상담"}</span></td>
                        <td>{item.title || item.case_id}</td>
                        <td>
                          <span className={`report-list-status ${caseStatusTone(item.case_status || item.status)}`}>
                            {item.case_status || item.status || "확인 필요"}
                          </span>
                        </td>
                        <td>{item.updated_at || item.created_at || "-"}</td>
                        <td>
                          <button
                            className="button"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              onOpenCase(item);
                            }}
                          >
                            열기
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {visibleCases.length > pageSize && (
              <nav className="table-pagination" aria-label="최근 분석 이력 페이지">
                <button
                  className="button"
                  type="button"
                  disabled={currentPage === 1}
                  onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
                >
                  이전
                </button>
                <span>{currentPage} / {pageCount}</span>
                <button
                  className="button"
                  type="button"
                  disabled={currentPage === pageCount}
                  onClick={() => setHistoryPage((page) => Math.min(pageCount, page + 1))}
                >
                  다음
                </button>
              </nav>
            )}
          </article>

          <aside className="case-detail-panel" aria-label="사건 상세">
            {selectedCase ? (
              <>
                <div className="panel-head">
                  <strong>사건 상세</strong>
                  <span className="tag">{selectedCase.type || "상담"}</span>
                </div>
                <div className="case-detail-body">
                  <h3>{selectedCase.title || selectedCase.case_id}</h3>
                  <dl>
                    <div>
                      <dt>상태</dt>
                      <dd>
                        <span className={`report-list-status ${caseStatusTone(selectedCase.case_status || selectedCase.status)}`}>
                          {selectedCase.case_status || selectedCase.status || "확인 필요"}
                        </span>
                      </dd>
                    </div>
                    <div><dt>최근 작업</dt><dd>{selectedCase.updated_at || selectedCase.created_at || "-"}</dd></div>
                    <div><dt>사건 ID</dt><dd>{selectedCase.case_id || selectedCase.job_id || "-"}</dd></div>
                  </dl>
                  <button className="button primary full" type="button" onClick={() => onOpenCase(selectedCase)}>
                    이어서 보기
                  </button>
                </div>
              </>
            ) : (
              <div className="empty-panel compact">
                <p>사건을 선택하면 상세 정보가 여기에 표시됩니다.</p>
              </div>
            )}
          </aside>
        </div>
      </div>
    </section>
  );
}

function HistoryScreen({ events, onRefresh }) {
  const [activeFilter, setActiveFilter] = useState("전체");
  const filterOptions = ["전체", "과태료", "과실비율", "리포트"];
  const filteredEvents =
    activeFilter === "전체"
      ? events
      : events.filter((event) => historyEventMatchesFilter(event, activeFilter));

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>과거 이력</h2>
          <p>상담과 리포트 진행 내역을 유형과 시점 기준으로 다시 확인합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button primary" type="button" onClick={onRefresh}>
            이력 새로고침
          </button>
        </div>
      </div>

      <div className="dashboard">
        <div className="filter-row">
          {filterOptions.map((option) => (
            <button
              className={activeFilter === option ? "quick-chip active" : "quick-chip"}
              key={option}
              type="button"
              onClick={() => setActiveFilter(option)}
            >
              {option}
            </button>
          ))}
        </div>
        <ol className="history-list">
          {filteredEvents.length === 0 ? (
            <li className="history-row empty">
              <div>
                <strong>아직 과거 이력이 없습니다.</strong>
                <p>상담이나 리포트 저장 후 이력이 쌓입니다.</p>
              </div>
            </li>
          ) : (
            filteredEvents.map((event) => (
              <li className="history-row" key={event.event_id || `${event.event_type}-${event.created_at}`}>
                <div>
                  <span className="tag green">{event.event_type}</span>
                  <strong>{event.summary}</strong>
                </div>
                <span>{formatDate(event.created_at)}</span>
              </li>
            ))
          )}
        </ol>
      </div>
    </section>
  );
}

function historyEventMatchesFilter(event, activeFilter) {
  const haystack = [
    event?.event_type,
    event?.summary,
    event?.status,
    event?.subject_type,
    event?.resource_type,
    event?.metadata?.routing_intent,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (activeFilter === "과태료") {
    return /fine|notice|penalty|ticket|과태료|고지/.test(haystack);
  }
  if (activeFilter === "과실비율") {
    return /fault|ratio|case_search|과실|비율|사고/.test(haystack);
  }
  if (activeFilter === "리포트") {
    return /report|download|리포트|보고서/.test(haystack);
  }
  return true;
}

function DeadlineGuidancePanel({ guidance }) {
  const nextActions = stringList(guidance?.next_actions);
  const limitations = stringList(guidance?.limitations);

  return (
    <aside
      className={`deadline-guidance-panel deadline-guidance-panel--${guidance.status}`}
      role={guidance.status === "normal" ? "status" : "alert"}
    >
      <span className="deadline-guidance-panel__title">{guidance.card_title}</span>
      <strong>{guidance.reason}</strong>
      {limitations[0] && <p>{limitations[0]}</p>}
      {nextActions.length > 0 && (
        <ul>
          {nextActions.map((action, index) => <li key={`deadline-action-${index}`}>{action}</li>)}
        </ul>
      )}
    </aside>
  );
}

function SafetyGuidancePanel({ guidance }) {
  const limitations = stringList(guidance?.limitations);
  const nextActions = stringList(guidance?.nextActions);

  return (
    <aside className="safety-guidance-panel" role="note">
      <span className="safety-guidance-panel__title">{guidance.title}</span>
      {guidance.reason && <strong>{guidance.reason}</strong>}
      {limitations.length > 0 && (
        <ul aria-label="확인할 한계">
          {limitations.map((item, index) => <li key={`safety-limitation-${index}`}>{item}</li>)}
        </ul>
      )}
      {nextActions.length > 0 && (
        <ul aria-label="다음 행동">
          {nextActions.map((item, index) => <li key={`safety-action-${index}`}>{item}</li>)}
        </ul>
      )}
    </aside>
  );
}

function ServiceInformationNotice() {
  return <aside className="service-information-notice" role="note">{SERVICE_INFORMATION_NOTICE}</aside>;
}

function EvidenceBoundaryPanel({ facts = [], userClaims = [] }) {
  if (!facts.length && !userClaims.length) {
    return null;
  }
  return (
    <section className="evidence-boundary-panel" aria-label="사실과 사용자 진술 구분">
      <div>
        <span className="eyebrow">현재 확인된 사실</span>
        {facts.length > 0 ? (
          facts.slice(0, 5).map((fact, index) => (
            <p key={`${fact.field || fact.label || "fact"}-${index}`}>
              <strong>{fact.field || fact.label || "확인 항목"}</strong>
              <span>{compactValue(fact.value || fact.description || fact)}</span>
            </p>
          ))
        ) : (
          <p>첨부 자료나 추가 확인을 통해 사실관계를 보완해야 합니다.</p>
        )}
      </div>
      <div>
        <span className="eyebrow">사용자 진술 · 추가 확인 필요</span>
        {userClaims.length > 0 ? (
          userClaims.slice(0, 5).map((claim, index) => (
            <p key={`${claim.field || "claim"}-${index}`}>
              <strong>{claim.field || "사용자 진술"}</strong>
              <span>{compactValue(claim.value)}</span>
              {claim.source_type && <small>출처 유형: {claim.source_type}</small>}
            </p>
          ))
        ) : (
          <p>별도로 분리해 표시할 사용자 진술이 없습니다.</p>
        )}
      </div>
    </section>
  );
}


function CaseResultScreen({
  analysisCards = [],
  caseType = "fine",
  currentReport = null,
  deadlineGuidance = null,
  resultSafetyGuidance = null,
  isAuthenticated = false,
  onOpenChat,
  onOpenReport,
  onPrepareDraftRegeneration,
  onPrepareMissingEvidence,
  onRunReportAction,
  registeredAttachments = [],
  reportingPayload = null,
  reportActionStatus = "",
  supervisorExecution = null,
  supervisorState = null,
  userClaims = [],
}) {
  const isFault = caseType === "fault";
  const appealDownloadBlocked = reportingPayload?.appeal_gate?.blocked === true;
  const sections = Array.isArray(reportingPayload?.sections) ? reportingPayload.sections : [];
  const nodeResults = Array.isArray(supervisorExecution?.node_results) ? supervisorExecution.node_results : [];
  const faultRatioNode = nodeResults.find((node) => node?.node_code === "text_ml_case_search");
  const lawGroundNode = nodeResults.find((node) => node?.node_code === "law_ground_search");
  const reportStatus = reportingPayload?.stage || currentReport?.status || "draft";
  const reportStatusText = reportStatusLabel(reportStatus);
  const facts = Array.isArray(supervisorState?.collected_facts) ? supervisorState.collected_facts : [];
  const metrics = isFault
    ? [
        { label: "사고 유형", value: findReportText(sections, /사고 유형|사고 개요|교차로|차선/, "사고 유형 확인 필요"), detail: "사고 설명과 자료 기준" },
        { label: "주요 쟁점", value: `${Math.max(analysisCards.length, 1)}건`, detail: "진입 순서·충돌 위치·시야" },
        { label: "제출 자료", value: `${registeredAttachments.length}건`, detail: "사진·영상·진술 자료" },
        { label: "검토 상태", value: reportStatusText, detail: "리포트 연결 가능" },
      ]
    : [
        { label: "처분 유형", value: findReportText(sections, /처분 유형|과태료|범칙금/, "과태료·범칙금"), detail: "고지서 분석 기준" },
        {
          label: "의견제출 기한",
          value: deadlineGuidance?.deadline || findReportText(sections, /제출 기한|의견제출|마감|D-/, "기한 확인 필요"),
          detail: deadlineGuidance?.deadline ? "확인된 기한 기준" : "고지서 원문 확인 필요",
        },
        { label: "검토 상태", value: reportStatusText, detail: "확인된 사실과 누락 자료" },
        { label: "필요 자료", value: facts.length > 0 ? `${facts.length}건 확인` : "추가 확인", detail: "현장 사진·정차 사유" },
      ];
  const nextActions = isFault
    ? [
        ["사고 사실관계 고정", "시간·장소·진입 방향·충돌 위치를 리포트에 고정합니다."],
        ["보험사 주장 비교", "보험사 안내 과실비율과 AI가 찾은 쟁점을 나란히 확인합니다."],
        ["추가 증거 요청", "보험사 접수 내역과 사고 경위 설명을 보완합니다."],
      ]
    : [
        ["현장 자료 보강", "표지판과 차량 위치가 함께 보이는 사진을 추가합니다."],
        ["의견제출서 초안 확인", "사실관계 중심의 초안을 검토하고 수정합니다."],
        ["제출 전 최종 점검", "제출 기관·기한·첨부 파일을 다시 확인합니다."],
      ];

  return (
    <section className="screen case-result-screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>{isFault ? "사고 과실비율 분석 결과" : "과태료·범칙금 분석 결과"}</h2>
          <p>{isFault ? "사고 장면과 쟁점, 보험사 대응에 필요한 후속 조치를 확인합니다." : "고지서에서 읽은 처분 정보와 이의제기 검토 결과를 확인합니다."}</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onOpenChat}>상담으로 돌아가기</button>
          <button className="button primary" type="button" onClick={onOpenReport}>리포트 작업대 열기</button>
        </div>
      </div>

      <div className="dashboard case-result-dashboard">
        <ServiceInformationNotice />
        {resultSafetyGuidance && <SafetyGuidancePanel guidance={resultSafetyGuidance} />}
        {deadlineGuidance && (
          <DeadlineGuidancePanel guidance={deadlineGuidance} />
        )}
        <div className="summary-grid">
          {metrics.map((metric) => (
            <MetricCard key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} />
          ))}
        </div>

        <div className="case-result-grid">
          <article className="case-result-panel">
            <div className="panel-head">
              <strong>{isFault ? "사고 장면과 쟁점" : "고지서·사실관계 정리"}</strong>
              <span className={reportStatus === "success" || reportStatus === "agent_execution_ready" ? "tag green" : "tag amber"}>{reportStatusText}</span>
            </div>
            <div className="case-result-panel__body">
              <div className="case-result-lead">
                <span className="eyebrow">현재 검토 요약</span>
                <strong>{isFault ? "진입 순서와 충돌 위치를 먼저 고정해야 합니다." : "처분 내용과 제출기한을 확인한 뒤 추가 자료를 보완해야 합니다."}</strong>
                <p>{reportingPayload?.summary || supervisorState?.conversation_summary || "현재 상담에서 확인된 사실과 다음 행동을 정리했습니다."}</p>
              </div>
              <EvidenceBoundaryPanel facts={facts} userClaims={userClaims} />

              {isFault && faultRatioNode ? (
                <FaultRatioInsightPanel node={faultRatioNode} />
              ) : facts.length === 0 && userClaims.length === 0 ? (
                <div className="case-result-facts">
                  {(facts.length > 0 ? facts.slice(0, 4) : [
                    { field: "확인된 사실", value: "상담 내용과 첨부 자료를 기준으로 정리 중" },
                    { field: "추가 확인", value: isFault ? "사고 장면 자료" : "표지판·차량 위치 사진" },
                  ]).map((fact, index) => (
                    <div className="case-result-fact" key={`${fact.field || "fact"}-${index}`}>
                      <span>{fact.field || fact.label || "확인 항목"}</span>
                      <strong>{compactValue(fact.value || fact.description || fact)}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
              {lawGroundNode && <LawGroundInsightPanel node={lawGroundNode} />}

              {analysisCards.length > 0 && (
                <div className="case-result-card-list">
                  {analysisCards.slice(0, 4).map((card, index) => (
                    <article className="case-result-card" key={analysisCardKey(card, index)}>
                      <span className={card.status === "success" ? "tag green" : "tag amber"}>{card.card_type}</span>
                      <strong>{card.title}</strong>
                      <p>{card.summary}</p>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </article>

          <aside className="case-result-panel case-result-next-panel">
            <div className="panel-head">
              <strong>다음 행동</strong>
              <span className="tag amber">우선순위</span>
            </div>
            <div className="case-result-panel__body">
              <div className="case-action-list">
                {nextActions.map(([title, description], index) => (
                  <div className="case-action" key={title}>
                    <span className="case-action__number">{index + 1}</span>
                    <div><strong>{title}</strong><p>{description}</p></div>
                  </div>
                ))}
              </div>
              <div className="case-result-cta">
                <button className="button primary full" type="button" onClick={onPrepareMissingEvidence}>자료 추가하기</button>
                <button className="button full" type="button" onClick={onPrepareDraftRegeneration}>초안 다시 만들기</button>
              </div>
              {reportActionStatus && <p className="status-message inside" role="status">{reportActionStatus}</p>}
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}
function reportTypeLabel(value) {
  const labels = {
    fine_notice_objection: "과태료 대응",
    fault_ratio_analysis: "과실비율 분석",
    generic_supervisor: "상담 요약",
    objection_draft: "이의신청 초안",
    fault_analysis: "과실 분석",
    general: "일반 리포트",
  };
  return labels[value] || value || "리포트";
}

function reportStatusLabel(value) {
  const labels = {
    draft: "작성 중",
    agent_execution_ready: "분석 준비",
    partial: "보완 필요",
    success: "분석 완료",
    ready: "저장 완료",
    downloaded: "다운로드 완료",
    report_saved: "저장 완료",
    metadata_saved: "저장 완료",
  };
  return labels[String(value || "").toLowerCase()] || value || "상태 확인";
}

function reportStatusTone(value) {
  const status = String(value || "").toLowerCase();
  if (["success", "ready", "report_saved", "metadata_saved"].includes(status)) return "complete";
  if (status === "downloaded") return "downloaded";
  if (status === "partial") return "attention";
  if (status === "agent_execution_ready") return "ready";
  return "progress";
}

function reportQualityLabel(report = {}) {
  if (report.partial_report) {
    return "검토 필요";
  }
  const quality = report?.metadata?.report_quality || report?.persistence?.report_quality || {};
  return quality.partial_report ? "검토 필요" : "검토 가능";
}

function sectionToneClass(title) {
  if (/근거|판례|법령|쟁점|증거|후속|가이드라인/.test(String(title || ""))) {
    return "report-section-card evidence";
  }
  return "report-section-card";
}

function groupReportSections(sections) {
  const grouped = {
    overview: [],
    grounds: [],
    actions: [],
    remainder: [],
  };

  if (!Array.isArray(sections)) {
    return grouped;
  }

  sections.forEach((section) => {
    const title = String(section?.title || "");
    if (/후속 조치|가이드라인|AI 작성|제출|첨부 자료|자료 요청|재생성|다운로드|모니터링|활용/.test(title)) {
      grouped.actions.push(section);
      return;
    }
    if (/근거|법령|판례|증거|이의제기|예상 결과|판단 근거|핵심 쟁점|유사 사례/.test(title)) {
      grouped.grounds.push(section);
      return;
    }
    if (/사고 개요|OCR 문서 분석|처분 결과|지원 결과|제출 자료 현황|AI 분석 결과|사건 개요|현재 단계|판단/.test(title)) {
      grouped.overview.push(section);
      return;
    }
    grouped.remainder.push(section);
  });

  return grouped;
}

function ReportActionAlert({ status }) {
  const text = String(status || "").trim();
  if (!text) {
    return null;
  }
  const isError = /실패|못했|못해|오류|에러/.test(text);
  const isSuccess = !isError && /완료|성공|저장했|반영했/.test(text);
  const tone = isError ? "error" : isSuccess ? "success" : "info";
  return (
    <div className={`report-action-alert ${tone}`} role="status">
      {text}
    </div>
  );
}

function DocumentTypeCards({ cards, onCopy }) {
  const documentTitles = {
    objection_draft: "이의신청서 초안",
    fact_summary: "사실관계 정리",
    insurance_submission: "보험사 제출용 요약",
  };
  if (!Array.isArray(cards) || cards.length === 0) {
    return null;
  }
  return (
    <section className="document-type-cards" aria-label="문서 유형별 정리">
      {cards.map((card) => {
        const sections = Array.isArray(card?.sections) ? card.sections : [];
        const statusLabel =
          card?.status === "ready"
            ? "복사 가능"
            : card?.status === "partial"
              ? "자료 보완 필요"
              : "제출 불가";
        const canCopy = Boolean(card?.copy_text) && card?.status !== "unavailable";
        const title = card?.title || documentTitles[card?.type] || "문서 정리";
        return (
          <article className="document-type-card" data-status={card?.status || "partial"} key={card?.type || card?.title}>
            <div className="document-type-card-head">
              <span className="tag">{statusLabel}</span>
              <strong>{title}</strong>
            </div>
            <p>{card?.description || "리포트 내용을 문서 목적에 맞게 정리합니다."}</p>
            {sections.length > 0 && (
              <div className="document-type-card-sections">
                {sections.slice(0, 2).map((section, index) => (
                  <p key={`${card?.type || "document"}-${section?.title || index}`}>
                    <strong>{section?.title || "리포트 항목"}</strong>
                    {section?.body ? ` · ${compactValue(section.body)}` : ""}
                  </p>
                ))}
              </div>
            )}
            {card?.notice && <p className="document-type-notice">{card.notice}</p>}
            {canCopy && (
              <button className="button" type="button" onClick={() => onCopy?.(card.copy_text, title)} disabled={!onCopy}>
                내용 복사
              </button>
            )}
          </article>
        );
      })}
    </section>
  );
}

function ReportingScreen({
  analysisCards = [],
  currentReport = null,
  isAuthenticated = false,
  onOpenChat,
  onOpenReport,
  onCopyDocumentCard,
  onPrepareDraftRegeneration,
  onPrepareMissingEvidence,
  onRefresh,
  onConfirmDocument,
  onRunReportAction,
  reportActionStatus = "",
  reportList = [],
  reportingPayload = null,
  supervisorExecution = null,
  supervisorState = null,
}) {
  const [isReportListCollapsed, setIsReportListCollapsed] = useState(false);
  const hasSavedReports = Array.isArray(reportList) && reportList.length > 0;
  const activeReportingPayload = currentReport?.content?.reporting_payload || reportingPayload;
  const appealDownloadBlocked = activeReportingPayload?.appeal_gate?.blocked === true;
  const documentConfirmation = activeReportingPayload?.document_confirmation || null;
  const hasOfficialDocument =
    documentConfirmation?.required === true ||
    ["fine_notice", "traffic_accident"].includes(activeReportingPayload?.document_variant) ||
    ["fine_notice_objection", "fault_ratio_analysis"].includes(activeReportingPayload?.report_type);
  const confirmation = {
    required: shouldShowDocumentConfirmation({
      documentConfirmation,
      isAuthenticated,
    }),
    confirmed: documentConfirmation?.confirmed === true,
    stale: documentConfirmation?.stale === true,
    appealBlocked: appealDownloadBlocked,
    reportId: currentReport?.report_id || activeReportingPayload?.report_id || null,
  };
  const hasReport = Boolean(activeReportingPayload || analysisCards.length || supervisorExecution || currentReport || hasSavedReports);
  const sections = Array.isArray(activeReportingPayload?.sections) ? activeReportingPayload.sections : [];
  const documentCards = Array.isArray(activeReportingPayload?.document_cards)
    ? activeReportingPayload.document_cards
    : [];
  const nodeResults = Array.isArray(supervisorExecution?.node_results) ? supervisorExecution.node_results : [];
  const faultRatioNode = nodeResults.find((node) => node?.node_code === "text_ml_case_search");
  const lawGroundNode = nodeResults.find((node) => node?.node_code === "law_ground_search");
  const reportPersistence = currentReport?.persistence || {};
  const reportMetadata = currentReport?.metadata || {};
  const reportStatus = activeReportingPayload?.stage || currentReport?.status || reportPersistence.status || "draft";
  const reportTitle = activeReportingPayload?.title || reportMetadata.title || "상담 분석 리포트";
  const reportSummary =
    activeReportingPayload?.summary ||
    currentReport?.summary ||
    (reportMetadata.case_id
      ? `내 사건 ${reportMetadata.case_id}에 저장된 리포트입니다.`
      : "최신 상담 결과를 리포팅 화면에 연결했습니다.");
  const activeReportTitle = activeReportingPayload?.title || currentReport?.title || reportTitle;
  const activeReportType = activeReportingPayload?.report_type || currentReport?.report_type || "general";
  const activeReportTypeLabel = reportTypeLabel(activeReportType);
  const reportDisplayLabel = activeReportType === "general" ? "상담 리포트" : activeReportTypeLabel;
  const savedReportCountLabel = hasSavedReports ? `${reportList.length}건` : hasReport ? "1건" : "리포트 없음";
  const reportTagClass = currentReport || reportStatus === "agent_execution_ready" ? "tag green" : "tag amber";
  const groupedSections = groupReportSections(sections);
  const overviewSections = (groupedSections.overview.length ? groupedSections.overview : groupedSections.remainder).slice(0, 4);
  const groundsSections = groupedSections.grounds;
  const actionSections = groupedSections.actions;
  const supportCards = analysisCards.slice(0, 3);

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>리포트 작업대</h2>
          <p>상담 결과에서 생성한 과태료·과실비율·사고 리포트를 검토하고 내려받는 화면입니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onRefresh}>목록 새로고침</button>
          <button className="button primary" type="button" onClick={onOpenChat}>리포트 생성 준비</button>
        </div>
      </div>

      <div className={isReportListCollapsed ? "report-workbench is-list-collapsed" : "report-workbench"}>
        <aside className={isReportListCollapsed ? "report-list is-collapsed" : "report-list"} aria-label="리포트 목록">
          <div className="panel-head compact">
            {!isReportListCollapsed && <strong>리포트 목록</strong>}
            <div className="report-list-head-actions">
              {!isReportListCollapsed && <span className="report-list-count">{savedReportCountLabel}</span>}
              <button
                className="report-list-collapse-toggle"
                type="button"
                onClick={() => setIsReportListCollapsed((value) => !value)}
                aria-label={isReportListCollapsed ? "리포트 목록 펼치기" : "리포트 목록 접기"}
                title={isReportListCollapsed ? "리포트 목록 펼치기" : "리포트 목록 접기"}
              >
                <span>{isReportListCollapsed ? "»" : "«"}</span>
                {!isReportListCollapsed && <strong>접기</strong>}
              </button>
            </div>
          </div>
          {!isReportListCollapsed && !hasSavedReports && <ServiceInformationNotice />}
          {!isReportListCollapsed && hasSavedReports && (
            <div className="report-saved-list">
              {reportList.map((report) => {
                const isActive = report?.report_id === currentReport?.report_id;
                const payload = report?.content?.reporting_payload || {};
                return (
                  <button
                    className={isActive ? "report-list-card active" : "report-list-card"}
                    type="button"
                    key={report?.report_id || report?.title}
                    onClick={() => onOpenReport?.(report)}
                  >
                    <span className={`report-list-status ${reportStatusTone(payload.stage || report?.status)}`}>
                      {reportStatusLabel(payload.stage || report?.status)}
                    </span>
                    <strong>{payload.title || report?.title || "상담 리포트"}</strong>
                    <p>{report?.metadata?.updated_at || "최근 작업 시간 없음"}</p>
                  </button>
                );
              })}
            </div>
          )}
          {!isReportListCollapsed && hasSavedReports && <ServiceInformationNotice />}
        </aside>

        <article className="report-canvas" aria-label="리포트 미리보기">
          {hasReport ? (
            <div className="report-page">
              <span className="report-document-label">{reportDisplayLabel}</span>
              <h3>{activeReportTitle}</h3>
              <p>{reportSummary}</p>
              <div className="report-status-strip">
                <span>작성 상태</span>
                <strong className={`report-status-badge ${reportStatusTone(reportStatus)}`}>
                  {reportStatusLabel(reportStatus)}
                </strong>
                <p>상담 내용을 바탕으로 확인된 내용을 정리하고 있습니다.</p>
              </div>

              <DocumentTypeCards cards={documentCards} onCopy={onCopyDocumentCard} />

              <div className="report-story-grid">
                {overviewSections.map((section) => (
                  <ReportSectionPreview compact detailLimit={2} key={`overview-${section.title}`} section={section} />
                ))}
                {overviewSections.length === 0 && currentReport && (
                  <article className="report-empty-hint">
                    <strong>저장 리포트</strong>
                    <p>
                      리포트 ID {currentReport.report_id}
                      {reportMetadata.updated_at ? ` · 최근 작업 ${reportMetadata.updated_at}` : ""}
                    </p>
                  </article>
                )}
              </div>

              <div className="report-focus-columns">
                <section className="report-focus-panel" aria-label="핵심 근거">
                  <div className="report-focus-header">
                    <strong>판단 근거</strong>
                  </div>
                  <div className="report-section-list">
                    {groundsSections.length > 0 ? (
                      groundsSections.map((section) => (
                        <ReportSectionPreview detailLimit={3} key={`grounds-${section.title}`} section={section} />
                      ))
                    ) : (
                      <div className="report-empty-hint">
                        <strong>근거 항목이 아직 정리되지 않았습니다.</strong>
                        <p>역질문이 더 필요하거나 Agent 결과가 도착하면 이 영역을 채웁니다.</p>
                      </div>
                    )}
                  </div>
                </section>

                <section className="report-focus-panel" aria-label="다음 작업">
                  <div className="report-focus-header">
                    <strong>다음 단계</strong>
                  </div>
                  <div className="report-section-list">
                    {actionSections.length > 0 ? (
                      actionSections.map((section) => (
                        <ReportSectionPreview detailLimit={3} key={`actions-${section.title}`} section={section} />
                      ))
                    ) : (
                      <div className="report-empty-hint">
                        <strong>다음 작업 항목이 아직 없습니다.</strong>
                        <p>리포트 저장 전까지는 제출 단계 대신 상담 요약만 유지합니다.</p>
                      </div>
                    )}
                  </div>
                </section>
              </div>

              {supportCards.length > 0 && (
                <div className="report-support-strip">
                  <strong>보조 분석</strong>
                  <div className="report-support-chips">
                    {supportCards.map((card, index) => (
                      <span className="report-support-chip" key={analysisCardKey(card, index)}>
                        {card.card_type}: {card.summary}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="report-page-empty">
              <h3>사고 리포트를 선택하면 문서가 열립니다.</h3>
              <p>저장된 사고 리포트의 개요, 근거, 후속 행동을 문서 형태로 검토할 수 있습니다.</p>
            </div>
          )}
        </article>

        <aside className="report-inspector" aria-label="상태와 다운로드">
          <div className="panel-head compact">
            <strong>상태·다운로드</strong>
          </div>
          <ReportActionAlert status={reportActionStatus} />
          {hasReport ? (
            <>
              <DocumentConfirmationPanel
                confirmation={confirmation}
                isAuthenticated={isAuthenticated}
                onConfirm={onConfirmDocument}
              />
              <div className="inspector-actions">
                {hasOfficialDocument && (
                  <button
                  className="button"
                  type="button"
                  onClick={() => onRunReportAction?.("download_objection")}
                  disabled={!hasReport || appealDownloadBlocked || !confirmation.confirmed}
                >
                  {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 이의신청서 DOCX"}
                </button>
                )}
                <button
                  className="button"
                  type="button"
                  onClick={() => onRunReportAction?.("save")}
                  disabled={!hasReport}
                >
                  {isAuthenticated ? "리포트 저장" : "로그인 후 저장"}
                </button>
                <button className="button" type="button" onClick={onPrepareMissingEvidence} disabled={!hasReport}>
                  누락 자료 추가
                </button>
                <button className="button" type="button" onClick={onPrepareDraftRegeneration} disabled={!hasReport}>
                  초안 재생성
                </button>
              </div>
              <div className="inspector-section">
                <strong>리포트 검토 상태</strong>
                <p>{supervisorState?.conversation_summary || "최신 상담 상태를 확인했습니다."}</p>
              </div>
              <div className="inspector-section">
                <strong>반영된 분석 결과</strong>
                <p>분석 항목 {analysisCards.length}건과 근거·누락 자료를 리포트에 반영했습니다.</p>
              </div>
              {faultRatioNode && <FaultRatioInsightPanel compact node={faultRatioNode} />}
              {lawGroundNode && <LawGroundInsightPanel compact node={lawGroundNode} />}
            </>
          ) : (
            <div className="inspector-section">
              <span className="tag green">대기</span>
              <strong>리포트 선택 필요</strong>
              <p>선택된 리포트의 상태와 다운로드 버튼이 이곳에 표시됩니다.</p>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function ReportSectionPreview({ section, detailLimit = 3, compact = false }) {
  const items = Array.isArray(section?.items) ? section.items.slice(0, detailLimit) : [];
  const itemCount = Array.isArray(section?.items) ? section.items.length : 0;
  return (
    <article className={`${sectionToneClass(section?.title)} preview${compact ? " compact" : ""}`}>
      <div className="report-section-heading">
        <strong>{section?.title || "리포트 섹션"}</strong>
        {itemCount > 0 && <span className="tag">{itemCount}개</span>}
      </div>
      {items.length > 0 ? (
        items.map((item, index) => <p key={`${section?.title || "section"}-${index}`}>{compactValue(item)}</p>)
      ) : (
        <p>표시할 항목이 없습니다.</p>
      )}
    </article>
  );
}

function MetricCard({ detail, label, value }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function restoreConversationMessages(job = {}, item = {}) {
  const storedMessages = Array.isArray(job.conversation_messages) ? job.conversation_messages : [];
  const messages = storedMessages
    .map((message) => ({
      role: message?.role === "assistant" ? "assistant" : "user",
      content: String(message?.content || "").trim(),
      status: message?.metadata?.response_status || job.status || "success",
    }))
    .filter((message) => message.content);
  const assistantMessage = assistantMessageText(
    job.assistant_message || job.assistant_message_payload,
    job.progress_message || "저장된 상담 결과를 불러왔습니다."
  );

  if (!messages.some((message) => message.role === "user")) {
    messages.unshift({
      role: "user",
      content: item?.title || job.routing_intent || "저장된 상담",
    });
  }
  if (!messages.some((message) => message.role === "assistant")) {
    messages.push({
      role: "assistant",
      content: assistantMessage,
      status: job.status || "success",
      pending_questions: job.pending_questions || [],
    });
  }
  return messages;
}

function restoreAnalysisResponse(job = {}, item = {}) {
  const reportingPayload = job.reporting_payload || job.supervisor_state?.reporting_payload || null;
  return {
    ...job,
    cards: Array.isArray(job.cards) ? job.cards : [],
    assistant_message: assistantMessageText(
      job.assistant_message || job.assistant_message_payload,
      job.progress_message || "저장된 상담 결과를 불러왔습니다."
    ),
    pending_questions: Array.isArray(job.pending_questions) ? job.pending_questions : [],
    reporting_payload: reportingPayload,
    supervisor_state: job.supervisor_state || null,
    supervisor_execution: job.supervisor_execution || null,
    persistence: {
      conversation_save_state: "saved",
      job_id: job.job_id || item?.job_id || item?.case_id || "",
      session_id: job.session_id || item?.session_id || "",
    },
  };
}

function restoreCurrentReport(job = {}, item = {}) {
  const reportId = job.latest_report_id || item?.latest_report_id || item?.report_id || "";
  if (!reportId) {
    return null;
  }
  const latestReport = Array.isArray(job.reports)
    ? job.reports.find((report) => report?.report_id === reportId) || job.reports[0]
    : null;
  const reportStatus = job.latest_report_status || latestReport?.status || item?.latest_report_status || item?.status || "saved";
  return {
    report_id: reportId,
    status: reportStatus,
    persistence: {
      status: reportStatus,
      report_quality: latestReport?.report_quality || {},
    },
    metadata: {
      case_id: job.job_id || item?.case_id || item?.job_id || "",
      title:
        latestReport?.title ||
        item?.title ||
        assistantMessageText(job.assistant_message || job.assistant_message_payload, "저장된 상담 리포트"),
      updated_at: latestReport?.updated_at || job.updated_at || item?.updated_at || item?.last_event_at || "",
      report_count: job.report_count || item?.report_count || 1,
    },
  };
}

function normalizeAnalysisCards(cards) {
  return cards.map((card) => ({
    card_type: normalizeLabel(card.card_type),
    title: normalizeDisplayText(card.title || "분석 항목"),
    status: card.status || "partial",
    summary: normalizeDisplayText(card.summary || "추가 확인이 필요합니다."),
  }));
}

function detectCaseType({ analysisCards = [], analysisResponse = null, currentReport = null } = {}) {
  const source = [
    ...analysisCards.flatMap((card) => [card?.card_type, card?.title, card?.summary]),
    analysisResponse?.routing_intent,
    analysisResponse?.reporting_payload?.title,
    currentReport?.metadata?.title,
  ]
    .filter(Boolean)
    .join(" ");
  return /사고|과실|교차로|보험/.test(source) ? "fault" : "fine";
}

function caseResultRoute(card = {}) {
  const source = [card.card_type, card.title, card.summary].filter(Boolean).join(" ");
  if (/사고|과실|교차로|보험/.test(source)) {
    return "faultResult";
  }
  if (/과태료|고지서|범칙금|이의/.test(source)) {
    return "fineResult";
  }
  return null;
}

function findReportText(sections, pattern, fallback) {
  const values = (Array.isArray(sections) ? sections : []).flatMap((section) => [
    section?.title,
    ...(Array.isArray(section?.items) ? section.items : []),
  ]);
  const match = values.find((value) => pattern.test(String(compactValue(value))));
  return match ? compactValue(match) : fallback;
}

function normalizeLabel(value) {
  const labels = {
    fine_notice: "고지서 분석",
    law_ground: "근거 확인",
    objection_report: "초안 작성",
    supervisor_summary: "분석 요약",
    agent_input_schema: "입력 확인",
    reporting_preview: "리포트 준비",
  };
  return labels[value] || value || "분석";
}

function attachmentStatusLabel(value) {
  const labels = {
    clean: "안전 확인 완료",
    failed: "파일 확인 필요",
    pending: "안전 확인 중",
    rejected: "다른 파일 필요",
    scan_pending: "안전 확인 중",
    success: "연결 완료",
  };
  return labels[String(value || "").toLowerCase()] || "연결됨";
}

function buildDeveloperDiagnostic(result = {}) {
  const nodeResults = Array.isArray(result?.supervisor_execution?.node_results)
    ? result.supervisor_execution.node_results
    : [];
  return {
    executionMode: result.execution_mode || result?.supervisor_execution?.execution_mode || null,
    nodeResults: nodeResults.map((node) => ({
      code: node.node_code,
      mode: node.adapter_execution_mode || node.execution_mode,
      status: node.status,
    })),
    reportStage: result?.reporting_payload?.stage || null,
    status: result.status || null,
    supervisorStage: result?.supervisor_state?.stage || null,
  };
}

function logDeveloperDiagnostic(event, payload) {
  if (!import.meta.env.DEV) {
    return;
  }
  console.debug(`[TrafficDisputeAI] ${event}`, payload);
}

function caseStatusLabel(value) {
  const labels = {
    queued: "대기",
    running: "분석 중",
    partial: "추가 확인",
    success: "분석 완료",
    failed: "확인 필요",
  };
  return labels[String(value || "").toLowerCase()] || value || "상태 확인";
}

function caseStatusTone(value) {
  const status = String(value || "").toLowerCase();
  if (/완료|success|ready|저장/.test(status)) return "complete";
  if (/다운로드|downloaded/.test(status)) return "downloaded";
  if (/보완|확인|기한 임박|기한 경과|partial|failed/.test(status)) return "attention";
  return "ready";
}

function isReportingPayloadReady(reportingPayload, supervisorState) {
  if (!reportingPayload) {
    return false;
  }
  const pendingQuestions = Array.isArray(supervisorState?.next_questions) ? supervisorState.next_questions : [];
  const missingFields = Array.isArray(supervisorState?.missing_fields) ? supervisorState.missing_fields : [];
  // `reporting_payload.stage` is only populated on the Supervisor-LLM path
  // (supervisor_llm_service._normalized_reporting_payload); the rule-based
  // fallback builder never sets it. `supervisor_state.stage` is set reliably
  // on both paths, so check that instead.
  return supervisorState?.stage === "agent_execution_ready" && pendingQuestions.length === 0 && missingFields.length === 0;
}

function hasReportGenerationNode(supervisorState) {
  // Only routing intents whose Agent plan includes objection_report_generation
  // (currently just fine_notice_objection, see NODE_PLANS in
  // chat_orchestration_service.py) ever produce a persisted report. Showing
  // the save/download actions for other intents (e.g. traffic_law_search)
  // leads users to a "wait for the worker" message that never resolves,
  // because nothing is ever generated for those intents.
  const packages = Array.isArray(supervisorState?.agent_input_packages)
    ? supervisorState.agent_input_packages
    : [];
  return packages.some((item) => item?.node_code === "objection_report_generation");
}

function latestMessageIndex(messages, role) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === role) {
      return index;
    }
  }
  return -1;
}

function compactValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "-";
    }
    return value
      .slice(0, 3)
      .map((item) => compactValue(item))
      .join(", ");
  }
  if (typeof value === "object") {
    const label = value.label || value.title || value.field || value.node_code;
    const itemValue = value.value ?? value.summary ?? value.text ?? value.question ?? value.status;
    if (label && itemValue !== undefined && itemValue !== null && itemValue !== "") {
      return `${label}: ${compactValue(itemValue)}`;
    }
    return Object.entries(value)
      .slice(0, 4)
      .map(([key, item]) => `${key}: ${compactValue(item)}`)
      .join(" · ");
  }
  return String(value);
}

function normalizeDisplayText(value) {
  return String(value || "").trim();
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  return String(value).slice(0, 10).replaceAll("-", ".");
}
