# 상세 사고 30건 A/B/C 실험 보고서

## 결론

- 구조 후처리 B/C는 벡터 단독 A보다 Top-3 정답 회수를 15건에서 21건으로 6건 높였다.
- B와 C의 정확도가 같은 것은 오류가 아니라, 현재는 같은 Canonical 조건·같은 hard-bucket 알고리즘을 PostgreSQL과 Neo4j가 각각 동일하게 실행했기 때문이다.
- 따라서 이 결과는 ‘Neo4j가 더 정확하다’는 근거가 아니라, PostgreSQL 후처리로 현 단계의 정확도 이득을 얻을 수 있고 Neo4j는 차로 경로·다단계 관계 확장 시의 후보라는 근거다.

## 실험 계약

- A/B/C는 같은 30개 질문, 같은 Qwen3-Embedding-4B GPU 벡터, 같은 pgvector exact-cosine Top-50 후보를 사용한다.
- B/C는 검색 가중치를 더하지 않는다. PDF 조건의 hard bucket만으로 후보의 모순 여부를 처리한 뒤 기존 cosine 순서를 유지한다.
- 과실비율 계산은 세 실험에 동일한 Calculator를 사용하며, 정답지는 G4 평가에서만 읽는다.

## 핵심 결과

- A: Hit@1 10/30 (33.3%), Hit@3 15/30 (50.0%), MRR@3 0.4111, End-to-End 7/30 (23.3%)
- B: Hit@1 11/30 (36.7%), Hit@3 21/30 (70.0%), MRR@3 0.5056, End-to-End 8/30 (26.7%)
- C: Hit@1 11/30 (36.7%), Hit@3 21/30 (70.0%), MRR@3 0.5056, End-to-End 8/30 (26.7%)
- B/C semantic parity: True; p50/p95 후처리 latency는 PostgreSQL 39.68/62.99 ms, Neo4j 88.75/109.47 ms다.

## A 대비 B/C 변화

- Top-3로 새로 회수된 8건: fault_complete30_q02, fault_complete30_q09, fault_complete30_q10, fault_complete30_q16, fault_complete30_q24, fault_complete30_q25, fault_complete30_q26, fault_complete30_q28
- 반대로 Top-3에서 이탈한 2건: fault_complete30_q04, fault_complete30_q30. 따라서 순증은 6건(15건→21건)이다.
- Top-1 정답으로 새로 선택된 3건: fault_complete30_q02, fault_complete30_q23, fault_complete30_q28
- 계산 가능 상태로 새로 전환된 9건: fault_complete30_q02, fault_complete30_q04, fault_complete30_q08, fault_complete30_q09, fault_complete30_q14, fault_complete30_q15, fault_complete30_q16, fault_complete30_q17, fault_complete30_q30
- Top-50 Recall은 세 방법 모두 28/30 (93.3%)다. 즉 남은 오류의 대부분은 후보 회수보다 Rule 선택·Party 매핑·계산 조건의 한계다.

## 해석 원칙

- Recall@50은 후보 회수의 진단값이며, 실제 선택 성능은 Hit@1·Hit@3·End-to-End Exact로 판단한다.
- B/C가 같다면 두 저장소가 동일 Canonical 조건 계약을 충실히 재현했다는 뜻이다. Neo4j 도입 판단은 정확도뿐 아니라 관계 경로 확장성·운영 latency도 함께 본다.
- Final Ratio Exact가 낮은 이유는 계산기가 추론해서 수치를 만드는 문제가 아니라, 현재 30건 중 선택 Rule·Party mapping·base ratio가 모두 맞아야 통과하도록 엄격히 평가했기 때문이다.
- 개별 오답 및 계산 차이는 case_by_case_results.jsonl에서 확인한다.
