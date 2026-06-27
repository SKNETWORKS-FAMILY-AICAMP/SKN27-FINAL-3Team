import { useMemo, useState } from "react";

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

export default function ChatbotMockFlow({ apiBase = "/api", authToken = "dev-mock-token" }) {
  const [sessionId, setSessionId] = useState(null);
  const [question, setQuestion] = useState("이 고지서로 이의신청서를 만들 수 있을까요?");
  const [mockStatus, setMockStatus] = useState("success");
  const [response, setResponse] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);

  const progressStatus = response?.progress?.status || "pending";
  const analysisSteps = response?.analysis_plan?.steps || [];
  const canRunReportAction = response?.report_links?.length > 0;

  const requestPayload = useMemo(
    () => ({
      session_id: sessionId,
      user_text: question,
      attachments: MOCK_ATTACHMENTS,
      mock_status: mockStatus,
    }),
    [mockStatus, question, sessionId]
  );

  async function ensureSession() {
    if (sessionId) {
      return sessionId;
    }
    const nextSessionId = `ses_mock_${Date.now()}`;
    setSessionId(nextSessionId);
    return nextSessionId;
  }

  async function submitMockMessage() {
    setLoading(true);
    setReport(null);
    const activeSessionId = await ensureSession();
    const fallbackResponse = buildFallbackResponse({
      ...requestPayload,
      session_id: activeSessionId,
    });

    try {
      const result = await postJson(
        `${apiBase}/chat/messages`,
        {
          ...requestPayload,
          session_id: activeSessionId,
        },
        authToken
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
        `${apiBase}/reports`,
        {
          action,
          session_id: response.session_id,
        },
        authToken
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

async function postJson(url, payload, authToken) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

function buildFallbackResponse(payload) {
  const status = payload.mock_status || "success";
  const common = {
    message_id: `msg_mock_${Date.now()}`,
    session_id: payload.session_id,
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

