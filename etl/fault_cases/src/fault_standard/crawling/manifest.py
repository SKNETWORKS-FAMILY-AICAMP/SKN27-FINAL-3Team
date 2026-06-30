"""Collection manifest 기록 모듈.

수집 단계에서 성공, 실패, 중복, 수동 등록 등 모든 결과를 JSONL로 남긴다.
manifest가 있어야 어떤 PDF를 어디서 왜 받았는지 추적할 수 있다.
"""

# json은 dict를 JSON 문자열로 저장하기 위해 사용한다.
import json

# Path는 manifest 파일 경로를 다루기 위해 사용한다.
from pathlib import Path

# Iterable은 여러 row를 기록할 때 타입 힌트로 사용한다.
from typing import Iterable


# append_jsonl 함수는 JSONL 파일에 row 하나를 추가한다.
def append_jsonl(path: Path, row: dict) -> None:
    # manifest가 들어갈 폴더를 생성한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # 파일을 append 모드로 연다.
    with path.open("a", encoding="utf-8") as file:
        # dict를 JSON 문자열로 변환해 한 줄로 기록한다.
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


# write_jsonl 함수는 JSONL 파일을 새로 작성한다.
def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    # 출력 폴더를 생성한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    # 파일을 write 모드로 연다.
    with path.open("w", encoding="utf-8") as file:
        # rows를 하나씩 순회한다.
        for row in rows:
            # 각 row를 JSON 문자열 한 줄로 저장한다.
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


# read_jsonl 함수는 기존 JSONL 파일을 읽어 dict 목록으로 반환한다.
def read_jsonl(path: Path) -> list[dict]:
    # 파일이 없으면 빈 리스트를 반환한다.
    if not path.exists():
        # 아직 수집 이력이 없다는 뜻이다.
        return []
    # 결과 row를 담을 리스트를 만든다.
    rows = []
    # 파일을 읽기 모드로 연다.
    with path.open("r", encoding="utf-8") as file:
        # 파일을 한 줄씩 순회한다.
        for line in file:
            # 빈 줄은 건너뛴다.
            if not line.strip():
                # 빈 줄이면 다음 줄로 넘어간다.
                continue
            # JSON 문자열을 dict로 파싱한다.
            rows.append(json.loads(line))
    # 읽은 row 목록을 반환한다.
    return rows
