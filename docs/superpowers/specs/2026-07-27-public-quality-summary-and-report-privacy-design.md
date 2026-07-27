# 공개 품질 요약 및 리포트 비공개 경계 설계

## 목적

사용자 응답과 리포트에 노출되는 품질 정보를 일관된 공개 계약으로 정리하고, 개발·운영 확인용 내부 메타데이터가 사용자 화면이나 산출물에 노출되지 않도록 경계를 강화한다. 동시에 법령 최신성, 검색 한계, 부분 결과 여부를 채팅과 리포트에서 같은 기준으로 보여주고, 사고 상황 이미지 삽입 기능의 현재 부재와 확장 경계를 명확히 남긴다.

## 현재 확인된 상태

- `app/web/FrontendAppShell.jsx`는 이미 `law_ground_search` 카드와 `report_quality` 패널을 렌더링하지만, 사용자용 공개 품질 계약이 하나로 정리되어 있지 않다.
- `app/services/agent_node_service.py`의 `retrieval` 메타데이터는 사용자 화면에서 필요 없는 내부 필드까지 포함할 수 있다. 현재 구조상 `embedding`, `data_provenance`, `sql_tables`, `query` 같은 필드가 섞일 여지가 있다.
- `backend/chatbot/repositories.py`는 리포트 상세와 provenance에서 일부 민감 정보를 제거하고 있지만, 사용자 공개 DTO와 운영자용 provenance의 책임 경계가 더 명시적일 필요가 있다.
- 운영자용 `analysis_job_provenance`는 `dataset_version`, `embedding`, `prompt_version`, `release_version` 같은 내부 확인용 정보를 보존해야 한다.
- 사용자 요청 기준으로는 로그인 상태, 내부 로그, 저장소 경로, Python 파일명, storage hop, signed URL, raw 예외 문구 같은 정보가 사용자 응답·리포트·품질 패널 어디에도 보이면 안 된다.
- 사고 상황을 간단히 보여주는 생성 이미지가 리포트에 자동 삽입되는 기능은 현재 코드 기준으로 완성된 형태로 확인되지 않았다. 일부 `scene_diagram` 슬롯은 있으나, 사용자 설명을 받아 이미지를 생성하고 저장·삽입하는 end-to-end 기능은 없다.

## 범위

### 포함

- 사용자 응답과 리포트에서 공통으로 쓰는 공개 품질 요약 계약 정의
- 법령 최신성, 검색 제한, 부분 결과, fallback 여부의 사용자용 표현 정리
- 사용자 노출 payload에서 제거해야 할 비공개 필드 목록과 서버 측 sanitization 경계 고정
- 프런트가 공개 품질 요약을 최소 노출 + 조건부 상세 노출 방식으로 렌더링하도록 정리
- 마스터 체크리스트의 `C`와 `I` 항목을 이번 설계 기준으로 갱신할 근거 정리
- 사고 상황 이미지 기능의 현재 상태 점검 결과와 후속 확장 경계 문서화

### 제외

- 운영자용 provenance API의 제거 또는 축소
- 실제 이미지 생성 provider 연결, 저장, moderation, 비용 승인
- 리포트 문서 템플릿 전면 개편
- OCR/Vision 자체 정확도 개선
- live 배포 환경에서의 사람 smoke

## 선택한 접근

세 가지 접근을 검토했고, 이번 구현은 다음 조합으로 간다.

1. 사용자 화면이 기존 `retrieval`과 `report_quality` 원본을 그대로 읽는 방식은 유지하지 않는다.
2. 서버가 사용자용 공개 품질 DTO를 별도로 생성하고, 프런트와 리포트는 그 DTO만 읽는다.
3. 품질 정보는 항상 최소 요약을 보여주고, stale·partial·fallback·blocked·limitations 존재 시에만 상세 경고를 확장한다.

이 접근을 선택한 이유는 기존 operator provenance와 충돌하지 않으면서, 사용자 노출 필드를 서버가 강하게 통제할 수 있기 때문이다. 프런트에서 조건 분기만 추가하는 방식보다 누출 가능성이 낮고, 채팅과 리포트가 같은 정보를 같은 언어로 보여줄 수 있다.

## 설계

### A. 공개 품질 요약 계약

서버는 사용자용 품질 정보를 하나의 공개 DTO로 정규화한다. 이름은 구현 시점에 기존 구조와 맞춰 확정하되, 역할은 다음과 같다.

- 채팅 응답의 `law_ground_search` insight
- 최종 assistant 응답에 포함되는 결과 패널
- 리포트 상세의 `report_quality`/`reporting_payload`

공개 DTO는 최소한 아래 의미를 포함한다.

- `status`: `ready`, `partial`, `empty`, `blocked`, `failed` 중 사용자에게 보여줄 상태
- `partial_result`: 부분 결과 여부
- `review_required`: 추가 확인 필요 여부
- `freshness`: 기준일, 조회 시각, 최신성 제한 문구
- `retrieval`: 사용된 공개 검색 경로 요약, fallback 여부, 결과 수
- `limitation_count`: 사용자에게 공개 가능한 제한사항 개수
- `limitations`: 사용자에게 보여도 되는 제한사항 목록
- `confidence_label`: 이미 공개돼도 되는 coarse confidence가 있을 때만 사용

이 DTO는 “운영자 확인용 provenance”를 축약해서 넘기는 구조가 아니라, 처음부터 사용자 공개 목적에 맞게 안전한 필드만 새로 조합하는 구조여야 한다.

### B. 항상 최소 노출, 조건부 상세 노출

사용자 화면에는 항상 최소 품질 요약을 노출한다.

- 근거 확인 상태
- 법령 기준일
- 조회 시각
- 부분 결과 여부 또는 추가 확인 필요 여부

상세 제한사항은 아래 조건일 때만 보여준다.

- `partial_result == true`
- `review_required == true`
- `status`가 `partial`, `blocked`, `failed`, `empty`
- freshness warning 또는 retrieval limitation 존재
- limitation count > 0

이 규칙은 채팅 insight 패널과 리포트 action panel 모두에 동일하게 적용한다. 문구 차이로 인해 같은 사건이 화면마다 다르게 보이는 문제를 피하기 위해, 상세 노출 기준은 프런트 임의 규칙이 아니라 서버 계약을 우선한다.

### C. 비공개 경계와 sanitization

사용자 응답, 리포트 payload, 공개 품질 요약에 절대로 포함되면 안 되는 필드는 다음과 같다.

- raw query text
- local path, file path, Python 파일명
- `storage_uri`, `source_storage_uri`, signed URL, bucket/key
- SQL table 이름, DB 내부 식별자, raw `data_provenance`
- embedding provider/model/dimension 세부값
- prompt version/hash, release version, runtime version
- raw exception message, stack trace, provider error body
- 내부 로그 문구, debug blob, trace ID, session cookie, access token

운영자용 provenance는 기존처럼 별도 조회 경로에 남긴다. 다만 사용자 공개 DTO를 만들 때는 “허용 목록 기반 allowlist”를 사용한다. 이미 있는 객체에서 민감 필드를 제거하는 방식보다, 사용자용으로 허용된 필드만 새 객체에 복사하는 방식이 맞다.

### D. 법령 최신성과 검색 한계 공개 방식

법령 검색 품질은 사용자에게 아래 수준까지만 공개한다.

- 근거 검색 상태
- 사용된 공개 backend label
- 매칭된 법령 수
- 조회 시각
- 적용 기준일
- 최신성 제한 안내
- 사용자 행동에 영향을 주는 제한사항

여기서 backend label은 운영 세부를 설명하는 값이 아니라 coarse label이어야 한다. 예를 들어 `postgres_pgvector` 같은 내부 구현명은 그대로 노출하지 않고, 필요하면 `법령 근거 검색`, `기준 데이터 검색`, `대체 검색 경로 사용`처럼 사용자용 문구로 치환한다.

`dataset_version`은 운영자 provenance에 남기되, 사용자에게는 직접 노출하지 않는다. 사용자는 “언제 기준으로 확인했는지”와 “최신 개정이 반영되지 않았을 수 있는지”만 알면 된다.

### E. 리포트와 채팅의 공통 품질 문구

같은 사건에서 채팅과 리포트가 서로 다른 경고를 보여주지 않도록 공개 품질 문구를 공통 helper 또는 공통 서버 payload로 정리한다.

- 채팅은 요약 중심
- 리포트는 요약 + 제한사항 목록 중심
- 둘 다 같은 limitation source를 사용

리포트의 `partial_report`, `review_required`, `analysis_job_status`, `limitations`는 기존 필드를 재사용할 수 있지만, 사용자 공개용으로 다시 정규화한 뒤 사용한다. 기존 `metadata.report_quality`를 그대로 프런트가 해석하는 구조는 이번 범위에서 줄인다.

### F. 사고 상황 이미지 기능 경계

현재 구현 기준으로는 “사용자 설명을 받아 사고 상황 이미지를 생성하고 리포트에 자동 삽입하는 기능”이 없다고 본다. 이번 범위에서는 다음까지만 설계에 포함한다.

- 리포트에 scene visual 슬롯을 둘 수 있는지 확인
- 기존 `scene_diagram` 또는 유사 필드가 있으면 사용자용 설명 카드 수준으로만 연결 가능성 검토
- 이미지 생성 자체는 후속 기능으로 분리

후속 기능으로 확장할 때도 기본값은 `off`여야 한다. 이유는 다음과 같다.

- 사용자 사실과 다른 장면을 과도하게 사실처럼 보이게 만들 수 있다.
- 개인정보, 장소 정보, 차량 정보가 이미지 prompt로 확장될 수 있다.
- 생성 이미지는 법적 산출물의 일부로 오인될 수 있다.

따라서 후속 기능은 “사고 상황 참고 이미지” 또는 “설명용 도식” 수준으로만 취급해야 하며, 공식 판단 근거나 법률 문서의 사실 확정 자료로 다루면 안 된다.

## 기존 구현 및 설계와의 충돌 검토

### 충돌 없음

- 운영자 provenance를 유지하면서 사용자용 공개 DTO를 분리하는 방향은 기존 `analysis_job_provenance` 설계와 충돌하지 않는다.
- 리포트 상세 DTO가 제한된 `report_quality`만 공개해야 한다는 기존 리포트 API 설계와 정합적이다.
- 이미 프런트에 있는 `LawGroundInsightPanel`, `ReportActionPanel`은 렌더링 위치를 유지한 채 데이터 소스만 더 안전한 DTO로 바꿀 수 있다.

### 주의할 점

- 기존 테스트 일부는 `retrieval.embedding`이나 `data_provenance.dataset_version`을 공개 payload에서 기대할 수 있다. 그 경우 operator 경로와 user-facing 경로를 구분해 테스트를 나눠야 한다.
- `matched_laws`의 `source_reference`는 사용자에게 필요한 최소 근거 표기만 유지하고, 내부 chunk ID나 운영 식별자처럼 보이는 값은 표현을 재검토해야 한다.
- 기존 체크리스트에서 “dataset version 노출”처럼 읽힐 수 있는 문장이 있다면, 사용자 노출과 운영 증적을 구분하는 문구로 바로잡아야 한다.

## 변경 대상 파일

- Modify: `app/services/agent_node_service.py`
- Modify: `app/services/analysis_job_query_service.py`
- Modify: `backend/chatbot/repositories.py`
- Modify: `app/web/FrontendAppShell.jsx`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: 공개 품질·리포트·provenance 관련 테스트 파일

## 테스트 전략

- 사용자 공개 DTO가 허용 필드만 포함하는지 서버 단위 테스트를 추가한다.
- `storage_uri`, signed URL, local path, raw query, embedding/model, SQL table, debug metadata가 사용자 payload에 없음을 회귀 테스트로 고정한다.
- law freshness와 retrieval limitation이 사용자용 요약으로 정규화되는지 테스트한다.
- 프런트 테스트에서 최소 요약은 항상 보이고, 상세 제한사항은 조건부로만 보이는지 검증한다.
- 리포트 상세와 채팅 결과가 같은 limitation 문구를 쓰는지 검증한다.
- operator provenance 테스트는 유지하되, 사용자 공개 경로와 기대 필드를 분리한다.

## 체크리스트 반영 원칙

- `C. P1 — 근거 검색 품질과 최신성`은 사용자 최신성 정보의 “노출 여부”가 아니라 “공개 가능한 범위로 안전하게 정규화되었는지”까지 포함해 갱신한다.
- `I. 검증·운영·발표 완성도`는 operator provenance와 사용자 공개 품질 정보가 서로 다른 경계라는 점을 문장으로 분리한다.
- “개발을 위해 필요한 내부 정보가 사용자에게 보이지 않아야 한다”는 요구는 `A-1 개인정보 보호`와 `I`의 공개 품질 정보 항목 모두에 반영한다.

## 완료 기준

- 사용자 응답과 리포트가 공통 공개 품질 DTO를 사용한다.
- 사용자 화면과 산출물에서 내부 로그, 경로, 저장소, debug, provider 세부, raw provenance가 보이지 않는다.
- 법령 최신성·검색 한계·부분 결과가 최소 요약 + 조건부 상세 방식으로 일관되게 노출된다.
- 사고 상황 이미지 자동 삽입은 “현재 미구현, 후속 분리”로 명확히 기록된다.

## 제외 범위

- 생성 이미지 provider 연동
- 이미지 저장·다운로드·문서 삽입 파이프라인
- 운영자 provenance 삭제
- live 배포 확인과 사람 승인 게이트
