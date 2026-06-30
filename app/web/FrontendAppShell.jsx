import { useMemo, useState } from "react";

import ChatbotMockFlow from "./ChatbotMockFlow.jsx";
import { createFrontendApi } from "./apiClient.js";
import { buildAuthContext, readStoredAuthToken } from "./authSession.js";

const ROUTES = [
  { id: "entry", label: "Start" },
  { id: "chatbot", label: "Chatbot" },
  { id: "mypage", label: "My Case" },
  { id: "history", label: "History" },
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
    setStatusMessage("Loading guest session");
    try {
      const guest = await api.createGuestSession({
        guest_id: guestId,
        session_id: sessionId || undefined,
      });
      setGuestId(guest?.guest?.guest_id || "");
      setSessionId(guest?.session_binding?.session_id || sessionId);
      setStatusMessage("Guest session ready");
      return guest;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  async function loadMyPageSummary() {
    setStatusMessage("Loading my case summary");
    try {
      const summary = await api.getMyPageSummary({ sessionId, identity });
      setMypageSummary(summary);
      setStatusMessage("My case summary loaded");
      return summary;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  async function loadHistoryEvents() {
    setStatusMessage("Loading history");
    try {
      const history = await api.listHistoryEvents({ sessionId, identity });
      setHistoryEvents(history);
      setStatusMessage("History loaded");
      return history;
    } catch (error) {
      setStatusMessage(error.message);
      return null;
    }
  }

  return (
    <main className="frontend-shell" data-auth-state={authContext.auth_state}>
      <header className="frontend-shell__header">
        <strong>Traffic Dispute AI</strong>
        <nav aria-label="Frontend sections">
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
          <h1>Start traffic dispute consultation</h1>
          <p>Use guest mode for a quick mock flow, or continue with Google inside the chatbot.</p>
          <label htmlFor="shell-session-id">Session id</label>
          <input
            id="shell-session-id"
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="ses_demo"
            value={sessionId}
          />
          <button onClick={bootstrapGuestSession} type="button">
            Start guest session
          </button>
          <button onClick={() => setActiveRoute("chatbot")} type="button">
            Open chatbot
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
          <h2>My Case summary</h2>
          <button onClick={loadMyPageSummary} type="button">
            Refresh summary
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
          <h2>History</h2>
          <button onClick={loadHistoryEvents} type="button">
            Refresh history
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
