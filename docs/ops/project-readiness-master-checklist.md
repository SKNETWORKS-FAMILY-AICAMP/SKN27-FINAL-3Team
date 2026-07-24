# 프로젝트 마스터 체크리스트

이 문서는 평가자 공통 컨펌 사항과 구현·PR 검증 결과를 한 곳에서 관리하는 기준 목록이다. 요약 표로 대체하지 않는다.

최신 통합 검증과 사람 실행 게이트:
`docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`

## 상태 표기

- `[x]` `dev` 머지와 필요한 회귀 테스트·CI를 확인했다.
- `[~]` 구현 또는 PR이 진행 중이다.
- `[ ]` 미착수다.
- `[?]` 코드 흔적은 있으나 실제 종단 검증이 부족하다.
- `[!]` CI 실패, 외부 의존성 또는 정책 결정으로 막혔다.

## PR 공통 최종 게이트 (2026-07-18 이후)

모든 신규 구현 PR은 머지 전에 아래 항목을 반드시 확인한다. 변경 범위에 해당하지 않는 항목은 PR 본문에 근거와 함께 `해당 없음`을 명시한다.

- 변경 파일 목록과 의도하지 않은 파일 수정 여부
- 대상 단위·회귀 테스트
- 타입 검사 또는 린트
- 핵심 기능의 직접 실행 또는 빌드 검증
- 보안·권한·개인정보 경계 변경 여부
- 정책·경로·응답 값의 하드코딩 금지와 모듈화
- PR 설명과 구현 계획·실제 변경의 일치 여부

## 평가자 공통 컨펌 사항 — 유지해야 하는 방향

- [x] 서비스는 법적 정답이나 확정 판단을 대신하지 않고, 근거·한계·다음 행동을 정리한다.
- [x] 교통 분쟁의 문제를 사고 건수가 아닌 근거 탐색 비용과 정보 비대칭으로 정의한다.
- [x] 자료 입력 → 사건 구조화 → 근거 검색 → 한계 표시 → 리포트 생성의 서비스 흐름을 유지한다.
- [x] React, Django, Agent, ETL, 저장소, 인프라가 책임별로 분리된 구조를 유지한다.
- [x] OCR, 기한 확인, 법령 확인, 사유·위험·실익 판단을 조건부 흐름으로 나눈다.
- [x] 검색 결과가 부족하거나 신뢰도가 낮으면 성공처럼 포장하지 않고 partial 또는 failed와 제한사항을 반환한다.

## 보완이 필요한 핵심 축

- [x] 사용자의 주관적 주장과 검증 가능한 객관적 사실을 분리하는 입력 가드레일 — #221, #279
- [~] 법령·과실 기준·판례 데이터의 최신성과 갱신 파이프라인 — 승인 seed manifest·법령 적재·readiness·수동 갱신 절차는 구현, source별 운영 재색인과 실DB 증적은 사람 게이트
- [~] 긴급하고 당황한 사용자를 위한 단계형 UX와 명확한 다음 행동 — PR #296 결과·기한·다음 행동 화면과 역질문 사유 표시 완료. PR #300에서 데스크톱 실제 브라우저의 진입·예시 선택·질문 전송·안전한 응답 확인까지 완료했으며, 모바일·첨부·리포트 다운로드 실사용성 검증은 남음
- [~] OCR·영상·검색·생성형 결과의 정확도 검증 지표와 테스트셋 — 법령 RAG 평가 완료, OCR/Vision 실데이터 품질은 #28·#39·#170
- [ ] 채팅이 길어져도 사건 맥락을 잃지 않는 요약·압축·상태 관리
- [x] 서비스 범위, 판단 불가 사례 처리, 법률 서비스 경계의 명문화 — #264
- [x] JSON/DB 구조가 아닌 사용자용 판단 카드·근거·주의사항 중심의 결과 화면 — PR #296 통합, UI 계약 테스트·Vite build
- [x] 리포트/이의신청 문서와 보험사 제출 자료까지 연결하는 실사용 가치 — #238, #279

## A. P0 — 안전한 판단의 입력 경계

### A-1. 개인정보 보호

- [x] 채팅 입력 개인정보 보호 경계 도입
- [x] PII 마스킹 및 민감 입력 보호 보강
- [x] OCR 결과물 개인정보 경계 보강 — #210
- [x] 분석 API에서 입력 보호를 요청 예약·지문 생성보다 앞에 배치 — #217 / PR #218
- [x] 분석 API 거부 응답을 일반 장애가 아닌 안전한 4xx 계약으로 정리 — #217 / PR #218
- [x] 보호 처리 파생 필드가 멱등성 지문을 바꾸지 않도록 보완 — #217 / PR #218
- [x] 채팅 메시지·에이전트 실행 진입점에서 입력 보호를 부수 효과보다 앞에 배치하고 안전한 4xx로 변환 — #219 / PR #220
- [x] 보고서·다운로드 개인정보 노출 회귀 테스트 — #226 / PR #228 (운영 로그 경계는 별도 작업)
- [x] 운영 로그 개인정보 노출 회귀 테스트 — #249 / PR #250
- [x] 프롬프트 인젝션과 비신뢰 OCR/RAG 자료가 시스템 지시·도구 호출 조건으로 작동하지 않도록 하는 경계 — #251 / PR #252

### A-2. 객관적 사실과 주관적 주장 분리

- [x] 사건 입력을 검증 가능한 사실, 사용자 주장, 미확인·추정으로 구조화 — #221 / PR #222
- [x] Supervisor 입력 스키마에 `fact`, `claim`, `unknown`, `evidence_source` 구분 추가 — #221 / PR #222
- [x] 에이전트 호출 전 근거 없는 주장을 검색 조건·과실 판단 근거로 단정 사용하지 않도록 가드레일 추가 — #221 / PR #222
- [x] 응답과 보고서에서 사용자 진술, 첨부자료 확인, 추가 확인 필요를 구분 표기 — #221 / PR #222
- [x] 증거 부족 시 과실 판단 대신 필요한 자료를 요청하는 역질문 연결 — #221 / PR #222
- [x] 주관적 진술·상충 진술·증거 없는 진술 회귀 테스트 — #221 / PR #222
- [x] Supervisor 입력 스키마 → 역질문 → 호출 계획 → 에이전트 결과 취합 → 사용자 응답의 E2E 계약 테스트 — #229 / PR #230
- [x] Supervisor LLM/fallback 단계에서도 에이전트 패키지의 첨부파일을 `attachment_id` 선택자로만 보관하고, 임의 메타데이터·원문을 제거하는 사전 정규화 — #231 / PR #232
- [~] 생성형 에이전트의 실제 연결, mock/대체 모드, 실패 시 사용자 응답을 분리한 런타임 스모크 테스트 — #247. `feat-supervisor-contract-p0`에서 운영 fallback과 검증 계약을 `supervisor_conversation_state.v2`로 일치시키고, Registry 기반 owner/required input 주입, strict Structured Output, 실제 `submit_message()` 4개 라우팅 회귀, 안전한 실패 사유 로그, 배포 Worker loop를 통과하는 단일 production runtime smoke 승격 게이트를 구현했다. 독립 리뷰에서 발견한 nested `slot_state` 권한 침범, inline worker 우회, malformed plan 예외, invalid candidate 재사용도 회귀 테스트와 함께 수정했다. 로컬 집중 회귀 `159 passed`, 전체 `test/` `1000 passed, 38 skipped`, Django `370 tests`, Compose config, Vite build는 통과했으며, 실제 OpenAI/Agent/Reporting 유료 스모크는 공개 승격 직전 명시 승인 후 `smoke_supervisor_conversation_runtime` 1회로 검증해야 하므로 완료로 표시하지 않음

### A-3. 권한과 소유권 경계

- [x] 다른 사용자의 세션·분석 작업·첨부파일·보고서에 접근할 수 없는지 E2E 권한 회귀 테스트 — #254 / PR #255
- [x] 비회원·로그인 사용자 전환과 세션 소유권의 일관성 검증 — #256 / PR #257
- [x] 유출·복제된 `guest_id`만으로 비회원 세션의 로그인 결합이나 접근이 가능하지 않도록 서버 검증 가능한 guest credential 경계 도입 — #258 / PR #260

## B. P0 — 서비스 범위와 법률 안전성

- [x] 정답을 대신 내리지 않고 판단을 돕는다는 방향 유지
- [x] 검색 실패·낮은 신뢰도 시 제한사항을 반환하는 기반
- [x] 판단하기 어려운 사례의 표준 처리 방식 — #264
- [x] 서비스 범위 명문화: 차량 간 사고, 차량-보행자, 차량-자전거, 차량-시설물, 과태료·범칙금, 민사상 과실 검토, 형사상 검토 — #264
- [x] 범위별 지원 / 참고 정보만 제공 / 지원 제외 정책 — #264
- [x] 법률 자문이 아닌 정보·근거 정리 서비스임을 화면과 보고서에 일관되게 고지 — #264
- [x] 제출기한·이의신청 기한·긴급 행동을 결과 상단에서 별도 강조 — #264
- [x] 판단 불가 또는 근거 부족 사례의 안전한 안내 문구·다음 행동 표준화 — #264

## C. P1 — 근거 검색 품질과 최신성

### C-1. 검색 품질

- [x] 법령 근거 검색 계약 및 흐름 보완 — #208
- [x] RAG, pgvector, Neo4j 기반 검색 구조
- [x] 검색 결과 부족 시 partial/failed 처리 기반
- [x] 선택된 RAG 도메인의 런타임 예외를 개별 `failed` 결과로 격리하고, 정상 도메인 결과는 `partial`로 유지하는 회귀 테스트 — PR #275
- [x] ES·lexical fallback 제거와 법령·심의사례 pgvector-only 런타임 경계 문서화 — #291
- [x] 법령·심의사례 필수 readiness 및 공통 임베딩 공간(`openai/text-embedding-3-large/1024`) 불일치 차단 계약·회귀 테스트 — #291
- [x] 법령 RAG pgvector 전환 기준, 임베딩·조문 chunk 품질 평가와 RAGAS 증적 정리 — #280, #282, #285, #289
  - 전체 A/B 수치, phase·RAGAS latency, 실행환경, 자동화 테스트 증적: `docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md`의 `legal-ab-018-pgvector-gates-20260722` 섹션
- [x] 대표 사고 시나리오별 검색 정확도 평가 세트 — `etl/fault_cases/evaluation`의 complete30·qrels·공식 평가자산 manifest
- [x] 검색 결과의 근거 출처·적용 시점·조회 시각·한계 표시 — 공개 결과 계약, #279 E2E, 법령 `effective_at`·`retrieved_at`과 결과 화면
- [x] 유사도 점수만으로 결론을 내리지 않도록 하는 근거 검토 기준 — 저점수 차단, 필수 근거 검증, 유사사례 advisory 계약 테스트

### C-2. 데이터 최신성

- [x] ETL·수집·색인 기반과 승인 seed bundle manifest·무결성 검증 존재
- [!] P0 법령 `data-seed`는 법령 API secret 또는 검증된 seed bundle이 없으면 실제 적재 성공을 주장할 수 없음. 0건 수집은 빈 embedding·후속 단계 오류로 진행하지 않고 즉시 실패해야 함
- [~] P0 승인 seed bundle의 해시·크기·row·embedding 공간 검증, 법령 atomic load, release marker, 배포 전 readiness는 자동화. 판례·심의사례 source별 재임베딩은 기존 #48·#50 파이프라인과 운영 데이터/비용 승인이 필요한 사람 게이트
- [ ] P0 심의사례 1536차원 데이터 백업 후 `text-embedding-3-large/1024`로 재임베딩하고, 법령·심의사례 공통 공간 readiness와 대표 쿼리 latency를 운영 DB에서 검증 — #291
- [~] P0 적재 전 manifest/hash/row/schema/embedding 검증, 법령 atomic load, 적재 후 count·index·대표 검색 smoke와 실패 시 release marker 미생성은 구현. #299 첫 단계의 법령 source별 공통 `run_summary` v2와 freshness validation은 PR #301로 `dev` 병합 완료(`8cc2fc8`); 판례·심의사례 통합과 운영 DB 증적 보관은 남음
- [~] 법령·과실 기준·판례별 최신성 메타데이터 — 법령 source별 provider·적용일·수집/검증 시각·data version은 #299 첫 단계 PR #301로 병합 완료, 과실 기준·판례는 남음
- [~] 수집 시점, 마지막 검증일, 출처, 적용 시점 저장 — 법령 `source_summaries` 계약과 결정적 `dataset_version` 구현, 운영 DB 보관은 남음
- [~] 정기 갱신 스케줄 또는 운영 수동 갱신 절차 — 법령 수동 실행·검증·실패 후 재실행 runbook 구현, 정기 스케줄은 남음
- [~] 갱신 실패·오래된 데이터·출처 불명 데이터 경고 — `missing_sources`·`failed_sources`·`stale_sources` 자동 차단 CLI 구현, CloudWatch 알림 연결은 남음
- [ ] 사용자 결과에 기준일과 최신성 제한사항 표시
- [ ] 변경된 법령·과실 기준 회귀 테스트

## D. P1 — 자료 분석 정확도

### D-1. OCR

- [x] 교통사고 OCR 런타임 보강 — #206
- [x] OCR 개인정보 경계 보강 — #210
- [?] OCR 모델 비용·성능·속도 비교 기반 — 이혜림 후순위: 실제 Provider 실행과 집계 결과 필요
- [ ] 기관 양식·저해상도·촬영 각도·손상·흐림 문서 평가 세트 — 이혜림 후순위: 정답지 포함 Golden set 필요
- [ ] 문서 유형별 OCR 및 필드 추출 정확도 측정 — 이혜림 후순위: 실제 정답 대비 평가 결과 필요
- [~] 저신뢰도 시 직접 수정·확인 요청 UX와 확인 전 후속 분석 차단은 구현. 재촬영 안내의 실기기 사용성 검증은 남음
- [x] 기한·금액·처분번호 등 중요 필드의 사용자 확인 단계 — OCR 확인 카드와 공식 문서 4항목 최종 확인 게이트

### D-2. 블랙박스·영상 분석

- [~] #294 / PR #295: 채팅 drag-and-drop과 MP4/MOV 업로드 계약, scan-ready 영상의 `vision_media_analysis` sync adapter, 안전한 실패 코드, 근거 검색 handoff 구현. 최신 커밋 CI와 실제 checkpoint 환경 smoke는 병합 전 확인 필요
- [?] 실제 Vision checkpoint·의존성·실행 장치가 준비된 환경에서 원본 블랙박스 영상으로 handoff를 생성하는 운영 smoke는 아직 미검증. 모델 품질 개선은 이 작업 범위에서 제외
- [ ] 진로 변경, 차선 침범, 신호 위반, 정지·감속, 충돌 직전 거리·상대 위치, 시야 가림·판단 불가 구간을 다루는 비전 파이프라인
- [x] 단순 객체 탐지와 사고 쟁점 분석을 구분하는 출력 계약 — `analysis_kind`, `event_candidates`, `not_determined_by_vision`
- [x] 프레임 추출·시간축·저품질/실패 영상 처리 — key frame timestamp와 decode·timeout·dependency 안전 실패 계약
- [x] 영상 결과의 신뢰도·근거 프레임·한계 표시 — score·key frame·uncertainty·limitations 공개 DTO 계약

## E. P1 — 사용자 경험과 결과 화면

- [x] 비회원 상담, Google 로그인, 파일 첨부, 분석 진행, 내 사건, 이력, 리포트 흐름의 기반
- [~] 긴급 상황에서 UI가 충분히 단순하고 직관적인지 검증 필요 — 2026-07-23 PR #300 실제 데스크톱 브라우저 점검에서 초기 화면, 입력창 노출, 예시 질문 선택, 질문 전송, 응답 표시를 확인. 정량적 사용성·모바일·키보드·스크린리더 검증은 아직 미실시
- [x] DB/JSON 중심 노출을 사용자용 단계형 화면으로 정리 — PR #296의 상담·결과·마이페이지·히스토리·리포트 화면과 Vite build·UI 계약 검증
- [x] 상담 화면 병합 회귀와 무근거 응답 품질 보강 — PR #300: 정의되지 않은 빠른 질문 변수로 인한 흰 화면 제거, 입력창을 첫 화면 안에 배치, 과태료 질문 라우팅 보강, 검증된 법령 검색이 없을 때 확정 판단 대신 기관·기한·증빙·다음 행동을 안내하는 안전한 fallback 적용. 병합 전 CI 사용자 확인, 집중 회귀 `48 passed`, Ruff 통과, Vite production build 성공
- [ ] 입력 단계 UI: 사고 유형 선택, 사실관계 입력, 주장 입력, 첨부자료 업로드, 누락 정보 확인 — 2026-07-22 점검: 첨부자료 업로드(첨부 목적 select)만 구현. 사고 유형 선택, 사실관계·주장 입력은 구조화된 화면 없이 자유 텍스트 채팅에 의존
- [x] 결과 화면 UI: 검토 상태, 판단 근거, 참고 법령·사례, 진술/확인 사실 구분, 주의사항, 제출기한, 다음 행동 — #279 `user_claims`와 확인 사실을 별도 패널로 표시
- [x] 역질문 UX에서 부족한 정보와 필요한 이유를 짧고 명확하게 표시 — `FollowUpNote`의 필수·선택 그룹과 항목별 `reason` 렌더링
- [x] 분석 진행·대기·부분 완료·실패 상태를 사용자 언어로 표시 — 2026-07-22 점검: `reportStatusLabel`/`caseStatusLabel`/`attachmentStatusLabel` 함수가 draft·running·partial·success·failed를 "작성 중"/"분석 중"/"보완 필요"/"분석 완료"/"확인 필요" 등으로 변환. 모든 노출 지점이 이 함수를 거치는지 전수 조사는 하지 않음
- [ ] 모바일/태블릿과 접근성 점검 — 2026-07-22 점검: `max-width` 반응형 브레이크포인트(720/860/900/1000/1280px) 다수 존재하나 실기기 테스트·키보드 내비게이션·스크린리더 점검은 없음. 오늘 다크 테마 전환으로 `--subtle`/`--muted`(반투명 텍스트) 명도 대비를 아직 검증하지 않아 우선 점검 필요

### E-6. 채팅창 drag-and-drop 첨부 분류와 실제 Agent handoff — P0

- [x] #294 / PR #295: 채팅 입력 drop zone, JPEG/PNG/WebP/PDF/MP4/MOV 허용 정책, 업로드 목적·MIME 불일치 차단, 스캔 상태 표시, 지원하지 않는 파일의 사용자용 재시도 안내와 최신 회귀·Vite build
- [x] 고지서 PDF/이미지는 `fine_notice_analysis`의 OCR 1차 결과를 사용자 확인 카드로 표시하고, 확인 전 법령 검색·이의절차·문서 생성을 차단. 확인 후에만 `law_ground_search`와 `appeal_decision_flow`을 계획에 추가
- [x] 블랙박스 영상은 기존 Vision pipeline adapter를 통해 `text_ml_case_search`·`law_ground_search`로 handoff. checkpoint 부재·의존성·decode·timeout은 안전한 실패 코드와 다음 행동으로 반환
- [~] 제공된 `2026-07-23-runpod-serverless-vision-design.md`를 기준으로 PR #304 (`feat-runpod-serverless-vision`)에서 `VISION_RUNTIME_PROVIDER=runpod`, HTTPS signed URL, `/run`·`/status` polling, job ID 재사용, stable remote error code, 격리·정리형 Serverless worker와 배포 환경 계약을 구현. PR #303과 병합 커밋 `5f3728e`까지의 운영 관측 기반 위에서 local/mock 계약을 검증했고, 전체 `test/` `960 passed, 38 skipped`, Django `368 passed`, Dockerfile build check도 통과. restricted key 발급·유료 RunPod Endpoint 생성·모델 artifact 승인·비식별 실영상 smoke는 사람 게이트이므로 아직 운영 연결 완료로 표시하지 않음
- [x] 사고 사진(`accident_scene`)은 서버 저장 문서 분류를 사용자가 `attachment_id`로 확인한 뒤 사진 전용 사례·법령 검색 계획으로 연결. 클라이언트 분류 주입, 오래된 분류, 사진의 Vision 영상 경로 오호출을 회귀 테스트로 차단
- [ ] PDF 고지서, 사고 사진, 블랙박스 영상, 지원하지 않는 파일, 분류 불명 파일의 다섯 E2E 시나리오를 실제 adapter 경계까지 검증. mock fixture 통과만으로 실제 Vision 연결 완료로 판단하지 않음

## F. P1 — 채팅 맥락·사건 상태 관리

- [x] `conversation_summary` 필드와 상담 요약 기반 존재
- [?] 장기 멀티턴 사건 상태를 안전하게 압축하는 체계는 미검증
- [x] #224 채팅 세션 기반 역질문 상태 저장·서버 우선 복원 계약 / PR #225
- [ ] 당사자·차량, 일시·장소, 사고 유형, 확인 사실, 사용자 주장, 첨부자료, 검색 근거, 미확인 항목, 기한, 진행 단계를 담는 구조화된 사건 메모리
- [ ] 오래된 대화 압축 시 판단 근거·출처·미확인 사실 보존
- [ ] 요약 과정의 정보 변경·소실 회귀 테스트
- [x] 사건별 채팅 세션·분석·리포트 연결 — canonical 소유권·대표 흐름 E2E #279
- [x] 채팅 세션/히스토리 API 공식 OpenAPI 계약화 — #270, #274

## G. P1 — 리포트와 실사용 가치

- [x] 이의신청서 생성 에이전트 기반
- [x] 보고서 핸드오프 및 다운로드 기반
- [x] 상담·OCR·법령 검색 결과가 실제 문서에 올바르게 연결되는 canonical E2E 검증 — #279
- [x] 리포트 목록·상세·다운로드 API 계약 및 문서 E2E — #226 / PR #228 (생성 POST는 deferred 유지)
- [x] 이의신청서 초안, 사실관계 정리, 보험사 제출 자료를 문서 종류로 분리 — #245
- [x] 문서 생성 전 사용자 최종 확인: 사실관계, 관할기관, 기한, 첨부자료 — #241 / PR #242
- [x] DOCX 전용 한글 렌더링, 개인정보 마스킹, 권한 검증 및 PDF 사용자 다운로드 제거 — #238
- [x] fine_notice·traffic_accident 공식 이의신청서의 DOCX 다운로드와 appeal gate E2E, 일반 분석 리포트의 다운로드 비제공 — #238
- [ ] 유료화 후보는 기능 완성·안전성 검증 후 별도 기획 검토

## H. API 계약화 진행 현황

- [x] 인증·세션 계약 — #212
- [x] 파일 API 계약 — #214
- [x] 분석 작업 생성·조회·결과 계약 — #216
- [x] 분석 입력 프라이버시 거부 응답 — #217
- [x] 리포트 조회·다운로드 API 계약 — #226 / PR #228 (생성 POST는 deferred 유지)
- [x] 채팅 세션·메시지·저장 API 계약 — #270: shadow OpenAPI, 200/202/503 채팅 응답, guest credential·소유권 회귀 검증
- [x] 마이페이지 API 계약 — #272: shadow OpenAPI, owner/session 소유권·raw guest ID 차단·limit 기본값 폴백 회귀 검증
- [x] 히스토리 API 계약 — #274: shadow OpenAPI, App JWT·guest credential 경계와 owner/session/job 소유권 회귀 검증
- [x] 에이전트 노드 API 계약 — #268: 공개 분석 결과 DTO의 Worker/Supervisor 내부 필드 차단 및 API·소유권 회귀 검증
- [x] 전체 오류·권한 오류·부분 결과 응답 공통 계약 정리 — #277: 401/403 의미, 채팅 partial/unavailable, 분석 결과 pending OpenAPI·런타임 회귀 검증

## I. 검증·운영·발표 완성도

- [~] AWS 저비용 파일럿 기반 — 서울 리전 Free 플랜에서 상태 버킷과 65개 기반 리소스를 apply하고, Free 플랜 허용 8 GiB x86 `m7i-flex.large`, 비공개·암호화 Single-AZ `db.t4g.micro` PostgreSQL, S3·ECR·SSM·CloudWatch·SNS·월 $50 Budget을 실제 생성했다. RDS 자동 백업 1일·삭제 방지·최종 snapshot 유지, SNS 이메일 활성 ARN, EC2 상태검사·SSM Online, Docker Compose·IMDS 방화벽·4 GiB swap과 재시작 복구를 확인했으며 최종 `terraform plan`은 `No changes`다. Amazon Linux `curl-minimal` 충돌은 user-data에서 중복 `curl` 설치를 제거하고 계약 회귀 `70 passed`로 고정했다. 애플리케이션 release 배포·운영 DB/RAG smoke, 실제 ALARM/OK 수신 확인, 검증 후 RDS 정지/재기동 실증은 남음
- [x] 보안·DB·OAuth·LLM·RAG·워커·파일 검사·객체 저장소 점검 기반
- [x] PR 단위 CI 체계
- [x] 대표 사용자 흐름 E2E: 자료 입력, 사실/주장 분리, OCR, Supervisor 계획, 법령·판례 검색, 한계 표시, 리포트 생성·다운로드 — #279
- [x] 실제 데스크톱 브라우저 상담 스모크와 런타임 회귀 보강 — PR #300, `dev` 병합 커밋 `3fd0fcdddbc2b8e30e7993dbcfe6376535bec68a`
- [ ] OCR·검색·생성형·영상 분석 품질 지표와 결과 공개 방식
- [~] #294 / PR #295: `job_id`·`execution_id` 기반 Agent 실행 metadata와 handoff를 보존하고 원문·OCR 전문·경로·비밀값을 raw execution metadata에서 제거. #299 두 번째 단계에서 `show_analysis_job_provenance`와 운영 runbook, invocation·retrieval 연결 및 개인정보 비노출 회귀를 구현; 실제 운영 공급자 장애 trace 실증은 남음
- [~] 법령·판례 적재와 Agent 호출의 대표 성공·부분 실패·실패 시나리오에서 run/trace 로그가 실제 생성되고, 운영자가 관련 산출물·실패 단계·다음 조치를 추적할 수 있는 회귀 테스트와 조회 절차 제공 — Worker 성공 통합과 partial operator 조회 회귀, 안전한 오류 코드 조회는 구현. 실제 운영 법령·판례·외부 공급자 실패 증적은 남음
- [~] 외부 서비스 장애, 데이터 갱신 실패, 큐 적체의 운영 관측 — PR #303으로 `dev` 병합 완료(`5f3728e`). `operational_health.v1`, 단발·반복 조회 command, 개인정보 없는 queue·lease·retry·Worker/provider 실패·법령 freshness 집계, 전용 `ops-monitor`, CloudWatch metric filter·alarm과 운영 runbook 구현. 실제 AWS ALARM/OK·SNS 수신 증적은 사람 게이트
- [~] 분석 작업 중복 요청·멱등 재시도·Worker lease/timeout 계약과 회귀 테스트는 완료. 사용자 직접 취소 API는 파일럿 공개 범위에서 제외
- [~] 첨부파일 보존 기간·명시 삭제·물리 purge·재시도와 HistoryEvent 접근 감사는 구현. 대화·OCR·보고서별 운영 보존 기간 최종값은 개인정보 처리방침 승인 필요
- [~] 결과 재현을 위한 모델·프롬프트·에이전트 버전과 검색 데이터 기준일 기록 — PR #301의 법령 `run_id`·`dataset_version`·source별 `data_version`에 이어 `feat-299-execution-provenance`에서 Supervisor model·prompt version/hash, Agent runtime·adapter·release version, embedding model, 검색 dataset version·검증/기준/조회 시각 저장과 `job_id` 조회를 구현. 운영 release 값 주입과 실제 DB smoke는 남음
- [~] Worker lease, bounded timeout, 사용량 제한, 8GiB 파일럿 capacity preflight와 회귀 테스트는 완료. CloudWatch 초기 임계값·heartbeat·queue age·stale lease·Worker/provider·법령 데이터 alarm을 Terraform 변수로 구현. 실제 부하 수치 기반 최종 임계값과 SNS ALARM/OK 수신은 운영 환경 검증 필요
- [x] 배포 전 체크리스트와 롤백 절차 — `docs/ops/release-checklist.md`, `docs/ops/rollback-plan.md`, AWS pilot 자동 롤백·회귀 테스트
- [ ] 발표자료 오타·용어·서비스 범위 최종 검수

## J. 1차 운영 배포 — RAG 부트스트랩과 공개 승격

- [x] 운영 RAG 시드 묶음 생성·이중 검증 — 법령 청크 97,394개, OpenAI `text-embedding-3-large` 1024차원 임베딩 97,394개, 심의사례 904개, 법제처 공식 판례 88건·343개 청크. `production_rag_seed_manifest.v1` build·verify·dry-run 통과, 승인 대상 SHA-256 `279e78cf70db05156c316ddfbddff2eb4c08ea8c199fcb1df1f0f40600eeed6c`
- [x] 신규 RDS source-specific pgvector 부트스트랩 자동화 — 비용 절약형 A안대로 별도 RDS 없이 `law_db`에 심의사례 전용 테이블과 canonical OpenAI 1024차원 partial HNSW를 구성한다. 유지보수 역할의 스키마 적용 → 앱 최소 권한 부여, manifest-bound 904청크/226문서 idempotent loader, 본문 hash 변경 시에만 재임베딩, 유료 호출 명시 승인, 정확한 행 수·인덱스 확인과 private stage 실패 정리를 구현했다. 관련 계약 `192 passed`, 전체 `test/` `979 passed, 38 skipped`, Django `368 tests`, PowerShell parser·Vite production build·Compose config 통과
- [x] 운영 RAG bundle 로컬 적재 전 검증 — 실제 비공개 bundle의 심의사례 904개/226문서를 DB 접속 전에 전부 파싱했고 중복 ID·필수 필드·짧은 본문·음수 순서를 차단했다. 승인 플래그가 없으면 Terraform·S3·SSM·DB·OpenAI 호출 전에 종료하도록 고정
- [ ] 심의사례 904개 OpenAI 임베딩 1회 유료 호출 승인 및 실행
- [ ] 법령·심의사례 pgvector 실제 RDS 적재와 HNSW·행 수·공유 embedding space 확인
- [ ] 비공개 initial stage에서 법령 검색·유사 심의사례 검색 smoke 통과 및 `.production-rag-seed.complete` 기록
- [ ] RunPod restricted API key·Endpoint ID를 private runtime에 입력하고 비식별 실영상 success·partial·failure·timeout smoke 수행 — 사람 게이트
- [ ] Google OAuth 최초 live smoke용 일회용 code 발급·교환·재사용 거부 확인 — 사람 게이트
- [ ] 실제 고지서 fixture를 Clean S3 `canonical/acceptance/`에 업로드하고 유료 non-DL/Supervisor acceptance smoke 승인 — 사람 게이트
- [ ] HTTPS 공개 승격 후 상담·OAuth·첨부·분석·리포트 조회·다운로드 실제 브라우저 QA
- [ ] CloudWatch ALARM→OK와 SNS 이메일 수신, Budget 영향, EC2·RDS 정지/재기동 복구 확인

## K. 2차 고도화 — S3 + CloudFront 정적 프런트엔드 전달

### K-1. 설계·비용·Terraform

- [x] 2차 목표 구조 설계 — React/Vite는 private S3 + CloudFront, `/api/*`는 기존 EC2 HTTPS origin. ALB·NAT Gateway·ECS/Fargate는 추가하지 않음
- [ ] 계정 CloudFront Free Plan/무료 사용량, 요청 수·전송량·S3 GET·저장·Route 53/도메인·로그·선택적 WAF 비용 재확인
- [ ] `infra/terraform-pilot`에 private frontend S3, encryption, versioning, Block Public Access, OAC, bucket policy, distribution, cache/origin request policy, outputs 구현
- [ ] us-east-1 ACM provider alias, Route 53 alias 또는 외부 DNS용 정확한 CNAME/TXT output 구현
- [ ] 기존 SNS·Budget 재사용과 CloudFront 4xx·5xx·origin latency·S3 AccessDenied·배포 실패 지표/알람 구현
- [ ] Terraform fmt·validate·계약 테스트·plan 통과. 생성/변경/삭제·예상 비용·다운타임·DNS 영향·롤백 가능성을 사람이 검토한 뒤 apply

### K-2. 정적 배포·캐시·SPA

- [ ] 해시 asset은 1년 immutable, `index.html`은 no-cache로 분리하고 index를 마지막에 업로드
- [ ] 전체 `/*` invalidation 대신 `/index.html`과 필요한 최소 경로만 무효화
- [ ] `/api/*`는 managed caching-disabled/TTL 0, 실제 Authorization·Content-Type·cookie·query·guest/session header만 전달
- [ ] CloudFront Function으로 확장자 없는 프런트 route만 `/index.html`로 rewrite하고 `/api/*` 및 누락 asset 404는 보존
- [ ] production build, 이전 dist 보관, 안전한 S3 대상 검증, 업로드, distribution 완료 대기, smoke, 이전 artifact 복원 자동화
- [ ] GitHub Actions 도입 시 OIDC, production environment 승인, 장기 AWS access key 금지, artifact·롤백 로그 보존

### K-3. 도메인·보안·OAuth

- [ ] 소유 도메인 확정 — `app.<domain>`은 CloudFront, `origin.<domain>`은 EC2+Caddy origin으로 분리 — 사람 게이트
- [ ] CloudFront viewer 인증서 us-east-1 ACM 발급과 DNS validation — 사람 게이트
- [ ] EC2 443을 CloudFront origin-facing prefix list로 제한하고 private origin header를 Caddy/HAProxy에서 검증
- [ ] origin header를 Git·access log에 남기지 않고 Terraform state·S3 state bucket·SSM SecureString 접근을 최소화
- [ ] Google OAuth origin/redirect, Django allowed hosts, CORS/CSRF, secure cookie·SameSite, trusted proxy, `X-Forwarded-Proto`를 canonical CloudFront origin으로 전환 — 사람 게이트 포함
- [ ] 장애 관리 경로를 제외한 EC2 Elastic IP 직접 우회 접근 차단 및 Caddy 인증서 갱신 경로 확인

### K-4. 2차 브라우저 QA·롤백 완료 게이트

- [ ] `/`, 실제 JS/CSS, 누락 asset, React deep-link, 누락 route 응답과 Cache-Control·Age·Via·X-Cache 검증
- [ ] API 정상·401·403·404·OPTIONS·POST가 정적 `index.html`로 변환되지 않고 cache hit가 발생하지 않는지 검증
- [ ] 비회원 상담, 질문 전송, Google 로그인, 첨부 업로드, RunPod 진행 상태, 리포트 조회·다운로드, 새로고침, 모바일 viewport 실제 브라우저 QA
- [ ] 사용자별 인증 응답과 리포트·첨부가 공유 캐시에 저장되지 않고 mixed-content/콘솔 오류가 없는지 확인
- [ ] 이전 dist 복원·index invalidation·브라우저 smoke와 DNS TTL 기반 기존 EC2 진입점 복구 연습
- [ ] CloudFront distribution은 즉시 삭제하지 않고 비활성화·관찰 후 제거하며 RDS·Clean/Quarantine S3·첨부·리포트는 보존

## 권장 실행 순서

1. [x] #219 채팅·에이전트 실행 입력 보호 경계 / PR #220
2. [x] #221 / PR #222 사실·주장·미확인 정보 분리 가드레일
3. [x] #223 / PR #223 서비스 범위·판단 불가 사례·기한 강조 정책
4. [x] #224 / PR #225 사건 메모리·역질문·채팅 세션 계약
5. [x] #226 / PR #228 리포트 조회·다운로드 API 및 문서 E2E (생성 POST deferred)
6. [ ] 근거 최신성 및 검색 품질 평가
7. [ ] OCR 품질 평가 후 영상 분석 범위 결정
