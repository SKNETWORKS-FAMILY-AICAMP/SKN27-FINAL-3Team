# text_ml_case_search active 10 실행 결과 보고서

## 목적

active 10개 full optional input을 실제 Elasticsearch RAG와 연결해 실행하고, Agent V2 출력 JSON이 Supervisor가 받을 수 있는 형태로 안정적으로 생성되는지 확인한다.

이번 확인의 핵심은 `review_case` 심의사례 근거와 `fault_ratio_precedent` 과실비율 판례 근거가 같은 output schema 안에 함께 들어오는지이다.

## 입력 및 산출물

| 항목 | 경로 |
| --- | --- |
| 입력 JSONL | C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\review_case_output\schema_search_test\text_ml_case_search_agent_input_full_optional_fields.jsonl |
| Agent 출력 JSONL | C:\dev\project\SKN27-FINAL-3Team\etl\fault_cases\artifacts\review_case_output\agent_runs\text_ml_case_search_full_optional_agent_outputs.jsonl |
| 검색 입력 variant | schema_search_text |

## 전체 요약

| 항목 | 값 |
| --- | --- |
| 생성 시각 | 2026-07-05T21:01:05 |
| active input 수 | 10 |
| status_counts | {"success": 10} |
| evidence 총합 | 100 |
| review_case evidence 총합 | 50 |
| fault_ratio_precedent evidence 총합 | 50 |
| similar_cases 총합 | 50 |
| display_evidence 총합 | 100 |
| zero_evidence_count | 0 |
| 결론 | PASS: active 10 inputs returned stable Agent V2 JSON with both review_case and fault_ratio_precedent evidence. |

## 케이스별 결과

| run | contract | status | evidence | review | precedent | display | ratio | top_review_reference | top_precedent_reference | top_precedent_case |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 0 : 100 | review_case_db:review_case_2017_032889#review_case_2... | fault_ratio_precedent_db:117909#117909:structured_15... | 99다19346 |
| 2 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 20 : 80 | review_case_db:review_case_2018_062943#review_case_2... | fault_ratio_precedent_db:117997#117997:structured_15... | 99다30428 |
| 3 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 30 : 70 | review_case_db:review_case_2019_053543#review_case_2... | fault_ratio_precedent_db:605559#605559:structured_15... | 2023나41651 |
| 4 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(피청구) : B(청구) = 80 : 20 | review_case_db:review_case_2016_051812#review_case_2... | fault_ratio_precedent_db:67558#67558:structured_1500... | 2005다7177 |
| 5 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 20 : 80 | review_case_db:review_case_2019_005556#review_case_2... | fault_ratio_precedent_db:117997#117997:structured_15... | 99다30428 |
| 6 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 30 : 70 | review_case_db:review_case_2019_053543#review_case_2... | fault_ratio_precedent_db:236063#236063:structured_15... | 2021나80829 |
| 7 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 90 : 10 | review_case_db:review_case_2019_042370#review_case_2... | fault_ratio_precedent_db:117997#117997:structured_15... | 99다30428 |
| 8 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(청구) : B(피청구) = 20 : 80 | review_case_db:review_case_2018_062943#review_case_2... | fault_ratio_precedent_db:81877#81877:structured_1500... | 2002다38767 |
| 9 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(피청구) : B(청구) = 60 : 40 | review_case_db:review_case_2018_041713#review_case_2... | fault_ratio_precedent_db:70703#70703:structured_1500... | 2006가단113723 |
| 10 | text_ml_case_search_v2 | success | 10 | 5 | 5 | 10 | A(피청구) : B(청구) = 20 : 80 | review_case_db:review_case_2018_005556#review_case_2... | fault_ratio_precedent_db:171923#171923:structured_15... | 2013다5435 |

## 판례 대표 근거 확인

아래 표는 각 run에서 `fault_ratio_precedent` source_type으로 들어온 대표 판례 근거를 따로 보여준다. 기존 보고서에서 판례가 안 보였던 이유는 첫 번째 display_evidence만 표기했기 때문이며, 병합 순서상 review_case가 먼저 표시됐기 때문이다.

| run | case_number | court | decision_date | precedent_reference | precedent_title | summary | matched_snippets |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 99다19346 | 대법원 | 1999-07-23 | fault_ratio_precedent_db:117909#117909:structured_1500_250:0002 | 손해배상(자) | 판시사항: [1] 황색 점선의 중앙선이 설치된 고속도로에서 자기차선을 따라 운행하는 자동차 운전자에게 반대차선의 자동차가 중앙선을 침범할 것을 예상하여 운전할 주의의무가 있는지 여부(한정 소극) [2] 중앙선을... | 판시사항: [1] 황색 점선의 중앙선이 설치된 고속도로에서 자기차선을 따라 운행하는 자동차 운전자에게 반대차선의 자동차가 중앙선을 침범할 것을 예상하여 운전할 주의의무가 있는지 여부(한정 소극) [2] 중앙선을 침범하여 운행하던 자동차가 반대차선에서 과속으로 운행하던 자동차와 충돌... |
| 2 | 99다30428 | 대법원 | 1999-08-24 | fault_ratio_precedent_db:117997#117997:structured_1500_250:0005 | 구상금 | 합하여 발생한 것이라고 판단하여 소외 2의 과실을 25%로 정하였다. 원심의 위 판단 부분을 살펴보면, 원심은, 소외 2를 정지신호에서 직진신호로 바뀔 즈음에 직진신호에 따라 출발하여 교차로를 통과하려는 운전자... | 거쳐 직진신호로 바뀌자 다시 가속하여 교차로에 진입한 사실, 소외 2 진행 방향의 신호가 그와 같은 경우에 소외 1 진행 방향의 신호는 계속 정지신호인 사실, 소외 1은 교차로에 이르기 이전부터 전방의 신호가 정지신호이었음에도 이를 무시한 채 그대로 교차로에 진입한 사실, 소외 2... |
| 3 | 2023나41651 | 서울중앙지방법원 | 2024-04-17 | fault_ratio_precedent_db:605559#605559:structured_1500_250:0019 | 부당이득금 | 과실비율을 새로이 판단하여야 한다). 가) 소외 2는 2차로에서 신호대기를 하던 중 좌회전 전용차로인 1차로로 급히 진입한 것이었으므로 1차로를 주행하던 소외 1로서는 2차로에서 직진 신호를 기다리고 있던 소외... | 과실비율을 새로이 판단하여야 한다). 가) 소외 2는 2차로에서 신호대기를 하던 중 좌회전 전용차로인 1차로로 급히 진입한 것이었으므로 1차로를 주행하던 소외 1로서는 2차로에서 직진 신호를 기다리고 있던 소외 2가 갑자기 좌회전 전용차로로 차선을 변경할 것을 예측하기는 어려웠을.... |
| 4 | 2005다7177 | 대법원 | 2005-05-13 | fault_ratio_precedent_db:67558#67558:structured_1500_250:0005 | 손해배상(자) | 한 원인이 되었다는 이유로 피고의 책임을 80%로 제한하였다. 2. 기록에 비추어 살펴보면, 원고가 사고 당시 제한시속을 넘어 과속하였다는 원심의 사실인정은 정당하고, 거기에 상고이유에서 주장하는 바와 같은 채... | 예상하여 그에 따른 사고발생을 미리 방지할 특별한 조치까지 강구할 주의의무는 없으며, 다만 신호를 준수하여 진행하는 차량의 운전자라고 하더라도 이미 교차로에 진입하고 있는 다른 차량이 있다거나 다른 차량이 그 진행방향의 신호가 진행신호에서 정지신호로 바뀐 직후에 교차로를 진입하여.... |
| 5 | 99다30428 | 대법원 | 1999-08-24 | fault_ratio_precedent_db:117997#117997:structured_1500_250:0005 | 구상금 | 합하여 발생한 것이라고 판단하여 소외 2의 과실을 25%로 정하였다. 원심의 위 판단 부분을 살펴보면, 원심은, 소외 2를 정지신호에서 직진신호로 바뀔 즈음에 직진신호에 따라 출발하여 교차로를 통과하려는 운전자... | 거쳐 직진신호로 바뀌자 다시 가속하여 교차로에 진입한 사실, 소외 2 진행 방향의 신호가 그와 같은 경우에 소외 1 진행 방향의 신호는 계속 정지신호인 사실, 소외 1은 교차로에 이르기 이전부터 전방의 신호가 정지신호이었음에도 이를 무시한 채 그대로 교차로에 진입한 사실, 소외 2... |
| 6 | 2021나80829 | 서울중앙지방법원 | 2022-11-25 | fault_ratio_precedent_db:236063#236063:structured_1500_250:0009 | 구상금 | %] 및 이에 대한 지연손해금을 구상금으로 지급할 의무가 있다. 3. 청구원인에 관한 판단 가. 공동불법행위 책임의 발생 1) 과실비율 이 사건의 쟁점은 과실비율이다. 앞서 인정한 사실 및 앞서 든 증거들을 종... | %] 및 이에 대한 지연손해금을 구상금으로 지급할 의무가 있다. 3. 청구원인에 관한 판단 가. 공동불법행위 책임의 발생 1) 과실비율 이 사건의 쟁점은 과실비율이다. / 원고차량에게 위험경고를 한 다른 차량은 원고차량을 발견하고 이를 피해서 1차로로 진로변경을 하여 사고를 방지하... |
| 7 | 99다30428 | 대법원 | 1999-08-24 | fault_ratio_precedent_db:117997#117997:structured_1500_250:0005 | 구상금 | 합하여 발생한 것이라고 판단하여 소외 2의 과실을 25%로 정하였다. 원심의 위 판단 부분을 살펴보면, 원심은, 소외 2를 정지신호에서 직진신호로 바뀔 즈음에 직진신호에 따라 출발하여 교차로를 통과하려는 운전자... | 거쳐 직진신호로 바뀌자 다시 가속하여 교차로에 진입한 사실, 소외 2 진행 방향의 신호가 그와 같은 경우에 소외 1 진행 방향의 신호는 계속 정지신호인 사실, 소외 1은 교차로에 이르기 이전부터 전방의 신호가 정지신호이었음에도 이를 무시한 채 그대로 교차로에 진입한 사실, 소외 2... |
| 8 | 2002다38767 | 대법원 | 2002-09-06 | fault_ratio_precedent_db:81877#81877:structured_1500_250:0003 | 손해배상(자) | fault_ratio_evidence_terms: 80%로, 위 피고의 과실비율 과실비율 과실상계 과실상계에 관하여는 위 피해자측인 위 소외 2의 과실비율을 80%로, 위 피고의 과실비율을 20% 손해배상 손해... | fault_ratio_evidence_terms: 80%로, 위 피고의 과실비율 과실비율 과실상계 과실상계에 관하여는 위 피해자측인 위 소외 2의 과실비율을 80%로, 위 피고의 과실비율을 20% 손해배상 손해배상(자) 주의의무 피고의 과실 횡단보도 fault_ratio_numbe... |
| 9 | 2006가단113723 | 부산지법 | 2007-03-23 | fault_ratio_precedent_db:70703#70703:structured_1500_250:0008 | 손해배상(자)등 | 책되어야 한다고 주장한다. 나. 판 단 (1) 일반적으로 중앙선이 설치된 도로를 자기 차로를 따라 운행하는 자동차 운전자로서는 마주 오는 자동차도 자기 차로를 지켜 운행하리라고 신뢰하는 것이 보통이므로 상대방... | 판 단 (1) 일반적으로 중앙선이 설치된 도로를 자기 차로를 따라 운행하는 자동차 운전자로서는 마주 오는 자동차도 자기 차로를 지켜 운행하리라고 신뢰하는 것이 보통이므로 상대방 자동차의 비정상적인 운행을 미리 예견할 수 있는 특별한 사정이 없다면 상대방 자동차가 중앙선을 침범해 들... |
| 10 | 2013다5435 | 대법원 | 2013-05-23 | fault_ratio_precedent_db:171923#171923:structured_1500_250:0005 | 손해배상(자) | 【원고, 상고인】 【피고, 피상고인】 전국화물자동차운송사업연합회 (소송대리인 법무법인 태일 담당변호사 김재용) 【원심판결】 서울중앙지법 2012. 11. 30. 선고 2012나24179 판결 【주 문】 원심판결... | 정지되게 한 데에 그 운전자의 과실이 있다면 이는 특별한 사정이 없는 한 후행 추돌사고로 인한 손해에 대해서도 인과관계가 있다고 보아야 할 것이다(대법원 2009. 12. 10. / 그런데도 원고 차량 운전자는 전혀 조향장치를 조작하지 않고 스키드 마크도 남기지 않은 채 그대로 피... |

## 안전 점검

| 점검 항목 | 결과 |
| --- | --- |
| 전체 success 여부 | True |
| 모든 입력 evidence 보유 | True |
| 모든 입력 display_evidence 보유 | True |
| 모든 입력 양쪽 source 보유 | True |
| 모든 입력 V2 계약 버전 | True |
| success 아닌 run | [] |
| evidence 0개 run | [] |
| review_case 0개 run | [] |
| fault_ratio_precedent 0개 run | [] |
| ratio 없음 run | [] |
| display warning run | [] |
| 인코딩 점검 필요 run | [] |
| V2 계약 아닌 run | [] |

## 해석

- `review_case`와 `fault_ratio_precedent`가 모두 1개 이상이면 V2 통합 RAG가 실제 Agent 출력에 반영된 것이다.
- `evidence_count`는 최종 병합 결과이며, 기본 전략은 5+5 source quota, final_top_k=10이다.
- 검색기 내부 BM25 점수는 source 간 직접 비교 기준이 아니다. V2는 source별 quota로 병합해 두 근거 유형을 함께 노출한다.
- 특정 run에서 한쪽 source가 0개라면 검색 실패라기보다 해당 질의에서 해당 source의 후보가 부족했거나 validator에서 제거됐을 수 있다.

## 다음 단계

1. 상위 display_evidence가 사용자에게 보여줄 근거로 충분한지 샘플 검수한다.
2. Supervisor 계약 V2 문서의 source_summary와 multi-source evidence 설명에 맞게 실제 연결한다.
3. 추후 traffic_precedent 또는 standard 인정기준 확장 여부를 결정한다.
