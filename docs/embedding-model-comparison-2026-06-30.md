# E5 vs OpenAI 임베딩 정량 비교 보고서

- 생성일: 2026-06-30T00:22:41.709838+00:00
- 비교 범위: 동일 chunk 68건 / 입력 68건
- E5: `intfloat/multilingual-e5-large`
- OpenAI: `text-embedding-3-large` (1024 dimensions)

## 1. 요약

- 두 모델 모두 100.0% coverage로 전체 입력에 대한 임베딩을 보유했다.
- exact-text retrieval Top-1 accuracy는 E5 0.824, OpenAI 1.000이다.
- 모델 간 1위 결과 일치율은 0.824, Top-5 평균 Jaccard는 0.661이다.
- 문서 간 pairwise similarity Pearson 상관은 0.937이다.

## 2. Coverage / Vector 품질

| 항목 | E5 | OpenAI |
|---|---:|---:|
| 임베딩 건수 | 68 | 68 |
| 차원 | 1024 | 1024 |
| vector norm 평균 | 1.000000 | 1.000000 |
| vector norm 표준편차 | 0.000000 | 0.000000 |

## 3. Retrieval 비교

| 지표 | E5 | OpenAI | 해석 |
|---|---:|---:|---|
| Exact-text Top-1 accuracy | 0.824 | 1.000 | 입력 chunk 본문을 질의로 넣었을 때 원 chunk를 1위로 회수한 비율 |
| Exact-text Recall@5 | 1.000 | 1.000 | 원 chunk가 Top-5 안에 포함된 비율 |
| MRR | 0.895 | 1.000 | 원 chunk 순위의 역수 평균 |
| Top-1 margin 평균 | 0.001886 | 0.027410 | 1위와 2위 cosine score 차이 |

- 모델 간 Top-1 agreement: 0.824
- 모델 간 Top-5 평균 Jaccard: 0.661

## 4. Embedding Space 비교

| 지표 | E5 | OpenAI |
|---|---:|---:|
| 문서 pairwise cosine 평균 | 0.887625 | 0.644725 |
| 문서 pairwise cosine 중앙값 | 0.874825 | 0.638359 |
| 문서 pairwise cosine p95 | 0.976621 | 0.892899 |
| Top-5 동일 source neighbor 비율 | 0.000 | 0.000 |

- 모델 간 문서 similarity matrix Pearson: 0.937
- 모델 간 문서 neighbor Top-5 평균 Jaccard: 0.693

## 5. 예시 Query 결과

### `road_traffic_act:2026-06-30:offline:article:제1조:article:1`

| Rank | E5 chunk | E5 score | OpenAI chunk | OpenAI score |
|---:|---|---:|---|---:|
| 1 | `road_traffic_act:2026-06-30:offline:article:제1조:article:1` | 0.931383 | `road_traffic_act:2026-06-30:offline:article:제1조:article:1` | 1.000000 |
| 2 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.928504 | `traffic_safety_act:2026-06-30:offline:article:제1조:article:1` | 0.945002 |
| 3 | `road_act:2026-06-30:offline:article:제1조:article:1` | 0.927505 | `road_act:2026-06-30:offline:article:제1조:article:1` | 0.941357 |

### `road_traffic_act:2026-06-30:offline:article:제2조:article:2`

| Rank | E5 chunk | E5 score | OpenAI chunk | OpenAI score |
|---:|---|---:|---|---:|
| 1 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제2조:article:2` | 0.933833 | `road_traffic_act:2026-06-30:offline:article:제2조:article:2` | 1.000000 |
| 2 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2` | 0.933295 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2` | 0.972677 |
| 3 | `road_traffic_act:2026-06-30:offline:article:제2조:article:2` | 0.932614 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제2조:article:2` | 0.969645 |

### `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1`

| Rank | E5 chunk | E5 score | OpenAI chunk | OpenAI score |
|---:|---|---:|---|---:|
| 1 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.932545 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.999172 |
| 2 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.929797 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.954676 |
| 3 | `road_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.929689 | `road_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.953261 |

### `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2`

| Rank | E5 chunk | E5 score | OpenAI chunk | OpenAI score |
|---:|---|---:|---|---:|
| 1 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2` | 0.934265 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2` | 0.999831 |
| 2 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제2조:article:2` | 0.932767 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제2조:article:2` | 0.974596 |
| 3 | `road_act_enforcement_decree:2026-06-30:offline:article:제2조:article:2` | 0.932227 | `road_traffic_act:2026-06-30:offline:article:제2조:article:2` | 0.973275 |

### `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1`

| Rank | E5 chunk | E5 score | OpenAI chunk | OpenAI score |
|---:|---|---:|---|---:|
| 1 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.933008 | `road_traffic_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.999209 |
| 2 | `road_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.930321 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.955662 |
| 3 | `road_traffic_act_enforcement_decree:2026-06-30:offline:article:제1조:article:1` | 0.929115 | `traffic_safety_act_enforcement_rule:2026-06-30:offline:article:제1조:article:1` | 0.948826 |


## 6. 데이터 품질 및 해석 한계

- No automated data quality warning was detected.
- 현재 평가는 정답 라벨이 없는 상태에서 exact-text self retrieval과 모델 간 agreement를 본다. 실제 사용자 질문 품질 평가는 별도 gold query set을 구축한 뒤 Recall@K, nDCG, MRR로 재측정하는 것이 좋다.
- E5는 권장 방식에 맞춰 문서에는 `passage:`, 질의에는 `query:` prefix를 사용했다. OpenAI 임베딩은 query/document prefix 구분이 없으므로 exact-text self retrieval Top-1은 OpenAI 쪽이 구조적으로 유리하게 측정될 수 있다.

## 7. 결론

OpenAI 임베딩은 E5와 동일한 1024차원 비교군으로 생성되었고, 전체 입력 68건에 대해 coverage가 맞춰졌다. 현 단계에서는 데이터 인코딩 품질 이슈 때문에 특정 모델의 최종 우위를 단정하기보다, 두 모델의 검색 안정성 및 neighbor 구조 차이를 기반으로 후속 gold query 평가를 진행하는 것이 타당하다.
