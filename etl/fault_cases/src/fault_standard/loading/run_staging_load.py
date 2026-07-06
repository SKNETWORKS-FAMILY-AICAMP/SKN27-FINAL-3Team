"""CLI entrypoint for loading fault standard JSONL outputs into PostgreSQL staging.

이 파일의 역할:
- 이미 실행 중인 PostgreSQL에 접속한다.
- staging 테이블을 만들거나, 전처리 JSONL을 staging 테이블에 적재한다.
- Docker 실행이나 DB 생성은 하지 않는다. 그 기능은 run_staging_pipeline.py가 담당한다.
"""

from __future__ import annotations

# CLI 옵션을 파싱하기 위해 사용한다.
import argparse
# 에러 메시지를 stderr로 출력하기 위해 사용한다.
import sys
# source-root 인자를 파일 경로 객체로 바꾸기 위해 사용한다.
from pathlib import Path

# `.env` 기반 PostgreSQL connection을 생성한다.
from .db import connect_postgres
# 실제 JSONL 탐색/적재 로직과 기본 설정값을 가져온다.
from .staging_loader import DEFAULT_BATCH_SIZE, DEFAULT_PREPROCESSED_ROOT, load_staging
# `--create-schema-only`일 때 staging DDL만 생성하기 위해 사용한다.
from .staging_schema import create_staging_schema


def parse_args() -> argparse.Namespace:
    """PowerShell/터미널에서 넘긴 실행 옵션을 argparse Namespace로 변환한다."""
    # CLI 설명 문구를 정의한다.
    parser = argparse.ArgumentParser(description="Load fault standard preprocessed JSONL files into PostgreSQL staging tables.")
    # 전처리 산출물 루트 폴더를 받는다. 기본값은 artifacts/fault_standard_output/preprocessed다.
    parser.add_argument("--source-root", default=str(DEFAULT_PREPROCESSED_ROOT), help="Preprocessed output root directory.")
    # DB 접속 정보가 들어 있는 .env 파일 경로를 받는다.
    parser.add_argument("--env-file", default=".env", help="Environment file with PostgreSQL settings.")
    # 적재 batch 이름을 받는다. 없으면 loader 내부에서 timestamp 기반 이름을 만든다.
    parser.add_argument("--batch-name", default=None, help="Batch name. Defaults to timestamped name.")
    # 전처리 버전 라벨을 batch metadata에 남기기 위해 받는다.
    parser.add_argument("--preprocess-version", default=None, help="Optional preprocessing version label.")
    # batch 설명 문구를 DB에 남기기 위해 받는다.
    parser.add_argument("--description", default="fault standard staging load", help="Batch description.")
    # execute_values로 한 번에 insert할 row 묶음 크기를 받는다.
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Bulk insert page size.")
    parser.add_argument(
        # 같은 batch-name이 있을 때 지우고 다시 넣을지, 그대로 추가할지 결정한다.
        "--mode",
        choices=("replace-batch", "append"),
        default="replace-batch",
        help="replace-batch deletes an existing batch with the same name before loading.",
    )
    # 데이터 적재 없이 테이블만 만들고 종료하는 옵션이다.
    parser.add_argument("--create-schema-only", action="store_true", help="Only create staging tables and exit.")
    # argparse가 해석한 결과를 main()에서 쓰도록 반환한다.
    return parser.parse_args()


def main() -> int:
    """CLI 실행 진입점. 성공하면 0, 실패하면 1을 반환한다."""
    # 사용자가 입력한 CLI 옵션을 읽는다.
    args = parse_args()
    try:
        # .env 정보를 사용해 PostgreSQL에 접속한다.
        conn = connect_postgres(args.env_file)
    except Exception as exc:
        # 접속 자체가 실패하면 적재를 진행할 수 없으므로 에러를 출력하고 종료한다.
        print(f"[staging] database connection failed: {exc}", file=sys.stderr)
        return 1

    # DDL/INSERT를 하나의 명시적 transaction 안에서 관리한다.
    conn.autocommit = False
    try:
        # 스키마만 만들라는 옵션이면 DDL 생성 후 종료한다.
        if args.create_schema_only:
            create_staging_schema(conn)
            print("[staging] schema ready")
            return 0

        # 실제 전처리 JSONL 전체를 staging 테이블로 적재한다.
        result = load_staging(
            conn=conn,
            source_root=Path(args.source_root),
            batch_name=args.batch_name,
            preprocess_version=args.preprocess_version,
            description=args.description,
            replace_batch=args.mode == "replace-batch",
            batch_size=args.batch_size,
        )
    except Exception as exc:
        # 적재 중 하나라도 실패하면 transaction을 되돌린다.
        conn.rollback()
        print(f"[staging] load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # 성공/실패와 무관하게 DB connection을 닫는다.
        conn.close()

    # 적재 결과 요약을 터미널에 출력한다.
    print(f"[staging] batch_id={result['batch_id']} batch_name={result['batch_name']}")
    print(f"[staging] source_root={result['source_root']}")
    print(f"[staging] jsonl_files={result['file_count']}")
    print("[staging] table counts:")
    # 테이블명을 정렬해서 출력하면 매번 결과 비교가 쉽다.
    for table_name, count in sorted(result["db_counts"].items()):
        print(f"  - {table_name}: {count}")
    # 정상 종료를 의미한다.
    return 0


if __name__ == "__main__":
    # `python -m ...run_staging_load`로 실행될 때 main()을 호출한다.
    raise SystemExit(main())
