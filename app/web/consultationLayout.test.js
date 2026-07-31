import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const fullShell = readFileSync(new URL("./FrontendAppShell.jsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const shell = fullShell.slice(
  fullShell.indexOf("function ChatScreenV2("),
  fullShell.indexOf("function OcrConfirmationCard("),
);

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
  assert.match(composer, /aria-label="전송"/);
  assert.match(composer, /<span aria-hidden="true">↑<\/span>/);
  assert.doesNotMatch(composer, /파일을 끌어 놓거나/);
  assert.doesNotMatch(composer, /영상은 Vision 분석/);
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
  assert.match(compactStyles, /\.composer-send\s*\{[^}]*width:\s*40px/s);
});
