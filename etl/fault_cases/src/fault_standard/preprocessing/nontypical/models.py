# -*- coding: utf-8 -*-
"""전처리 과정에서 공통으로 사용하는 데이터 구조를 정의합니다."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PageText:
    """PDF 한 페이지의 텍스트 정보를 담는 자료 구조입니다."""

    # PDF 안에서의 실제 페이지 번호입니다. 1부터 시작합니다.
    page_no: int

    # PDF Loader가 처음 읽은 원문 텍스트입니다.
    raw_text: str

    # 기본 클리닝을 적용한 텍스트입니다.
    clean_text: str

    # 어떤 Loader로 읽었는지 저장합니다.
    extractor: str

    # 페이지 추출 중 에러가 있으면 문자열로 저장합니다.
    error: Optional[str] = None
