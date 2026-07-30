# 과실비율 RAG 부트스트랩

이 디렉터리는 판례·인정기준 RAG 데이터베이스를 최초 구축할 때 사용하는
검증 완료 임베딩 묶음을 Git으로 전달하는 위치다.

## 디렉터리 규칙

```text
bootstrap/
├── precedent/
│   └── qwen3_4b_bge_v1/
└── fault_standard/
    └── qwen3_4b_r6/
```

- 첫 번째 하위 디렉터리는 RAG 도메인이다.
- 두 번째 하위 디렉터리는 임베딩·검색 계약 버전이다.
- 각 버전 디렉터리는 데이터 파일과 해시·모델 정보를 담은 README 또는
  manifest를 함께 보관한다.

## 경계

- 이곳은 런타임 Python 패키지가 아니다.
- `etl/fault_cases/artifacts/`의 실험 산출물과 구분한다.
- `etl/fault_cases/standard_TEST/` 등 생성·검증 원본은 이동하거나 수정하지 않는다.
- 데이터베이스 적재기는 이 검증된 복사본을 입력으로 사용하되 파일을 직접
  수정하지 않는다.
- 동일 artifact의 Git 전달용 복사본을 다른 런타임 디렉터리에 중복 보관하지 않는다.

