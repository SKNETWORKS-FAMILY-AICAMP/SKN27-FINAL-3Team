# HISTORY 이관 목록

최종 RAG 통합 운영구축 과정에서 단순 기록, 중간 산출물, 덮어쓰기된 문서들을 아카이빙한 내역입니다. 해당 파일들은 더 이상 운영이나 에이전트 통합에서 참조되지 않으나, 추적성을 위해 보존됩니다.

| 원래 경로 | HISTORY 경로 | 이관 이유 | 대체된 최종 코드/문서 | 백업 위치 |
| --- | --- | --- | --- | --- |
| 중간 생성된 임시 번들 | `HISTORY_LOCAL/...` | 공간 확보 및 혼선 방지 | 없음 (최종 런타임이 대체) | `legacy_runnable` 등 |
| 실패한 메타데이터 v1/v2 | `HISTORY_LOCAL/...` | 실패한 실험 데이터 | v9/qwen4b 최종 적용안 | 로컬 |
| 5개 모델 1024차원 비교 등 | `HISTORY_LOCAL/...` | 기록 보존 | `legacy_runnable/embedding_fixed1024_5models/` | 로컬 |
| 불필요한 __pycache__ | 일괄 삭제 | 공간 낭비 | 자동 재생성됨 | 없음 |
| 구형 에이전트 (`src/agents`) | `HISTORY_LOCAL/old_agents` | 혼동 방지 (사용 중단) | `rag_runtime/agent_runtime/` | 로컬 |
| 구조변경 유틸 (`backup_tools`) | `HISTORY_LOCAL/backup_tools` | 14단계 완료로 인한 용도 폐기 | 없음 | 로컬 |
