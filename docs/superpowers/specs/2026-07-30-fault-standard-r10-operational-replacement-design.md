# Fault Standard R10 Operational Replacement Design

## 1. 목적

현재 `etl/fault_cases/rag_runtime/fault_standard` 인정기준 RAG를
`etl/fault_cases/standard_TEST`에서 검증된 R10 릴리스 기반으로 교체한다.

이번 작업의 목적은 다음 세 가지다.

1. R10의 Qwen3-Embedding-4B 검색, PostgreSQL 구조 판정, Neo4j 관계 판정,
   Calculator V2를 현재 운영 RAG 계약 안으로 이식한다.
2. Rule을 정상 선택한 요청에는 사고 조건이 일부 부족하더라도 항상 기본 과실비율
   숫자를 반환한다.
3. 기존 구현과 R10을 독립적으로 운영하고 즉시 되돌릴 수 있는 전환 구조를 만든다.

선택한 방식은 세 번째 권장안인 **운영 코드 이식 + 격리된 저장소 + 기능 플래그
전환**이다. `standard_TEST` 폴더를 운영 중에 직접 import하거나 기존 DB를 제자리에서
덮어쓰지 않는다.

## 2. 기준 릴리스와 금지 대상

운영 이식의 유일한 기준은 다음 R10 릴리스다.

- Release ID: `fault_standard_r10_9e86695d05190c6d`
- Manifest:
  `etl/fault_cases/standard_TEST/11_ARTIFACTS/10_RECOVERY/R10_RELEASE/fault_standard_r10_release_manifest.json`
- 상태: `EXPERIMENTAL_PASS_NOT_PRODUCTION_READY`
- Rule: 277
- Search document: 6,145
- Embedding: 6,175
- Embedding model: `Qwen/Qwen3-Embedding-4B`
- Model revision: `5cf2132abc99cad020ac570b19d031efec650f2b`
- Dimension/normalization: 2,560 / L2

다음 결과물은 품질 회귀가 확인되었으므로 운영 이식에 사용하지 않는다.

- R10 Next: `EXPERIMENTAL_FAIL`
- R20: `R20_QUALITY_FAIL`
- `standard_TEST` 안의 invalid iteration 및 failed candidate

R10의 COMPLETE30 결과는 C 방식 Hit@1 73.3%, Recall@50 100%,
Final Ratio Exact 60%다. 따라서 이 서비스의 숫자는 자동 법률판단의 확정값이 아니라,
이후 과실비율 에이전트가 심의사례와 판례 근거를 결합할 때 사용하는 인정기준
기준값(anchor)이다.

## 3. 범위

### 포함

- R10 릴리스 manifest와 필수 artifact의 hash/count 검증
- R10 전용 PostgreSQL 스키마와 Neo4j 데이터셋의 격리 적재
- 현재 `RagRequest -> DomainSearchResult` 계약을 유지하는 R10 어댑터
- R10 C 검색 경로와 단계별 B/A 강등 처리
- Rule 기본비율을 이용한 강제 숫자 반환 정책
- 검색, 선택, Variant, 당사자 매핑, 계산의 추적 정보
- legacy/R10 기능 플래그, shadow 비교, 전환, 롤백
- 단위, 통합, COMPLETE30, 장애 주입, 계약 회귀 테스트

### 제외

- 심의사례 RAG V2 교체
- 판례 NEW++ 서비스 구현
- 심의사례의 A/B 또는 청구인/피청구인 비율을 사용자/상대방 방향으로 변환하는 코드
- 인정기준, 심의사례, 판례를 합쳐 최종 범위를 만드는 과실비율 에이전트
- Supervisor 최종 출력 스키마 변경
- R10의 원천 PDF/Core/Search artifact 자체 재생성
- R10 Next 또는 R20 개선 작업

심의사례 방향 보정과 최종 범위 계산은 이후 별도 설계에서 과실비율 에이전트의
책임으로 구현한다.

## 4. 접근법 비교와 선택 이유

### 접근 1: 현재 파일을 R10 코드로 직접 덮어쓰기

- 장점: 파일 변경량과 전환 절차가 작다.
- 단점: 기존 구현과 결과 비교가 어렵고 장애 시 즉시 복구하기 어렵다. 실험 폴더의
  경로와 환경에 운영 코드가 결합될 위험이 있다.

### 접근 2: `standard_TEST`를 운영 런타임에서 직접 import

- 장점: R10 코드 복사가 적다.
- 단점: 테스트 스냅샷 폴더가 운영 의존성이 되고 failed candidate와 운영 코드의
  경계가 흐려진다. 폴더 이동이나 정리에도 서비스가 깨질 수 있다.

### 접근 3: 운영 코드 이식 + 격리 저장소 + 기능 플래그

- 장점: 현재 공개 계약을 유지하면서 R10을 독립 검증할 수 있다. shadow 비교,
  점진 전환, 즉시 롤백이 가능하다. `standard_TEST`를 제거해도 운영 코드가 유지된다.
- 단점: 어댑터, 별도 적재, 전환 설정과 테스트가 추가된다.

운영 안정성과 추적 가능성이 가장 높은 접근 3을 채택한다.

## 5. 목표 구조

```text
Supervisor/상위 호출자
  -> 현재 RagRequest 계약
  -> fault_standard.service
     -> runtime selector (legacy | r10 | shadow)
        -> legacy runtime
        -> R10 operational runtime
           -> query embedding
           -> PostgreSQL exact cosine Top-50
           -> PostgreSQL structural rerank (B)
           -> Neo4j relationship/path rerank (C)
           -> selected Rule + party mapping
           -> forced numeric calculator
     -> 현재 DomainSearchResult 계약
  -> 이후 과실비율 에이전트가 다른 RAG 결과와 조립
```

운영 코드는 `etl/fault_cases/rag_runtime/fault_standard` 아래에 둔다.
`standard_TEST`는 이식 근거와 artifact source로만 사용하며 Python import 경로에
포함하지 않는다.

운영 bootstrap에 필요한 승인 artifact는 hash 검증 후
`etl/fault_cases/rag_runtime/database/releases/fault_standard_r10/v1`으로
승격한다. 운영 loader와 검증기는 이 공식 경로만 읽는다. 이 경로에는 R10 release
manifest, Core/Search/Calculator 입력, 압축 embedding, PostgreSQL/Neo4j 적재
계약과 load report만 포함하며 COMPLETE30 정답과 R10 Next/R20 결과물은 포함하지
않는다.

구성요소의 책임은 다음과 같이 분리한다.

- `release_contract`: 허용된 release ID, hash, 개수, 모델 revision을 검증한다.
- `input_adapter`: 현재 `accident_facts`를 R10이 사용하는 정규화 facts로 변환한다.
- `repository`: PostgreSQL 및 Neo4j 조회만 담당한다.
- `selector`: A Top-50, B 구조 판정, C 관계 판정과 선택 trace를 만든다.
- `calculator`: 선택된 Rule의 비율과 확인된 가감요소만 계산한다.
- `result_adapter`: R10 내부 결과를 기존 `DomainSearchResult`로 변환한다.
- `runtime_selector`: legacy, r10, shadow 실행 모드를 결정한다.

각 구성요소는 다른 구성요소의 내부 자료구조를 직접 참조하지 않고 명시적 입력과
출력 객체로 통신한다.

## 6. 검색 및 선택 데이터 흐름

1. 현재 `RagRequest`에서 `query_text`, `query_vector`, `accident_facts`,
   `message_id`를 읽는다.
2. 사전 제공 벡터가 있으면 차원과 유한값을 검증한다. 없으면 고정된 R10 모델
   revision으로 query vector를 생성한다.
3. PostgreSQL R10 인덱스에서 exact cosine 기준 Top-50을 조회한다.
4. 같은 Top-50 후보에 PostgreSQL 구조 조건을 적용하여 B 순위를 만든다.
5. Neo4j가 정상일 때 관계와 ordered path 정보를 적용하여 C 순위를 만든다.
6. 최종 후보에서 Rule과 인정기준상의 당사자 역할을 선택한다.
7. 선택된 Rule을 강제 숫자 계산 정책에 전달한다.
8. 상위 근거 최대 10개와 전체 선택·계산 trace를 `DomainSearchResult`에 담는다.

C 단계는 후보 집합을 새로 만들지 않는다. A에서 얻은 동일 Top-50 후보만
재정렬한다. 정답 ID, COMPLETE30 문항 ID, 평가 점수는 운영 선택에 사용하지 않는다.

## 7. 숫자 반환 정책

사용자 결정에 따라 “조건이 부족하면 숫자를 만들지 않는다”는 R10 Next 정책은
적용하지 않는다. 아래 규칙을 사용한다.

### 7.1 정상 Rule 선택 시

1. 조건에 맞는 Variant가 하나로 확정되면 해당 Variant 비율을 사용한다.
2. Variant가 없거나, 조건 부족·충돌로 특정 Variant를 확정하지 못하면 선택된
   Rule의 기본비율을 사용한다.
3. 첫 번째 Variant 또는 검색 순서상 앞선 Variant를 임의로 선택하지 않는다.
4. predicate가 `true`로 확인된 가감요소만 적용한다.
5. 누락 또는 불명확한 가감요소는 `0`으로 취급하여 적용하지 않는다.
6. 최종 양 당사자 비율은 각각 0~100이고 합은 100이어야 한다.

`ratio_source`는 반드시 `variant` 또는 `rule_base`로 기록한다.
기본비율로 강등된 경우 `fallback_reason`, `missing_fields`,
`unconfirmed_adjustments`를 함께 반환한다.

### 7.2 숫자를 만들지 않는 실패

다음은 “조건 부족”이 아니라 실행 또는 데이터 계약 실패이므로 숫자를 꾸며내지
않는다.

- query embedding 생성 실패 또는 잘못된 2,560차원 벡터
- PostgreSQL 연결 실패 또는 Top-50 조회 실패
- 선택된 Rule의 기본비율/양 당사자 정의가 R10 데이터에서 누락됨
- 비율 합이 100이 아니거나 범위를 벗어나는 데이터 무결성 오류
- release ID, hash, 모델 revision 또는 필수 row count 불일치

이 경우 도메인 결과는 `failed`, `calculation_result`는 `null`이다.

## 8. 당사자 방향

R10 계산 결과는 현재 계약과 동일하게 `user`와 `opponent` 기준 비율을 반환하되,
반드시 다음 추적 정보를 포함한다.

- `party_mapping`: user/opponent가 인정기준 원문의 어느 당사자에 대응하는지
- `source_party_ratio`: 원문 당사자 기준 비율
- `base_ratio`: user/opponent로 변환된 기본비율
- `final_ratio`: 확인된 가감요소까지 반영한 user/opponent 비율

당사자 매핑이 불명확한 경우 Variant와 동일하게 임의 매핑하지 않는다. 다만
Rule의 양 당사자 행동과 현재 사고의 user/opponent 행동을 비교하여 기존 R10
selector가 유일한 매핑을 만들 수 있어야 정상 Rule 선택으로 본다. 매핑 자체가
없으면 사용자 기준 숫자를 만들 수 없으므로 `failed`가 아니라 `partial`과
원문 당사자 비율을 반환한다. 과실비율 에이전트는 이 값을 최종 사용자 비율로
사용하지 않는다.

이 `partial` 결과의 `calculation_result.status`는
`party_mapping_unresolved`, `source_party_ratio`는 원문 비율,
`base_ratio`와 `final_ratio`는 `null`로 고정한다.

심의사례의 A/B 및 청구인/피청구인 방향 보정은 이 모듈에 넣지 않는다.

## 9. 출력 계약

외부 함수 계약은 그대로 유지한다.

```text
handle_request(RagRequest) -> DomainSearchResult
```

정상 숫자 결과의 `calculation_result`는 최소한 다음 의미를 제공한다.

```json
{
  "status": "calculated",
  "release_id": "fault_standard_r10_9e86695d05190c6d",
  "rule_id": "selected-rule-id",
  "ratio_source": "variant | rule_base",
  "variant_id": null,
  "party_mapping": {
    "user": "source-party-id",
    "opponent": "source-party-id"
  },
  "source_party_ratio": {},
  "base_ratio": {
    "user": 30,
    "opponent": 70
  },
  "applied_adjustments": [],
  "unconfirmed_adjustments": [],
  "final_ratio": {
    "user": 30,
    "opponent": 70
  },
  "selection_trace": {},
  "fallback_reason": "variant_unresolved",
  "missing_fields": []
}
```

기존 소비자가 사용하는 `domain`, `status`, `evidence`,
`calculation_result`, `limitations`, `missing_fields` 필드는 제거하거나 이름을
바꾸지 않는다. 새 필드는 `calculation_result` 내부에 추가한다.

상태 의미는 다음과 같다.

- `success`: R10 Rule 선택, user/opponent 매핑, 숫자 계산이 모두 성공
- `partial`: 검색과 Rule 선택은 성공했지만 당사자 방향을 확정하지 못함
- `failed`: 검색, 저장소, release 계약 또는 데이터 무결성 실패

Variant가 불명확하여 Rule 기본비율을 사용한 결과는 숫자가 유효하므로
`success`다. 이 사실은 `ratio_source`, `fallback_reason`, `missing_fields`로
투명하게 남긴다.

## 10. 저장소 격리

R10 PostgreSQL과 Neo4j 데이터는 기존 운영 데이터와 물리적 또는 논리적으로
분리한다.

### PostgreSQL

- 기존 전용 DB `fault_standard_db` 안에 `fault_standard_r10` schema를 새로 만든다.
- R10 release ID를 모든 적재와 조회의 고정 조건으로 사용한다.
- 기존 공용 `rag_qwen4` 데이터와 섞지 않는다.
- 운영 조회 전 Rule 277, search document 6,145, embedding 6,175,
  dimension 2,560을 검증한다.

### Neo4j

- 기존 전용 서비스 `fault-standard-neo4j` 안에 `FaultStandardR10` 격리 label과
  `release_id=fault_standard_r10_9e86695d05190c6d`를 사용한다.
- 기존 graph의 node/relationship를 삭제하거나 제자리 변환하지 않는다.
- 관계 수, 고아 node, 필수 관계, 중복 Rule을 적재 보고서와 대조한다.

적재 검증은 새 schema와 새 label/release ID만 대상으로 한다. 기존
`rag_qwen4`, `FaultStandardOperational`, V7/V9 label은 읽기·쓰기·삭제하지 않는다.

## 11. 실행 모드와 전환

환경 설정 `FAULT_STANDARD_RUNTIME_VERSION`은 다음 모드를 제공한다.

- `legacy`: 현재 인정기준 구현만 호출
- `r10`: R10 구현만 호출
- `shadow`: legacy 결과를 사용자에게 반환하고 R10도 내부 비교용으로 실행

기본값은 배포 전까지 `legacy`다. 알 수 없는 설정값은 자동으로 R10을 선택하지 않고
시작 단계에서 설정 오류로 처리한다.

shadow 모드에서는 다음 항목만 비교 로그에 남긴다.

- 요청/trace 식별용 비식별 ID
- 각 런타임 상태
- 선택 Rule ID
- user/opponent 기본 및 최종 비율
- R10 `ratio_source`
- 후보/계산 단계별 지연시간
- 차이 분류

원문 사용자 질의, 개인정보, 전체 사고 사실은 비교 로그에 기록하지 않는다.

## 12. 장애 처리와 강등

R10 내부 검색 단계는 다음 순서로 강등한다.

1. PostgreSQL + Neo4j C 성공: C 결과 사용
2. Neo4j 장애: PostgreSQL B 결과로 계산하고 `partial` 및 limitation 기록
3. 구조 조회 일부 장애지만 A Top-50과 Rule 기본 레코드가 정상:
   A 1위 Rule의 근거는 반환하되 자동 숫자 계산은 하지 않고 `partial`
4. embedding 또는 PostgreSQL vector 조회 장애: `failed`

구조 저장소 장애 시 legacy 결과로 몰래 전환하지 않는다. runtime 단위 전환은
오직 `FAULT_STANDARD_RUNTIME_VERSION`과 명시적 롤백 절차로 수행한다. 그래야
사용자가 받은 결과의 출처를 추적할 수 있다.

## 13. 검증 전략

### 13.1 Release preflight

- manifest release ID와 모든 필수 artifact SHA-256 검증
- 모델 ID/revision, dimension, normalization 검증
- Rule/search document/embedding 개수 검증
- R10 Next, R20, invalid iteration 경로 참조가 0인지 검사
- 운영 Python 코드에서 `standard_TEST` import가 0인지 검사

### 13.2 단위 테스트

- input fact 정규화와 충돌 보존
- 2,560차원 query vector 검증
- Top-50 후보 집합 유지
- B/C deterministic ordering
- Variant 단일 확정
- Variant 불명확 시 Rule 기본비율 사용
- 첫 번째 Variant 임의 선택 금지
- 확인된 adjustment만 적용
- 누락 adjustment를 0으로 처리
- 비율 범위와 합 100 불변식
- user/opponent party mapping
- 상태와 `DomainSearchResult` 직렬화

### 13.3 통합 테스트

- 실제 R10 PostgreSQL에서 vector Top-50과 구조 레코드 조회
- 실제 R10 Neo4j에서 관계/path 조회
- Neo4j 중단 시 B 강등
- 잘못된 release ID/hash/count에서 시작 차단
- 기존 `agent_runtime`이 계약 변경 없이 R10 결과를 수용

### 13.4 평가 및 전환 Gate

동일한 COMPLETE30 입력과 고정 query vector로 R10 기준 결과를 재현한다.

- Recall@50: 30/30 유지
- C Hit@1: 22/30보다 감소하지 않음
- C Final Ratio Exact: 18/30보다 감소하지 않음
- 세 번 실행 결과가 deterministic
- runtime에서 Gold/qrels 접근 0
- 모든 정상 Rule 선택 결과에 숫자 존재
- Variant 불명확 강등 결과의 `ratio_source=rule_base`
- 인프라 장애에서 숫자 조작 0

이후 실제 대표 사고 질의의 shadow 결과를 검토한다. 알려진 R10 한계인 q06/q13
selector, q28/q30 adjustment 중복 위험, Neo4j rerank demotion 8건은 별도 회귀
목록으로 추적하며 숨기지 않는다.

## 14. 전환 및 롤백

1. 현재 legacy 결과와 환경 설정을 baseline으로 동결한다.
2. R10 artifact preflight를 통과시킨다.
3. 격리된 PostgreSQL/Neo4j에 적재하고 저장소 검증을 통과시킨다.
4. `legacy` 모드에서 코드와 계약 회귀 테스트를 통과시킨다.
5. `shadow` 모드로 R10 차이 보고서를 만든다.
6. COMPLETE30 및 shadow 승인 후 `r10`으로 전환한다.
7. 장애 또는 품질 Gate 실패 시 설정을 `legacy`로 되돌린다.

롤백은 데이터 삭제를 요구하지 않는다. R10 저장소는 원인 분석을 위해 보존하고,
별도 승인 전에는 기존 저장소나 copied test 폴더를 삭제하지 않는다.

## 15. 구현 순서

1. 계약·baseline 고정
2. release preflight 및 금지 경로 검사
3. R10 운영 패키지 골격과 내부 타입
4. PostgreSQL migration/loader/repository
5. Neo4j loader/repository
6. query embedding 및 A Top-50
7. B/C selector와 trace
8. 강제 숫자 calculator
9. 기존 `DomainSearchResult` 어댑터
10. runtime feature flag와 shadow 비교
11. 단위/통합/COMPLETE30/장애 테스트
12. shadow 보고서, R10 전환, 롤백 검증

구체적인 파일 목록, 테스트 이름, 각 단계의 실패 테스트와 실행 명령은 이 설계
승인 후 별도 구현 계획에 작성한다.

## 16. 완료 조건

- 운영 코드가 `standard_TEST`를 import하지 않는다.
- 허용된 R10 release ID와 artifact만 사용한다.
- 기존 Supervisor 경계와 `DomainSearchResult` 필드가 깨지지 않는다.
- 정상 Rule 선택 시 Variant 정보가 부족해도 Rule 기본비율 숫자가 반환된다.
- 첫 번째 Variant 임의 선택과 미확인 adjustment 적용이 없다.
- user/opponent 매핑과 비율 출처가 trace에 남는다.
- R10 저장소가 기존 저장소와 격리되고 삭제 없는 롤백이 가능하다.
- COMPLETE30 기준 성능이 R10 기준보다 후퇴하지 않는다.
- `legacy`, `shadow`, `r10` 모드의 테스트가 모두 통과한다.
- 심의사례/판례/최종 과실비율 에이전트 작업이 이번 범위에 섞이지 않는다.
