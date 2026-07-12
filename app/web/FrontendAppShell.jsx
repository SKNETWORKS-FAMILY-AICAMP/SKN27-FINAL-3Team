import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { createFrontendApi } from "./apiClient.js";
import {
  buildAuthContext,
  buildGoogleLoginPayload,
  persistAuthSession,
  readStoredAuthSession,
  readStoredAuthToken,
} from "./authSession.js";

const ROUTES = [
  { id: "entry", label: "서비스 안내" },
  { id: "chatbot", label: "상담" },
  { id: "mypage", label: "내 사건" },
  { id: "history", label: "과거 이력" },
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
const DEMO_PERSONA_ID = "school_zone_fine_notice_parent";
const CONFIGURED_EXECUTION_MODE = ["sync", "async_worker", "mock"].includes(
  import.meta.env.VITE_AGENT_EXECUTION_MODE
)
  ? import.meta.env.VITE_AGENT_EXECUTION_MODE
  : "sync";
const ATTACHMENT_PURPOSES = [
  { value: "fine_notice", label: "고지서" },
  { value: "accident_scene", label: "사고 사진" },
  { value: "blackbox_video", label: "블랙박스" },
  { value: "insurance_record", label: "보험 접수" },
];

export default function FrontendAppShell({
  apiBase = "/api",
  authToken = "",
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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSavingConversation, setIsSavingConversation] = useState(false);
  const [attachmentPurpose, setAttachmentPurpose] = useState("fine_notice");
  const executionMode = CONFIGURED_EXECUTION_MODE;
  const [selectedUploadFile, setSelectedUploadFile] = useState(null);
  const [uploadInputResetKey, setUploadInputResetKey] = useState(0);
  const [registeredAttachments, setRegisteredAttachments] = useState([]);
  const [isRegisteringAttachment, setIsRegisteringAttachment] = useState(false);
  const [reportActionStatus, setReportActionStatus] = useState("");
  const [currentReport, setCurrentReport] = useState(null);
  const [pendingAuthAction, setPendingAuthAction] = useState(null);
  const [guestDetailedReportUsed, setGuestDetailedReportUsed] = useState(false);
  const [activeCaseId, setActiveCaseId] = useState("");
  const [caseWorkspace, setCaseWorkspace] = useState(null);
  const [isCreatingCase, setIsCreatingCase] = useState(false);

  const effectiveAuthToken = authSessionId ? activeAuthToken || authToken : "";
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
  const personaRun = analysisResponse?.persona_run || null;
  const assistantAnswer = analysisResponse?.assistant_message || "";
  const supervisorState = analysisResponse?.supervisor_state || null;
  const reportingPayload = analysisResponse?.reporting_payload || null;
  const supervisorExecution = analysisResponse?.supervisor_execution || null;
  const consultationState = analysisResponse?.consultation_state?.v2 || null;
  const caseType = detectCaseType({ analysisCards, analysisResponse, currentReport });

  async function bootstrapGuestSession(nextRoute = "chatbot") {
    setStatusMessage("로그인 없이 바로 상담을 시작할 수 있도록 임시 세션을 준비하고 있습니다.");
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
        setStatusMessage("자료 업로드를 위해 Google 로그인 후 현재 상담 세션에 이어서 연결합니다.");
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
        try {
          const scanResult = await api.processFileScan(
            {
              attachmentId: attachment.attachment_id,
              session_id: activeSession,
            },
            nextIdentity
          );
          attachment = scanResult?.attachment || attachment;
        } catch (_scanError) {
          attachment = {
            ...attachment,
            scan_status: attachment.scan_status || "scan_pending",
          };
        }
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

  async function runCurrentReportAction(action = "download") {
    const jobId = analysisResponse?.persistence?.job_id || analysisResponse?.supervisor_execution?.job_id || "";
    if (!analysisResponse || !jobId) {
      setReportActionStatus("리포트 action을 실행할 상담 결과가 아직 없습니다.");
      return;
    }
    setReportActionStatus(action === "download" ? "리포트 다운로드 metadata를 준비하고 있습니다." : "리포트를 저장하고 있습니다.");
    try {
      let activeSessionId = analysisResponse?.session_id || sessionId;
      let nextIdentity = identity;
      if (!authSessionId) {
        setPendingAuthAction({ type: `report_${action}`, jobId });
        setReportActionStatus("리포트 작업을 위해 Google 로그인 후 같은 상담 세션으로 이어갑니다.");
        const loginState = await loginAndBindCurrentSession({
          source: `report_${action}`,
          nextRoute: "chatbot",
        });
        activeSessionId = activeSessionId || loginState.sessionId;
        nextIdentity = loginState.identity;
        setPendingAuthAction(null);
      }
      const report = await api.runReportAction(
        {
          action,
          report_id: currentReport?.report_id || `rep_${jobId}`,
          job_id: jobId,
          session_id: activeSessionId,
          report_type: "general",
          title: reportingPayload?.title || "상담 분석 리포트",
          reporting_payload: reportingPayload,
        },
        nextIdentity
      );
      setCurrentReport(report);
      let downloadedFilename = "";
      if (action === "download" && report?.report_id) {
        downloadedFilename = await triggerReportDownload({
          reportId: report.report_id,
          sessionId: activeSessionId,
          requestIdentity: nextIdentity,
        });
      }
      setReportActionStatus(
        action === "download"
          ? `다운로드 완료: ${downloadedFilename || report.download_url || report.report_id}`
          : `리포트 저장 완료: ${report.report_id}`
      );
      if (nextIdentity.authSessionId) {
        await loadMyPageSummary({ identity: nextIdentity, sessionId: activeSessionId });
        await loadHistoryEvents({ identity: nextIdentity, sessionId: activeSessionId });
      }
      setActiveRoute("reporting");
    } catch (_error) {
      setPendingAuthAction(null);
      setReportActionStatus(`리포트 action 실행에 실패했습니다. ${_error?.message || ""}`.trim());
    }
  }

  async function triggerReportDownload({ reportId, sessionId: activeSessionId, requestIdentity }) {
    const file = await api.downloadReport({
      reportId,
      sessionId: activeSessionId,
      identity: requestIdentity,
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
    setStatusMessage("누락 자료를 추가할 수 있도록 상담 입력으로 이동했습니다. 고지서 원본, 현장 사진, 블랙박스 중 가진 자료를 선택해 주세요.");
    setActiveRoute("chatbot");
  }

  function prepareDraftRegeneration() {
    setQuestion("추가 자료를 반영해 이의신청서 초안과 제출 가이드라인을 다시 정리해줘");
    setStatusMessage("초안 재생성 요청 문구를 입력창에 준비했습니다. 추가 자료가 있으면 먼저 첨부한 뒤 전송해 주세요.");
    setActiveRoute("chatbot");
  }

  async function processQueuedWorkerResult(chatResult, requestIdentity) {
    const workItem = chatResult?.work_item || chatResult?.supervisor_execution?.work_item || null;
    if (chatResult?.execution_mode !== "async_worker" || !workItem?.work_item_id) {
      return chatResult;
    }
    if (!requestIdentity?.authToken) {
      logDeveloperDiagnostic("worker.status", { status: "queued", authenticated: false });
      return chatResult;
    }

    logDeveloperDiagnostic("worker.status", { status: "processing", authenticated: true });
    try {
      const workerResult = await api.processAgentWorkItems({ limit: 1 }, requestIdentity);
      const processedItem =
        (workerResult?.work_items || []).find((item) => item.work_item_id === workItem.work_item_id) ||
        workerResult?.work_items?.[0] ||
        {};
      const nextWorkItem = {
        ...workItem,
        status: processedItem.status || workItem.status,
        job_status: processedItem.job_status || workItem.job_status,
      };
      const enrichedResult = {
        ...chatResult,
        status: processedItem.job_status || chatResult.status,
        worker_result: workerResult,
        supervisor_execution: {
          ...(chatResult.supervisor_execution || {}),
          work_item: nextWorkItem,
          worker_result: {
            processed: workerResult?.processed || 0,
            status: processedItem.status || null,
            job_status: processedItem.job_status || null,
          },
        },
        work_item: nextWorkItem,
      };
      logDeveloperDiagnostic("worker.status", {
        jobStatus: processedItem.job_status || null,
        status: processedItem.status || "requested",
      });
      return enrichedResult;
    } catch (_error) {
      logDeveloperDiagnostic("worker.error", { message: _error?.message || "automatic processing failed" });
      return chatResult;
    }
  }

  async function pollQueuedWorkerResult(chatResult, requestIdentity) {
    const workItem = chatResult?.work_item || chatResult?.supervisor_execution?.work_item || null;
    if (chatResult?.execution_mode !== "async_worker" || !workItem?.work_item_id) {
      return chatResult;
    }
    if (!requestIdentity?.authToken) {
      logDeveloperDiagnostic("worker.status", { status: "queued", authenticated: false });
      return chatResult;
    }

    logDeveloperDiagnostic("worker.status", { status: "polling", authenticated: true });
    try {
      const jobDetailResult = await api.getAnalysisJobDetail({ jobId: workItem.job_id, identity: requestIdentity });
      const jobDetail = jobDetailResult?.job || {};
      const processedItem = jobDetail.work_item || {};
      const progressState = jobDetail.progress_state || processedItem.progress_state || {};
      const nextWorkItem = {
        ...workItem,
        status: processedItem.status || workItem.status,
        job_status: progressState.job_status || jobDetail.status || workItem.job_status,
        progress_state: progressState,
      };
      const enrichedResult = {
        ...chatResult,
        status: jobDetail.status || progressState.job_status || chatResult.status,
        job_detail: jobDetail,
        supervisor_execution: {
          ...(chatResult.supervisor_execution || {}),
          work_item: nextWorkItem,
          worker_poll: {
            contract_version: "worker_progress_polling.v1",
            status: processedItem.status || null,
            job_status: jobDetail.status || null,
            progress_state: progressState,
          },
        },
        work_item: nextWorkItem,
      };
      logDeveloperDiagnostic("worker.status", {
        jobStatus: jobDetail.status || null,
        status: processedItem.status || "waiting",
      });
      return enrichedResult;
    } catch (_error) {
      logDeveloperDiagnostic("worker.error", { message: _error?.message || "progress polling failed" });
      return chatResult;
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
          ...(shouldUseDemoPersona(trimmedQuestion) ? { persona_id: DEMO_PERSONA_ID } : {}),
        },
        submitIdentity
      );
      const workerResult = await pollQueuedWorkerResult(result, submitIdentity);
      logDeveloperDiagnostic("chat.result", buildDeveloperDiagnostic(workerResult));
      setChatMessages([
        ...conversationHistory,
        {
          role: "assistant",
          content: workerResult?.assistant_message || "상담 내용을 접수했습니다.",
          status: workerResult?.status || "partial",
          pending_questions: workerResult?.pending_questions || [],
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
          ? "상담 응답을 받았습니다. 이 상담은 로그인 계정에 연결됩니다."
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
      setStatusMessage("로그인 또는 저장 연결에 실패했습니다. 상담은 현재 임시 세션에서 계속 진행할 수 있습니다.");
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
      "이번 상담은 임시 세션으로만 계속 진행합니다. 저장하지 않으면 내 사건 이력에는 표시하지 않습니다."
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

  async function openSavedCase(item) {
    if (item?.case_id) {
      setStatusMessage("사건 워크스페이스를 불러오고 있습니다.");
      try {
        const workspace = await api.getCaseWorkspace({ caseId: item.case_id, sessionId, identity });
        setActiveCaseId(item.case_id);
        setCaseWorkspace(workspace);
        setActiveRoute("caseWorkspace");
        setStatusMessage("사건 워크스페이스를 열었습니다.");
        return;
      } catch (_workspaceError) {
        // Legacy mypage rows continue through the existing analysis-job restore path.
      }
    }
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

  async function createPreciseAnalysisCase() {
    if (!analysisResponse || !consultationState) {
      setStatusMessage("먼저 사고 상황을 상담 메시지로 알려 주세요.");
      return;
    }
    setIsCreatingCase(true);
    setStatusMessage("현재 상담을 정밀분석 사건으로 전환하고 있습니다.");
    try {
      let requestIdentity = identity;
      let activeSessionId = sessionId;
      if (!authSessionId) {
        const loginState = await loginAndBindCurrentSession({ source: "case_workspace_v2", nextRoute: "chatbot" });
        requestIdentity = loginState.identity;
        activeSessionId = loginState.sessionId;
      }
      const created = await api.createCase(
        {
          session_id: activeSessionId,
          case_type: "fault_ratio",
          title: submittedQuestion || "교통사고 과실 초기상담",
          consultation_state: { v2: consultationState },
          email_notification_enabled: false,
        },
        requestIdentity
      );
      const workspace = await api.getCaseWorkspace({
        caseId: created.case_id,
        sessionId: activeSessionId,
        identity: requestIdentity,
      });
      setActiveCaseId(created.case_id);
      setCaseWorkspace(workspace);
      setActiveRoute("caseWorkspace");
      setStatusMessage("사건을 만들었습니다. 사실 카드를 확인한 뒤 분석을 시작해 주세요.");
    } catch (_error) {
      setStatusMessage(`사건 전환에 실패했습니다. ${_error?.message || ""}`.trim());
    } finally {
      setIsCreatingCase(false);
    }
  }

  async function refreshCaseWorkspace() {
    if (!activeCaseId) return null;
    const workspace = await api.getCaseWorkspace({ caseId: activeCaseId, sessionId, identity });
    setCaseWorkspace(workspace);
    return workspace;
  }

  async function confirmWorkspaceFacts(factCards) {
    if (!activeCaseId) return;
    const facts = Object.fromEntries(
      (factCards || [])
        .filter((item) => item?.field && item?.value)
        .map((item) => [item.field, item.value])
    );
    await api.confirmCaseFacts(
      {
        caseId: activeCaseId,
        facts,
        sources: (factCards || []).filter((item) => item?.value).map((item) => ({
          field: item.field,
          source: item.source || item.classification,
        })),
        conflicts: (factCards || []).filter((item) => item?.classification === "conflict"),
        user_edit_history: [],
      },
      identity
    );
    await refreshCaseWorkspace();
    setStatusMessage("사실관계 버전을 확정했습니다.");
  }

  async function startWorkspaceAnalysis() {
    if (!activeCaseId) return;
    try {
      await api.startCaseAnalysis(
        { caseId: activeCaseId, idempotency_key: `${activeCaseId}-${Date.now()}` },
        identity
      );
      await refreshCaseWorkspace();
      setStatusMessage("정밀분석을 대기열에 등록했습니다.");
    } catch (_error) {
      setStatusMessage(`분석을 시작하지 못했습니다. ${_error?.message || ""}`.trim());
    }
  }

  return (
    <div className="app-shell" data-auth-state={authContext.auth_state}>
      {activeRoute === "entry" && (
      <header className="topbar">
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
            {ROUTES.map((route) => (
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
            <button className="button primary" onClick={() => setActiveRoute("chatbot")} type="button">
              상담 시작
            </button>
          </nav>
        </div>
      </header>
      )}

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
              analysisCards={analysisCards}
              attachmentPurpose={attachmentPurpose}
              assistantAnswer={assistantAnswer}
              authSessionId={authSessionId}
              chatMessages={chatMessages}
              currentReport={currentReport}
              consultationState={consultationState}
              isCreatingCase={isCreatingCase}
              onCreateCase={createPreciseAnalysisCase}
              onOpenCaseResult={(route) => setActiveRoute(route)}
              isRegisteringAttachment={isRegisteringAttachment}
              isSubmitting={isSubmitting}
              isSavingConversation={isSavingConversation}
              onKeepTemporary={keepConversationTemporary}
              onRegisterAttachment={registerAttachmentMetadata}
              onRunReportAction={runCurrentReportAction}
              onSaveConversation={saveConversationAfterLogin}
              onSubmit={submitServiceMessage}
              pendingAuthAction={pendingAuthAction}
              question={question}
              registeredAttachments={registeredAttachments}
              reportActionStatus={reportActionStatus}
              saveDecision={saveDecision}
              savePromptVisible={savePromptVisible}
              selectedUploadFile={selectedUploadFile}
              personaRun={personaRun}
              reportingPayload={reportingPayload}
              setAttachmentPurpose={setAttachmentPurpose}
              setQuestion={setQuestion}
              setSelectedUploadFile={setSelectedUploadFile}
              statusMessage={statusMessage}
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

          {activeRoute === "caseWorkspace" && (
            <CaseWorkspaceScreen
              key={activeCaseId || "case-workspace"}
              workspace={caseWorkspace}
              onBack={() => setActiveRoute("chatbot")}
              onConfirmFacts={confirmWorkspaceFacts}
              onRefresh={refreshCaseWorkspace}
              onStartAnalysis={startWorkspaceAnalysis}
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
              analysisCards={analysisCards}
              currentReport={currentReport}
              isAuthenticated={Boolean(authSessionId)}
              onOpenChat={() => setActiveRoute("chatbot")}
              onRefresh={async () => {
                await loadMyPageSummary();
                await loadHistoryEvents();
              }}
              onPrepareDraftRegeneration={prepareDraftRegeneration}
              onPrepareMissingEvidence={prepareMissingEvidenceUpload}
              onRunReportAction={runCurrentReportAction}
              reportActionStatus={reportActionStatus}
              reportingPayload={reportingPayload}
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

function EntryScreen({ onGuestStart, onOpenChat }) {
  return (
    <section className="entry-screen">
      <div className="entry-copy">
        <span className="eyebrow">로그인 후 바로 상담 시작</span>
        <h1>사고와 과태료 자료를 올리면 AI가 필요한 다음 행동을 정리합니다.</h1>
        <p className="lead">
          고지서, 사고 사진, 블랙박스 설명을 입력하면 과태료 이의제기 가능성, 과실비율 쟁점,
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
              <p>로그인 후 고지서, 현장 사진, 블랙박스 자료를 연결합니다.</p>
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
                    <p>고지서, 현장 사진, 블랙박스 자료를 분석 목적과 함께 제출합니다.</p>
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
                        {analysisCards.map((card) => (
                          <div className="result-card" key={`${card.card_type}-${card.title}`}>
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
            비회원 세션 만들기
          </button>
        </div>
        <p className="entry-note">
          저장을 선택하지 않으면 현재 상담은 임시 세션 기준으로만 유지하고, 마이페이지 이력으로 넘기지 않습니다.
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
              <p>로그인 화면으로 막지 않고 게스트 상담 세션을 먼저 엽니다.</p>
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

      <nav className="sidebar-mini-nav" aria-label="보조 화면">
        <button className={activeRoute === "mypage" ? "nav-item active" : "nav-item"} type="button" onClick={() => onNavigate("mypage")}>
          내 사건 전체
        </button>
        <button className={activeRoute === "reporting" ? "nav-item active" : "nav-item"} type="button" onClick={() => onNavigate("reporting")}>
          리포트
        </button>
      </nav>

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
  assistantAnswer,
  authSessionId,
  chatMessages,
  consultationState,
  currentReport,
  isCreatingCase,
  onOpenCaseResult,
  onCreateCase,
  isRegisteringAttachment,
  isSavingConversation,
  isSubmitting,
  onKeepTemporary,
  onRegisterAttachment,
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
  personaRun,
  reportingPayload,
  setAttachmentPurpose,
  setQuestion,
  setSelectedUploadFile,
  statusMessage,
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
          { role: "assistant", content: assistantAnswer || "상담 내용을 기준으로 확인 가능한 항목을 정리했습니다." },
        ]
      : [];
  const hasConversation = visibleMessages.length > 0;
  const latestAssistantIndex = latestMessageIndex(visibleMessages, "assistant");
  const isAuthenticated = Boolean(authSessionId);
  const uploadButtonLabel = isRegisteringAttachment
    ? "등록 중"
    : selectedUploadFile
      ? isAuthenticated
        ? "파일 업로드"
        : "Google 로그인 후 업로드"
      : "파일 선택 필요";
  const quickQuestions = [
    "과태료 고지서를 받았는데 어떻게 해야 하는지 봐줘",
    "6월 24일 오후 3시 초등학교 앞에서 아이가 아파 잠깐 정차했고 블랙박스가 있어",
    "신호 없는 교차로에서 나는 직진, 상대는 우측 진입 중 사고가 났어",
    "블랙박스 원본과 보험사 접수 내역이 있어",
  ];
  const [isReportingExpanded, setIsReportingExpanded] = useState(false);

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>AI 교통 상담</h2>
          <p>로그인 없이 먼저 이야기하고, 저장이나 정밀 분석이 필요해질 때 계정을 연결합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onKeepTemporary}>
            이번 세션만 유지
          </button>
          <button className="button primary" type="button" onClick={onSaveConversation} disabled={isSavingConversation}>
            {isSavingConversation ? "연결 중" : "Google 로그인 후 저장"}
          </button>
        </div>
      </div>

      <section className="chat-attachment-bar" aria-label="상담 자료 첨부">
        <div className="attachment-tools">
          <label>
            <span>첨부 목적</span>
            <select value={attachmentPurpose} onChange={(event) => setAttachmentPurpose(event.target.value)}>
              {ATTACHMENT_PURPOSES.map((item) => (
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
              accept="image/*,application/pdf,video/*"
              type="file"
              onChange={(event) => setSelectedUploadFile(event.target.files?.[0] || null)}
            />
          </label>
          <button
            className="button"
            type="button"
            onClick={onRegisterAttachment}
            disabled={isRegisteringAttachment || !selectedUploadFile}
          >
            {uploadButtonLabel}
          </button>
          <span className="tag">자료 {registeredAttachments.length}건</span>
        </div>
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
                ? "저장 선택 전까지는 임시 세션 상담으로 다룹니다."
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
                        {!isUser && (
                          <strong>
                            {personaRun
                              ? "예시 사건 기준으로 상담을 진행했습니다."
                              : supervisorState
                                ? "상담 내용을 분석에 필요한 정보로 정리했습니다."
                                : "상담 내용을 기준으로 확인 가능한 항목을 정리했습니다."}
                          </strong>
                        )}
                        <p>{message.content}</p>
                        {!isUser && isLatestAssistant && (
                          <>
                            {personaRun && <PersonaRunTimeline personaRun={personaRun} />}
                            {analysisCards.length > 0 && (
                              <div className="result-cards">
                                {analysisCards.map((card) => (
                                  <div className="result-card" key={`${card.card_type}-${card.title}`}>
                                    <span className={card.status === "success" ? "tag green" : "tag amber"}>
                                      {card.card_type}
                                    </span>
                                    <strong>{card.title}</strong>
                                    <p>{card.summary}</p>
                                    {caseResultRoute(card) && (
                                      <div className="result-card-actions">
                                        <button
                                          className="button primary small"
                                          type="button"
                                          onClick={() => onOpenCaseResult(caseResultRoute(card))}
                                        >
                                          결과 화면 열기
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                            {consultationState?.schema_version === "consultation_state.v2" && (
                              <AdaptiveIntakePanel
                                consultationState={consultationState}
                                isCreatingCase={isCreatingCase}
                                onCreateCase={onCreateCase}
                              />
                            )}
                            {(supervisorState || reportingPayload || analysisCards.length > 0) && (
                              <details
                                className="reporting-disclosure"
                                open={isReportingExpanded}
                                onToggle={(event) => setIsReportingExpanded(event.currentTarget.open)}
                              >
                                <summary className="reporting-disclosure__summary">
                                  <span className="reporting-disclosure__title">
                                    <span className="reporting-disclosure__icon" aria-hidden="true">↗</span>
                                    <span>
                                      <strong>분석·리포팅 보기</strong>
                                      <small>핵심 답변은 위에 두고, 근거와 저장 작업은 필요할 때 확인하세요.</small>
                                    </span>
                                  </span>
                                  <span className="reporting-disclosure__action">{isReportingExpanded ? "접기" : "펼쳐보기"}</span>
                                </summary>
                                <div className="reporting-disclosure__body">
                                  {supervisorState && (
                                    <AnalysisProgressPanel
                                      analysisCards={analysisCards}
                                      reportingPayload={reportingPayload}
                                      supervisorState={supervisorState}
                                    />
                                  )}
                                  {reportingPayload && <ReportingPreviewPanel reportingPayload={reportingPayload} />}
                                  {(reportingPayload || analysisCards.length > 0) && (
                                    <ReportActionPanel
                                      currentReport={currentReport}
                                      isAuthenticated={Boolean(authSessionId)}
                                      onRunReportAction={onRunReportAction}
                                      reportActionStatus={reportActionStatus}
                                    />
                                  )}
                                </div>
                              </details>
                            )}
                          </>
                        )}
                      </div>
                    </article>
                  );
                })}
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
              <strong>이번 상담은 임시 세션으로 유지합니다.</strong>
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
              <div className="chat-input__context">
                <div>
                  <span>지금 필요한 건 완벽한 문장이 아니에요</span>
                  <strong>사고·고지서 상황을 아는 만큼만 적어주세요</strong>
                </div>
                <small>장소 · 시간 · 상대방 행동 · 받은 안내 내용을 떠오르는 대로 적으면 됩니다.</small>
              </div>
              <div className="attachment-strip">
                <span>자료 업로드와 정밀 분석은 상담 중 필요한 시점에 로그인 후 진행합니다.</span>
              </div>
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

function AdaptiveIntakePanel({ consultationState, isCreatingCase, onCreateCase }) {
  const riskGate = consultationState?.risk_gate || {};
  const readiness = consultationState?.readiness || {};
  const factCards = Array.isArray(consultationState?.fact_cards) ? consultationState.fact_cards : [];
  const nextQuestions = Array.isArray(consultationState?.next_questions) ? consultationState.next_questions : [];
  const isHighRisk = riskGate.decision === "high_risk_handoff";

  return (
    <section className="adaptive-intake" aria-label="선택적 핵심 입력">
      <div className="adaptive-intake__head">
        <div>
          <span className="eyebrow">선택적 핵심 입력</span>
          <strong>{isHighRisk ? "고위험 사건 안내가 먼저 필요합니다" : "확인된 사실과 부족한 항목"}</strong>
        </div>
        <span className={isHighRisk ? "tag red" : readiness.fault_range_allowed ? "tag green" : "tag amber"}>
          자료 충족도 {readiness.completed_count || 0}/{readiness.required_count || 4}
        </span>
      </div>
      {riskGate.immediate_actions?.length > 0 && (
        <ul className="adaptive-intake__actions">
          {riskGate.immediate_actions.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
      <div className="fact-card-grid">
        {factCards.slice(0, 6).map((item) => (
          <article className={`fact-card is-${item.classification || "unconfirmed"}`} key={item.field}>
            <span>{factClassificationLabel(item.classification)}</span>
            <strong>{item.label}</strong>
            <p>{item.value || "아직 확인되지 않았습니다."}</p>
          </article>
        ))}
      </div>
      {nextQuestions.length > 0 && !isHighRisk && (
        <div className="adaptive-question-list">
          <strong>다음으로 확인할 내용</strong>
          {nextQuestions.map((item) => <p key={item.field}>{item.question}</p>)}
        </div>
      )}
      {consultationState.intent === "fault_ratio" && (
        <div className="adaptive-intake__footer">
          <p>
            {isHighRisk
              ? "과실 범위 대신 증거 보존과 전문가 전달용 상담자료를 준비합니다."
              : readiness.fault_range_allowed
                ? "핵심 4요소가 확인되었습니다. 사실을 직접 확인한 뒤 정밀분석을 시작할 수 있습니다."
                : "부족한 항목을 계속 대화로 보완할 수 있으며, 현재 상태로도 부분 상담을 저장할 수 있습니다."}
          </p>
          <button className="button primary" type="button" onClick={onCreateCase} disabled={isCreatingCase}>
            {isCreatingCase ? "사건 만드는 중" : isHighRisk ? "전문가 상담자료 준비" : "정밀분석으로 전환"}
          </button>
        </div>
      )}
    </section>
  );
}

function CaseWorkspaceScreen({ workspace, onBack, onConfirmFacts, onRefresh, onStartAnalysis }) {
  const initialCards = Array.isArray(workspace?.fact_cards) ? workspace.fact_cards : [];
  const [factCards, setFactCards] = useState(initialCards);
  const summary = workspace?.summary || {};
  const caseInfo = workspace?.case || {};
  const confirmedFacts = workspace?.confirmed_facts || null;
  const readiness = summary.evidence_readiness || {};
  const faultAssessment = workspace?.fault_assessment || {};
  const externalEvidence = Array.isArray(workspace?.external_evidence) ? workspace.external_evidence : [];
  const missingMaterials = Array.isArray(workspace?.missing_materials) ? workspace.missing_materials : [];
  const reports = Array.isArray(workspace?.reports) ? workspace.reports : [];
  const stages = ["자료 확인", "장면 분석", "사례·근거 확인", "요약서 준비"];

  useEffect(() => {
    setFactCards(initialCards);
  }, [workspace?.case?.updated_at]);

  if (!workspace) {
    return (
      <section className="screen case-workspace-screen">
        <div className="empty-panel"><strong>사건 워크스페이스를 불러오는 중입니다.</strong></div>
      </section>
    );
  }

  return (
    <section className="screen case-workspace-screen">
      <div className="screen-header">
        <div className="screen-title">
          <span className="eyebrow">AI 교통분쟁 초기상담</span>
          <h2>{caseInfo.title || "사고 직후 과실 초기상담"}</h2>
          <p>확인된 사실, 장면 근거, 과실 변동 요인과 웹 요약서를 한곳에서 관리합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button" onClick={onBack}>상담으로 돌아가기</button>
          <button className="button" type="button" onClick={onRefresh}>상태 새로고침</button>
          <button className="button primary" type="button" onClick={onStartAnalysis} disabled={!confirmedFacts}>
            정밀분석 시작
          </button>
        </div>
      </div>

      <div className="workspace-summary-grid">
        <WorkspaceSummaryCard label="즉시 행동" value={`${summary.immediate_actions?.length || 0}건`} detail={summary.immediate_actions?.[0] || "안전과 증거 보존을 먼저 확인하세요."} />
        <WorkspaceSummaryCard label="현재 판단" value={summary.current_assessment?.label || "분석 전"} detail={summary.current_assessment?.reason || "확정 과실 판단이 아닙니다."} />
        <WorkspaceSummaryCard label="자료 충족도" value={`${readiness.completed_count || 0}/${readiness.required_count || 4}`} detail={readiness.fault_range_allowed ? "범위 분석 가능" : "핵심 사실 보완 필요"} />
        <WorkspaceSummaryCard label="분석 상태" value={summary.analysis_status?.stage || "자료 확인"} detail={summary.analysis_status?.message || caseStatusLabel(caseInfo.status)} />
      </div>

      <div className="workspace-stage-bar" aria-label="분석 단계">
        {stages.map((stage) => (
          <span className={stage === summary.analysis_status?.stage ? "active" : ""} key={stage}>{stage}</span>
        ))}
      </div>

      <div className="case-workspace-grid">
        <article className="workspace-panel fact-confirmation-panel">
          <div className="panel-head">
            <div><span className="eyebrow">confirmed_facts.v1</span><strong>사실관계 확인</strong></div>
            <span className={confirmedFacts ? "tag green" : "tag amber"}>{confirmedFacts ? `v${confirmedFacts.version_no} 확정` : "사용자 확인 필요"}</span>
          </div>
          <div className="fact-card-grid">
            {factCards.map((item, index) => (
              <label className={`fact-card editable is-${item.classification || "unconfirmed"}`} key={item.field || index}>
                <span>{factClassificationLabel(item.classification)}</span>
                <strong>{item.label || item.field}</strong>
                <textarea
                  value={item.value || ""}
                  placeholder="확인한 사실을 입력해 주세요."
                  onChange={(event) => setFactCards((cards) => cards.map((card, cardIndex) =>
                    cardIndex === index ? { ...card, value: event.target.value, classification: "user_statement" } : card
                  ))}
                />
              </label>
            ))}
          </div>
          <button className="button primary" type="button" onClick={() => onConfirmFacts(factCards)}>
            사실 카드 수정·확정
          </button>
        </article>

        <article className="workspace-panel location-panel">
          <div className="panel-head"><div><span className="eyebrow">Leaflet + VWorld</span><strong>사고 위치 확인</strong></div></div>
          <VWorldMap location={caseInfo.location} />
          <p>{caseInfo.location?.address || "주소 후보와 좌표를 확인한 뒤 저장하는 영역입니다."}</p>
        </article>

        <article className="workspace-panel annotated-frame-panel">
          <div className="panel-head"><strong>주석 프레임</strong><span className="tag">최대 3개</span></div>
          <div className="annotated-frame-grid">
            {(workspace.annotated_frames || []).length > 0
              ? workspace.annotated_frames.map((item) => <div key={item.artifact_id}><strong>{item.artifact_type}</strong><p>{item.source_timestamp_ms || 0}ms</p></div>)
              : <div className="empty-panel"><strong>확정된 주석 프레임이 없습니다.</strong><p>자료가 있으면 Vision 분석 후 표시됩니다.</p></div>}
          </div>
        </article>

        <article className="workspace-panel accident-diagram-panel">
          <div className="panel-head"><strong>SVG 사고 도식</strong><span className="tag green">데이터 기반</span></div>
          <div className="accident-svg" dangerouslySetInnerHTML={{ __html: workspace.accident_diagram?.svg || "" }} />
          <p>생성형 사고 이미지가 아니라 확정 사실을 좌표와 화살표로 표현합니다.</p>
        </article>

        <article className="workspace-panel fault-assessment-panel">
          <div className="panel-head"><strong>과실 범위·변동 요인</strong><span className="tag">fault_assessment.v2</span></div>
          <strong className="workspace-big-value">
            {faultAssessment.fault_range?.display || "수치 표시 전"}
          </strong>
          <p>{faultAssessment.unavailable_reason || "범위는 확정 판단이 아니며 자료와 근거에 따라 달라집니다."}</p>
          <ul>{(faultAssessment.change_factors || []).map((item) => <li key={item}>{item}</li>)}</ul>
        </article>

        <article className="workspace-panel evidence-panel">
          <div className="panel-head"><strong>외부 근거</strong><span className="tag">출처 필수</span></div>
          {externalEvidence.length > 0 ? externalEvidence.map((item, index) => (
            <div className="evidence-item" key={`${item.provider}-${index}`}>
              <strong>{item.provider}</strong>
              {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">원문 출처</a> : <span>출처 확인 필요</span>}
              <p>{item.limitation}</p>
            </div>
          )) : <div className="empty-panel"><strong>아직 연결된 외부 근거가 없습니다.</strong><p>사례·근거 확인 단계에서 갱신됩니다.</p></div>}
        </article>

        <article className="workspace-panel missing-panel">
          <div className="panel-head"><strong>부족 자료</strong><span className="tag amber">{missingMaterials.length}건</span></div>
          {missingMaterials.length > 0
            ? <ul>{missingMaterials.map((item) => <li key={item.field}>{item.label}</li>)}</ul>
            : <p>핵심 4요소가 모두 확인되었습니다.</p>}
        </article>

        <article className="workspace-panel report-list-panel">
          <div className="panel-head"><div><span className="eyebrow">웹 자동 생성 · PDF 요청 시 생성</span><strong>초기상담 요약서</strong></div></div>
          {reports.length > 0 ? reports.map((report) => (
            <div className="report-version-row" key={report.report_id}>
              <div><strong>v{report.version_no} · {report.title}</strong><p>{report.content_summary}</p></div>
              <span className="tag">{report.status}</span>
            </div>
          )) : <div className="empty-panel"><strong>분석 완료 후 웹 요약서가 자동 생성됩니다.</strong><p>PDF는 사용자가 요청할 때 같은 버전으로 생성합니다.</p></div>}
        </article>
      </div>
    </section>
  );
}

function VWorldMap({ location = {} }) {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const lat = Number(location?.latitude || location?.lat);
  const lng = Number(location?.longitude || location?.lng);
  const apiKey = import.meta.env.VITE_VWORLD_API_KEY || "";

  useEffect(() => {
    if (!mapRef.current || !Number.isFinite(lat) || !Number.isFinite(lng) || !apiKey) return undefined;
    if (mapInstanceRef.current) mapInstanceRef.current.remove();
    const map = L.map(mapRef.current, { zoomControl: true }).setView([lat, lng], 17);
    L.tileLayer(`https://api.vworld.kr/req/wmts/1.0.0/${apiKey}/Base/{z}/{y}/{x}.png`, {
      attribution: "© VWorld",
      maxZoom: 19,
    }).addTo(map);
    L.marker([lat, lng]).addTo(map).bindPopup("사용자가 확인한 사고 위치").openPopup();
    mapInstanceRef.current = map;
    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, [apiKey, lat, lng]);

  if (!Number.isFinite(lat) || !Number.isFinite(lng) || !apiKey) {
    return <div className="map-placeholder"><strong>지도 좌표 확인 대기</strong><p>VWorld 키와 사용자가 선택한 좌표가 준비되면 지도를 표시합니다.</p></div>;
  }
  return <div className="vworld-map" ref={mapRef} aria-label="사고 위치 지도" />;
}

function WorkspaceSummaryCard({ label, value, detail }) {
  return <article><span>{label}</span><strong>{value}</strong><p>{detail}</p></article>;
}

function factClassificationLabel(value) {
  return {
    user_statement: "사용자 진술",
    evidence_received: "자료에서 확인",
    evidence_confirmed: "자료에서 확인",
    unconfirmed: "미확인",
    conflict: "상충 정보",
  }[value] || "미확인";
}

function PersonaRunTimeline({ personaRun }) {
  const persona = personaRun?.persona || {};
  const snapshot = personaRun?.case_snapshot || {};
  const turns = Array.isArray(personaRun?.turns) ? personaRun.turns : [];
  const suggestions = Array.isArray(personaRun?.next_reply_suggestions) ? personaRun.next_reply_suggestions : [];

  return (
    <section className="persona-run" aria-label="데모 페르소나 상담 진행">
      <div className="persona-head">
        <div>
          <span className="eyebrow">Demo persona</span>
          <strong>{persona.name || "데모 사용자"} · {persona.case_type || "교통 상담"}</strong>
          <p>{persona.tone || "실제 상담 흐름 검증용 페르소나입니다."}</p>
        </div>
        <span className="tag green">{personaRun.stage || "ready"}</span>
      </div>

      <div className="persona-case-grid">
        <div>
          <span>고지 유형</span>
          <strong>{snapshot.notice_type || "-"}</strong>
        </div>
        <div>
          <span>금액</span>
          <strong>{snapshot.notice_amount || "-"}</strong>
        </div>
        <div>
          <span>장소</span>
          <strong>{snapshot.location || "-"}</strong>
        </div>
        <div>
          <span>핵심 주장</span>
          <strong>{snapshot.user_context || "-"}</strong>
        </div>
      </div>

      <div className="persona-turns">
        {turns.map((turn, index) => (
          <div className={turn.role === "assistant" ? "persona-turn ai" : "persona-turn user"} key={`${turn.role}-${index}`}>
            <span>{turn.speaker || (turn.role === "assistant" ? "AI" : "사용자")}</span>
            <p>{turn.message}</p>
          </div>
        ))}
      </div>

      {suggestions.length > 0 && (
        <div className="persona-suggestions">
          {suggestions.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function AnalysisProgressPanel({ analysisCards, reportingPayload, supervisorState }) {
  const facts = Array.isArray(supervisorState?.collected_facts) ? supervisorState.collected_facts : [];
  const questions = Array.isArray(supervisorState?.next_questions) ? supervisorState.next_questions : [];
  const hasAnalysis = analysisCards.length > 0;
  const hasReport = Boolean(reportingPayload);
  const steps = [
    { label: "입력 확인", description: "상담 내용과 첨부 자료를 확인했습니다.", status: "완료" },
    {
      label: "자료 분석",
      description: "사건 유형에 필요한 정보를 정리합니다.",
      status: hasAnalysis ? "완료" : "진행 중",
    },
    {
      label: "근거 확인",
      description: "관련 법령과 사례의 적용 조건을 확인합니다.",
      status: hasAnalysis ? "완료" : "대기",
    },
    {
      label: "리포트 준비",
      description: "확인된 결과와 다음 행동을 정리합니다.",
      status: hasReport ? "완료" : "대기",
    },
  ];

  return (
    <section className="analysis-progress" aria-label="분석 진행 상태">
      <div className="flow-panel-head">
        <div>
          <span className="eyebrow">분석 진행</span>
          <strong>{questions.length > 0 ? "추가 정보가 필요합니다" : "상담 내용을 순서대로 확인하고 있습니다"}</strong>
          <p>{supervisorState.conversation_summary}</p>
        </div>
        <span className={questions.length > 0 ? "tag amber" : "tag green"}>{questions.length > 0 ? "답변 필요" : "진행 중"}</span>
      </div>

      <div className="agent-plan">
        {steps.map((step, index) => (
          <div className="plan-step" key={step.label}>
            <span className="plan-index">{step.status === "완료" ? "✓" : index + 1}</span>
            <div><strong>{step.label}</strong><p>{step.description}</p></div>
            <span className="plan-status">{step.status}</span>
          </div>
        ))}
      </div>

      {facts.length > 0 && (
        <div className="fact-grid">
          {facts.map((item) => (
            <div className="fact-item" key={item.field}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div className="question-list">
          <strong>추가로 알려주세요</strong>
          {questions.map((item) => (
            <p key={item.field}>{item.question}</p>
          ))}
        </div>
      )}
    </section>
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
    <article className={compact ? "fault-ratio-insight-panel compact" : "fault-ratio-insight-panel"}>
      <div className="fault-ratio-insight-head">
        <span className="tag">과실 쟁점</span>
        <strong>유사 사례와 제출 자료 검토</strong>
      </div>
      <div className="fault-ratio-insight-grid">
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
        <div className="fault-ratio-insight-section">
          <strong>참고한 유사 사례</strong>
          {similarCases.slice(0, compact ? 2 : 3).map((item, index) => (
            <p key={item.source_ref || item.source_reference || item.case_id || `similar-case-${index}`}>
              {compactValue(item)}
            </p>
          ))}
        </div>
      )}
      {recommendedEvidence.length > 0 && (
        <div className="fault-ratio-insight-section">
          <strong>추가하면 좋은 자료</strong>
          <p>{compactValue(recommendedEvidence)}</p>
        </div>
      )}
      {limitations.length > 0 && (
        <div className="fault-ratio-insight-section">
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

function ReportingPreviewPanel({ reportingPayload }) {
  const sections = Array.isArray(reportingPayload?.sections) ? reportingPayload.sections : [];

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
      <div className="report-section-list">
        {sections.map((section) => (
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

function ReportActionPanel({ currentReport, isAuthenticated, onRunReportAction, reportActionStatus }) {
  const reportQuality =
    currentReport?.persistence?.report_quality ||
    currentReport?.report_quality ||
    currentReport?.metadata?.report_quality ||
    null;
  const hasReportQuality = Boolean(reportQuality);
  const reportLimitations = Array.isArray(reportQuality?.limitations) ? reportQuality.limitations.slice(0, 3) : [];
  const reportQualityTitle = reportQuality?.partial_report ? "일부 자료가 부족한 리포트" : "검토 준비가 완료된 리포트";
  const helperText = isAuthenticated
    ? reportActionStatus || "상담 결과를 reports metadata로 저장하거나 다운로드 경계를 확인할 수 있습니다."
    : reportActionStatus || "리포트 저장과 다운로드는 Google 로그인 후 사용할 수 있습니다.";

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
        <button className="button primary" type="button" onClick={() => onRunReportAction("download")}>
          {isAuthenticated ? "다운로드" : "로그인 후 다운로드"}
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
          <MetricCard label="저장 리포트" value={`${savedReports}건`} detail="PDF 생성 가능" />
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
    event?.metadata?.mock_scenario,
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
      summary: "법령·판례 근거, 이의제기 판단, 필요 증거, 예상 결과를 한 번에 확인합니다.",
      sections: selectedSections,
    };
  }
  return {
    label: "리포트",
    title: "리포트 상세",
    summary: "선택한 리포트 섹션을 확인합니다.",
    sections: selectedSections,
  };
}

function reportSectionsForInspector(sections, mode) {
  if (!Array.isArray(sections) || mode === "overview") {
    return [];
  }
  if (mode === "grounds") {
    return sections.filter((section) =>
      /근거|법령|판례|증거|이의제기|예상 결과|가이드라인/.test(String(section?.title || ""))
    );
  }
  return sections;
}

function CaseResultScreen({
  analysisCards = [],
  caseType = "fine",
  currentReport = null,
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
  const sections = Array.isArray(reportingPayload?.sections) ? reportingPayload.sections : [];
  const nodeResults = Array.isArray(supervisorExecution?.node_results) ? supervisorExecution.node_results : [];
  const faultRatioNode = nodeResults.find((node) => node?.node_code === "text_ml_case_search");
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
        ["추가 증거 요청", "블랙박스 원본과 사고 직후 사진을 보완합니다."],
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

              {analysisCards.length > 0 && (
                <div className="case-result-card-list">
                  {analysisCards.slice(0, 4).map((card) => (
                    <article className="case-result-card" key={`${card.card_type}-${card.title}`}>
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
                <button className="button full" type="button" onClick={() => onRunReportAction?.("download")} disabled={!currentReport && !reportingPayload}>
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

function ReportingScreen({
  analysisCards = [],
  currentReport = null,
  isAuthenticated = false,
  onOpenChat,
  onPrepareDraftRegeneration,
  onPrepareMissingEvidence,
  onRefresh,
  onRunReportAction,
  reportActionStatus = "",
  reportingPayload = null,
  supervisorExecution = null,
  supervisorState = null,
}) {
  const hasReport = Boolean(reportingPayload || analysisCards.length || supervisorExecution || currentReport);
  const sections = Array.isArray(reportingPayload?.sections) ? reportingPayload.sections : [];
  const nodeResults = Array.isArray(supervisorExecution?.node_results) ? supervisorExecution.node_results : [];
  const faultRatioNode = nodeResults.find((node) => node?.node_code === "text_ml_case_search");
  const reportPersistence = currentReport?.persistence || {};
  const reportMetadata = currentReport?.metadata || {};
  const reportStatus = reportingPayload?.stage || currentReport?.status || reportPersistence.status || "draft";
  const reportTitle = reportingPayload?.title || reportMetadata.title || "상담 분석 리포트";
  const reportSummary =
    reportingPayload?.summary ||
    (reportMetadata.case_id
      ? `내 사건 ${reportMetadata.case_id}에 저장된 리포트입니다.`
      : "최신 상담 결과를 리포팅 화면에 연결했습니다.");
  const reportTagClass = currentReport || reportStatus === "agent_execution_ready" ? "tag green" : "tag amber";
  const [selectedInspectorMode, setSelectedInspectorMode] = useState("overview");
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
            <span className="tag">{hasReport ? "1건" : "0건"}</span>
          </div>
          {hasReport ? (
            <div className="report-list-card">
              <span className={reportTagClass}>
                {reportStatusLabel(reportStatus)}
              </span>
              <strong>{reportTitle}</strong>
              <p>{reportSummary}</p>
              {currentReport && (
                <p>
                  저장 리포트: {currentReport.report_id}
                  {reportPersistence.status ? ` · ${reportStatusLabel(reportPersistence.status)}` : ""}
                </p>
              )}
              {reportActionStatus && <p>{reportActionStatus}</p>}
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
              <span className="eyebrow">리포트 미리보기</span>
              <h3>{reportTitle}</h3>
              <p>{reportSummary}</p>
              <div className="report-section-list">
                {sections.map((section) => (
                  <article key={section.title}>
                    <strong>{section.title}</strong>
                    {(section.items || []).map((item, index) => (
                      <p key={`${section.title}-${index}`}>{compactValue(item)}</p>
                    ))}
                  </article>
                ))}
                {sections.length === 0 && currentReport && (
                  <article>
                    <strong>저장 리포트</strong>
                    <p>
                      리포트 ID {currentReport.report_id}
                      {reportMetadata.updated_at ? ` · 최근 작업 ${reportMetadata.updated_at}` : ""}
                    </p>
                  </article>
                )}
              </div>
              {analysisCards.length > 0 && (
                <div className="result-cards">
                  {analysisCards.map((card) => (
                    <div className="result-card" key={`${card.card_type}-${card.title}`}>
                      <span className={card.status === "success" ? "tag green" : "tag amber"}>{card.card_type}</span>
                      <strong>{card.title}</strong>
                      <p>{card.summary}</p>
                    </div>
                  ))}
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

        <aside className="report-inspector" aria-label="근거와 작업">
          <div className="panel-head compact">
            <strong>근거·작업</strong>
          </div>
          {hasReport ? (
            <>
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
              {selectedInspectorMode !== "overview" && (
                <div className="inspector-section report-inspector-detail">
                  <span className="tag green">{inspectorDetail.label}</span>
                  <strong>{inspectorDetail.title}</strong>
                  <p>{inspectorDetail.summary}</p>
                  <div className="inspector-detail-list">
                    {inspectorDetail.sections.length > 0 ? (
                      inspectorDetail.sections.map((section) => (
                        <article key={`inspector-${section.title}`}>
                          <strong>{section.title}</strong>
                          {(section.items || []).slice(0, 5).map((item, index) => (
                            <p key={`${section.title}-${index}`}>{compactValue(item)}</p>
                          ))}
                        </article>
                      ))
                    ) : (
                      <article>
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
              <p>선택된 리포트의 제출 자료, 관련 기준, 후속 행동이 이곳에 표시됩니다.</p>
            </div>
          )}
          <div className="inspector-actions">
            <button
              className="button"
              type="button"
              onClick={() => onRunReportAction?.("download")}
              disabled={!hasReport}
            >
              {isAuthenticated ? "리포트 내려받기" : "로그인 후 내려받기"}
            </button>
            <button
              className="button"
              type="button"
              onClick={() => onRunReportAction?.("save")}
              disabled={!hasReport}
            >
              {isAuthenticated ? "리포트 저장" : "로그인 후 저장"}
            </button>
            <button
              className={selectedInspectorMode === "grounds" ? "button active" : "button"}
              type="button"
              onClick={() => setSelectedInspectorMode(selectedInspectorMode === "grounds" ? "overview" : "grounds")}
              disabled={!hasReport}
            >
              근거 보기
            </button>
            <button className="button" type="button" onClick={onPrepareMissingEvidence} disabled={!hasReport}>
              누락 자료 추가
            </button>
            <button className="button" type="button" onClick={onPrepareDraftRegeneration} disabled={!hasReport}>
              초안 재생성
            </button>
          </div>
        </aside>
      </div>
    </section>
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
  const assistantMessage =
    job.assistant_message ||
    job.assistant_message_payload?.answer ||
    job.progress_message ||
    "저장된 상담 결과를 불러왔습니다.";

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
    assistant_message:
      job.assistant_message ||
      job.assistant_message_payload?.answer ||
      job.progress_message ||
      "저장된 상담 결과를 불러왔습니다.",
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
      title: latestReport?.title || item?.title || job.assistant_message || "저장된 상담 리포트",
      updated_at: latestReport?.updated_at || job.updated_at || item?.updated_at || item?.last_event_at || "",
      report_count: job.report_count || item?.report_count || 1,
    },
  };
}

function normalizeAnalysisCards(cards) {
  return cards.map((card) => ({
    card_type: normalizeLabel(card.card_type),
    title: stripMockText(card.title || "분석 항목"),
    status: card.status || "partial",
    summary: stripMockText(card.summary || "추가 확인이 필요합니다."),
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
  return /사고|과실|교차로|블랙박스|보험/.test(source) ? "fault" : "fine";
}

function caseResultRoute(card = {}) {
  const source = [card.card_type, card.title, card.summary].filter(Boolean).join(" ");
  if (/사고|과실|교차로|블랙박스|보험/.test(source)) {
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
    persona_case_summary: "사례 요약",
    persona_next_questions: "추가 질문",
    persona_draft_outline: "초안 방향",
    persona_media_boundary: "사진/영상 한계",
    persona_law_summary: "법령 근거",
    persona_report_summary: "리포트",
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
    personaId: result?.persona_run?.persona?.persona_id || null,
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

function reportStatusLabel(value) {
  const labels = {
    agent_execution_ready: "리포트 준비 완료",
    downloaded: "내려받기 완료",
    draft: "작성 중",
    failed: "확인 필요",
    partial: "일부 자료 부족",
    report_saved: "저장 완료",
    saved: "저장 완료",
    success: "검토 완료",
  };
  return labels[String(value || "").toLowerCase()] || "검토 중";
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

function shouldUseDemoPersona(value) {
  const text = String(value || "");
  return ["페르소나", "데모", "샘플 상담", "끝까지 진행", "정민서"].some((keyword) => text.includes(keyword));
}

function stripMockText(value) {
  return String(value || "")
    .replace(/mock\s*/gi, "")
    .replace(/중간발표용\s*/g, "")
    .trim();
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  return String(value).slice(0, 10).replaceAll("-", ".");
}
