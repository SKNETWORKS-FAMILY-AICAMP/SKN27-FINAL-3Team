# 3코퍼스 공통 임베딩 A/B 실행기

프로젝트 루트에서 실행합니다. OpenAI 모델 실행 시에만 루트 `.env`의
`OPENAI_API_KEY`를 읽습니다. 키의 값·길이·일부는 로그나 산출물에 남기지 않습니다.

```powershell
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 preflight
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 snapshot

# OpenAI 1024차원 모델
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 embed-openai --model-key openai_small_1024 --model text-embedding-3-small --dimensions 1024 --batch-size 32
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 embed-openai --model-key openai_large_1024 --model text-embedding-3-large --dimensions 1024 --batch-size 32

# GPU 로컬 모델: E5에는 모델 권장 query/passage 접두어를 적용한다.
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 embed-local --model-key qwen3_06b_1024 --model Qwen/Qwen3-Embedding-0.6B --device cuda --trust-remote-code --batch-size 32
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 embed-local --model-key bge_m3_dense_1024 --model BAAI/bge-m3 --device cuda --batch-size 32
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 embed-local --model-key e5_large_1024 --model intfloat/multilingual-e5-large --device cuda --batch-size 32 --query-prefix "query: " --document-prefix "passage: "

# 각 모델마다 벡터 검증 후 검색·평가한다.
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 validate-vectors --model-key qwen3_06b_1024
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 retrieve-score --model-key qwen3_06b_1024

# 5개 모델 × 3개 코퍼스가 모두 완료된 후에만 두 개의 최종 MD를 생성한다.
python -m etl.fault_cases.src.embedding_ab_shared.track_b_5models_fixed1024.run_ab --run-id 20260716_embedding_ab_v1 build-reports
```

`build-reports`는 모델 또는 코퍼스 결과가 하나라도 빠지면 중단합니다. 따라서 부분
실험 결과가 최종 비교표나 분석 리포트로 잘못 표시되지 않습니다.
