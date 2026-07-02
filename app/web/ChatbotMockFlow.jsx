import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  buildAuthMeUrl,
  getJson,
  joinApiPath,
  postJson,
  toCanonicalApiBase,
} from "./apiClient.js";
import {
  buildAuthContext,
  buildDevGoogleProfile,
  clearStoredAuthSession,
  persistAuthSession,
  readStoredAuthToken,
  readStoredGoogleProfile,
} from "./authSession.js";

const MOCK_ATTACHMENTS = [
  {
    attachment_id: "att_0001",
    type: "image",
    purpose: "supporting_evidence",
    original_filename: "uploaded-evidence.jpg",
    privacy_risk: true,
  },
];

const STATUS_LABELS = {
  blocked: "대기",
  failed: "실패",
  partial: "추가 확인",
  pending: "분석 중",
  ready: "준비",
  running: "실행 중",
  skipped: "생략",
  success: "완료",
};

const AUTH_STATE_LABELS = {
  anonymous: "익명",
  authenticated: "회원",
  guest: "비회원",
};

const AUTH_SESSION_CONTRACT_FIELDS = ["guest_id", "user_id", "auth_session_id", "chat_session_id"];

export default function ChatbotMockFlow({
  apiBase = "/api",
  authToken = "dev-mock-token",
  googleClientId = "",
}) {
  void AUTH_SESSION_CONTRACT_FIELDS;

  const [sessionId, setSessionId] = useState(null);
  const [guestSession, setGuestSession] = useState(null);
  const [authSubject, setAuthSubject] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [activeAuthToken, setActiveAuthToken] = useState(() => readStoredAuthToken());
  const [googleProfile, setGoogleProfile] = useState(() => readStoredGoogleProfile());
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState(null);
  const [tokenActionLoading, setTokenActionLoading] = useState(null);
  const [tokenLifecycleError, setTokenLifecycleError] = useState(null);
  const [question, setQuestion] = useState(
    "과태료 고지서를 받았습니다. 이의신청서를 만들 수 있을까요?"
  );
  const [mockStatus, setMockStatus] = useState("success");
  const [response, setResponse] = useState(null);
  const [report, setReport] = useState(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const googleButtonRef = useRef(null);

  const authApiBase = useMemo(() => toCanonicalApiBase(apiBase), [apiBase]);
  const guestId = authSubject?.subject?.guest_id || guestSession?.guest?.guest_id || null;
  const authSessionId = authSubject?.subject?.auth_session_id || null;
  const userId = authSubject?.subject?.user_id || authSubject?.user?.user_id || null;
  const authState = authSubject?.auth_state || guestSession?.auth_state || "anonymous";
  const progressStatus = response?.progress?.status || "pending";
  const analysisSteps = response?.analysis_plan?.steps || [];
  const canRunReportAction = response?.report_links?.length > 0;

  const requestPayload = useMemo(
    () => ({
      session_id: sessionId,
      auth_context: buildAuthContext({ authState, guestId, authSessionId, sessionId, userId }),
      user_text: question,
      attachments: MOCK_ATTACHMENTS,
      mock_status: mockStatus,
    }),
    [authSessionId, authState, guestId, mockStatus, question, sessionId, userId]
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrapIdentity() {
      setAuthLoading(true);
      setAuthError(null);

      try {
        const guest = await postJson(joinApiPath(authApiBase, "auth/guest-session/"), {
          session_id: sessionId,
        });
        if (cancelled) {
          return;
        }

        setGuestSession(guest);

        let subject = null;
        try {
          subject = await getJson(buildAuthMeUrl(authApiBase, sessionId), {
            authToken: activeAuthToken || null,
            guestId: guest?.guest?.guest_id,
          });
        } catch (subjectError) {
          if (!activeAuthToken) {
            throw subjectError;
          }

          clearStoredAuthSession();
          setActiveAuthToken("");
          setGoogleProfile(null);
          subject = await getJson(buildAuthMeUrl(authApiBase, sessionId), {
            guestId: guest?.guest?.guest_id,
          });
        }
        if (cancelled) {
          return;
        }

        setAuthSubject(subject);
      } catch (error) {
        if (!cancelled) {
          setAuthError(error.message);
        }
      } finally {
        if (!cancelled) {
          setAuthLoading(false);
        }
      }
    }

    bootstrapIdentity();

    return () => {
      cancelled = true;
    };
  }, [authApiBase, activeAuthToken, sessionId]);

  const completeGoogleLogin = useCallback(
    async (googlePayload) => {
      setLoginLoading(true);
      setLoginError(null);
      setTokenLifecycleError(null);

      try {
        const payload = {
          provider: "google",
          guest_id: guestId,
          session_id: sessionId,
          ...googlePayload,
        };
        const result = await postJson(joinApiPath(authApiBase, "auth/login/"), payload);
        const nextToken = result?.access_token;
        if (!nextToken) {
          throw new Error("Google login did not return an access token.");
        }

        setActiveAuthToken(nextToken);
        setGoogleProfile(result?.user || null);
        persistAuthSession({ accessToken: nextToken, googleProfile: result?.user || null });
        setGuestSession((current) => ({
          ...(current || {}),
          auth_state: result.auth_state,
          guest: result.guest || current?.guest || null,
          subject: result.subject,
          session_binding: result.session_binding,
        }));
        setAuthSubject(result);

        const verifiedSubject = await getJson(buildAuthMeUrl(authApiBase, sessionId), {
          authToken: nextToken,
          guestId: result?.subject?.guest_id || guestId,
          authSessionId: result?.subject?.auth_session_id,
        });
        setAuthSubject(verifiedSubject);
        setAuthError(null);
        return verifiedSubject;
      } catch (error) {
        setLoginError(error.message);
        throw error;
      } finally {
        setLoginLoading(false);
      }
    },
    [authApiBase, guestId, sessionId]
  );

  const handleGoogleCredentialResponse = useCallback(
    async (credentialResponse) => {
      await completeGoogleLogin({
        credential: credentialResponse?.credential,
      });
    },
    [completeGoogleLogin]
  );

  useEffect(() => {
    if (
      !googleClientId
      || !googleButtonRef.current
      || typeof window === "undefined"
      || !window.google?.accounts?.id
    ) {
      return;
    }

    window.google.accounts.id.initialize({
      client_id: googleClientId,
      callback: handleGoogleCredentialResponse,
    });
    window.google.accounts.id.renderButton(googleButtonRef.current, {
      size: "large",
      text: "continue_with",
      theme: "outline",
    });
  }, [googleClientId, handleGoogleCredentialResponse]);

  async function startDevGoogleLogin() {
    const profile = buildDevGoogleProfile({ guestId });
    await completeGoogleLogin(profile);
  }

  async function refreshAccessToken() {
    if (!activeAuthToken) {
      setTokenLifecycleError("사용 가능한 앱 access token이 없습니다.");
      return null;
    }

    setTokenActionLoading("refresh");
    setTokenLifecycleError(null);

    try {
      const result = await postJson(
        joinApiPath(authApiBase, "auth/refresh/"),
        {
          guest_id: guestId,
          session_id: sessionId,
        },
        {
          authToken: activeAuthToken,
          guestId,
          authSessionId,
        }
      );
      const nextToken = result?.access_token;
      if (!nextToken) {
        throw new Error("Token refresh did not return an access token.");
      }

      setActiveAuthToken(nextToken);
      setGoogleProfile(result?.user || null);
      persistAuthSession({ accessToken: nextToken, googleProfile: result?.user || null });
      setGuestSession((current) => ({
        ...(current || {}),
        auth_state: result.auth_state,
        guest: result.guest || current?.guest || null,
        subject: result.subject,
        session_binding: result.session_binding,
      }));
      setAuthSubject(result);

      return await refreshAuthSubject({
        nextAuthToken: nextToken,
        nextGuestId: result?.subject?.guest_id || guestId,
        nextSessionId: sessionId,
      });
    } catch (error) {
      setTokenLifecycleError(error.message);
      return null;
    } finally {
      setTokenActionLoading(null);
    }
  }

  async function logout() {
    if (!activeAuthToken) {
      clearStoredAuthSession();
      setActiveAuthToken("");
      setGoogleProfile(null);
      await refreshAuthSubject({ nextAuthToken: null });
      return null;
    }

    setTokenActionLoading("logout");
    setTokenLifecycleError(null);

    try {
      const result = await postJson(
        joinApiPath(authApiBase, "auth/logout/"),
        {
          guest_id: guestId,
          session_id: sessionId,
        },
        {
          authToken: activeAuthToken,
          guestId,
          authSessionId,
        }
      );
      const nextGuestId = result?.subject?.guest_id || guestId;

      clearStoredAuthSession();
      setActiveAuthToken("");
      setGoogleProfile(null);
      setAuthSubject(result);

      const guest = await postJson(joinApiPath(authApiBase, "auth/guest-session/"), {
        guest_id: nextGuestId,
        session_id: sessionId,
      });
      setGuestSession(guest);

      return await refreshAuthSubject({
        nextAuthToken: null,
        nextGuestId: guest?.guest?.guest_id || nextGuestId,
        nextSessionId: sessionId,
      });
    } catch (error) {
      setTokenLifecycleError(error.message);
      return null;
    } finally {
      setTokenActionLoading(null);
    }
  }

  async function refreshAuthSubject({
    nextAuthToken = activeAuthToken,
    nextGuestId = guestId,
    nextSessionId = sessionId,
  } = {}) {
    const subject = await getJson(buildAuthMeUrl(authApiBase, nextSessionId), {
      authToken: nextAuthToken,
      guestId: nextGuestId,
    });
    setAuthSubject(subject);
    return subject;
  }

  async function refreshGuestSession(nextSessionId) {
    const guest = await postJson(joinApiPath(authApiBase, "auth/guest-session/"), {
      guest_id: guestId,
      session_id: nextSessionId,
    });
    setGuestSession(guest);

    const subject = await refreshAuthSubject({
      nextGuestId: guest?.guest?.guest_id,
      nextSessionId,
    });

    return { guest, subject };
  }

  async function ensureSession() {
    const activeSessionId = sessionId || `ses_mock_${Date.now()}`;
    if (!sessionId) {
      setSessionId(activeSessionId);
    }

    let activeGuestId = guestId;
    let activeAuthSessionId = authSessionId;
    let activeAuthState = authState;

    if (!activeGuestId || guestSession?.session_binding?.session_id !== activeSessionId) {
      try {
        const { guest, subject } = await refreshGuestSession(activeSessionId);
        activeGuestId = subject?.subject?.guest_id || guest?.guest?.guest_id || activeGuestId;
        activeAuthSessionId = subject?.subject?.auth_session_id || activeAuthSessionId;
        activeAuthState = subject?.auth_state || activeAuthState;
        setAuthError(null);
      } catch (error) {
        setAuthError(error.message);
      }
    }

    return {
      activeSessionId,
      activeGuestId,
      activeAuthSessionId,
      activeAuthState,
      activeUserId: authSubject?.subject?.user_id || authSubject?.user?.user_id || null,
    };
  }

  async function submitMockMessage() {
    setLoading(true);
    setReport(null);
    const { activeSessionId, activeGuestId, activeAuthSessionId, activeAuthState, activeUserId } =
      await ensureSession();
    const activeAuthContext = buildAuthContext({
      authState: activeAuthState,
      guestId: activeGuestId,
      authSessionId: activeAuthSessionId,
      sessionId: activeSessionId,
      userId: activeUserId,
    });
    const messagePayload = {
      ...requestPayload,
      session_id: activeSessionId,
      auth_context: activeAuthContext,
    };
    const fallbackResponse = buildFallbackResponse(messagePayload);

    try {
      const result = await postJson(
        joinApiPath(apiBase, "chat/messages/"),
        messagePayload,
        {
          authToken: activeAuthToken || authToken,
          guestId: activeGuestId,
          authSessionId: activeAuthSessionId,
        }
      );
      setResponse(result);
    } catch (_error) {
      setResponse(fallbackResponse);
    } finally {
      setLoading(false);
    }
  }

  async function runReportAction(action) {
    if (!response) {
      return;
    }
    const fallbackReport = {
      report_id: `rep_mock_${Date.now()}`,
      case_id: `case_mock_${Date.now()}`,
      status: action === "download" ? "downloaded" : "report_saved",
      download_url: action === "download" ? "/api/reports/mock/download" : null,
      limitations: ["프론트 fallback mock 결과입니다."],
    };

    try {
      const result = await postJson(
        joinApiPath(apiBase, "reports/"),
        {
          action,
          session_id: response.session_id,
          auth_context: buildAuthContext({
            authState,
            guestId,
            authSessionId,
            sessionId: response.session_id,
            userId,
          }),
        },
        {
          authToken: activeAuthToken || authToken,
          guestId,
          authSessionId,
        }
      );
      setReport(result);
    } catch (_error) {
      setReport(fallbackReport);
    }
  }

  const sessionStatusLabel = sessionId ? "상담 세션 연결됨" : "상담 전";
  const userStatusLabel =
    authState === "authenticated" ? "회원 상담" : guestId ? "비회원 상담" : "상담 준비";
  const dataStatusLabel = authState === "authenticated" ? "자료 분석 가능" : "텍스트 상담 가능";

  return (
    <main className="chatbot-mock">
      <section className="chatbot-mock__composer">
        <div className="section-heading">
          <span>상담 입력</span>
          <strong>교통 상담 작업대</strong>
        </div>
        <label htmlFor="mock-question">질문</label>
        <textarea
          id="mock-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={4}
        />

        <label htmlFor="mock-status">응답 상태</label>
        <select
          id="mock-status"
          value={mockStatus}
          onChange={(event) => setMockStatus(event.target.value)}
        >
          <option value="success">success</option>
          <option value="partial">partial</option>
          <option value="pending">pending</option>
          <option value="failed">failed</option>
        </select>

        <button type="button" onClick={submitMockMessage} disabled={loading}>
          {loading ? "요청 중" : "분석 요청"}
        </button>
      </section>

      <section className="chatbot-mock__identity" aria-live="polite">
        <div className="section-heading">
          <span>접속 상태</span>
          <strong>{authLoading ? "확인 중" : AUTH_STATE_LABELS[authState] || authState}</strong>
        </div>
        <dl>
          <div>
            <dt>상담 방식</dt>
            <dd>{userStatusLabel}</dd>
          </div>
          <div>
            <dt>자료 분석</dt>
            <dd>{dataStatusLabel}</dd>
          </div>
          <div>
            <dt>상담 상태</dt>
            <dd>{sessionStatusLabel}</dd>
          </div>
        </dl>
        <div className="chatbot-mock__login-actions">
          {googleClientId && <div ref={googleButtonRef} />}
          <button type="button" onClick={startDevGoogleLogin} disabled={loginLoading}>
            {loginLoading ? "Google 로그인 중" : "Google로 계속하기"}
          </button>
          {authState === "authenticated" && (
            <>
              <button
                type="button"
                onClick={refreshAccessToken}
                disabled={Boolean(tokenActionLoading)}
              >
                {tokenActionLoading === "refresh" ? "갱신 중" : "토큰 갱신"}
              </button>
              <button
                type="button"
                onClick={logout}
                disabled={Boolean(tokenActionLoading)}
              >
                {tokenActionLoading === "logout" ? "로그아웃 중" : "로그아웃"}
              </button>
            </>
          )}
        </div>
        {googleProfile && (
          <p>
            {googleProfile.display_name || "Google user"}{" "}
            {googleProfile.email ? `(${googleProfile.email})` : ""}
          </p>
        )}
        {authError && <p role="alert">{authError}</p>}
        {loginError && <p role="alert">{loginError}</p>}
        {tokenLifecycleError && <p role="alert">{tokenLifecycleError}</p>}
      </section>

      {response && (
        <section className="chatbot-mock__result" aria-live="polite">
          <div className={`chatbot-mock__progress is-${progressStatus}`}>
            <strong>{STATUS_LABELS[progressStatus] || progressStatus}</strong>
            <span>{response.progress?.message}</span>
          </div>

          <p>{response.assistant_message}</p>

          {analysisSteps.length > 0 && (
            <ol className="chatbot-mock__plan" aria-label="Supervisor analysis plan">
              {analysisSteps.map((step) => (
                <li className={`is-${step.status}`} key={`${step.order}-${step.node_code}`}>
                  <strong>{step.node_code}</strong>
                  <span>{STATUS_LABELS[step.status] || step.status}</span>
                </li>
              ))}
            </ol>
          )}

          {response.pending_questions?.map((item) => (
            <div className="chatbot-mock__question" key={item.field}>
              <strong>{item.field}</strong>
              <span>{item.question}</span>
            </div>
          ))}

          <div className="chatbot-mock__cards">
            {response.cards?.map((card) => (
              <article className={`chatbot-mock__card is-${card.status}`} key={card.title}>
                <span>{card.card_type}</span>
                <h3>{card.title}</h3>
                <p>{card.summary}</p>
              </article>
            ))}
          </div>

          <div className="chatbot-mock__actions">
            <button type="button" onClick={() => submitMockMessage()}>
              상담 다시 호출
            </button>
            <button type="button" onClick={() => runReportAction("save")} disabled={!canRunReportAction}>
              리포트 저장
            </button>
            <button
              type="button"
              onClick={() => runReportAction("download")}
              disabled={!canRunReportAction}
            >
              다운로드
            </button>
          </div>

          {response.limitations?.length > 0 && (
            <ul className="chatbot-mock__limitations">
              {response.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {report && (
        <section className="chatbot-mock__report">
          <strong>{report.status}</strong>
          <span>{report.report_id}</span>
          {report.download_url && <a href={report.download_url}>mock download</a>}
        </section>
      )}
    </main>
  );
}

function buildFallbackResponse(payload) {
  const status = payload.mock_status || "success";
  const common = {
    message_id: `msg_mock_${Date.now()}`,
    session_id: payload.session_id,
    auth_context: payload.auth_context,
    routing_intent: "objection_request",
    status,
    created_at: new Date().toISOString(),
  };

  if (status === "failed") {
    return {
      ...common,
      assistant_message: "현재 입력만으로는 분석 결과를 만들 수 없습니다.",
      progress: { status: "failed", message: "분석 가능한 입력을 찾지 못했습니다." },
      analysis_plan: buildFallbackAnalysisPlan({ status: "failed" }),
      cards: [],
      report_links: [],
      limitations: ["지원되는 형식의 고지서 이미지, PDF, 설명 텍스트를 다시 입력해 주세요."],
    };
  }

  if (status === "partial") {
    return {
      ...common,
      assistant_message: "일부 결과만 확인했습니다. 추가 정보가 필요합니다.",
      progress: { status: "partial", message: "필수 입력 보완이 필요합니다." },
      analysis_plan: buildFallbackAnalysisPlan({ status: "partial" }),
      pending_questions: [
        {
          field: "user_facts",
          question: "이의신청 사유와 당시 상황을 두세 문장으로 보완해 주세요.",
        },
      ],
      cards: [
        {
          card_type: "law_ground",
          title: "법령 근거 후보",
          status: "partial",
          summary: "위반 유형이 불명확해 semantic 검색 후보만 표시합니다.",
        },
      ],
      report_links: [],
      limitations: ["필수 입력이 부족해 리포트 초안 생성은 보류했습니다."],
    };
  }

  return {
    ...common,
    assistant_message: "고지서 내용과 관련 법령 근거 후보를 확인했습니다.",
    progress: {
      status: status === "pending" ? "pending" : "success",
      message: "분석 결과를 표시할 수 있습니다.",
    },
    analysis_plan: buildFallbackAnalysisPlan({ status }),
    cards: [
      {
        card_type: "fine_notice",
        title: "고지서 분석",
        status: "success",
        summary: "과태료 고지서로 추정되며 이의신청 기한 확인이 필요합니다.",
      },
      {
        card_type: "law_ground",
        title: "법령 근거 후보",
        status: "partial",
        summary: "도로교통법 관련 조항 후보가 있으나 최신성 확인이 필요합니다.",
      },
    ],
    report_links: [{ action: "save" }, { action: "download" }],
    limitations: ["프론트엔드 fallback mock 결과이며 실제 Agent 호출 결과가 아닙니다."],
  };
}

function buildFallbackAnalysisPlan({ status }) {
  const stepStatuses = {
    failed: ["failed", "skipped", "skipped", "skipped"],
    partial: ["success", "partial", "blocked", "blocked"],
    pending: ["running", "blocked", "blocked", "blocked"],
    success: ["success", "success", "success", "partial"],
  }[status] || ["success", "success", "success", "partial"];

  return {
    plan_id: `plan_mock_${Date.now()}`,
    routing_intent: "objection_request",
    steps: [
      "input_context_validation",
      "fine_notice_analysis",
      "law_ground_search",
      "objection_report_generation",
    ].map((nodeCode, index) => ({
      order: index + 1,
      node_code: nodeCode,
      status: stepStatuses[index],
    })),
  };
}
