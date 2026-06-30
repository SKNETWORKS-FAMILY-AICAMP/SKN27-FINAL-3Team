import { useMemo, useState } from "react";

import ChatbotMockFlow from "./ChatbotMockFlow.jsx";
import { createFrontendApi } from "./apiClient.js";
import { buildAuthContext, readStoredAuthToken } from "./authSession.js";

const ROUTES = [
  { id: "entry", label: "시작" },
  { id: "chatbot", label: "챗봇" },
  { id: "mypage", label: "내 사건" },
  { id: "history", label: "이력" },
];

export default function FrontendAppShell({
  apiBase = "/api",
  authToken = "dev-mock-token",
  googleClientId = "",
}) {
  const api = useMemo(() => createFrontendApi({ apiBase }), [apiBase]);
  const [activeRoute, setActiveRoute] = useState("entry");
  const [sessionId, setSessionId] = useState("");
  const [guestId, setGuestId] = useState("");
  const [authSessionId, setAuthSessionId] = useState("");
  const [mypageSummary, setMypageSummary] = useState(null);
  const [historyEvents, setHistoryEvents] = useState(null);
  const [statusMessage, setStatusMessage] = useState("");

  const identity = {
    authToken: readStoredAuthToken() || authToken,
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

  async function bootstrapGuestSession() {
    setStatusMessage("비회원 세션을 준비하는 중입니다.");
    try {
      const guest = await api.createGuestSession({
        guest_id: guestId,
        session_id: sessionId || undefined,
      });
      setGuestId(guest?.guest?.guest_id || "");
      setSessionId(guest?.session_binding?.session_id || sessionId);
      setStatusMessage("비회원 세션이 준비됐습니다.");
      return guest;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  async function loadMyPageSummary() {
    setStatusMessage("내 사건 요약을 불러오는 중입니다.");
    try {
      const summary = await api.getMyPageSummary({ sessionId, identity });
      setMypageSummary(summary);
      setStatusMessage("내 사건 요약을 불러왔습니다.");
      return summary;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  async function loadHistoryEvents() {
    setStatusMessage("이력을 불러오는 중입니다.");
    try {
      const history = await api.listHistoryEvents({ sessionId, identity });
      setHistoryEvents(history);
      setStatusMessage("이력을 불러왔습니다.");
      return history;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  return (
    <main className="frontend-shell" data-auth-state={authContext.auth_state}>
      <header className="frontend-shell__header">
        <strong>교통분쟁 AI</strong>
        <nav aria-label="프론트 화면">
          {ROUTES.map((route) => (
            <button
              aria-current={activeRoute === route.id ? "page" : undefined}
              key={route.id}
              onClick={() => setActiveRoute(route.id)}
              type="button"
            >
              {route.label}
            </button>
          ))}
        </nav>
      </header>

      {activeRoute === "entry" && (
        <section className="frontend-shell__entry">
          <h1>교통 과태료와 사고 상담을 한 화면에서 확인합니다</h1>
          <p>비회원 세션으로 챗봇 mock flow를 시작하고, 내 사건과 이력 API 연결 상태를 확인할 수 있습니다.</p>
          <label htmlFor="shell-session-id">세션 ID</label>
          <input
            id="shell-session-id"
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="ses_demo"
            value={sessionId}
          />
          <button onClick={bootstrapGuestSession} type="button">
            비회원 시작
          </button>
          <button onClick={() => setActiveRoute("chatbot")} type="button">
            챗봇 열기
          </button>
        </section>
      )}

      {activeRoute === "chatbot" && (
        <ChatbotMockFlow
          apiBase={apiBase}
          authToken={authToken}
          googleClientId={googleClientId}
        />
      )}

      {activeRoute === "mypage" && (
        <section className="frontend-shell__mypage">
          <h2>내 사건 요약</h2>
          <button onClick={loadMyPageSummary} type="button">
            요약 새로고침
          </button>
          <dl>
            <div>
              <dt>active_cases</dt>
              <dd>{mypageSummary?.active_cases ?? "-"}</dd>
            </div>
            <div>
              <dt>saved_reports</dt>
              <dd>{mypageSummary?.saved_reports ?? "-"}</dd>
            </div>
            <div>
              <dt>recent_analysis_count</dt>
              <dd>{mypageSummary?.recent_analysis_count ?? "-"}</dd>
            </div>
          </dl>
          <ul>
            {mypageSummary?.cases?.map((item) => (
              <li key={item.case_id || item.job_id}>
                <strong>{item.title || item.case_id}</strong>
                <span>{item.case_status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {activeRoute === "history" && (
        <section className="frontend-shell__history">
          <h2>상담 이력</h2>
          <button onClick={loadHistoryEvents} type="button">
            이력 새로고침
          </button>
          <ol>
            {historyEvents?.events?.map((event) => (
              <li key={event.event_id}>
                <strong>{event.event_type}</strong>
                <span>{event.summary}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {statusMessage && <p role="status">{statusMessage}</p>}
    </main>
  );
}
