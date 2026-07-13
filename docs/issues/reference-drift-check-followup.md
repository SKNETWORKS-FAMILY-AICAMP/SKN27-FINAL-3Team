---
title: "[appeal-judgment] law_refs 조문번호 드리프트 탐지 — 후속 작업 3건"
labels: "wbs"
assignees: ""
---

## 배경

`ai/agents/appeal_decision_flow/law_refs.py`가 MG(merit_classification_node) 참조 조문을
법령DB에서 고정 조문번호(article_no) exact match로 조회하는 방식은, 조문 "내용"만 개정되는
경우엔 안전하지만(enforce_date 최신본 자동 반영) 법 개정으로 **조문번호 자체가 재편**되면
(예: 142조가 143조로 밀림) 조회가 에러 없이 "성공"하면서 조용히 엉뚱한 조문을 LLM 근거로
주입할 위험이 있다는 게 논의 중 확인됐다.

2026-07-13, 이 위험을 탐지하기 위해 `etl/legal/reference_drift_check.py`(법령DB 현재 원문과
`law_refs.py`의 검증된 폴백 원문을 임베딩 코사인 유사도로 비교하는 배치 스크립트)를 신설했다.
상세 배경·설계 근거는
`docs/architecture/appeal-judgment/업데이트_기록.md`의 2026-07-13
"`law_refs.py`의 고정 조문번호 exact match 조회가 법 개정(재편)에 취약한 문제" 항목 참고.

이 이슈는 그 스크립트를 만들면서 남겨둔 후속 작업 3건을 추적하기 위한 것이다 — 스크립트
자체는 이미 구현·테스트(단위 테스트 8개 통과)까지 끝났고 아래 항목만 남아 있다.

## 담당자

- 담당자:
- GitHub 계정:
- 연결 parent issue:
- 연결 child issue:

## 작업 범위

- [ ] **CI/스케줄러 연결** — `etl/legal/reference_drift_check.py`는 독립 실행 가능한
      CLI(`python -m etl.legal.reference_drift_check`, 문제 발견 시 exit code 1)이지만
      아직 주기 실행되도록 배선돼 있지 않다. GitHub Actions cron이나 별도 스케줄러에
      연결해, 드리프트 발생 시 알림(이슈 자동 생성·Slack 알림 등)까지 이어지게 한다.
- [ ] **드리프트 임계값(0.75) 실측 검증** — 현재 `_DRIFT_THRESHOLD = 0.75`는 실측 데이터
      없이 정한 값이다. 실제 법 개정 재편 사례(또는 의도적으로 재현한 테스트 케이스)로
      "정상 소폭 개정"과 "재편으로 인한 완전히 다른 내용"이 실제로 이 임계값 기준으로
      잘 갈리는지 검증하고, 필요하면 재조정한다.
- [ ] **Windows 콘솔 cp949 인코딩 이슈 — 다른 CLI 스크립트도 점검** — 방금
      `reference_drift_check.py`를 실전 실행(로컬 DB 미기동 상태)하다가 `—`(em-dash)
      문자 때문에 `UnicodeEncodeError`로 죽는 걸 발견해 `sys.stdout.reconfigure(encoding="utf-8")`로
      고쳤다(해당 파일은 이미 수정 완료). 저장소의 다른 CLI 진입점
      (`etl/legal/search.py`의 `__main__` 등, Korean 텍스트를 stdout에 print하는 스크립트)도
      같은 문제가 있는지 점검이 필요하다.

## 입력 데이터

- `ai/agents/appeal_decision_flow/law_refs.py`의 `PINNED_REFERENCES`
- 법령DB(`law_chunks` 테이블, Postgres)

## 산출물

- CI/스케줄러 설정 파일(예: `.github/workflows/*.yml`) 또는 배포 스크립트
- 임계값 조정 근거를 남긴 검증 기록(테스트 케이스 또는 문서)
- cp949 인코딩 점검 결과 및 필요 시 수정된 CLI 스크립트

## 완료 기준

- `reference_drift_check`가 사람 개입 없이 주기적으로 실행되고, 드리프트 발견 시 담당자에게
  알림이 간다.
- 임계값이 최소 1건 이상의 실측(또는 의도적 재현) 케이스로 검증됐다.
- 저장소 내 다른 CLI 스크립트의 cp949 인코딩 위험 여부가 점검·기록됐다.

## 제외 범위

- 드리프트 감지 시 `law_refs.py`(하드코딩 폴백 원문·`PINNED_REFERENCES`)를 자동으로
  갱신하는 것은 범위 밖 — 법률 문구 확정은 여전히 사람이 직접 검토·수정한다. 이 스크립트는
  "무엇을 재검토해야 하는지"만 알려준다.

## Supervisor/Agent 연결

- 이 이슈가 반환해야 하는 결과 스키마: 해당 없음(운영 인프라 작업)
- Supervisor가 이 결과를 사용하는 방식: 해당 없음
- 연결 Agent: `appeal_decision_flow`(MG, `merit_classification_node`)가 간접적으로 영향받음

## 일정

- 시작 예정일:
- 중간 기준일:
- 최종 기준일:

## 검증 방법

- 실행 위치: 저장소 루트
- 실행 명령: `python -m etl.legal.reference_drift_check`
- 기대 결과: exit code 0(전부 정상) 또는 1(재검토 필요 건 존재), 각 조문별 `[OK]`/`[DRIFTED]`/`[MISSING]`/`[ERROR]` 결과 출력
- 통과 기준: 로컬 DB 미기동 등 예외 상황에서도 크래시 없이 결과가 출력됨(cp949 이슈 재발 없음)

## 참고 메모

- 관련 코드: `etl/legal/reference_drift_check.py`, `ai/agents/appeal_decision_flow/law_refs.py`
- 관련 테스트: `test/unit/test_legal_reference_drift_check.py`
- 상세 배경: `docs/architecture/appeal-judgment/업데이트_기록.md` 2026-07-13 항목
