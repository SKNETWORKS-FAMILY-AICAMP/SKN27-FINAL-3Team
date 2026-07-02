"""PostgreSQL loading utilities for fault standard preprocessing outputs.

이 패키지의 역할:
- 전처리된 과실비율 인정기준 JSONL을 PostgreSQL staging DB에 저장한다.
- `run_staging_pipeline.py`는 Docker/PostgreSQL 준비까지 포함한 원클릭 실행용이다.
- `run_staging_load.py`는 이미 준비된 DB에 적재만 수행하는 CLI다.
- `staging_schema.py`는 staging table 정의를 담당한다.
- `staging_loader.py`는 JSONL 탐색과 실제 insert를 담당한다.
- `db.py`는 PostgreSQL 접속 설정을 담당한다.
"""
