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
  const examples = shell.indexOf('className="quick-examples"');
  const messages = shell.indexOf('className="messages"');

  assert.ok(save >= 0);
  assert.ok(examples > save);
  assert.ok(messages > examples);
  assert.match(styles, /\.save-choice-panel\s*\{\s*order:\s*1;/);
  assert.match(styles, /\.quick-examples\s*\{\s*order:\s*2;/);
  assert.match(styles, /\.messages\s*\{\s*order:\s*3;/);
});

test("structured intake is collapsible and the composer owns message, attachment, and send", () => {
  assert.match(fullShell, /<details\s+className="consultation-intake-card"/);
  assert.match(fullShell, /<summary className="consultation-intake-card__summary"/);
  assert.match(fullShell, /open=\{isIntakeOpen\}/);
  assert.match(fullShell, /onToggle=\{\(event\) => setIsIntakeOpen\(event\.currentTarget\.open\)\}/);
  assert.doesNotMatch(fullShell, /defaultOpen=\{!hasStructuredIntake\}/);

  const composer = shell.slice(
    shell.indexOf('className="attachment-dropzone"'),
    shell.indexOf("{capabilityError &&"),
  );
  assert.match(composer, /aria-label="상담 메시지 입력"/);
  assert.match(composer, /className="attachment-plus"/);
  assert.match(composer, /className="button primary composer-send"/);
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
  assert.match(intakeComponent, /"필수 입력 조건"/);
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

test("intake opens whenever the selected consultation type changes", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.match(intakeComponent, /useEffect\(\(\) => setIsIntakeOpen\(true\), \[selectedType\]\)/);
  assert.match(intakeComponent, /open=\{isIntakeOpen\}/);
});

test("general consultation hides the required-input title and reset action", () => {
  const intakeComponent = fullShell.slice(
    fullShell.indexOf("function ConsultationIntakePanel("),
    fullShell.indexOf("function FollowUpNote("),
  );

  assert.match(intakeComponent, /const requiresStructuredDetails = isFineNotice \|\| isFaultRatio/);
  assert.match(
    intakeComponent,
    /requiresStructuredDetails \? "필수 입력 조건" : selectedType \? "상담 유형" : "먼저 상담 유형을 선택해 주세요\."/
  );
  assert.match(intakeComponent, /\{requiresStructuredDetails && \(\s*<div[^>]*>\s*<button/s);
});

test("intake card radius matches its chat container", () => {
  assert.match(styles, /\.chat-input\s*\{[^}]*border-radius:\s*14px/s);
  assert.match(styles, /\.consultation-intake-card\s*\{[^}]*border-radius:\s*14px/s);
});
