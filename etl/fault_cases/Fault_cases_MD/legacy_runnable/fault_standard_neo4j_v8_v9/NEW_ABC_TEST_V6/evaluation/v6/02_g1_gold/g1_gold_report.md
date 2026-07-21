# V6 G1 Gold Outcome 레저

## 중요한 범위

이 파일은 G1 입력 고정 후 생성한 숨은 평가 레저다. Runtime은 이 파일을 읽지 않는다.
기존 qrels에 최종비율이 없는 행은 기본비율과 확정 Party 매핑으로만 계산한 **base-only simulation assumption**으로 표시했다.
따라서 이 행은 PDF 수정요소까지 사람이 시각 검수한 Gold와 동등하다고 주장하지 않는다.

| 상태 | 건수 |
|---|---:|
| `calculated` | 33 |
| `insufficient_facts_for_exact_rule` | 10 |
| `needs_party_mapping` | 3 |
| `needs_ratio_or_mapping` | 3 |
| `no_exact_rule_in_corpus` | 1 |

| Label quality | 건수 |
|---|---:|
| `out_of_corpus_negative` | 1 |
| `ratio_derived_from_base_only` | 13 |
| `ratio_present_legacy_label` | 26 |
| `related_rule_only_not_gold` | 10 |

## 사용 규칙

- Rule ranking: 50개 전체에 대해 relevance qrels로 평가한다.
- End-to-end ratio: `expected_status=calculated`이고 `final_ratio`가 있는 행만 정답 분모에 넣는다.
- `insufficient_facts_for_exact_rule` 및 `no_exact_rule_in_corpus`는 정확한 Rule/비율을 억지로 만들지 않는 안전성 케이스다.
- 최종 보고서는 `ratio_present_legacy_label`과 `ratio_derived_from_base_only`를 반드시 분리 표기한다.
