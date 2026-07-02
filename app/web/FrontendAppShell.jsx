import { useMemo, useState } from "react";

import ChatbotMockFlow from "./ChatbotMockFlow.jsx";
import { createFrontendApi } from "./apiClient.js";
import {
  buildAuthContext,
  buildGoogleLoginPayload,
  persistAuthSession,
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

export default function FrontendAppShell({
  apiBase = "/api",
  authToken = "",
  googleClientId = "",
}) {
  void ChatbotMockFlow;

  const api = useMemo(() => createFrontendApi({ apiBase }), [apiBase]);
  const [activeRoute, setActiveRoute] = useState("entry");
  const [sessionId, setSessionId] = useState("");
  const [guestId, setGuestId] = useState("");
  const [authSessionId, setAuthSessionId] = useState("");
  const [mypageSummary, setMypageSummary] = useState(null);
  const [historyEvents, setHistoryEvents] = useState(null);
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [analysisResponse, setAnalysisResponse] = useState(null);
  const [activeAuthToken, setActiveAuthToken] = useState(() => readStoredAuthToken());
  const [savePromptVisible, setSavePromptVisible] = useState(false);
  const [saveDecision, setSaveDecision] = useState("undecided");
  const [statusMessage, setStatusMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSavingConversation, setIsSavingConversation] = useState(false);

  const identity = {
    authToken: activeAuthToken || authToken,
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
  const sessionLabel = isGuestReady ? "비회원 상담" : "상담 준비";
  const cases = mypageSummary?.cases || [];
  const history = historyEvents?.events || [];
  const analysisCards = analysisResponse?.cards?.length
    ? normalizeAnalysisCards(analysisResponse.cards)
    : [];

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

  async function submitServiceMessage() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setStatusMessage("상담 내용을 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setStatusMessage("상담 내용을 정리하고 있습니다.");
    setSubmittedQuestion(trimmedQuestion);

    const guestSessionResult = sessionId ? null : await bootstrapGuestSession("chatbot");
    const activeSession = sessionId || guestSessionResult?.sessionId || `ses_web_${Date.now()}`;
    const activeGuestId = guestId || guestSessionResult?.guestId || "";
    const activeAuthContext = buildAuthContext({
      authState: authContext.auth_state,
      guestId: activeGuestId,
      authSessionId,
      sessionId: activeSession,
      userId: null,
    });

    try {
      const result = await api.submitChatMessage(
        {
          session_id: activeSession,
          auth_context: activeAuthContext,
          conversation_save_state: authSessionId ? "saved" : "pending",
          user_text: trimmedQuestion,
          attachments: [],
          mock_status: "success",
        },
        {
          ...identity,
          guestId: activeGuestId,
          authSessionId,
        }
      );
      setAnalysisResponse(result);
      setSavePromptVisible(!authSessionId);
      setSaveDecision(authSessionId ? "saved" : "undecided");
      setStatusMessage(
        authSessionId
          ? "상담 응답을 받았습니다. 이 상담은 로그인 계정에 연결됩니다."
          : "상담 응답을 받았습니다. 조금 더 진행한 뒤 저장 여부를 선택할 수 있습니다."
      );
    } catch (_error) {
      setAnalysisResponse({
        cards: FALLBACK_ANALYSIS_CARDS,
      });
      setSavePromptVisible(!authSessionId);
      setStatusMessage("응답을 불러오지 못해 접수 상태만 표시합니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function saveConversationAfterLogin() {
    setIsSavingConversation(true);
    setStatusMessage("Google 로그인 후 현재 상담을 내 사건 이력에 연결하고 있습니다.");
    try {
      const guestSessionResult = sessionId ? null : await bootstrapGuestSession("chatbot");
      const activeSessionId = sessionId || guestSessionResult?.sessionId || `ses_web_${Date.now()}`;
      const activeGuestId = guestId || guestSessionResult?.guestId || "";
      const loginPayload = {
        guest_id: activeGuestId,
        session_id: activeSessionId,
        ...(await buildGoogleLoginPayload({ googleClientId, guestId: activeGuestId })),
      };
      const loginResult = await api.loginWithGoogleCode(loginPayload);
      const nextToken = loginResult?.access_token || "";
      const subject = loginResult?.subject || {};

      setActiveAuthToken(nextToken);
      setAuthSessionId(subject.auth_session_id || "");
      setGuestId(subject.guest_id || activeGuestId);
      setSessionId(activeSessionId);
      persistAuthSession({ accessToken: nextToken, googleProfile: loginResult?.user || null });
      const nextIdentity = {
        authToken: nextToken,
        authSessionId: subject.auth_session_id || "",
        guestId: subject.guest_id || activeGuestId,
      };
      await api.updateConversationSaveState(
        {
          session_id: activeSessionId,
          conversation_save_state: "saved",
          conversation_save_source: "google_login_save_prompt",
        },
        nextIdentity
      );
      const summary = await api.getMyPageSummary({ identity: nextIdentity, sessionId: activeSessionId });
      setMypageSummary(summary);
      setActiveRoute("mypage");

      setSaveDecision("saved");
      setSavePromptVisible(false);
      setStatusMessage("현재 상담을 Google 계정 기준 내 사건 이력에 저장했습니다.");
    } catch (_error) {
      setStatusMessage("로그인 또는 저장 연결에 실패했습니다. 상담은 현재 임시 세션에서 계속 진행할 수 있습니다.");
    } finally {
      setIsSavingConversation(false);
    }
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

  async function loadMyPageSummary() {
    setStatusMessage("내 사건을 불러오고 있습니다.");
    try {
      const summary = await api.getMyPageSummary({ sessionId, identity });
      setMypageSummary(summary);
      setStatusMessage("내 사건 현황을 업데이트했습니다.");
      return summary;
    } catch (_error) {
      setStatusMessage("저장된 사건을 찾지 못했습니다.");
      return null;
    }
  }

  async function loadHistoryEvents() {
    setStatusMessage("과거 이력을 불러오고 있습니다.");
    try {
      const events = await api.listHistoryEvents({ sessionId, identity });
      setHistoryEvents(events);
      setStatusMessage("과거 이력을 업데이트했습니다.");
      return events;
    } catch (_error) {
      setStatusMessage("저장된 이력을 찾지 못했습니다.");
      return null;
    }
  }

  return (
    <div className="app-shell" data-auth-state={authContext.auth_state}>
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

      <div className={activeRoute === "entry" ? "layout is-entry" : "layout"}>
        {activeRoute !== "entry" && (
          <aside className="sidebar" aria-label="사용자 작업 영역">
            <section className="profile-box">
              <div className="profile-row">
                <span className="avatar">{isGuestReady ? "비" : "AI"}</span>
                <div>
                  <div className="profile-name">{sessionLabel}</div>
                  <div className="profile-meta">
                    {isGuestReady ? "기본 상담 가능 · 자료 분석은 로그인 후" : "Google 로그인 또는 비회원 시작"}
                  </div>
                </div>
              </div>
              <button className="button primary" type="button" onClick={() => setActiveRoute("chatbot")}>
                새 상담 시작
              </button>
            </section>

            <nav className="nav-panel" aria-label="화면 이동">
              {ROUTES.filter((route) => route.id !== "entry").map((route) => (
                <button
                  className={activeRoute === route.id ? "nav-item active" : "nav-item"}
                  key={route.id}
                  onClick={() => setActiveRoute(route.id)}
                  type="button"
                >
                  {route.label}
                  {route.id === "chatbot" && submittedQuestion && <span className="badge">1</span>}
                </button>
              ))}
            </nav>

            <section className="deadline-panel">
              <strong>다가오는 일정</strong>
              <div className="empty-panel compact">
                <p>로그인 후 저장한 사건의 기한과 리포트 상태가 표시됩니다.</p>
              </div>
            </section>
          </aside>
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
              isSubmitting={isSubmitting}
              isSavingConversation={isSavingConversation}
              onKeepTemporary={keepConversationTemporary}
              onSaveConversation={saveConversationAfterLogin}
              onSubmit={submitServiceMessage}
              question={question}
              saveDecision={saveDecision}
              savePromptVisible={savePromptVisible}
              setQuestion={setQuestion}
              statusMessage={statusMessage}
              submittedQuestion={submittedQuestion}
            />
          )}

          {activeRoute === "mypage" && (
            <MyPageScreen cases={cases} onRefresh={loadMyPageSummary} summary={mypageSummary} />
          )}

          {activeRoute === "history" && (
            <HistoryScreen events={history} onRefresh={loadHistoryEvents} />
          )}

          {activeRoute === "reporting" && (
            <ReportingScreen />
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

function ChatScreenV2({
  analysisCards,
  isSavingConversation,
  isSubmitting,
  onKeepTemporary,
  onSaveConversation,
  onSubmit,
  question,
  saveDecision,
  savePromptVisible,
  setQuestion,
  statusMessage,
  submittedQuestion,
}) {
  const hasConversation = Boolean(submittedQuestion);
  const quickQuestions = [
    "과태료 고지서를 받았는데 이의제기 가능성을 봐줘",
    "교통사고 과실비율에서 쟁점이 될 부분을 정리해줘",
    "보험사 설명이 맞는지 확인하려면 어떤 자료가 필요해?",
    "블랙박스와 사진을 나중에 올리면 어떤 분석이 가능해?",
  ];

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
                <article className="message user">
                  <span className="message-avatar">나</span>
                  <div className="bubble">
                    <p>{submittedQuestion}</p>
                  </div>
                </article>

                <article className="message">
                  <span className="message-avatar">AI</span>
                  <div className="bubble wide">
                    <strong>상담 내용을 기준으로 확인 가능한 항목을 정리했습니다.</strong>
                    <p>
                      아래 결과는 현재 입력만 기준으로 한 1차 정리입니다. 추가 자료 분석이나 이력 저장이 필요하면
                      Google 로그인 후 현재 상담을 사건 이력으로 연결할 수 있습니다.
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
                  </div>
                </article>
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

function MyPageScreen({ cases, onRefresh, summary }) {
  const activeCases = summary?.active_cases ?? cases.length;
  const savedReports = summary?.saved_reports ?? 0;
  const recentCount = summary?.recent_analysis_count ?? cases.length;

  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>내 사건</h2>
          <p>진행 중인 상담, 저장한 리포트, 기한이 임박한 사건을 관리합니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button">새 상담</button>
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
            <button className="button" type="button">필터</button>
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
                {cases.length === 0 ? (
                  <tr>
                    <td colSpan="5">
                      <div className="table-empty">
                        <strong>아직 저장된 사건이 없습니다.</strong>
                        <p>상담을 시작하거나 리포트를 저장하면 이곳에 표시됩니다.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  cases.map((item) => (
                    <tr key={item.case_id || item.job_id || item.title}>
                      <td><span className="tag">{item.type || "상담"}</span></td>
                      <td>{item.title || item.case_id}</td>
                      <td>{item.case_status || item.status || "확인 필요"}</td>
                      <td>{item.updated_at || item.created_at || "-"}</td>
                      <td><button className="button" type="button">열기</button></td>
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
          <button className="quick-chip active" type="button">전체</button>
          <button className="quick-chip" type="button">과태료</button>
          <button className="quick-chip" type="button">과실비율</button>
          <button className="quick-chip" type="button">리포트</button>
        </div>
        <ol className="history-list">
          {events.length === 0 ? (
            <li className="history-row empty">
              <div>
                <strong>아직 과거 이력이 없습니다.</strong>
                <p>상담이나 리포트 저장 후 이력이 쌓입니다.</p>
              </div>
            </li>
          ) : (
            events.map((event) => (
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

function ReportingScreen() {
  return (
    <section className="screen">
      <div className="screen-header">
        <div className="screen-title">
          <h2>리포트 작업대</h2>
          <p>상담 결과에서 생성한 과실비율·사고 리포트를 검토하고 내려받는 화면입니다.</p>
        </div>
        <div className="screen-actions">
          <button className="button" type="button">목록 새로고침</button>
          <button className="button primary" type="button">리포트 생성 준비</button>
        </div>
      </div>

      <div className="report-workbench">
        <aside className="report-list" aria-label="리포트 목록">
          <div className="panel-head compact">
            <strong>리포트 목록</strong>
            <span className="tag">0건</span>
          </div>
          <div className="empty-panel report-empty">
            <strong>선택할 리포트가 없습니다.</strong>
            <p>상담 결과에서 리포트를 저장하면 사고 개요와 근거 문서가 여기에 표시됩니다.</p>
          </div>
        </aside>

        <article className="report-canvas" aria-label="리포트 미리보기">
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
        </article>

        <aside className="report-inspector" aria-label="근거와 작업">
          <div className="panel-head compact">
            <strong>근거·작업</strong>
          </div>
          <div className="inspector-section">
            <span className="tag green">대기</span>
            <strong>리포트 선택 필요</strong>
            <p>선택된 리포트의 제출 자료, 관련 기준, 후속 행동이 이곳에 표시됩니다.</p>
          </div>
          <div className="inspector-actions">
            <button className="button" type="button" disabled>PDF 내려받기</button>
            <button className="button" type="button" disabled>근거 보기</button>
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

function normalizeAnalysisCards(cards) {
  return cards.map((card) => ({
    card_type: normalizeLabel(card.card_type),
    title: stripMockText(card.title || "분석 항목"),
    status: card.status || "partial",
    summary: stripMockText(card.summary || "추가 확인이 필요합니다."),
  }));
}

function normalizeLabel(value) {
  const labels = {
    fine_notice: "고지서 분석",
    law_ground: "근거 확인",
    objection_report: "초안 작성",
  };
  return labels[value] || value || "분석";
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
