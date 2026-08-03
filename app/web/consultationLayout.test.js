import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const fullShell = readFileSync(new URL("./FrontendAppShell.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const shell = fullShell.slice(
  fullShell.indexOf("function ChatScreenV2("),
  fullShell.indexOf("function OcrConfirmationCard("),
);

test("chat submission and restoration use the response presentation boundary", () => {
  assert.match(
    fullShell,
    /import \{[\s\S]*normalizeChatResponsePresentation,[\s\S]*from "\.\/chatResponsePresentation\.js";/,
  );
  assert.match(fullShell, /normalizeChatResponsePresentation\(workerResult\)/);
  assert.match(fullShell, /normalizeChatResponsePresentation\(\{[\s\S]*\.\.\.job,/);

  const streamFunction = fullShell.slice(
    fullShell.indexOf("async function streamAssistantMessage("),
    fullShell.indexOf("function startNewConversation("),
  );
  assert.doesNotMatch(
    streamFunction,
    /\{ \.\.\.assistantMessage, content:\s*"", streaming:\s*false \}/,
  );
});

test("assistant answers use safe markdown while user messages stay plain text", () => {
  assert.match(fullShell, /import \{ SafeMarkdown \} from "\.\/SafeMarkdown\.js";/);
  assert.match(
    shell,
    /isUser \? <p>\{message\.content\}<\/p> : <SafeMarkdown content=\{message\.content\} \/>/,
  );
});

test("composer keyboard policy preserves newline and IME before submitting", () => {
  assert.match(fullShell, /import \{ composerKeyAction \} from "\.\/composerInteraction\.js";/);
  assert.match(shell, /onKeyDown=\{\(event\) => \{/);
  assert.match(shell, /composerKeyAction\(event, \{/);
  assert.match(shell, /hasContent: Boolean\(question\.trim\(\)\)/);
  assert.match(shell, /if \(action === "submit"\) \{/);
  assert.match(shell, /event\.preventDefault\(\);[\s\S]*onSubmit\(\);/);
  assert.match(shell, /aria-describedby="composer-keyboard-hint"/);
  assert.match(shell, /Enter 전송 · Shift\+Enter 줄바꿈/);
});

test("attachment menu exposes menu semantics and complete dismissal behavior", () => {
  for (const token of [
    "const attachmentMenuRef = useRef(null);",
    "const attachmentTriggerRef = useRef(null);",
    "const attachmentMenuItemRefs = useRef([]);",
    'aria-haspopup="menu"',
    'aria-controls="chat-attachment-menu"',
    'id="chat-attachment-menu"',
    'role="menu"',
    'role="menuitem"',
    'document.addEventListener("pointerdown", handleOutsidePointerDown);',
    'document.addEventListener("keydown", handleAttachmentMenuKeyDown);',
    'event.key === "Escape"',
    'event.key === "ArrowDown"',
    'event.key === "ArrowUp"',
    'event.key === "Home"',
    'event.key === "End"',
  ]) {
    assert.ok(shell.includes(token), `missing attachment menu contract: ${token}`);
  }
});

test("assistant turn keeps answer, limitations, one question, retry, and report in order", () => {
  assert.match(
    fullShell,
    /selectPrimaryFollowUpQuestion,[\s\S]*from "\.\/chatResponsePresentation\.js";/,
  );
  const assistantTurn = shell.slice(
    shell.indexOf("<SafeMarkdown content={message.content} />"),
    shell.indexOf("{appealDecisionUi &&"),
  );
  const answer = assistantTurn.indexOf("<SafeMarkdown");
  const limitations = assistantTurn.indexOf("<AssistantLimitationsDisclosure");
  const question = assistantTurn.indexOf("<AssistantPrimaryQuestion");
  const retry = assistantTurn.indexOf('className="assistant-retry-action"');
  const report = assistantTurn.indexOf('className="assistant-report-entry"');

  assert.ok(answer >= 0 && limitations > answer);
  assert.ok(question > limitations);
  assert.ok(retry > question);
  assert.ok(report > retry);
  assert.doesNotMatch(assistantTurn, /<FollowUpNote|<MissingFieldsPrompt|<SafetyGuidancePanel/);
  assert.match(fullShell, /<details className="assistant-limitations"/);
  assert.match(fullShell, /<summary>한계·주의사항<\/summary>/);
  assert.match(fullShell, />\s*현재 리포트 보기\s*<\/button>/);
});

test("consultation helpers appear before conversation messages", () => {
  const save = shell.indexOf('aria-label="상담 저장 선택"');
  const messages = shell.indexOf('className="messages"');

  assert.ok(save >= 0);
  assert.ok(messages > save);
  assert.match(styles, /\.save-choice-panel\s*\{\s*order:\s*1;/);
  assert.match(styles, /\.messages\s*\{\s*order:\s*3;/);
});

test("quick examples live quietly inside the empty conversation state", () => {
  const emptyState = shell.slice(
    shell.indexOf('className="chat-empty-state"'),
    shell.indexOf('<div className="chat-input">'),
  );
  const topLevelBeforeMessages = shell.slice(
    shell.indexOf('<div className="chat-main">'),
    shell.indexOf('className="messages"'),
  );

  assert.match(emptyState, /어떤 내용을 적어야 할지 막막하신가요/);
  assert.match(emptyState, /예시 질문 보기/);
  assert.match(emptyState, /quickQuestionGroups\.map/);
  assert.match(emptyState, /setQuestion\(item\)/);
  assert.match(emptyState, /quickExamplesRef\.current\.open = false/);
  assert.match(emptyState, /questionInputRef\.current\?\.focus\(\)/);
  assert.match(shell, /ref=\{questionInputRef\}/);
  assert.doesNotMatch(topLevelBeforeMessages, /서비스 예시 작동 방식/);
  assert.doesNotMatch(emptyState, /onSubmit/);
});

test("empty consultation labels the active authentication state", () => {
  const emptyState = shell.slice(
    shell.indexOf('className="chat-empty-state"'),
    shell.indexOf('<div className="chat-input">'),
  );

  assert.match(
    emptyState,
    /\{isAuthenticated \? "로그인 상담 중" : "비회원으로 상담 중"\}/,
  );
});

test("quick example disclosure uses a compact borderless hierarchy", () => {
  const compactStyles = styles.slice(styles.lastIndexOf("/* Compact quick examples */"));

  assert.match(compactStyles, /\.empty-state-examples\s*\{[^}]*font-size:\s*12px/s);
  assert.match(compactStyles, /\.empty-state-examples \.quick-examples\s*\{[^}]*border:\s*0/s);
  assert.match(compactStyles, /\.empty-state-examples \.quick-examples\s*\{[^}]*background:\s*transparent/s);
  assert.match(compactStyles, /\.empty-state-examples \.quick-examples-header\s*\{[^}]*min-height:\s*28px/s);
  assert.match(compactStyles, /\.empty-state-examples \.quick-examples-header\s*\{[^}]*width:\s*max-content/s);
});

test("structured intake keeps a compact type row and gates detail fields behind disclosure", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.match(intakeComponent, /className="consultation-type-row"/);
  assert.match(intakeComponent, /사건 유형/);
  assert.match(fullShell, /<details\s+className="consultation-intake-card"/);
  assert.match(fullShell, /<summary className="consultation-intake-card__summary"/);
  assert.match(intakeComponent, />상세 정보</);
  assert.match(intakeComponent, /const \[isIntakeOpen, setIsIntakeOpen\] = useState\(false\)/);
  assert.match(fullShell, /open=\{isIntakeOpen\}/);
  assert.match(fullShell, /onToggle=\{\(event\) => setIsIntakeOpen\(event\.currentTarget\.open\)\}/);
  assert.doesNotMatch(intakeComponent, /useEffect\(\(\) => setIsIntakeOpen\(true\)/);
});

test("composer owns message, attachment, and accessible icon send without persistent instructions", () => {
  const composer = shell.slice(
    shell.indexOf('className="attachment-dropzone"'),
    shell.indexOf("{capabilityError &&"),
  );
  assert.match(composer, /aria-label="상담 메시지 입력"/);
  assert.match(composer, /className="attachment-plus"/);
  assert.match(composer, /className="button primary composer-send"/);
  assert.match(composer, /aria-label="메시지 보내기"/);
  assert.match(composer, /className="composer-send-icon"/);
  assert.doesNotMatch(composer, /<span aria-hidden="true">↑<\/span>/);
  assert.doesNotMatch(composer, /파일을 끌어 놓거나/);
  assert.doesNotMatch(composer, /영상은 Vision 분석/);
});

test("selected files must be uploaded before manual chat submission", () => {
  const attachmentSelection = fullShell.slice(
    fullShell.indexOf("function handleAttachmentFile(file)"),
    fullShell.indexOf("function handleAttachmentDragOver(event)"),
  );
  const submitServiceMessage = fullShell.slice(
    fullShell.indexOf("async function submitServiceMessage("),
    fullShell.indexOf("async function retryLastAssistantMessage("),
  );
  const composer = shell.slice(
    shell.indexOf('className="attachment-dropzone"'),
    shell.indexOf("{capabilityError &&"),
  );

  assert.match(attachmentSelection, /파일이 선택되었습니다\. ‘업로드 시작’을 눌러 주세요\./);
  assert.doesNotMatch(attachmentSelection, /대기열에 연결했습니다/);
  assert.match(submitServiceMessage, /submissionKind === "manual"/);
  assert.match(submitServiceMessage, /selectedUploadFile \|\| isRegisteringAttachment/);
  assert.match(submitServiceMessage, /파일 업로드를 완료한 뒤 상담 내용을 보낼 수 있습니다\./);
  assert.match(composer, /isRegisteringAttachment \? "업로드 중" : isAuthenticated \? "업로드 시작"/);
  assert.match(
    composer,
    /disabled=\{isSubmitting \|\| isRegisteringAttachment \|\| Boolean\(selectedUploadFile\)\}/,
  );
  assert.match(composer, /선택됨 · 업로드 필요/);
});

test("structured intake uses the guest conversation palette", () => {
  const intakeStyles = styles.slice(
    styles.lastIndexOf(".consultation-intake-card {"),
    styles.indexOf("@media (max-width: 860px)", styles.lastIndexOf(".consultation-intake-card {")),
  );

  assert.match(intakeStyles, /background:\s*#eef1f7/);
  assert.match(intakeStyles, /color:\s*#111844/);
  assert.doesNotMatch(intakeStyles, /rgba\(10,\s*15,\s*19/);
});

test("intake label is inside the card and redundant fields are absent", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.doesNotMatch(intakeComponent, />입력 단계</);
  assert.match(intakeComponent, />필수 입력 조건</);
  assert.doesNotMatch(intakeComponent, /선택한 유형에 필요한 내용만 순서대로 입력할 수 있습니다/);
  assert.doesNotMatch(intakeComponent, /fineQuestion/);
  assert.doesNotMatch(intakeComponent, /missingDetails/);
  assert.doesNotMatch(intakeComponent, /consultation-intake-missing/);
});

test("fine notice uses three columns and its own composer prompt", () => {
  assert.match(fullShell, /isFineNotice \? " is-fine-notice" : ""/);
  assert.match(styles, /\.consultation-intake-grid\.is-fine-notice\s*\{[^}]*repeat\(3,/s);
  assert.match(
    shell,
    /consultationIntake\?\.consultationType === "fine_notice"[\s\S]*이의신청 이유와 위반일자의 상황을 자세히 입력해 주세요\./
  );
  assert.match(
    shell,
    /consultationIntake\?\.consultationType === "fault_ratio"[\s\S]*사고상황, 보험사 설명처럼 사고 발생 후 기억나는 내용을 입력해주세요\./
  );
});

test("intake details stay closed until the user opens them", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.match(intakeComponent, /useState\(false\)/);
  assert.doesNotMatch(intakeComponent, /useEffect\(\(\) => setIsIntakeOpen\(true\)/);
  assert.match(intakeComponent, /open=\{isIntakeOpen\}/);
});

test("general consultation hides the required-input title and reset action", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.match(intakeComponent, /const requiresStructuredDetails = isFineNotice \|\| isFaultRatio/);
  assert.match(intakeComponent, /\{requiresStructuredDetails && \(\s*<details/s);
  assert.match(intakeComponent, /className="consultation-intake-card__head"[\s\S]*입력 초기화/);
});

test("intake card radius matches its chat container", () => {
  assert.match(styles, /\.chat-input\s*\{[^}]*border-radius:\s*14px/s);
  assert.match(styles, /\.consultation-intake-card\s*\{[^}]*border-radius:\s*14px/s);
});

test("compact composer overrides cap the default vertical footprint", () => {
  const compactStyles = styles.slice(styles.lastIndexOf("/* Compact chat composer */"));

  assert.match(compactStyles, /\.chat-input\s*\{[^}]*padding:\s*8px/s);
  assert.match(compactStyles, /\.chat-input textarea\s*\{[^}]*min-height:\s*64px/s);
  assert.match(compactStyles, /\.composer-toolbar\s*\{[^}]*min-height:\s*44px/s);
  assert.match(compactStyles, /\.chat-input \.composer-send\s*\{[^}]*width:\s*44px/s);
  assert.match(compactStyles, /\.attachment-plus,[\s\S]*min-height:\s*44px/s);
});

test("mobile global navigation uses the four approved routes in order", () => {
  const navigation = fullShell.slice(
    fullShell.indexOf("function MobileGlobalNavigation("),
    fullShell.indexOf("function EntryScreenV2("),
  );
  const labels = ["가이드", "상담", "리포트", "내 사건"];
  let previousIndex = -1;

  for (const label of labels) {
    const labelIndex = navigation.indexOf(`label: "${label}"`);
    assert.ok(labelIndex > previousIndex, `${label} must follow the approved order`);
    previousIndex = labelIndex;
  }
  for (const route of ["guide", "chatbot", "reporting", "mypage"]) {
    assert.match(navigation, new RegExp(`id: "${route}"`));
  }
  assert.doesNotMatch(navigation, /새 상담/);
  assert.match(fullShell, /<MobileGlobalNavigation[\s\S]*activeRoute=\{activeRoute\}/);
  assert.match(styles, /\.mobile-bottom-nav\s*\{[^}]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/s);
  assert.match(styles, /padding-bottom:\s*calc\(84px \+ env\(safe-area-inset-bottom\)\)/);
  const mobileIaStyles = styles.slice(styles.lastIndexOf("/* Mobile IA hotfix */"));
  assert.match(mobileIaStyles, /@media \(max-width: 860px\)[\s\S]*\.app-top-nav nav\s*\{[^}]*display:\s*none/s);
});

test("new consultation remains a secondary action inside the chat screen", () => {
  const chatHeader = shell.slice(
    shell.indexOf('<div className="screen-header">'),
    shell.indexOf('<div className="chat-shell">'),
  );

  assert.match(fullShell, /onNewChat=\{startNewConversation\}/);
  assert.match(chatHeader, /className="button chat-new-conversation"/);
  assert.match(chatHeader, /onClick=\{onNewChat\}/);
  assert.match(chatHeader, />\s*새 상담\s*<\/button>/);
});

test("guest My Cases shows one focused Google login action", () => {
  const gate = fullShell.slice(
    fullShell.indexOf("function GuestCasesGate("),
    fullShell.indexOf("function MyPageScreen("),
  );
  const mypageRoute = fullShell.slice(
    fullShell.indexOf('{activeRoute === "mypage"'),
    fullShell.indexOf('{activeRoute === "history"'),
  );

  assert.match(mypageRoute, /authSessionId \? \(/);
  assert.match(mypageRoute, /<GuestCasesGate/);
  assert.equal((gate.match(/Google 로그인/g) || []).length, 1);
  assert.match(fullShell, /activeRoute === "mypage" && !authSessionId\s*\? null/);
});

test("entry actions and navigation use the approved consultation terminology", () => {
  const entry = fullShell.slice(
    fullShell.indexOf("function EntryScreenV2("),
    fullShell.indexOf("function GuideScreen("),
  );

  assert.match(entry, />AI 상담 시작<\/button>/);
  assert.doesNotMatch(entry, /사고 접수하기/);
  assert.doesNotMatch(entry, /<h3>사고 접수<\/h3>/);
  assert.match(entry, /<h3>상담 시작<\/h3>/);
});

test("mobile Korean labels wrap safely without shrinking touch targets", () => {
  const mobileIaStyles = styles.slice(styles.lastIndexOf("/* Mobile IA hotfix */"));

  assert.match(mobileIaStyles, /word-break:\s*keep-all/);
  assert.match(mobileIaStyles, /overflow-wrap:\s*anywhere/);
  assert.match(mobileIaStyles, /\.mobile-bottom-nav__item\s*\{[^}]*min-height:\s*52px/s);
  assert.match(mobileIaStyles, /\.mobile-bottom-nav__item svg\s*\{[^}]*width:\s*20px/s);
});

test("report list and inspector collapse independently around a dominant canvas", () => {
  const reporting = fullShell.slice(
    fullShell.indexOf("function ReportingScreen("),
    fullShell.indexOf("function ReportWorkbenchEmptyState("),
  );

  for (const token of [
    "const [isReportListCollapsed, setIsReportListCollapsed] = useState(false);",
    "const [isInspectorCollapsed, setIsInspectorCollapsed] = useState(false);",
    '"is-list-collapsed"',
    '"is-inspector-collapsed"',
    'className="report-list-collapse-toggle"',
    'className="report-inspector-collapse-toggle"',
    'aria-label={isInspectorCollapsed ? "상태·다운로드 펼치기" : "상태·다운로드 접기"}',
  ]) {
    assert.ok(reporting.includes(token), `missing report workbench contract: ${token}`);
  }
  assert.match(
    styles,
    /\.report-workbench\s*\{[^}]*grid-template-columns:\s*clamp\(220px, 15vw, 280px\) minmax\(520px, 1fr\) clamp\(240px, 16vw, 300px\)/s,
  );
  assert.match(styles, /\.report-workbench\.is-list-collapsed\.is-inspector-collapsed\s*\{[^}]*56px minmax\(520px, 1fr\) 56px/s);
});

test("report notice is contextual and the empty workbench has one primary action", () => {
  const reporting = fullShell.slice(
    fullShell.indexOf("function ReportingScreen("),
    fullShell.indexOf("function ReportWorkbenchEmptyState("),
  );
  const listPanel = reporting.slice(
    reporting.indexOf('<aside className={isReportListCollapsed'),
    reporting.indexOf('<article className="report-canvas"'),
  );
  const inspector = reporting.slice(
    reporting.indexOf('<aside className={isInspectorCollapsed'),
    reporting.lastIndexOf("</aside>"),
  );
  const emptyState = fullShell.slice(
    fullShell.indexOf("function ReportWorkbenchEmptyState("),
    fullShell.indexOf("function ReportSectionPreview("),
  );

  assert.doesNotMatch(listPanel, /<ServiceInformationNotice/);
  assert.match(inspector, /<ServiceInformationNotice \/>[\s\S]*className="inspector-actions"/);
  assert.match(reporting, /\{hasReport && \(\s*<div className="screen-actions">/);
  assert.equal((emptyState.match(/<button/g) || []).length, 1);
  assert.match(emptyState, /className="button primary"/);
});
