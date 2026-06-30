import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const MOCK_ATTACHMENTS = [
  {
    attachment_id: "att_0001",
    type: "image",
    purpose: "fine_notice",
    original_filename: "notice-sample.jpg",
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

const AUTH_TOKEN_STORAGE_KEY = "skn27.auth.accessToken";
const GOOGLE_PROFILE_STORAGE_KEY = "skn27.auth.googleProfile";

export default function ChatbotMockFlow({
  apiBase = "/api",
  authToken = "dev-mock-token",
  googleClientId = "",
}) {
  const [sessionId, setSessionId] = useState(null);
  const [guestSession, setGuestSession] = useState(null);
  const [authSubject, setAuthSubject] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [activeAuthToken, setActiveAuthToken] = useState(() => readStoredValue(AUTH_TOKEN_STORAGE_KEY) || "");
  const [googleProfile, setGoogleProfile] = useState(() => readStoredJson(GOOGLE_PROFILE_STORAGE_KEY));
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState(null);
  const [tokenActionLoading, setTokenActionLoading] = useState(null);
  const [tokenLifecycleError, setTokenLifecycleError] = useState(null);
  const [question, setQuestion] = useState("이 고지서로 이의신청서를 만들 수 있을까요?");
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

        const subject = await getJson(buildAuthMeUrl(authApiBase, sessionId), {
          authToken: activeAuthToken || null,
          guestId: guest?.guest?.guest_id,
        });
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
  }, [authApiBase, activeAuthToken]);

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
        writeStoredValue(AUTH_TOKEN_STORAGE_KEY, nextToken);
        setGoogleProfile(result?.user || null);
        writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, result?.user || null);
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
      setTokenLifecycleError("No app access token is available.");
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
      writeStoredValue(AUTH_TOKEN_STORAGE_KEY, nextToken);
      setGoogleProfile(result?.user || null);
      writeStoredJson(GOOGLE_PROFILE_STORAGE_KEY, result?.user || null);
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
      removeStoredValue(AUTH_TOKEN_STORAGE_KEY);
      removeStoredValue(GOOGLE_PROFILE_STORAGE_KEY);
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

      removeStoredValue(AUTH_TOKEN_STORAGE_KEY);
      removeStoredValue(GOOGLE_PROFILE_STORAGE_KEY);
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
    const { activeSessionId, activeGuestId, activeAuthSessionId, activeAuthState, activeUserId } = await ensureSession();
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
      limitations: ["프론트엔드 fallback mock 결과입니다."],
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

  return (
    <main className="chatbot-mock">
      <section className="chatbot-mock__composer">
        <label htmlFor="mock-question">질문</label>
        <textarea
          id="mock-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={4}
        />

        <label htmlFor="mock-status">Mock 상태</label>
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
        <strong>{authLoading ? "인증 확인 중" : AUTH_STATE_LABELS[authState] || authState}</strong>
        <dl>
          <div>
            <dt>guest_id</dt>
            <dd>{guestId || "-"}</dd>
          </div>
          <div>
            <dt>auth_session_id</dt>
            <dd>{authSessionId || "-"}</dd>
          </div>
          <div>
            <dt>user_id</dt>
            <dd>{userId || "-"}</dd>
          </div>
          <div>
            <dt>chat_session_id</dt>
            <dd>{sessionId || "-"}</dd>
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
                {tokenActionLoading === "refresh" ? "Refreshing token" : "Refresh token"}
              </button>
              <button
                type="button"
                onClick={logout}
                disabled={Boolean(tokenActionLoading)}
              >
                {tokenActionLoading === "logout" ? "Logging out" : "Logout"}
              </button>
            </>
          )}
        </div>
        {googleProfile && (
          <p>
            {googleProfile.display_name || "Google user"} {googleProfile.email ? `(${googleProfile.email})` : ""}
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
            <button type="button" onClick={() => runReportAction("download")} disabled={!canRunReportAction}>
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

async function postJson(url, payload, identity = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: buildRequestHeaders(identity, { includeContentType: true }),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

async function getJson(url, identity = {}) {
  const response = await fetch(url, {
    method: "GET",
    headers: buildRequestHeaders(identity),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

function buildRequestHeaders(
  { authToken, guestId, authSessionId } = {},
  { includeContentType = false } = {}
) {
  return {
    ...(includeContentType ? { "Content-Type": "application/json" } : {}),
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(guestId ? { "X-Guest-Id": guestId } : {}),
    ...(authSessionId ? { "X-Auth-Session-Id": authSessionId } : {}),
  };
}

function buildAuthContext({ authState, guestId, authSessionId, sessionId, userId }) {
  return {
    auth_state: authState || "anonymous",
    user_id: userId || null,
    guest_id: guestId || null,
    auth_session_id: authSessionId || null,
    session_id: sessionId || null,
  };
}

function buildDevGoogleProfile({ guestId }) {
  const suffix = String(guestId || "guest").replace(/^gst_/, "") || Date.now();
  return {
    google_sub: `dev-google-${suffix}`,
    email: `driver.${suffix}@example.com`,
    display_name: "Google Demo User",
  };
}

function readStoredValue(key) {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage.getItem(key);
  } catch (_error) {
    return null;
  }
}

function writeStoredValue(key, value) {
  if (typeof window === "undefined" || !value) {
    return;
  }
  try {
    window.localStorage.setItem(key, value);
  } catch (_error) {
    // Ignore storage failures; in-memory auth state still works for this session.
  }
}

function removeStoredValue(key) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(key);
  } catch (_error) {
    // Ignore storage failures.
  }
}

function readStoredJson(key) {
  const value = readStoredValue(key);
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    return null;
  }
}

function writeStoredJson(key, value) {
  if (!value) {
    removeStoredValue(key);
    return;
  }
  writeStoredValue(key, JSON.stringify(value));
}

function buildAuthMeUrl(apiBase, sessionId) {
  const url = joinApiPath(apiBase, "auth/me/");
  if (!sessionId) {
    return url;
  }
  return `${url}?session_id=${encodeURIComponent(sessionId)}`;
}

function joinApiPath(apiBase, path) {
  return `${trimTrailingSlash(apiBase)}/${path.replace(/^\/+/, "")}`;
}

function toCanonicalApiBase(apiBase) {
  const normalized = trimTrailingSlash(apiBase);
  return normalized.endsWith("/mock") ? normalized.slice(0, -"/mock".length) : normalized;
}

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
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
      limitations: ["지원 형식의 고지서 이미지, PDF, 설명 텍스트를 다시 입력해 주세요."],
    };
  }

  if (status === "partial") {
    return {
      ...common,
      assistant_message: "일부 결과만 확인되었습니다. 추가 정보가 필요합니다.",
      progress: { status: "partial", message: "필수 입력 보완이 필요합니다." },
      analysis_plan: buildFallbackAnalysisPlan({ status: "partial" }),
      pending_questions: [
        {
          field: "user_facts",
          question: "이의신청 사유와 당시 상황을 한두 문장으로 보완해 주세요.",
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
      limitations: ["필수 입력이 부족해 리포트 초안 생성은 보류되었습니다."],
    };
  }

  return {
    ...common,
    assistant_message: "고지서 내용과 관련 법령 근거 후보를 확인했습니다.",
    progress: { status: status === "pending" ? "pending" : "success", message: "분석 결과를 표시할 수 있습니다." },
    analysis_plan: buildFallbackAnalysisPlan({ status }),
    cards: [
      {
        card_type: "fine_notice",
        title: "고지서 분석",
        status: "success",
        summary: "과태료 고지서로 추정되며 의견제출 기한 확인이 필요합니다.",
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
    ].map((node_code, index) => ({
      order: index + 1,
      node_code,
      status: stepStatuses[index],
    })),
  };
}

