# Fault Standard Operational Neo4j Migration Design

## Goal

운영 인정기준 Neo4j를 실험 비교용 `Complete30V7`/`Complete30V9` 혼합 그래프에서 분리한다. 최종 운영 그래프에는 `FaultStandardOperational` 라벨만 사용하고, V7은 재현 가능한 이력 백업으로 보존한다.

## Current State

- 컨테이너 `fault-standard-neo4j`의 현재 논리 그래프는 V7 1,718 노드/1,441 관계와 V9 7,815 노드/13,196 관계로 구성된다.
- 두 그래프 사이의 관계는 없다.
- 운영 조회 코드는 `Complete30V9` 라벨만 조회한다.
- 현재 적재기는 전체 스냅샷을 `V9Import` 라벨과 원본 라벨 그대로 복원한다. 따라서 현재 적재기로 재적재하면 V7도 다시 생긴다.
- `etl/fault_cases/evaluation/fault_standard/`는 평가 질문·정답·임베딩 경로이며 Neo4j 그래프 백업 경로가 아니다.

## Target Model

운영 그래프의 모든 노드는 역할 라벨과 운영 소속 라벨을 함께 가진다.

```cypher
(:FaultStandardOperational:Rule {
  schema_version: 9,
  source_snapshot_id: "complete30-v9-operational",
  source_legacy_element_id: "legacy-node-id"
})
```

- 역할 라벨은 `Rule`, `Fact`, `Party`, `BaseFault`, `Adjustment`, `Context` 등 기존 도메인 의미를 유지한다.
- `FaultStandardOperational`은 운영 그래프 소속을 나타내는 고정 라벨이다.
- `schema_version: 9`는 구조 버전 이력이다. 버전을 라벨에 넣지 않는다.
- `source_snapshot_id`와 `source_legacy_element_id`는 원본 추적용 속성이다. `V9Import` 라벨은 사용하지 않는다.
- 운영 그래프에는 `Complete30V7`, `Complete30V9`, `V9Import` 라벨을 넣지 않는다.

## Migration Flow

1. 현재 `fault-standard-neo4j`에서 `Complete30V7` 서브그래프를 JSONL과 SHA-256 manifest로 읽기 전용 export한다.
2. V7 export는 `C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v7/`에 보관한다. 이 경로는 운영 publish 브랜치 및 평가 데이터와 분리한다.
3. V9 서브그래프만 읽어 새 운영 백업을 만든다. 기준은 7,815 노드와 13,196 관계다.
4. 임시 Neo4j 컨테이너/볼륨에 운영 백업을 `FaultStandardOperational` 모델로 적재한다. 현재 `fault-standard-neo4j`의 데이터와 볼륨은 이 단계에서 변경하지 않는다.
5. 자동 검증과 Runtime 회귀 검증이 통과하면, 새 그래프를 기존 서비스명 `fault-standard-neo4j`로 전환한다.
6. 전환 후 롤백 기간 동안 기존 V7+V9 DB를 보관한다. 명시적 정리 승인이 있을 때만 기존 컨테이너/볼륨을 삭제한다.

## Safety and Rollback

- 기존 컨테이너 안에서 `DETACH DELETE`로 V7을 먼저 지우지 않는다.
- export manifest는 노드/관계 수와 각 JSONL 파일의 SHA-256을 포함한다.
- 새 운영 컨테이너는 임시 이름과 별도 볼륨을 사용한다. 검증 실패 시 현재 컨테이너를 그대로 유지한다.
- 전환 전후 모두 `FAULT_STANDARD_NEO4J_URI`가 가리키는 서비스명은 `fault-standard-neo4j:7687`로 유지한다.
- 백업, 새 DB 적재, 검증, 전환은 각각 독립적으로 재실행 가능해야 한다.

## Verification Contract

운영 그래프 검증기는 다음을 JSON 보고서와 PASS/FAIL 종료 코드로 제공한다.

1. 노드 7,815개, 관계 13,196개를 확인한다.
2. `FaultStandardOperational` 라벨이 모든 운영 노드에 존재하는지 확인한다.
3. `Complete30V7`, `Complete30V9`, `V9Import` 라벨의 노드 수가 0인지 확인한다.
4. 원본 식별자와 `Rule.rule_id`의 중복·누락을 확인한다.
5. 고립 노드, Rule의 필수 관계(`HAS_BASE_FAULT`, `HAS_EVIDENCE`, `HAS_PARTY`, `REQUIRES_FACT`, `CONTAINS_RULE`) 누락, 필요한 `record_json` 누락을 확인한다.
6. 원본 V9의 라벨별·관계별 기대 수와 새 그래프의 역할별·관계별 수를 대조한다.
7. Runtime이 새 라벨로 후보 Rule과 관계 profile을 읽는지 테스트한다.

Neo4j 5 Community에서는 다중 라벨(`FaultStandardOperational` + `Rule`) 유니크 제약조건을 만들 수 없으므로, `source_legacy_element_id`만 DB 제약조건으로 고정하고 `Rule.rule_id` 고유성은 운영 검증기의 중복 검사로 보장한다.

## Scope Boundaries

- `evaluation/fault_standard/complete30_v9/`의 이름·데이터는 역사적 평가 계약이므로 변경하지 않는다.
- V7의 실험 문서·코드·산출물은 rescue 및 문서 이력에 보관하며 운영 DB에 적재하지 않는다.
- 기존 법률 Neo4j `skn27-neo4j`는 읽기·쓰기 모두 이관 대상이 아니다.
