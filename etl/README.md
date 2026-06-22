# etl

외부 또는 원천 데이터를 수집하고 정제해 저장소에 적재 가능한 형태로 만드는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `common/` | source registry, ingestion run tracking, 공통 ETL 유틸리티를 둔다. |
| `legal/` | 도로교통법, 시행령, 시행규칙, 고시, 행정 기준 수집과 전처리를 둔다. |
| `fine_rules/` | 과태료·범칙금·벌칙 분석용 룰과 매핑 데이터 준비 로직을 둔다. |
| `fault_cases/` | 판례, 유튜브 자막, 과실비율심의사례 수집과 전처리를 둔다. |
| `vision_manifest/` | 이미지/영상 dataset manifest와 metadata 준비 로직을 둔다. |

## 배치 원칙

- API 응답 로직과 화면 로직은 `etl/`에 두지 않는다.
- 법률 원문 데이터와 과태료 분석용 룰/매핑 데이터는 서로 분리한다.
- 원천 데이터 위치, 수집일, 이용 조건, 원문 reference를 추적 가능하게 남긴다.
- 저장소 구조와 migration은 `storage/`에 둔다.
