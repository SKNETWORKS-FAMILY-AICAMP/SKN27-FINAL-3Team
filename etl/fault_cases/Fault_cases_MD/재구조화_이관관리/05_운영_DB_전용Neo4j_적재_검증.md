# 5~6단계 운영 DB·전용 Neo4j·Qwen 4B 적재 검증

검증일: 2026-07-20  
검증 범위: 운영 검색용 PostgreSQL `rag_qwen4` 스키마와 인정기준 전용 Neo4j 복원 결과

## 1. 분리 원칙 확인

| 구분 | 대상 | 결과 |
|---|---|---|
| 법률 Neo4j | `skn27-neo4j` | 읽기 전용 대조만 수행, 데이터 변경 없음 |
| 인정기준 전용 Neo4j | `fault-standard-neo4j` | 별도 컨테이너·볼륨·내부 네트워크로 생성 |
| 인정기준 PostgreSQL | `fault_standard_db.rag_qwen4` | 기존 `search` 스키마와 분리 |
| 심의사례 PostgreSQL | `review_case_db.rag_qwen4` | 기존 스키마와 분리 |
| 판례 PostgreSQL | `precedent_db.rag_qwen4` | 새 전용 DB로 생성 |

`fault-standard-neo4j`에는 호스트 포트를 열지 않았습니다. 따라서 Docker 내부 서비스만 접근할 수 있으며, 법률 Neo4j의 포트·볼륨·인증값·초기화 스크립트를 공유하지 않습니다.

## 2. Qwen3-Embedding-4B 운영 인덱스 검증

기준 실행 그룹은 `native7_20260718_v1`의 `repeat_01`입니다. 세 코퍼스의 문서/청크 ID와 Parquet 벡터 ID를 먼저 대조한 뒤 적재했습니다.

| 코퍼스 | 원문 문서 | 청크 | 임베딩 | 차원 | NaN/Inf·고아 참조 |
|---|---:|---:|---:|---:|---|
| 인정기준 | 277 | 0 | 277 | 2,560 | 0건 |
| 심의사례 | 226 | 904 | 904 | 2,560 | 0건 |
| 판례 | 987 | 8,334 | 8,334 | 2,560 | 0건 |

각 행에는 원본/입력 텍스트 해시, 모델명, 정규화 여부, 실행 그룹, 생성 시각과 소스 참조를 보관했습니다. `rag_qwen4` 이외의 기존 벡터(1,024·1,536차원)는 변경하지 않았습니다.

### 모델 버전 주의

기존 AB 산출물에는 Hugging Face commit revision이 기록되어 있지 않습니다. 따라서 현재 적재 행은 `legacy_unpinned_native7_20260718_v1`로 명시했고, 검증 결과도 `LEGACY_UNPINNED_WARNING`을 유지합니다. 차원·정규화·ID·수치는 검증됐지만, 완전한 운영 재현성을 승인하려면 추후 revision을 고정한 Qwen 4B 재임베딩이 필요합니다.

검증 원본: `artifacts/rag_runtime/stage6/qwen4_operational_validation.json`

## 3. V9 인정기준 그래프 복원 대조

검증된 사전 백업의 `complete30-abc-neo4j` 논리 스냅샷을 새 `fault-standard-neo4j`에만 복원했습니다.

| 항목 | 백업 매니페스트 | 전용 Neo4j 복원 후 | 판정 |
|---|---:|---:|---|
| 노드 | 9,533 | 9,533 | PASS |
| 관계 | 14,637 | 14,637 | PASS |

복원 대상 노드에는 원본 식별자를 보존하고 `V9Import` 라벨을 추가했습니다. 이는 기존 법률 그래프와의 식별 충돌을 막기 위한 전용 그래프 내부 표식입니다.

검증 원본: `artifacts/rag_runtime/stage5/complete30_v9_graph_import.json`

## 4. 기존 법률 Neo4j 무변경 확인

복원 완료 뒤 기존 `skn27-neo4j`를 읽기 전용 Cypher로 다시 계수했습니다.

| 항목 | 기준 백업 계수 | 현재 읽기 계수 | 판정 |
|---|---:|---:|---|
| 노드 | 99,964 | 99,964 | PASS |
| 관계 | 451,861 | 451,861 | PASS |

따라서 5~6단계의 데이터 적재와 전용 Neo4j 복원은 법률 그래프의 데이터 수를 바꾸지 않았습니다.

## 5. 다음 단계 진입 조건

- Qwen 4B 운영 검색 인덱스의 ID·차원·참조 무결성: 충족
- V9 전용 그래프의 백업 대조: 충족
- 법률 그래프 무변경 대조: 충족
- 모델 revision 고정: 경고 상태로 기록, 이후 재임베딩 개선 과제

위 조건에 따라 7단계 인정기준 RAG, 8단계 판례 B-4 RAG, 9단계 심의사례 RAG 구현을 진행할 수 있습니다.

## 6. `rag_qwen4` 스키마 덤프·복원 검증

각 운영 DB의 `rag_qwen4` 스키마를 소유권·권한 없이 덤프한 뒤, 별도로 만든 임시 검증 DB에 `vector` 확장을 설치하고 복원했습니다. 임시 DB는 검증 뒤 삭제했습니다.

| 원본 DB | 복원 후 확인 테이블 | 판정 |
|---|---|---|
| `fault_standard_db` | `documents`, `chunks`, `embeddings` | PASS |
| `review_case_db` | `documents`, `chunks`, `embeddings` | PASS |
| `precedent_db` | `documents`, `chunks`, `embeddings` | PASS |

덤프 및 기계 검증 기록: `artifacts/rag_runtime/stage5/schema_backups/`
