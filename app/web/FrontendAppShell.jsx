import { useEffect, useMemo, useRef, useState } from "react";

import { createFrontendApi } from "./apiClient.js";
import {
  buildAuthContext,
  buildGoogleLoginPayload,
  clearStoredAuthSession,
  persistAuthSession,
  readStoredAuthSession,
  readStoredAuthToken,
  scheduleAppJwtRefresh,
} from "./authSession.js";

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
const ATTACHMENT_PURPOSE_LABELS = {
  fine_notice: "고지서",
  supporting_evidence: "보조 자료",
};

function waitForWorkerPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, WORKER_POLL_INTERVAL_MS));
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

function analysisCardKey(card, index) {
  return `${card?.card_type || "analysis"}-${card?.title || "card"}-${index}`;
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
  const [authSessionId, setAuthSessionId] = useState(() => storedAuthSession.auth_session_id || "");
  const [mypageSummary, setMypageSummary] = useState(null);
  const [historyEvents, setHistoryEvents] = useState(null);
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
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
  const [reportActionStatus, setReportActionStatus] = useState("");
  const [currentReport, setCurrentReport] = useState(null);
  const [reportList, setReportList] = useState([]);
  const [pendingAuthAction, setPendingAuthAction] = useState(null);
  const [guestDetailedReportUsed, setGuestDetailedReportUsed] = useState(false);
  const authRefreshContextRef = useRef({ guestId, sessionId });
  authRefreshContextRef.current = { guestId, sessionId };

  const effectiveAuthToken = activeAuthToken || "";
  const identity = {
    authToken: effectiveAuthToken,
    guestId,
    authSessionId,
  };
  const authContext = buildAuthContext({
    authState: authSessionId ? "authenticated" : guestId ? "guest" : "anonymous",
    guestId,
    authSessionId,
    sessionId,
    userId: null,
  });
  const isGuestReady = Boolean(guestId);
  const sessionLabel = authSessionId ? "Google 계정 상담" : isGuestReady ? "비회원 상담" : "상담 준비";
  const cases = mypageSummary?.cases || [];
  const history = historyEvents?.events || [];
  const analysisCards = analysisResponse?.cards?.length
    ? normalizeAnalysisCards(analysisResponse.cards)
    : [];
  const assistantAnswer =
    analysisResponse?.assistant_message?.core_answer ||
    assistantMessageText(analysisResponse?.assistant_message);
  const assistantFollowUp = analysisResponse?.assistant_message?.follow_up || null;
  const deadlineGuidance = analysisResponse?.deadline_guidance || null;
  const supervisorState = analysisResponse?.supervisor_state || null;
  const reportingPayload = analysisResponse?.reporting_payload || null;
  const supervisorExecution = analysisResponse?.supervisor_execution || null;
  const caseType = detectCaseType({ analysisCards, analysisResponse, currentReport });
  const isLiveReportingReady = isReportingPayloadReady(reportingPayload, supervisorState);
  const visibleReportingPayload = isLiveReportingReady ? reportingPayload : null;
  const visibleAnalysisCards = isLiveReportingReady
    ? analysisCards
    : analysisCards.filter((card) => card?.card_type !== "reporting_preview");
  const attachmentPurposes = Array.from(
    new Set((capabilityCatalog?.capabilities || []).flatMap((capability) => capability.attachment_purposes || []))
  ).map((value) => ({ value, label: ATTACHMENT_PURPOSE_LABELS[value] || value }));

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
          setActiveAuthToken(nextToken);
          setAuthSessionId(nextAuthSessionId);
          setGuestId(nextGuestId);
          persistAuthSession({ guestId: nextGuestId });
        } catch (_error) {
          if (!refreshEffectActive) {
            return;
          }
          clearStoredAuthSession();
          if (refreshContext.guestId) {
            persistAuthSession({ guestId: refreshContext.guestId });
          }
          setActiveAuthToken("");
          setAuthSessionId("");
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
      const guest = await api.createGuestSession({
        guest_id: guestId,
        session_id: sessionId || undefined,
      });
      const nextGuestId = guest?.guest?.guest_id || guestId;
      const nextSessionId = guest?.session_binding?.session_id || sessionId || `ses_web_${Date.now()}`;
      setGuestId(nextGuestId);
      setSessionId(nextSessionId);
      setStatusMessage("임시 상담을 시작했습니다. 상세 분석이나 이력 저장이 필요해질 때 Google 로그인을 안내합니다.");
      setActiveRoute(nextRoute);
      return { guestId: nextGuestId, sessionId: nextSessionId };
    } catch (error) {
      setStatusMessage("상담 준비에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      return null;
    }
  }

  async function ensureGuestSession(nextRoute = "chatbot") {
    if (sessionId && guestId) {
      setActiveRoute(nextRoute);
      return { sessionId, guestId };
    }
    const guestSessionResult = await bootstrapGuestSession(nextRoute);
    if (guestSessionResult?.sessionId) {
      return guestSessionResult;
    }
    const fallbackSessionId = sessionId || `ses_web_${Date.now()}`;
    setSessionId(fallbackSessionId);
    setActiveRoute(nextRoute);
    return { sessionId: fallbackSessionId, guestId };
  }

  async function loginAndBindCurrentSession({ source = "manual_login", nextRoute = "chatbot" } = {}) {
    const activeGuestSession = await ensureGuestSession(nextRoute);
    const activeSessionId = activeGuestSession.sessionId || sessionId || `ses_web_${Date.now()}`;
    const activeGuestId = activeGuestSession.guestId || guestId || "";
    const loginPayload = {
      guest_id: activeGuestId,
      session_id: activeSessionId,
      ...(await buildGoogleLoginPayload({ googleClientId, guestId: activeGuestId })),
    };
    const loginResult = await api.loginWithGoogleCode(loginPayload);
    const nextToken = loginResult?.access_token || "";
    const subject = loginResult?.subject || {};
    const nextAuthSessionId = subject.auth_session_id || "";
    const nextGuestId = subject.guest_id || activeGuestId;
    const nextUserId = subject.user_id || loginResult?.user?.user_id || null;

    setActiveAuthToken(nextToken);
    setAuthSessionId(nextAuthSessionId);
    setGuestId(nextGuestId);
    setSessionId(activeSessionId);
    persistAuthSession({
      accessToken: nextToken,
      googleProfile: loginResult?.user || null,
      authSessionId: nextAuthSessionId,
      guestId: nextGuestId,
      sessionId: activeSessionId,
      userId: nextUserId,
    });

    const nextIdentity = {
      authToken: nextToken,
      authSessionId: nextAuthSessionId,
      guestId: nextGuestId,
    };
    return {
      authSessionId: nextAuthSessionId,
      authToken: nextToken,
      guestId: nextGuestId,
      identity: nextIdentity,
      loginResult,
      sessionId: activeSessionId,
      source,
      userId: nextUserId,
    };
  }

  // Local dev only: fakes "logged in" purely in the browser so the logged-in UI can be
  // reviewed, with zero backend calls. Deliberately does NOT set an auth token — leaving
  // it empty keeps identity.authToken falsy, so requests still go out with X-Guest-Id and
  // hit the backend's guest-allowed paths (chat/messages, files, reports, auth/me) instead
  // of being forced through real Bearer-JWT validation with a fake, unparseable token.
  // Screens that strictly require a real session (mypage summary/history) will still
  // come back empty/error, since there's no real auth session in the database.
  function previewLoggedInUi() {
    const previewSessionId = sessionId || `ses_preview_${Date.now()}`;
    const previewGuestId = guestId || `gst_preview_${Date.now()}`;
    setSessionId(previewSessionId);
    setGuestId(previewGuestId);
    setAuthSessionId(`auth_preview_${Date.now()}`);
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
    setSessionId("");
    setMypageSummary(null);
    setHistoryEvents(null);
    setChatMessages([]);
    setAnalysisResponse(null);
    setCurrentReport(null);
    setReportList([]);
    setPendingAuthAction(null);
    setReportActionStatus("");
    setWorkerActionStatus("");
    setSavePromptVisible(false);
    setSaveDecision("undecided");
    setGuestDetailedReportUsed(false);
    setSubmittedQuestion("");
    setQuestion("");
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
      setStatusMessage("첨부 등록에 실패했습니다.");
      setPendingAuthAction(null);
    } finally {
      setIsRegisteringAttachment(false);
    }
  }

  async function runCurrentReportAction(action = "download_report") {
    const jobId = currentReport?.job_id || analysisResponse?.persistence?.job_id || analysisResponse?.supervisor_execution?.job_id || "";
    let documentType = action === "download_objection" ? "objection_form" : "report";
    const reportAction = action === "save" ? "save" : "download";
    const activeReportingPayload = currentReport?.content?.reporting_payload || visibleReportingPayload;
    const appealGate = activeReportingPayload?.appeal_gate || null;
    const actionDefinition = Array.isArray(activeReportingPayload?.report_actions)
      ? activeReportingPayload.report_actions.find((item) => item?.type === action)
      : null;
    documentType = actionDefinition?.document_type || documentType;
    if (reportAction === "download") {
      if (appealGate?.blocked === true) {
        setReportActionStatus(appealGate.reason || "이의신청 가능 여부를 확인한 뒤 문서를 다운로드할 수 있습니다.");
        return;
      }
      if (actionDefinition && actionDefinition.document_format !== "docx") {
        setReportActionStatus("DOCX 형식으로 준비된 문서만 다운로드할 수 있습니다.");
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
        ? documentType === "objection_form"
          ? "이의신청서 DOCX를 준비하고 있습니다."
          : "분석 리포트 DOCX를 준비하고 있습니다."
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

  async function triggerReportDownload({ reportId, sessionId: activeSessionId, requestIdentity, documentType = "report" }) {
    const file = await api.downloadReport({
      reportId,
      sessionId: activeSessionId,
      identity: requestIdentity,
      documentType,
    });
    const filename = file.filename || `${reportId}.txt`;
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

  async function submitServiceMessage() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setStatusMessage("상담 내용을 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setStatusMessage("상담 내용을 정리하고 있습니다.");
    setSubmittedQuestion(trimmedQuestion);

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
    const nextUserMessage = { role: "user", content: trimmedQuestion };
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
          user_text: trimmedQuestion,
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
      setChatMessages([
        ...conversationHistory,
        {
          role: "assistant",
          content:
            workerResult?.assistant_message?.core_answer ||
            assistantMessageText(workerResult?.assistant_message, "상담 내용을 접수했습니다."),
          status: workerResult?.status || "partial",
          pending_questions: workerResult?.pending_questions || [],
          followUp: workerResult?.assistant_message?.follow_up || null,
        },
      ]);
      setAnalysisResponse(workerResult);
      setQuestion("");
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
      setChatMessages([
        ...conversationHistory,
        {
          role: "assistant",
          content: "응답을 불러오지 못해 접수 상태만 표시합니다.",
          status: "partial",
          pending_questions: [],
        },
      ]);
      setAnalysisResponse({
        cards: FALLBACK_ANALYSIS_CARDS,
      });
      setSavePromptVisible(!authSessionId);
      setStatusMessage("응답을 불러오지 못해 접수 상태만 표시합니다.");
    } finally {
      setIsSubmitting(false);
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
    setAnalysisResponse(null);
    setCurrentReport(null);
    setReportActionStatus("");
    setSaveDecision("undecided");
    setSavePromptVisible(false);
    setGuestDetailedReportUsed(false);
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

  return (
    <div className="app-shell" data-auth-state={authContext.auth_state}>
      <header className={activeRoute === "entry" ? "topbar" : "topbar topbar-with-mobile-nav"}>
        <div className="topbar-inner">
          <button
            className="brand"
            type="button"
            onClick={() => setActiveRoute("entry")}
            aria-label="교통분쟁 AI 처음 화면"
          >
            <span className="brand-mark">AI</span>
            <span>교통분쟁 AI</span>
          </button>
          <nav className="top-actions" aria-label="주요 메뉴">
            {TAB_ROUTES.map((route) => (
              <button
                className={activeRoute === route.id ? "button active" : "button ghost"}
                aria-current={activeRoute === route.id ? "page" : undefined}
                key={route.id}
                onClick={() => setActiveRoute(route.id)}
                type="button"
              >
                {route.label}
              </button>
            ))}
            {activeRoute === "entry" && (
              <button className="button primary" onClick={() => setActiveRoute("chatbot")} type="button">
                상담 시작
              </button>
            )}
            {authSessionId ? (
              <button className="button ghost" type="button" onClick={logoutAndResetSession}>
                로그아웃
              </button>
            ) : (
              <button
                className="button primary"
                type="button"
                onClick={saveConversationAfterLogin}
                disabled={isSavingConversation}
              >
                {isSavingConversation ? "연결 중" : "Google 로그인"}
              </button>
            )}
          </nav>
        </div>
      </header>

      <div className={activeRoute === "entry" ? "layout is-entry" : "layout"}>
        {activeRoute !== "entry" && (
          <ConversationSidebar
            activeRoute={activeRoute}
            cases={cases}
            currentTitle={submittedQuestion}
            isAuthenticated={Boolean(authSessionId)}
            isGuestReady={isGuestReady}
            isSavingConversation={isSavingConversation}
            onLogin={saveConversationAfterLogin}
            onLogout={logoutAndResetSession}
            onNavigate={setActiveRoute}
            onNewChat={startNewConversation}
            onOpenCase={openSavedCase}
            savePromptVisible={savePromptVisible}
            sessionLabel={sessionLabel}
            statusMessage={statusMessage}
          />
        )}

        <main className="workspace" aria-live="polite">
          {activeRoute === "entry" && (
            <EntryScreenV2
              onGuestStart={() => bootstrapGuestSession("chatbot")}
              onOpenChat={() => bootstrapGuestSession("chatbot")}
            />
          )}

          {activeRoute === "chatbot" && (
            <ChatScreenV2
              analysisCards={visibleAnalysisCards}
              attachmentPurpose={attachmentPurpose}
              attachmentPurposes={attachmentPurposes}
              assistantAnswer={assistantAnswer}
              assistantFollowUp={assistantFollowUp}
              authSessionId={authSessionId}
              chatMessages={chatMessages}
              currentReport={currentReport}
              onOpenCaseResult={(route) => setActiveRoute(route)}
              isRegisteringAttachment={isRegisteringAttachment}
              isSubmitting={isSubmitting}
              isSavingConversation={isSavingConversation}
              onKeepTemporary={keepConversationTemporary}
              onPreviewLoggedInUi={previewLoggedInUi}
              onRegisterAttachment={registerAttachmentMetadata}
              onOpenReporting={() => setActiveRoute("reporting")}
              onRunReportAction={runCurrentReportAction}
              onSaveConversation={saveConversationAfterLogin}
              onSubmit={submitServiceMessage}
              pendingAuthAction={pendingAuthAction}
              showPreviewLoggedInUi={Boolean(import.meta.env.DEV)}
              question={question}
              registeredAttachments={registeredAttachments}
              reportActionStatus={reportActionStatus}
              saveDecision={saveDecision}
              savePromptVisible={savePromptVisible}
              selectedUploadFile={selectedUploadFile}
              reportingPayload={reportingPayload}
              setAttachmentPurpose={setAttachmentPurpose}
              setQuestion={setQuestion}
              setSelectedUploadFile={setSelectedUploadFile}
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
              isAuthenticated={Boolean(authSessionId)}
              onOpenChat={() => setActiveRoute("chatbot")}
              onOpenReport={() => setActiveRoute("reporting")}
              onPrepareDraftRegeneration={prepareDraftRegeneration}
              onPrepareMissingEvidence={prepareMissingEvidenceUpload}
              onRunReportAction={runCurrentReportAction}
              registeredAttachments={registeredAttachments}
              reportingPayload={reportingPayload}
              reportActionStatus={reportActionStatus}
              supervisorExecution={supervisorExecution}
              supervisorState={supervisorState}
            />
          )}

          {activeRoute === "mypage" && (
            <MyPageScreen
              cases={cases}
              onOpenChat={() => setActiveRoute("chatbot")}
              onOpenCase={openSavedCase}
              onRefresh={loadMyPageSummary}
              summary={mypageSummary}
            />
          )}

          {activeRoute === "history" && (
            <HistoryScreen events={history} onRefresh={loadHistoryEvents} />
          )}

          {activeRoute === "reporting" && (
            <ReportingScreen
              analysisCards={visibleAnalysisCards}
              currentReport={currentReport}
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
              onRunReportAction={runCurrentReportAction}
              reportActionStatus={reportActionStatus}
              reportList={reportList}
              reportingPayload={visibleReportingPayload}
              supervisorExecution={supervisorExecution}
              supervisorState={supervisorState}
            />
          )}

          {activeRoute !== "chatbot" && statusMessage && (
            <p className="status-message" role="status">
              {statusMessage}
            </p>
          )}
        </main>
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

function EntryScreenV2({ onGuestStart, onOpenChat }) {
  return (
    <section className="entry-screen">
      <div className="entry-copy">
        <span className="eyebrow">로그인 없이 먼저 상담</span>
        <h1>당황한 순간에는 가입보다 질문이 먼저입니다.</h1>
        <p className="lead">
          사고 상황, 과태료 고지서, 보험사 설명을 바로 적어 주세요. 대화가 충분히 진행된 뒤
          이력 저장이나 추가 자료 분석이 필요할 때 Google 로그인을 안내합니다.
        </p>
        <div className="hero-actions">
          <button className="button primary large" type="button" onClick={onOpenChat}>
            바로 상담 시작
          </button>
          <button className="button large" type="button" onClick={onGuestStart}>
            비회원으로 상담 시작
          </button>
        </div>
        <p className="entry-note">
          저장을 선택하지 않으면 현재 상담은 임시로만 유지하고, 마이페이지 이력으로 넘기지 않습니다.
        </p>
      </div>

      <div className="entry-panel">
        <div className="panel-topline">
          <span>상담 흐름</span>
          <strong>Chat first</strong>
        </div>
        <div className="flow-stack">
          <div className="flow-step active">
            <span>1</span>
            <div>
              <strong>질문부터 시작</strong>
              <p>로그인 화면으로 막지 않고 비회원 상담을 먼저 엽니다.</p>
            </div>
          </div>
          <div className="flow-step">
            <span>2</span>
            <div>
              <strong>상담 진행</strong>
              <p>상황 정리, 필요한 자료, 다음 행동을 먼저 안내합니다.</p>
            </div>
          </div>
          <div className="flow-step">
            <span>3</span>
            <div>
              <strong>저장 여부 선택</strong>
              <p>로그인 후 저장하면 마이페이지 이력으로 연결하고, 아니면 임시로 둡니다.</p>
            </div>
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
  isGuestReady,
  isSavingConversation,
  onLogin,
  onLogout,
  onNavigate,
  onNewChat,
  onOpenCase,
  savePromptVisible,
  sessionLabel,
  statusMessage,
}) {
  const hasCases = cases.length > 0;
  const currentConversationTitle = currentTitle || "새 상담";

  return (
    <>
      <aside className="sidebar chat-sidebar" aria-label="대화 목록과 계정">
        <div className="sidebar-brand">
          <button className="brand compact" type="button" onClick={() => onNavigate("chatbot")}>
            <span className="brand-mark">AI</span>
            <span>교통분쟁 AI</span>
          </button>
        </div>

      <div className="sidebar-actions">
        <button className="nav-item primary-action" type="button" onClick={onNewChat}>
          <span>새 상담</span>
          <span>+</span>
        </button>
        <button className="nav-item" type="button" onClick={() => onNavigate("history")}>
          <span>상담 검색</span>
        </button>
      </div>

      <section className="conversation-section" aria-label="현재 대화">
        <div className="section-label">현재</div>
        <button
          className={activeRoute === "chatbot" ? "conversation-card active" : "conversation-card"}
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
              className="conversation-card"
              key={item.case_id || item.job_id || item.title}
              type="button"
              onClick={() => onOpenCase(item)}
            >
              <strong>{item.title || item.case_id}</strong>
              <span>
                {caseStatusLabel(item.case_status || item.status)}
                {item.latest_report_id ? " · 리포트 저장" : " · 리포트 대기"}
              </span>
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
  attachmentPurpose,
  attachmentPurposes,
  assistantAnswer,
  assistantFollowUp,
  capabilityError,
  authSessionId,
  chatMessages,
  currentReport,
  onOpenCaseResult,
  isRegisteringAttachment,
  isSavingConversation,
  isSubmitting,
  onKeepTemporary,
  onRegisterAttachment,
  onOpenReporting,
  onPreviewLoggedInUi,
  onRunReportAction,
  onSaveConversation,
  onSubmit,
  pendingAuthAction,
  question,
  registeredAttachments,
  reportActionStatus,
  saveDecision,
  savePromptVisible,
  selectedUploadFile,
  reportingPayload,
  setAttachmentPurpose,
  setQuestion,
  setSelectedUploadFile,
  showPreviewLoggedInUi,
  submittedQuestion,
  supervisorExecution,
  supervisorState,
  uploadInputResetKey,
}) {
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
  const uploadButtonLabel = isRegisteringAttachment
    ? "등록 중"
    : selectedUploadFile
      ? isAuthenticated
        ? "파일 업로드"
        : "Google 로그인 후 업로드"
      : "파일 선택 필요";
  const quickQuestions = [
    "과태료 고지서를 받았는데 어떻게 해야 하는지 봐줘",
    "6월 24일 오후 3시 초등학교 앞에서 아이가 아파 잠깐 정차했어",
    "신호 없는 교차로에서 나는 직진, 상대는 우측 진입 중 사고가 났어",
    "보험사 접수 내역을 바탕으로 과실 쟁점을 정리해줘",
  ];
  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>AI 교통 상담</h2>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onKeepTemporary}>
            저장하지 않고 계속하기
          </button>
          <button className="button primary" type="button" onClick={onSaveConversation} disabled={isSavingConversation}>
            {isSavingConversation ? "연결 중" : "Google 로그인 후 저장"}
          </button>
          {showPreviewLoggedInUi && (
            <button
              className="button"
              type="button"
              onClick={onPreviewLoggedInUi}
              title="로컬 개발 전용: 백엔드 호출 없이 화면만 로그인 상태로 바꿈"
            >
              UI 미리보기 (로그인 상태로 보기)
            </button>
          )}
        </div>
      </div>

      <section className="chat-attachment-bar" aria-label="상담 자료 첨부">
        <div className="attachment-tools">
          <label>
            <span>첨부 목적</span>
            <select value={attachmentPurpose} onChange={(event) => setAttachmentPurpose(event.target.value)}>
              {attachmentPurposes.map((item) => (
                <option value={item.value} key={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="file-picker">
            <span>파일</span>
            <input
              key={uploadInputResetKey}
              accept="image/*,application/pdf"
              type="file"
              onChange={(event) => setSelectedUploadFile(event.target.files?.[0] || null)}
            />
          </label>
          <button
            className="button"
            type="button"
            onClick={onRegisterAttachment}
            disabled={isRegisteringAttachment || !selectedUploadFile || Boolean(capabilityError)}
          >
            {uploadButtonLabel}
          </button>
          <span className="tag">자료 {registeredAttachments.length}건</span>
        </div>
        {capabilityError && <p className="attachment-help" role="alert">{capabilityError}</p>}
        {!isAuthenticated && selectedUploadFile && !pendingAuthAction && (
          <p className="attachment-help" role="status">
            자료 분석은 Google 로그인 후 현재 상담에 그대로 연결됩니다.
          </p>
        )}
        {pendingAuthAction && (
          <p className="attachment-help" role="status">
            로그인 후 요청한 작업을 같은 상담에서 이어갑니다.
          </p>
        )}
        {registeredAttachments.length > 0 && (
          <div className="attachment-list" aria-label="상담 연결 자료">
            {registeredAttachments.slice(-3).map((attachment) => (
              <span key={attachment.attachment_id}>
                {attachment.original_filename || attachment.filename || attachment.purpose}
                <em>{attachmentStatusLabel(attachment.scan_status || attachment.status)}</em>
              </span>
            ))}
          </div>
        )}
      </section>

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
                <span className="eyebrow">비회원 상담</span>
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
                      <div className={isUser ? "bubble" : "bubble wide"}>
                        <p>{message.content}</p>
                        {!isUser && message.followUp && <FollowUpNote followUp={message.followUp} />}
                        {!isUser && isLatestAssistant && (
                          <>
                            <MissingFieldsPrompt supervisorState={supervisorState} />
                            {canGenerateReport && (reportingPayload || analysisCards.length > 0) && (
                              <ReportActionPanel
                                currentReport={currentReport}
                                isAuthenticated={Boolean(authSessionId)}
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
                {isSubmitting && (
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
                <span className="eyebrow">저장 선택</span>
                <strong>이 상담을 마이페이지 이력에 저장할까요?</strong>
                <p>저장하면 Google 계정에 연결하고, 저장하지 않으면 PostgreSQL 이력 전환 없이 임시 상담으로 유지합니다.</p>
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

          <div className="quick-row" aria-label="빠른 질문">
            {quickQuestions.map((item) => (
              <button className="quick-chip" type="button" key={item} onClick={() => setQuestion(item)}>
                {item}
              </button>
            ))}
          </div>

          <div className="chat-input">
            <div className="input-stack">
              <textarea
                aria-label="상담 메시지 입력"
                placeholder="사고 상황, 고지서 내용, 보험사 설명처럼 지금 기억나는 내용을 입력해 주세요."
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
              />
            </div>
            <button className="button primary" type="button" onClick={onSubmit} disabled={isSubmitting}>
              {isSubmitting ? "정리 중" : "전송"}
            </button>
          </div>
        </div>
      </div>
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
              <li key={item.label || index}>{item.label}</li>
            ))}
          </ul>
        </div>
      )}
      {optionalItems.length > 0 && (
        <div className="follow-up-group follow-up-group-optional">
          <span className="follow-up-group-label">알려주시면 더 좋아요</span>
          <ul>
            {optionalItems.map((item, index) => (
              <li key={item.label || index}>{item.label}</li>
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
  const retrieval = structuredResult.retrieval || {};
  const matchedLaws = Array.isArray(structuredResult.matched_laws)
    ? structuredResult.matched_laws
    : [];
  const attemptedBackends = Array.isArray(retrieval.attempted_backends)
    ? retrieval.attempted_backends
    : [];
  const limitations = Array.isArray(node?.limitations) ? node.limitations : [];

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
          <strong>{compactValue(retrieval.status || (matchedLaws.length > 0 ? "ready" : "empty"))}</strong>
        </p>
        <p>
          <span>검색 저장소</span>
          <strong>{compactValue(retrieval.backend || "unavailable")}</strong>
        </p>
        <p>
          <span>확인된 근거</span>
          <strong>{matchedLaws.length}건</strong>
        </p>
      </div>
      {matchedLaws.length > 0 && (
        <div className="agent-insight-section">
          <strong>관련 법령 후보</strong>
          {matchedLaws.slice(0, compact ? 2 : 4).map((item, index) => (
            <p key={item.source_reference || `law-ground-${index}`}>
              <strong>{compactValue([item.law_name || item.title, item.article].filter(Boolean).join(" "))}</strong>
              {item.summary && <span>{compactValue(item.summary)}</span>}
              <small>출처: {compactValue(item.source_reference)}</small>
            </p>
          ))}
        </div>
      )}
      {attemptedBackends.length > 0 && (
        <div className="agent-insight-section">
          <strong>검색 시도 경로</strong>
          <p>{compactValue(retrieval.attempted_backends)}</p>
        </div>
      )}
      {limitations.length > 0 && (
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
          <span className="eyebrow">리포트 미리보기</span>
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

function ReportReadyNotice({ isAuthenticated, onOpenReporting, onRunReportAction, reportingPayload, reportActionStatus }) {
  const appealDownloadBlocked = reportingPayload?.appeal_gate?.blocked === true;
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
        <button
          className="button primary"
          type="button"
          onClick={() => onRunReportAction("download_objection")}
          disabled={appealDownloadBlocked}
        >
          {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 DOCX"}
        </button>
      </div>
    </section>
  );
}

function ReportActionPanel({ currentReport, isAuthenticated, onRunReportAction, reportingPayload, reportActionStatus }) {
  const activeReportingPayload = currentReport?.content?.reporting_payload || reportingPayload;
  const appealDownloadBlocked = activeReportingPayload?.appeal_gate?.blocked === true;
  const reportQuality =
    currentReport?.persistence?.report_quality ||
    currentReport?.report_quality ||
    currentReport?.metadata?.report_quality ||
    null;
  const hasReportQuality = Boolean(reportQuality);
  const reportLimitations = Array.isArray(reportQuality?.limitations) ? reportQuality.limitations.slice(0, 3) : [];
  const reportQualityTitle = reportQuality?.partial_report ? "일부 자료가 부족한 리포트" : "검토 준비가 완료된 리포트";
  const helperText = isAuthenticated
    ? reportActionStatus || activeReportingPayload?.appeal_gate?.reason || "상담 결과를 저장하거나 제출 문서와 분석 리포트 DOCX를 준비할 수 있습니다."
    : reportActionStatus || "리포트 저장과 DOCX 다운로드는 Google 로그인 후 사용할 수 있습니다.";

  return (
    <section className="report-action-panel" aria-label="리포트 저장과 다운로드">
      <div>
        <span className="eyebrow">리포트 상태</span>
        <strong>{currentReport?.report_id || "리포트 준비 중"}</strong>
        <p>{helperText}</p>
        {hasReportQuality && (
          <div className="report-quality-panel" data-partial-report={String(Boolean(reportQuality.partial_report))}>
            <span className={reportQuality.partial_report ? "tag amber" : "tag green"}>
              {reportQuality.partial_report ? "일부 자료 부족" : "검토 준비 완료"}
            </span>
            <strong className="report-quality-title">{reportQualityTitle}</strong>
            <span className="tag">분석 상태 · {caseStatusLabel(reportQuality.analysis_job_status)}</span>
            <span className="tag">확인할 한계 · {reportQuality.limitation_count ?? 0}건</span>
            {reportQuality.partial_report && (
              <p className="report-quality-warning">최종 제출 전에 부족한 자료와 사실관계를 확인해 주세요.</p>
            )}
            {reportLimitations.length > 0 && (
              <ul className="report-quality-limitations" aria-label="report quality limitations">
                {reportLimitations.map((item, index) => (
                  <li key={`report-quality-limitation-${index}`}>{compactValue(item)}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <div className="report-action-buttons">
        <button className="button" type="button" onClick={() => onRunReportAction("save")}>
          {isAuthenticated ? "저장" : "로그인 후 저장"}
        </button>
        <button
          className="button"
          type="button"
          onClick={() => onRunReportAction("download_report")}
          disabled={appealDownloadBlocked}
        >
          분석 리포트 DOCX
        </button>
        <button
          className="button primary"
          type="button"
          onClick={() => onRunReportAction("download_objection")}
          disabled={appealDownloadBlocked}
        >
          {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 이의신청서 DOCX"}
        </button>
      </div>
    </section>
  );
}

function MyPageScreen({ cases, onOpenCase, onOpenChat, onRefresh, summary }) {
  const activeCases = summary?.active_cases ?? cases.length;
  const savedReports = summary?.saved_reports ?? 0;
  const recentCount = summary?.recent_analysis_count ?? cases.length;
  const hasCases = cases.length > 0;
  const [showActionableOnly, setShowActionableOnly] = useState(false);
  const visibleCases = showActionableOnly
    ? cases.filter((item) => {
        const status = String(item.case_status || item.status || "").toLowerCase();
        return /partial|pending|queued|running|draft|review|기한|추가|확인|대기|진행|작성/.test(status);
      })
    : cases;

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
          <MetricCard label="기한 임박" value="1건" detail="의견제출 D-3" />
          <MetricCard label="저장 리포트" value={`${savedReports}건`} detail="DOCX 다운로드 가능" />
          <MetricCard label="최근 분석" value={`${recentCount}건`} detail="상담/리포트 포함" />
        </div>

        <article className="table-panel">
          <div className="panel-head">
            <strong>최근 분석 이력</strong>
            <button
              className={showActionableOnly ? "button active" : "button"}
              type="button"
              disabled={!hasCases}
              aria-pressed={showActionableOnly}
              onClick={() => setShowActionableOnly((value) => !value)}
            >
              {showActionableOnly ? "전체 보기" : "필터"}
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
                  visibleCases.map((item) => (
                    <tr key={item.case_id || item.job_id || item.title}>
                      <td><span className="tag">{item.type || "상담"}</span></td>
                      <td>{item.title || item.case_id}</td>
                      <td>{item.case_status || item.status || "확인 필요"}</td>
                      <td>{item.updated_at || item.created_at || "-"}</td>
                      <td><button className="button" type="button" onClick={() => onOpenCase(item)}>열기</button></td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
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

function reportInspectorDetail(sections, mode) {
  const selectedSections = reportSectionsForInspector(sections, mode);
  if (mode === "grounds") {
    return {
      label: "근거",
      title: "판단 근거와 제출 자료",
      summary: "판단 근거, 핵심 쟁점, 유사 사례를 모아서 확인합니다.",
      sections: selectedSections,
    };
  }
  if (mode === "actions") {
    return {
      label: "작업",
      title: "다음 제출 작업과 정리 순서",
      summary: "누락 자료 보완, 제출 준비, 재생성 포인트를 모아서 확인합니다.",
      sections: selectedSections,
    };
  }
  return {
    label: "리포트",
    title: "리포트 상세",
    summary: "선택한 리포트의 섹션과 검토 상태를 확인합니다.",
    sections: selectedSections,
  };
}

function reportSectionsForInspector(sections, mode) {
  if (!Array.isArray(sections) || mode === "overview") {
    return [];
  }
  if (mode === "grounds") {
    return sections.filter((section) =>
      /근거|법령|판례|증거|이의제기|예상 결과|판단 근거|핵심 쟁점|유사 사례/.test(String(section?.title || ""))
    );
  }
  if (mode === "actions") {
    return sections.filter((section) =>
      /후속 조치|가이드라인|AI 작성|제출|첨부 자료|자료 요청|재생성|다운로드|모니터링|활용/.test(
        String(section?.title || "")
      )
    );
  }
  return sections;
}

function DeadlineGuidancePanel({ guidance }) {
  const nextActions = Array.isArray(guidance?.next_actions) ? guidance.next_actions : [];
  const limitations = Array.isArray(guidance?.limitations) ? guidance.limitations : [];

  return (
    <aside className={`deadline-guidance-panel deadline-guidance-panel--${guidance.status}`} role="alert">
      <span className="deadline-guidance-panel__title">{guidance.card_title}</span>
      <strong>{guidance.reason}</strong>
      {limitations[0] && <p>{limitations[0]}</p>}
      {nextActions.length > 0 && (
        <ul>
          {nextActions.map((action) => <li key={action}>{action}</li>)}
        </ul>
      )}
    </aside>
  );
}


function CaseResultScreen({
  analysisCards = [],
  caseType = "fine",
  currentReport = null,
  deadlineGuidance = null,
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
        { label: "의견제출 기한", value: findReportText(sections, /제출 기한|의견제출|마감|D-/, "기한 확인 필요"), detail: "고지서 원문 확인 필요" },
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
        {deadlineGuidance && deadlineGuidance.status !== "normal" && (
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

              {isFault && faultRatioNode ? (
                <FaultRatioInsightPanel node={faultRatioNode} />
              ) : (
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
              )}
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
                <button
                  className="button full"
                  type="button"
                  onClick={() => onRunReportAction?.("download")}
                  disabled={(!currentReport && !reportingPayload) || appealDownloadBlocked}
                >
                  {isAuthenticated ? "리포트 다운로드" : "로그인 후 다운로드"}
                </button>
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

function ReportingScreen({
  analysisCards = [],
  currentReport = null,
  isAuthenticated = false,
  onOpenChat,
  onOpenReport,
  onPrepareDraftRegeneration,
  onPrepareMissingEvidence,
  onRefresh,
  onRunReportAction,
  reportActionStatus = "",
  reportList = [],
  reportingPayload = null,
  supervisorExecution = null,
  supervisorState = null,
}) {
  const hasSavedReports = Array.isArray(reportList) && reportList.length > 0;
  const activeReportingPayload = currentReport?.content?.reporting_payload || reportingPayload;
  const appealDownloadBlocked = activeReportingPayload?.appeal_gate?.blocked === true;
  const hasReport = Boolean(activeReportingPayload || analysisCards.length || supervisorExecution || currentReport || hasSavedReports);
  const sections = Array.isArray(activeReportingPayload?.sections) ? activeReportingPayload.sections : [];
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
  const savedReportCountLabel = hasSavedReports ? `${reportList.length}건` : hasReport ? "1건" : "0건";
  const reportTagClass = currentReport || reportStatus === "agent_execution_ready" ? "tag green" : "tag amber";
  const [selectedInspectorMode, setSelectedInspectorMode] = useState("overview");
  const groupedSections = groupReportSections(sections);
  const overviewSections = (groupedSections.overview.length ? groupedSections.overview : groupedSections.remainder).slice(0, 4);
  const groundsSections = groupedSections.grounds;
  const actionSections = groupedSections.actions;
  const supportCards = analysisCards.slice(0, 3);
  const inspectorDetail = reportInspectorDetail(sections, selectedInspectorMode);

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

      <div className="report-workbench">
        <aside className="report-list" aria-label="리포트 목록">
          <div className="panel-head compact">
            <strong>리포트 목록</strong>
            <span className="tag">{savedReportCountLabel}</span>
          </div>
          {hasReport ? (
            <div className="report-list-card">
              <span className={reportTagClass}>
                {reportStatusLabel(reportStatus)}
              </span>
              <strong>{reportTitle}</strong>
              <div className="report-card-tags">
                <span className="tag">{activeReportTypeLabel}</span>
                <span className={reportTagClass}>{reportStatusLabel(reportStatus)}</span>
              </div>
              <strong>{activeReportTitle}</strong>
              <p>{reportSummary}</p>
              {currentReport && (
                <p>
                  저장 리포트: {currentReport.report_id}
                  {reportPersistence.status ? ` · ${reportStatusLabel(reportPersistence.status)}` : ""}
                </p>
              )}
              {reportActionStatus && <p>{reportActionStatus}</p>}
              {hasSavedReports && (
                <div className="report-saved-list">
                  {reportList.slice(0, 5).map((report) => (
                    <button
                      className={
                        currentReport?.report_id === report.report_id
                          ? "report-list-card compact active"
                          : "report-list-card compact"
                      }
                      key={report.report_id}
                      type="button"
                      onClick={() => onOpenReport?.(report)}
                    >
                      <div className="report-card-tags">
                        <span className="tag">{reportTypeLabel(report.report_type)}</span>
                        <span className={report.partial_report ? "tag amber" : "tag green"}>
                          {reportQualityLabel(report)}
                        </span>
                      </div>
                      <strong>{report.title || report.report_id}</strong>
                      <p>{report.summary || report.status}</p>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="empty-panel report-empty">
              <strong>선택할 리포트가 없습니다.</strong>
              <p>상담 결과에서 리포트를 저장하면 사고 개요와 근거 문서가 여기에 표시됩니다.</p>
            </div>
          )}
        </aside>

        <article className="report-canvas" aria-label="리포트 미리보기">
          {hasReport ? (
            <div className="report-page">
              <span className="eyebrow">{activeReportTypeLabel}</span>
              <h3>{activeReportTitle}</h3>
              <p>{reportSummary}</p>
              <div className="summary-grid">
                <MetricCard detail={activeReportTypeLabel} label="리포트 상태" value={reportStatusLabel(reportStatus)} />
                <MetricCard detail="표시 가능한 주요 섹션" label="리포트 섹션" value={`${sections.length}개`} />
                <MetricCard detail="법령·증거·판례 중심" label="근거 묶음" value={`${groundsSections.length}개`} />
                <MetricCard detail="제출·보완·재생성 중심" label="다음 작업" value={`${actionSections.length}개`} />
              </div>

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
                    <div>
                      <span className="eyebrow">Grounds</span>
                      <strong>핵심 근거</strong>
                    </div>
                    <span className="tag">{groundsSections.length}개</span>
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
                    <div>
                      <span className="eyebrow">Next</span>
                      <strong>다음 작업</strong>
                    </div>
                    <span className="tag">{actionSections.length}개</span>
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
              <span className="eyebrow">리포트 미리보기</span>
              <h3>사고 리포트를 선택하면 문서가 열립니다.</h3>
              <p>저장된 사고 리포트의 개요, 근거, 후속 행동을 문서 형태로 검토할 수 있습니다.</p>
              <div className="report-placeholder-grid">
                <div />
                <div />
                <div />
                <div />
              </div>
            </div>
          )}
        </article>

        <aside className="report-inspector" aria-label="상태와 다운로드">
          <div className="panel-head compact">
            <strong>상태·다운로드</strong>
          </div>
          {hasReport ? (
            <>
              <div className="inspector-actions">
                <button
                  className="button"
                  type="button"
                  onClick={() => onRunReportAction?.("download_report")}
                  disabled={!hasReport || appealDownloadBlocked}
                >
                  분석 리포트 DOCX
                </button>
                <button
                  className="button"
                  type="button"
                  onClick={() => onRunReportAction?.("download_objection")}
                  disabled={!hasReport || appealDownloadBlocked}
                >
                  {isAuthenticated ? "이의신청서 DOCX" : "로그인 후 이의신청서 DOCX"}
                </button>
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
                <span className={reportTagClass}>{reportStatusLabel(reportStatus)}</span>
                <strong>{activeReportTypeLabel}</strong>
                <p>{reportSummary}</p>
              </div>
              <div className="inspector-section">
                <strong>세부 보기</strong>
                <p>중앙 문서에서 빠르게 보고, 필요한 경우 아래에서 섹션별로 다시 펼쳐봅니다.</p>
                <div className="inspector-mode-switch">
                  <button
                    className={selectedInspectorMode === "overview" ? "button active" : "button"}
                    type="button"
                    onClick={() => setSelectedInspectorMode("overview")}
                    disabled={!hasReport}
                  >
                    개요
                  </button>
                  <button
                    className={selectedInspectorMode === "grounds" ? "button active" : "button"}
                    type="button"
                    onClick={() => setSelectedInspectorMode("grounds")}
                    disabled={!hasReport}
                  >
                    근거
                  </button>
                  <button
                    className={selectedInspectorMode === "actions" ? "button active" : "button"}
                    type="button"
                    onClick={() => setSelectedInspectorMode("actions")}
                    disabled={!hasReport}
                  >
                    다음 작업
                  </button>
                </div>
              </div>
              <div className="inspector-section">
                <span className={reportTagClass}>{reportStatusLabel(reportStatus)}</span>
                <strong>리포트 검토 상태</strong>
                <p>{supervisorState?.conversation_summary || "최신 상담 상태를 확인했습니다."}</p>
              </div>
              <div className="inspector-section">
                <strong>반영된 분석 결과</strong>
                <p>분석 항목 {analysisCards.length}건과 근거·누락 자료를 리포트에 반영했습니다.</p>
              </div>
              {faultRatioNode && <FaultRatioInsightPanel compact node={faultRatioNode} />}
              {lawGroundNode && <LawGroundInsightPanel compact node={lawGroundNode} />}
              {selectedInspectorMode !== "overview" && (
                <div className="inspector-section report-inspector-detail">
                  <span className="tag green">{inspectorDetail.label}</span>
                  <strong>{inspectorDetail.title}</strong>
                  <p>{inspectorDetail.summary}</p>
                  <div className="inspector-detail-list">
                    {inspectorDetail.sections.length > 0 ? (
                      inspectorDetail.sections.map((section) => (
                        <ReportSectionPreview compact detailLimit={4} key={`inspector-${section.title}`} section={section} />
                      ))
                    ) : (
                      <article className="report-empty-hint">
                        <strong>표시할 항목 없음</strong>
                        <p>현재 리포트 payload에 해당 섹션이 없습니다. 상담을 이어가면 항목을 다시 채울 수 있습니다.</p>
                      </article>
                    )}
                  </div>
                </div>
              )}
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
