"""파일 해시와 파일 크기 계산 모듈.

수집 manifest에는 파일 크기와 SHA256을 반드시 기록한다.
이 값이 있어야 같은 파일인지, 제목만 바뀐 파일인지, 내용이 개정된 파일인지 판단할 수 있다.
"""

# hashlib는 SHA256 해시를 계산하기 위해 사용한다.
import hashlib

# Path는 파일 경로를 다루기 위해 사용한다.
from pathlib import Path


# calculate_sha256 함수는 파일 내용을 읽어 SHA256 해시를 계산한다.
def calculate_sha256(file_path: Path) -> str:
    # sha256 객체를 생성한다.
    digest = hashlib.sha256()
    # 파일을 바이너리 모드로 연다.
    with file_path.open("rb") as file:
        # 큰 파일을 한 번에 읽지 않기 위해 1MB 단위로 반복한다.
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            # 읽은 조각을 해시 계산에 추가한다.
            digest.update(chunk)
    # 16진수 문자열 해시를 반환한다.
    return digest.hexdigest()


# file_size 함수는 파일 크기를 바이트 단위로 반환한다.
def file_size(file_path: Path) -> int:
    # Path.stat().st_size로 파일 크기를 가져온다.
    return file_path.stat().st_size
