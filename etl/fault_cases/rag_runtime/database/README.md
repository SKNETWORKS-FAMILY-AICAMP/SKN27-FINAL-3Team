# 운영 DB 전용 영역

이 디렉터리는 운영 DB의 export, import, validation 절차를 보관한다.

- `migrations/`: 운영 스키마 생성 스크립트
- `loaders/`: 검증된 원본 데이터를 운영 DB에 적재하는 도구
- `validation/`: 적재 결과의 구조·수량·관계·provenance 검증기

## 인정기준 Neo4j 운영 전환

운영 그래프는 V7 이력 그래프와 분리된 V9-only `FaultStandardOperational` 그래프다.
비밀번호는 로컬의 무시 대상 `.env` 또는 비밀 저장소에서 주입한다. 문서나 명령줄에 실제 비밀번호를 기록하지 않는다.

```powershell
python -B -m etl.fault_cases.rag_runtime.database.graph_export `
  --label Complete30V7 `
  --output-dir C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v7

python -B -m etl.fault_cases.rag_runtime.database.graph_export `
  --label Complete30V9 `
  --output-dir C:/dev/project/SKN27-RAG-rescue/etl/fault_cases/HISTORY_LOCAL/neo4j_archives/complete30_v9_source
```

V9 export는 `import_fault_standard_operational_graph`로 새 운영 볼륨에 적재한다. 이후
`validate_fault_standard_operational_graph`가 노드·관계 수, 운영 라벨, provenance, Rule 관계,
고립 노드, 필수 속성, 제약조건을 검증한다.

검증이 PASS한 뒤 서비스 컨테이너를 `fault-standard-neo4j`로 전환한다. 기존 컨테이너와
볼륨은 롤백 기간 동안 보관하며, 별도 승인 없이는 삭제하지 않는다.
