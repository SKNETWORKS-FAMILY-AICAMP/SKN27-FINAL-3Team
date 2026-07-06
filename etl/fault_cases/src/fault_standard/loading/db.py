"""Database connection helpers for fault standard loading scripts.

이 파일의 역할:
- loading 단계에서 PostgreSQL 접속 정보를 한 곳에서 읽는다.
- `.env` 파일과 OS 환경변수를 기준으로 DB 접속 파라미터를 만든다.
- 실제 psycopg2 connection 객체를 생성한다.
"""

from __future__ import annotations

# 환경변수에서 POSTGRES_* 값을 읽기 위해 사용한다.
import os
# psycopg2가 없을 때 에러 메시지를 stderr로 출력하기 위해 사용한다.
import sys
# `.env` 경로를 문자열/Path 둘 다 받을 수 있게 하기 위해 사용한다.
from pathlib import Path
# DB 접속 설정 dict의 value 타입을 넓게 표현하기 위해 사용한다.
from typing import Any

# 프로젝트 공통 .env 로더를 사용해 환경변수를 주입한다.
from etl.common.utils import load_env_file


def load_database_env(env_file: str | Path = ".env") -> dict[str, Any]:
    """Load PostgreSQL connection settings from environment variables.

    우선순위:
    1. `FAULT_STANDARD_POSTGRES_DB`: 과실비율 인정기준 전용 DB
    2. `POSTGRES_DB`: 기존 compose 공통 DB
    3. `law_db`: 아무 설정도 없을 때의 기존 기본값
    """
    # `.env`가 있으면 파일 안의 값을 현재 프로세스 환경변수로 올린다.
    load_env_file(Path(env_file))
    # 인정기준은 law_db와 분리할 수 있도록 전용 DB 변수를 우선 사용한다.
    db_name = os.getenv("FAULT_STANDARD_POSTGRES_DB") or os.getenv("POSTGRES_DB", "law_db")
    # psycopg2.connect(**params)에 그대로 넘길 접속 파라미터를 만든다.
    return {
        # Docker compose PostgreSQL 포트가 로컬로 열려 있으므로 기본 host는 localhost다.
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        # PostgreSQL 기본 포트는 5432이고, compose에서도 이 포트를 사용한다.
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        # compose의 POSTGRES_USER와 맞춘다.
        "user": os.getenv("POSTGRES_USER", "postgres"),
        # 로컬 개발용 기본 비밀번호다. 실제 값은 .env에서 덮어쓴다.
        "password": os.getenv("POSTGRES_PASSWORD", "change-me"),
        # 최종 접속 대상 DB 이름이다.
        "dbname": db_name,
    }


def connect_postgres(env_file: str | Path = ".env"):
    """Create a psycopg2 PostgreSQL connection using project env settings."""
    try:
        # psycopg2는 PostgreSQL 접속 드라이버다. requirements에 psycopg2-binary가 필요하다.
        import psycopg2
    except ImportError:
        # 패키지가 없으면 사용자가 바로 원인을 알 수 있게 stderr로 안내한다.
        print("psycopg2-binary is required. Install dependencies from requirements.txt.", file=sys.stderr)
        raise

    # `.env`/환경변수에서 접속 정보를 만든다.
    params = load_database_env(env_file)
    # PostgreSQL connection 객체를 생성해서 호출자에게 넘긴다.
    return psycopg2.connect(**params)
