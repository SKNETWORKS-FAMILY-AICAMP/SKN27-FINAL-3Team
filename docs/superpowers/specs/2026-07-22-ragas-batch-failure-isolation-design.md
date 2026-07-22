# 법령 RAGAS 배치 실패 격리 설계

## 1. 목적

Issue #285는 공개 법령 20개 질의의 PostgreSQL lexical·pgvector RAGAS 평가에서 한 질의의 생성 또는 평가 실패가 backend 전체 결과를 덮어쓰지 않도록 한다. 질의별 실패는 안전하게 식별하고, 모든 질의와 필수 metric이 유효한 경우에만 backend RAGAS 집계를 전환 판단 근거로 제공한다.

## 2. 기존 기준과 범위

PR #284에 이미 존재하는 다음 경계는 수정하거나 다시 구현하지 않는다.

- `.env.rag-eval`의 로컬 전용 환경 경계와 `.env.rag-eval.example`
- PostgreSQL corpus·embedding space preflight
- PostgreSQL lexical ↔ pgvector의 동일 filter·top-5 A/B 수집
- 운영 RAG 경로, Elasticsearch, Neo4j, 임베딩 재생성, 법령 corpus 수집

`etl/legal/run_evaluation.py`의 현재 `run_ragas()`는 answer 생성 또는 RAGAS batch evaluate 중 하나가 실패하면 해당 backend 전체를 `not_evaluated`로 만든다. 이것이 Issue #285의 직접 변경 대상이다.

## 3. 대안과 선택

| 대안 | 장점 | 한계 | 결정 |
| --- | --- | --- | --- |
| 현재처럼 backend별 단일 batch | 호출 수가 적다. | 실패 질의를 식별할 수 없고 전체 결과를 잃는다. | 제외 |
| 실패한 batch만 재귀적으로 분할 | 정상 batch에서는 호출 수가 적다. | batch-level 실패와 query-level 실패를 구분할 수 없고, 재시도로 비용·결과 재현성이 불명확하다. | 제외 |
| 질의별 생성·평가 후 backend별 엄격 집계 | 실패 질의와 backend를 정확히 기록하고 다음 질의를 계속 평가한다. | 최대 20회씩 평가하므로 실행 시간이 늘어난다. | 채택 |

## 4. 결과 계약

`run_ragas()`는 backend마다 아래 구조를 반환한다.

```json
{
  "status": "evaluated | not_evaluated",
  "reason": "",
  "generator_model": "gpt-4o-mini",
  "judge_model": "gpt-4o-mini",
  "embedding_model": "text-embedding-3-small",
  "query_results": [
    {
      "query_id": "law-q001",
      "backend": "postgres_lexical",
      "status": "evaluated | not_evaluated",
      "error_code": "",
      "latency_ms": 0
    }
  ],
  "metrics": {
    "context_precision": 0.0,
    "context_recall": 0.0,
    "faithfulness": 0.0,
    "answer_relevancy": 0.0
  }
}
```

- `query_results`의 각 항목은 정확히 `query_id`, `backend`, `status`, `error_code`, `latency_ms`만 가진다. 생성 답변, 질문, 법령 context, 예외 원문, API key, OCR·첨부파일 데이터는 기록하지 않는다.
- 모든 질의가 `evaluated`이고 네 metric이 모두 유한한 0~1 숫자일 때만 backend `status`를 `evaluated`로 하고 `metrics`를 포함한다.
- 한 질의라도 `not_evaluated`이거나 metric이 누락·NaN·범위 밖이면 backend `status`는 `not_evaluated`, `reason`은 `incomplete_ragas_evidence`이며 aggregate `metrics`는 포함하지 않는다.
- 빈 context는 외부 API를 호출하지 않고 `no_ragas_contexts`로 기록한다.

허용되는 안전한 오류 코드는 기존 `openai_api_key_missing`, `empty_generated_answer`, `ragas_dependencies_not_installed`, `ragas_runtime_unavailable`과 새 `no_ragas_contexts`, `ragas_metrics_incomplete`, `ragas_metrics_invalid`으로 제한한다. 알 수 없는 예외는 항상 `ragas_runtime_unavailable`으로 정규화한다.

## 5. 처리 흐름

1. 기존 preflight와 deterministic A/B가 성공한 뒤 backend별 RAGAS record를 만든다.
2. 각 record에 대해 context 존재 여부를 먼저 확인한다.
3. context가 있으면 답변 생성과 단일-record RAGAS 평가를 수행하고 전체 시간을 `latency_ms`로 기록한다.
4. 실패는 안전한 코드로 정규화해 해당 record에만 기록하고 다음 record를 계속 처리한다.
5. 유효한 네 metric은 메모리에서만 모아 평균을 계산한다. per-query metric은 결과 파일에 쓰지 않는다.
6. 모든 record의 성공·metric 완전성을 검증한 뒤에만 aggregate를 `evaluated`로 반환한다.
7. 기존 `transition_decision()`은 `status == "evaluated"`와 complete aggregate metric이 있을 때만 RAGAS gate를 통과 대상으로 취급한다.

## 6. 테스트와 검증

테스트는 외부 API를 호출하지 않고 monkeypatch로 생성·평가 helper를 대체한다.

- 한 질의의 생성 실패 뒤에도 다음 질의가 평가되고 실패 질의만 안전한 결과를 남긴다.
- RAGAS helper가 두 metric만 반환하거나 NaN·범위 밖 값을 반환하면 aggregate가 `not_evaluated`가 된다.
- 모든 질의가 네 metric을 반환하면 backend aggregate가 정확한 평균으로 `evaluated`가 된다.
- 예외 원문, 질문, answer, context, key-like 문자열이 `query_results`와 JSON 결과에 포함되지 않는다.
- 빈 context는 외부 생성·평가 helper를 호출하지 않는다.
- 기존 public_law 경계, 20개 질의 제한, transition gate와 environment contract 테스트를 함께 실행한다.

## 7. 완료 후 기록

- `docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md`에 #285의 실제 재실행 결과 또는 미실행 사유를 추가한다. 실행하지 않은 metric은 기록하지 않는다.
- `docs/ops/project-readiness-master-checklist.md`의 C-1에 #285 근거를 추가하되, 현재 pgvector no-result·p95 gate가 미통과이므로 상태는 `[~]`로 유지한다.
- GitHub Issue #285에는 테스트 결과와 실제 RAGAS 재실행 여부를 기록한다. Issue #282는 결과 기록 후 별도로 종료 여부를 판단한다.
