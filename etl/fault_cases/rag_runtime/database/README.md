# 운영 DB 전용 영역

이 경로에는 후속 단계에서만 새 운영 DB의 마이그레이션·적재·검증 코드를 둔다.

- `migrations/`: 새 운영 스키마만 생성한다.
- `loaders/`: 기존 원본·청크를 새 운영 DB로 적재한다.
- `validation/`: 행 수·차원·해시·검색 스모크 검증을 수행한다.

기존 `skn27-postgres`, `skn27-neo4j`, 실험 DB 컨테이너의 스키마·테이블을 직접 변경하는 코드는 이곳에 두지 않는다.

## 인정기준 Neo4j 이관

운영 그래프 이관은 V7 이력 보관과 V9-only 운영 그래프 재생성을 분리한다.

```powershell
$env:FAULT_STANDARD_NEO4J_PASSWORD = '<운영 Neo4j 비밀번호>'
python -B -m etl.fault_cases.rag_runtime.database.graph_export `
  --label Complete30V7 `
  --output-dir C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v7
python -B -m etl.fault_cases.rag_runtime.database.graph_export `
  --label Complete30V9 `
  --output-dir C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v9_source
```

V9 원본 export는 새 임시 Neo4j에 `import_fault_standard_operational_graph`로 적재한다. 적재 후 `validate_fault_standard_operational_graph`가 `7,815` 노드와 `13,196` 관계, `FaultStandardOperational` 라벨, 필수 Rule 관계, provenance, 고립 노드, 역할·관계별 기대 수를 모두 확인해야 한다.

검증 통과 뒤에만 운영 서비스명 `fault-standard-neo4j`로 전환한다. 기존 컨테이너와 볼륨은 롤백 기간 동안 보관하고, 별도 승인 없이 삭제하지 않는다. Compose는 `FAULT_STANDARD_NEO4J_DATA_VOLUME` 및 `FAULT_STANDARD_NEO4J_LOG_VOLUME`으로 이관 볼륨을 명시할 수 있으며, 기본값은 운영 이관 볼륨이다.
