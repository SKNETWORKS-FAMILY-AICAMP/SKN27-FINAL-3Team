"""One-command setup and staging load for fault standard preprocessing outputs.

This wrapper keeps docker-compose untouched and uses the existing PostgreSQL
service. It creates the target database when it is missing, then delegates the
actual JSONL staging load to the shared loader.

이 파일의 역할:
- 사용자가 긴 PowerShell 명령을 여러 번 치지 않도록 한 번에 실행한다.
- docker compose의 postgres 서비스가 꺼져 있으면 자동으로 켠다.
- fault_standard_db 같은 전용 DB가 없으면 생성한다.
- staging schema 생성과 JSONL 적재는 기존 loader 함수에 위임한다.
"""

from __future__ import annotations

# CLI 옵션을 받기 위해 사용한다.
import argparse
# 환경변수를 읽고 현재 프로세스에 target DB 이름을 설정하기 위해 사용한다.
import os
# `docker compose up -d postgres`를 Python 코드에서 실행하기 위해 사용한다.
import subprocess
# stderr 출력과 종료 처리를 위해 사용한다.
import sys
# PostgreSQL 컨테이너가 준비될 때까지 재시도 간격을 두기 위해 사용한다.
import time
# docker-compose.yml, .env, source-root 같은 경로를 다루기 위해 사용한다.
from pathlib import Path
# DB 접속 파라미터 dict의 값 타입을 넓게 표현하기 위해 사용한다.
from typing import Any

# 프로젝트 공통 .env 로더를 사용한다.
from etl.common.utils import load_env_file

# DB 접속 함수와 env 해석 함수를 재사용한다.
from .db import connect_postgres, load_database_env
# 실제 staging 적재 로직과 기본값을 재사용한다.
from .staging_loader import DEFAULT_BATCH_SIZE, DEFAULT_PREPROCESSED_ROOT, load_staging
# schema만 생성하는 옵션에서 사용한다.
from .staging_schema import create_staging_schema

# 사용자가 DB 이름을 따로 주지 않았을 때 사용할 인정기준 전용 DB 이름이다.
DEFAULT_FAULT_STANDARD_DB = "fault_standard_db"
# 반복 실행해도 같은 batch를 교체할 수 있도록 고정 기본 batch명을 사용한다.
DEFAULT_BATCH_NAME = "fault_standard_preprocessed_latest"
# 현재 전처리 산출물 버전 라벨 기본값이다.
DEFAULT_PREPROCESS_VERSION = "v1"


def parse_args() -> argparse.Namespace:
    """PowerShell/터미널 실행 옵션을 파싱한다."""
    # 전체 pipeline의 CLI 설명을 정의한다.
    parser = argparse.ArgumentParser(
        description="Create the fault-standard PostgreSQL database if needed, then load preprocessed JSONL files into staging tables."
    )
    # 전처리 산출물 루트 폴더를 지정한다.
    parser.add_argument("--source-root", default=str(DEFAULT_PREPROCESSED_ROOT), help="Preprocessed output root directory.")
    # DB 접속 정보가 들어 있는 .env 파일을 지정한다.
    parser.add_argument("--env-file", default=".env", help="Environment file with PostgreSQL settings.")
    parser.add_argument(
        # 적재 대상 DB를 직접 지정할 수 있게 한다.
        "--database",
        default=None,
        help=f"Target database for fault-standard staging. Defaults to FAULT_STANDARD_POSTGRES_DB or {DEFAULT_FAULT_STANDARD_DB}.",
    )
    parser.add_argument(
        # target DB를 만들 때 접속할 기존 DB를 지정한다.
        "--admin-database",
        default=None,
        help="Existing database used only to create the target database. Defaults to POSTGRES_DB, then postgres.",
    )
    # 적재 batch 이름이다. 기본값은 매번 같은 batch를 교체하는 용도다.
    parser.add_argument("--batch-name", default=DEFAULT_BATCH_NAME, help="Batch name to create or replace.")
    # batch metadata에 남길 전처리 버전이다.
    parser.add_argument("--preprocess-version", default=DEFAULT_PREPROCESS_VERSION, help="Preprocessing version label.")
    # batch 설명 문구다.
    parser.add_argument("--description", default="fault standard staging load", help="Batch description.")
    # bulk insert 페이지 크기다.
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Bulk insert page size.")
    parser.add_argument(
        # 같은 batch-name을 지우고 다시 적재할지, 새로 추가할지 결정한다.
        "--mode",
        choices=("replace-batch", "append"),
        default="replace-batch",
        help="replace-batch deletes an existing batch with the same name before loading.",
    )
    # DB와 table만 준비하고 실제 데이터 적재는 건너뛰는 옵션이다.
    parser.add_argument("--create-schema-only", action="store_true", help="Create database and staging tables only.")
    # 이미 DB가 있다는 것을 알고 있을 때 DB 생성 확인을 건너뛰는 옵션이다.
    parser.add_argument("--skip-create-db", action="store_true", help="Skip target database creation check.")
    # Docker를 직접 켠 상태에서 compose up 호출을 생략하는 옵션이다.
    parser.add_argument("--skip-docker-up", action="store_true", help="Skip automatic 'docker compose up -d postgres'.")
    # argparse 결과를 반환한다.
    return parser.parse_args()


def configure_target_database(env_file: str | Path, database: str | None) -> str:
    """Load .env and set the target database for this process."""
    # .env 파일을 먼저 읽어서 POSTGRES_* 값을 환경변수로 올린다.
    load_env_file(Path(env_file))
    # CLI 인자 > FAULT_STANDARD_POSTGRES_DB > 기본값 순서로 target DB를 고른다.
    target_db = database or os.getenv("FAULT_STANDARD_POSTGRES_DB") or DEFAULT_FAULT_STANDARD_DB
    # 이후 connect_postgres()가 같은 DB를 보도록 현재 프로세스 환경변수에 고정한다.
    os.environ["FAULT_STANDARD_POSTGRES_DB"] = target_db
    # 로그 출력과 DB 생성 함수에서 쓰도록 DB 이름을 반환한다.
    return target_db


def postgres_connection_params(env_file: str | Path, dbname: str) -> dict[str, Any]:
    """Build connection parameters for a specific PostgreSQL database."""
    # 기본 DB 접속 파라미터를 읽는다.
    params = load_database_env(env_file)
    # 이 함수는 특정 DB에 접속해야 하므로 dbname만 덮어쓴다.
    params["dbname"] = dbname
    # psycopg2.connect(**params)에 넘길 dict를 반환한다.
    return params


def find_compose_project_dir() -> Path:
    """Find the nearest project directory that contains docker-compose.yml."""
    # 현재 작업 디렉터리와 이 파일의 상위 폴더들을 후보로 본다.
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    # 후보 중 docker-compose.yml이 있는 첫 폴더를 compose 프로젝트 루트로 사용한다.
    for candidate in candidates:
        if (candidate / "docker-compose.yml").exists():
            return candidate
    # 어디에서도 compose 파일을 못 찾으면 Docker 자동 실행을 할 수 없다.
    raise FileNotFoundError("docker-compose.yml not found from current working directory or script path.")


def start_postgres_service() -> None:
    """Start the existing compose postgres service without changing compose files."""
    # docker compose 명령을 실행할 프로젝트 루트를 찾는다.
    project_dir = find_compose_project_dir()
    print("[staging] starting docker compose service: postgres")
    # 기존 docker-compose.yml을 그대로 사용해서 postgres 서비스만 띄운다.
    result = subprocess.run(
        ["docker", "compose", "up", "-d", "postgres"],
        cwd=project_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    # docker compose stdout을 사용자에게 보여준다.
    if result.stdout.strip():
        print(result.stdout.strip())
    # docker compose stderr도 숨기지 않고 보여준다.
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    # compose 명령 실패 시 이후 DB 접속으로 넘어가지 않는다.
    if result.returncode != 0:
        raise RuntimeError(f"docker compose up -d postgres failed with exit code {result.returncode}")


def connect_with_retry(params: dict[str, Any], attempts: int = 20, delay_seconds: float = 1.0):
    """Connect to PostgreSQL, waiting briefly for a freshly started container."""
    # PostgreSQL connection을 만들기 위해 psycopg2를 사용한다.
    import psycopg2

    # 마지막 접속 실패 원인을 저장했다가 최종 실패 때 다시 던진다.
    last_error: Exception | None = None
    # 컨테이너가 막 켜진 직후에는 DB가 아직 준비 중일 수 있어 여러 번 시도한다.
    for attempt in range(1, attempts + 1):
        try:
            # 접속에 성공하면 connection 객체를 즉시 반환한다.
            return psycopg2.connect(**params)
        except psycopg2.OperationalError as exc:
            # 접속 실패 원인을 저장한다.
            last_error = exc
            # 마지막 시도라면 더 기다리지 않고 실패 처리한다.
            if attempt == attempts:
                break
            # 다음 재시도 전 잠깐 기다린다.
            time.sleep(delay_seconds)
    # 끝까지 실패하면 마지막 OperationalError를 그대로 보여준다.
    raise last_error or RuntimeError("PostgreSQL connection failed")


def ensure_database_exists(env_file: str | Path, target_db: str, admin_db: str | None) -> None:
    """Create the target database if it does not exist."""
    try:
        # DB 존재 여부 확인과 CREATE DATABASE 실행을 위해 psycopg2를 사용한다.
        import psycopg2
        # DB 이름을 안전하게 SQL identifier로 넣기 위해 psycopg2.sql을 사용한다.
        from psycopg2 import sql
    except ImportError:
        # psycopg2가 없으면 사용자가 바로 설치 원인을 알 수 있게 안내한다.
        print("psycopg2-binary is required. Install dependencies from requirements.txt.", file=sys.stderr)
        raise

    # DB 생성은 target DB가 아닌 이미 존재하는 maintenance DB에 접속해서 해야 한다.
    maintenance_db = admin_db or os.getenv("POSTGRES_DB") or "postgres"
    # target DB와 maintenance DB가 같으면 아직 target DB가 없을 수 있으므로 postgres로 바꾼다.
    if maintenance_db == target_db:
        maintenance_db = "postgres"

    # maintenance DB 접속 파라미터를 만든다.
    params = postgres_connection_params(env_file, maintenance_db)
    # 막 시작한 컨테이너를 고려해 재시도하며 접속한다.
    conn = connect_with_retry(params)
    # CREATE DATABASE는 transaction 안에서 실행할 수 없으므로 autocommit이 필요하다.
    conn.autocommit = True
    try:
        # cursor를 열어 DB 존재 확인과 생성 SQL을 실행한다.
        with conn.cursor() as cur:
            # pg_database catalog에서 target DB가 이미 있는지 확인한다.
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
            if cur.fetchone():
                print(f"[staging] database already exists: {target_db}")
                return
            # target DB가 없으면 새로 생성한다. DB 이름은 Identifier로 안전하게 감싼다.
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(target_db)))
            print(f"[staging] database created: {target_db}")
    finally:
        # DB 생성 확인용 connection을 닫는다.
        conn.close()


def print_load_result(result: dict[str, Any]) -> None:
    """staging 적재 결과를 사람이 읽기 쉬운 형태로 출력한다."""
    # batch 식별자를 출력한다.
    print(f"[staging] batch_id={result['batch_id']} batch_name={result['batch_name']}")
    # 어떤 전처리 루트에서 읽었는지 출력한다.
    print(f"[staging] source_root={result['source_root']}")
    # 읽은 JSONL 파일 개수를 출력한다.
    print(f"[staging] jsonl_files={result['file_count']}")
    print("[staging] table counts:")
    # 테이블별 적재 건수를 정렬해서 출력한다.
    for table_name, count in sorted(result["db_counts"].items()):
        print(f"  - {table_name}: {count}")


def main() -> int:
    """전체 자동 pipeline 실행 진입점."""
    # CLI 옵션을 읽는다.
    args = parse_args()
    # target DB를 결정하고 현재 프로세스 환경변수에도 반영한다.
    target_db = configure_target_database(args.env_file, args.database)
    print(f"[staging] target_database={target_db}")

    try:
        # 기본적으로 postgres compose 서비스를 자동으로 시작한다.
        if not args.skip_docker_up:
            start_postgres_service()

        # target DB가 없으면 생성한다.
        if not args.skip_create_db:
            ensure_database_exists(args.env_file, target_db, args.admin_database)

        # target DB에 실제 적재용 connection을 만든다.
        conn = connect_postgres(args.env_file)
    except Exception as exc:
        # Docker/DB 생성/접속 중 하나라도 실패하면 여기서 종료한다.
        print(f"[staging] database setup failed: {exc}", file=sys.stderr)
        return 1

    # 이후 schema 생성과 적재는 하나의 transaction 흐름으로 관리한다.
    conn.autocommit = False
    try:
        # 스키마만 만들라는 옵션이면 DDL 생성 후 종료한다.
        if args.create_schema_only:
            create_staging_schema(conn)
            conn.commit()
            print("[staging] schema ready")
            return 0

        # 실제 staging 적재는 공통 loader 함수에 위임한다.
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
        # 적재 실패 시 DB 변경사항을 rollback한다.
        conn.rollback()
        print(f"[staging] load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # 성공/실패와 무관하게 connection을 닫는다.
        conn.close()

    # 정상 적재 결과를 출력한다.
    print_load_result(result)
    # 정상 종료 code다.
    return 0


if __name__ == "__main__":
    # `python -m ...run_staging_pipeline`으로 실행되면 main()을 호출한다.
    raise SystemExit(main())
