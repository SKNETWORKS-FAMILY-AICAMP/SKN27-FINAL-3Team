#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
traffic_prec_api_collector_all_raw_commented.py

국가법령정보센터 Open API에서 '판례(prec)' 데이터를 수집하는 코드입니다.

이 버전의 핵심은 다음과 같습니다.

1. 법령이 아니라 판례 데이터만 수집합니다.
2. 교통사고 관련 가능성이 있는 키워드로 판례 후보를 넓게 검색합니다.
3. 상세 조회된 판례를 traffic/skipped로 나누지 않습니다.
4. 상세 조회된 모든 판례 후보를 all_prec_candidates_raw.jsonl 하나에 저장합니다.
5. 진짜 교통사고 판례인지, 과실비율 후보인지는 나중에 전처리/분류 단계에서 판단합니다.

.env 예시:
LAW_GO_KR_OC=발급받은_API키

테스트 실행:
python traffic_prec_api_collector_all_raw_commented.py --max-pages-per-keyword 1 --fresh

전체 실행:
python traffic_prec_api_collector_all_raw_commented.py --fresh

참고:
--classify 옵션을 주면 topic_labels를 참고용으로 붙일 수 있습니다.
하지만 이 옵션을 사용해도 파일은 나누지 않고 all_prec_candidates_raw.jsonl 하나에만 저장합니다.
"""

# ============================================================
# 표준 라이브러리 import
# ============================================================

from __future__ import annotations  # 타입 힌트에서 아직 정의되지 않은 타입을 문자열처럼 늦게 평가할 수 있게 함

import argparse  # 명령행 인자 처리를 위해 사용
import html  # HTML 엔티티(&amp; 등)를 일반 문자로 바꾸기 위해 사용
import json  # JSON / JSONL 파일 저장을 위해 사용
import os  # 환경변수 읽기를 위해 사용
import re  # 정규식 기반 텍스트 정리를 위해 사용
import sys  # 에러 출력 및 프로그램 종료를 위해 사용
import time  # API 요청 사이 sleep 처리를 위해 사용
from dataclasses import asdict, dataclass  # 실행 통계 객체를 dict로 바꿔 JSON 저장하기 위해 사용
from pathlib import Path  # 파일 경로를 OS 독립적으로 다루기 위해 사용
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple  # 타입 힌트용
from urllib.parse import urlencode  # source_reference URL 생성 시 query string을 만들기 위해 사용

import requests  # HTTP 요청을 보내기 위해 사용
import xml.etree.ElementTree as ET  # XML 응답 파싱을 위해 사용
from requests.adapters import HTTPAdapter  # requests 재시도 어댑터 연결용
from urllib3.util.retry import Retry  # HTTP 재시도 정책 설정용


# ============================================================
# 국가법령정보센터 판례 API URL
# ============================================================

# 판례 목록 검색 API 주소입니다.
LIST_URL = "https://www.law.go.kr/DRF/lawSearch.do"

# 판례 본문 상세 조회 API 주소입니다.
DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"


# ============================================================
# API 목록 검색에 사용할 기본 키워드
# ============================================================
# 이 키워드는 "후보를 가져오기 위한 검색어"입니다.
# 이 키워드로 검색된 결과가 곧바로 진짜 교통사고 판례라는 뜻은 아닙니다.
# 이 키워드로 목록 후보를 넓게 가져온 뒤, 상세 조회 결과를 all_prec_candidates_raw.jsonl에 저장합니다.

DEFAULT_KEYWORDS = [
    # -------------------------
    # 교통사고 전체 후보 수집용
    # -------------------------
    "교통사고",  # 가장 기본적인 교통사고 검색어
    "자동차 사고",  # 자동차 사고 표현이 들어간 판례 검색
    "차량 사고",  # 차량 사고 표현이 들어간 판례 검색
    "차량 충돌",  # 충돌 사고 후보 검색
    "자동차 충돌",  # 자동차 충돌 사고 후보 검색
    "추돌",  # 후방 추돌 등 추돌 사고 후보 검색
    "후미추돌",  # 후미추돌 사고 후보 검색
    "접촉사고",  # 접촉사고 표현이 들어간 판례 검색
    "교차로 사고",  # 교차로 사고 후보 검색
    "신호위반 사고",  # 신호위반 사고 후보 검색
    "중앙선 침범",  # 중앙선 침범 사고 후보 검색
    "차로 변경 사고",  # 차로 변경 사고 후보 검색
    "진로 변경 사고",  # 진로 변경 사고 후보 검색
    "안전거리 미확보",  # 안전거리 미확보 사고 후보 검색
    "횡단보도 사고",  # 횡단보도 사고 후보 검색
    "보행자 사고",  # 보행자 사고 후보 검색
    "자전거 사고",  # 자전거 사고 후보 검색
    "이륜차 사고",  # 이륜차 사고 후보 검색
    "오토바이 사고",  # 오토바이 사고 후보 검색
    "전동킥보드 사고",  # 전동킥보드 사고 후보 검색
    "개인형 이동장치 사고",  # PM 사고 후보 검색
    "PM 사고",  # PM 약어가 들어간 사고 후보 검색
    "회전교차로 사고",  # 회전교차로 사고 후보 검색
    "유턴 사고",  # 유턴 사고 후보 검색
    "좌회전 사고",  # 좌회전 사고 후보 검색
    "우회전 사고",  # 우회전 사고 후보 검색
    "주차장 사고",  # 주차장 사고 후보 검색
    "개문 사고",  # 문 열림 사고 후보 검색
    "어린이보호구역 사고",  # 어린이보호구역 사고 후보 검색
    "스쿨존 사고",  # 스쿨존 사고 후보 검색

    # -------------------------
    # 과실비율 후보까지 넓게 잡기 위한 검색어
    # -------------------------
    "손해배상(자)",  # 자동차 손해배상 민사 판례 후보 검색
    "손해배상 교통사고",  # 손해배상 + 교통사고 문맥 후보 검색
    "구상금 교통사고",  # 구상금 + 교통사고 문맥 후보 검색
    "자동차보험 구상금",  # 자동차보험 구상금 후보 검색
    "보험자대위 교통사고",  # 보험자대위 + 교통사고 후보 검색
    "과실상계 교통사고",  # 과실상계 + 교통사고 후보 검색
    "과실비율 교통사고",  # 과실비율 + 교통사고 후보 검색
    "자동차손해배상",  # 자동차손해배상 관련 판례 후보 검색
    "교통사고처리특례법",  # 교통사고처리특례법 관련 형사 판례 후보 검색
    "도로교통법위반",  # 도로교통법위반 관련 판례 후보 검색
]


# ============================================================
# 참고용 교통사고 라벨 키워드
# ============================================================
# 이 키워드는 수집 파일을 나누기 위해 쓰지 않습니다.
# --classify 옵션을 켰을 때 topic_labels 참고 라벨을 붙이는 데만 사용합니다.
# 실제 교통사고 여부는 나중에 전처리/분류 단계에서 다시 판단합니다.

TRAFFIC_TERMS = [
    "교통사고",  # 교통사고 표현
    "자동차",  # 자동차 표현
    "차량",  # 차량 표현
    "승용차",  # 승용차 표현
    "승합차",  # 승합차 표현
    "화물차",  # 화물차 표현
    "버스",  # 버스 표현
    "택시",  # 택시 표현
    "오토바이",  # 오토바이 표현
    "이륜차",  # 이륜차 표현
    "이륜자동차",  # 이륜자동차 표현
    "원동기장치자전거",  # 원동기장치자전거 표현
    "자전거",  # 자전거 표현
    "전동킥보드",  # 전동킥보드 표현
    "개인형 이동장치",  # 개인형 이동장치 표현
    "pm",  # PM 약어
    "보행자",  # 보행자 표현
    "횡단보도",  # 횡단보도 표현
    "교차로",  # 교차로 표현
    "회전교차로",  # 회전교차로 표현
    "신호등",  # 신호등 표현
    "신호위반",  # 신호위반 표현
    "중앙선",  # 중앙선 표현
    "차로",  # 차로 표현
    "차선",  # 차선 표현
    "추돌",  # 추돌 표현
    "충돌",  # 충돌 표현
    "접촉사고",  # 접촉사고 표현
    "개문",  # 개문 사고 표현
    "운전자",  # 운전자 표현
    "운행",  # 운행 표현
    "주차장",  # 주차장 표현
    "안전거리",  # 안전거리 표현
    "어린이보호구역",  # 어린이보호구역 표현
    "스쿨존",  # 스쿨존 표현
    "도로교통법",  # 도로교통법 표현
    "교통사고처리특례법",  # 교통사고처리특례법 표현
    "자동차손해배상",  # 자동차손해배상 표현
]


# ============================================================
# 참고용 과실비율 후보 라벨 키워드
# ============================================================
# 이 키워드도 파일을 나누기 위해 쓰지 않습니다.
# --classify 옵션을 켰을 때 topic_labels 참고 라벨을 붙이는 데 사용합니다.

FAULT_RATIO_TERMS = [
    "과실비율",  # 과실비율 직접 표현
    "과실 비율",  # 띄어쓰기 있는 과실 비율 표현
    "과실상계",  # 과실상계 표현
    "과실 상계",  # 띄어쓰기 있는 과실 상계 표현
    "책임비율",  # 책임비율 표현
    "책임 비율",  # 띄어쓰기 있는 책임 비율 표현
    "손해배상(자)",  # 자동차 손해배상 사건명
    "손해배상",  # 손해배상 일반 표현
    "구상금",  # 구상금 사건 표현
    "보험자대위",  # 보험자대위 표현
    "공동불법행위",  # 공동불법행위 표현
    "운행자책임",  # 운행자책임 표현
    "주의의무",  # 주의의무 표현
    "안전운전의무",  # 안전운전의무 표현
    "과실",  # 과실 일반 표현
]


# ============================================================
# 참고용 topic_labels 생성 규칙
# ============================================================
# key = 붙일 라벨명
# value = 해당 라벨을 붙일 때 찾을 키워드 목록

LABEL_RULES = {
    "fault_ratio_candidate": FAULT_RATIO_TERMS,  # 과실비율 후보 라벨
    "pm_candidate": ["전동킥보드", "개인형 이동장치", "pm"],  # PM 사고 후보 라벨
    "crosswalk_candidate": ["횡단보도", "보행자"],  # 횡단보도/보행자 사고 후보 라벨
    "roundabout_candidate": ["회전교차로"],  # 회전교차로 사고 후보 라벨
    "intersection_candidate": ["교차로"],  # 교차로 사고 후보 라벨
    "rear_end_candidate": ["추돌", "안전거리"],  # 추돌/안전거리 후보 라벨
    "lane_change_candidate": ["차로 변경", "진로 변경", "차선 변경", "끼어들기"],  # 차로 변경 후보 라벨
    "signal_violation_candidate": ["신호위반", "신호 위반", "신호등"],  # 신호위반 후보 라벨
    "centerline_candidate": ["중앙선"],  # 중앙선 침범 후보 라벨
    "parking_lot_candidate": ["주차장"],  # 주차장 사고 후보 라벨
    "door_open_candidate": ["개문"],  # 개문 사고 후보 라벨
}


# ============================================================
# .env 파일 로드
# ============================================================

def load_dotenv_file() -> None:
    """
    .env 파일에서 API 키를 읽어 환경변수에 넣는 함수입니다.

    역할:
    - python-dotenv 패키지 없이 직접 .env 파일을 읽습니다.
    - 현재 실행 폴더, 코드 파일이 있는 폴더, 상위 폴더 순서로 .env를 찾습니다.
    - LAW_GO_KR_OC=API키 형태의 값을 os.environ에 등록합니다.
    """

    # .env 파일을 찾을 후보 위치를 순서대로 만든다.
    candidates = [
        Path.cwd() / ".env",  # 1순위: 현재 명령어를 실행한 폴더의 .env
        Path(__file__).resolve().parent / ".env",  # 2순위: 이 파이썬 파일이 있는 폴더의 .env
        Path.cwd().parent / ".env",  # 3순위: 현재 실행 폴더의 상위 폴더 .env
    ]

    # 후보 경로를 하나씩 확인한다.
    for env_path in candidates:
        # 해당 경로에 .env 파일이 없으면 다음 후보로 넘어간다.
        if not env_path.exists():
            continue

        # .env 파일을 UTF-8로 읽고 줄 단위로 순회한다.
        for line in env_path.read_text(encoding="utf-8").splitlines():
            # 줄 앞뒤 공백을 제거한다.
            line = line.strip()

            # 빈 줄이면 건너뛴다.
            if not line:
                continue

            # 주석 줄이면 건너뛴다.
            if line.startswith("#"):
                continue

            # key=value 형태가 아니면 건너뛴다.
            if "=" not in line:
                continue

            # 첫 번째 = 기준으로 key와 value를 나눈다.
            key, value = line.split("=", 1)

            # key 앞뒤 공백을 제거한다.
            key = key.strip()

            # value 앞뒤 공백과 따옴표를 제거한다.
            value = value.strip().strip('"').strip("'")

            # key와 value가 있고, 아직 같은 환경변수가 없으면 등록한다.
            if key and value and key not in os.environ:
                os.environ[key] = value

        # .env를 하나라도 찾고 로드했으면 안내 메시지를 출력한다.
        print(f"[env] .env 로드 완료: {env_path}")

        # 첫 번째로 찾은 .env만 사용하고 함수 종료
        return

    # 어떤 위치에서도 .env를 찾지 못한 경우 안내 메시지를 출력한다.
    print("[env] .env 파일을 찾지 못했습니다. 환경변수 또는 --oc 값을 확인하세요.")


def get_oc_from_args_or_env(args: argparse.Namespace) -> str:
    """
    국가법령정보센터 Open API 인증값 OC를 가져오는 함수입니다.

    역할:
    - 먼저 .env 파일을 로드합니다.
    - 그 다음 명령행 인자 --oc를 확인합니다.
    - 없으면 환경변수 LAW_GO_KR_OC, LAW_OC, OPEN_LAW_OC 순서로 확인합니다.
    - 끝까지 없으면 에러 메시지를 출력하고 프로그램을 종료합니다.
    """

    # .env 파일이 있으면 환경변수로 로드한다.
    load_dotenv_file()

    # 명령행 인자 또는 환경변수에서 API 인증값을 찾는다.
    oc = (
        args.oc  # 1순위: 실행할 때 --oc로 직접 넘긴 값
        or os.getenv("LAW_GO_KR_OC")  # 2순위: .env 또는 환경변수 LAW_GO_KR_OC
        or os.getenv("LAW_OC")  # 3순위: 환경변수 LAW_OC
        or os.getenv("OPEN_LAW_OC")  # 4순위: 환경변수 OPEN_LAW_OC
    )

    # 인증값이 없으면 실행할 수 없으므로 에러를 출력하고 종료한다.
    if not oc:
        print(
            "ERROR: API 인증값이 없습니다.\n"
            ".env 파일에 아래처럼 넣어주세요.\n\n"
            "LAW_GO_KR_OC=발급받은_API키\n\n"
            "또는 실행할 때 --oc 발급받은_API키 로 전달하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 인증값이 확인되었음을 출력한다.
    print("[env] API 인증값 확인 완료")

    # 찾은 인증값을 반환한다.
    return oc


# ============================================================
# HTTP 요청 및 XML 파싱 유틸 함수
# ============================================================

def make_session(timeout_retries: int = 4) -> requests.Session:
    """
    requests.Session을 만들고 재시도 정책을 붙이는 함수입니다.

    역할:
    - API 요청을 반복할 때 connection pool을 재사용합니다.
    - 429, 500, 502, 503, 504 같은 일시적 오류는 자동 재시도합니다.
    - User-Agent와 Accept 헤더를 설정합니다.
    """

    # requests 세션 객체를 만든다.
    session = requests.Session()

    # HTTP 요청 실패 시 재시도 정책을 설정한다.
    retry = Retry(
        total=timeout_retries,  # 전체 재시도 횟수
        connect=timeout_retries,  # 연결 실패 재시도 횟수
        read=timeout_retries,  # 응답 읽기 실패 재시도 횟수
        status=timeout_retries,  # 특정 HTTP 상태코드 재시도 횟수
        backoff_factor=0.7,  # 재시도 간격 증가 계수
        status_forcelist=(429, 500, 502, 503, 504),  # 재시도할 HTTP 상태코드 목록
        allowed_methods=("GET",),  # GET 요청만 재시도 대상으로 지정
        raise_on_status=False,  # 상태코드 오류를 즉시 예외로 올리지 않음
    )

    # HTTPAdapter에 재시도 정책과 연결 풀 크기를 설정한다.
    adapter = HTTPAdapter(
        max_retries=retry,  # 위에서 만든 재시도 정책 적용
        pool_connections=20,  # 연결 풀 개수
        pool_maxsize=20,  # 풀에서 유지할 최대 연결 수
    )

    # http URL 요청에 adapter를 적용한다.
    session.mount("http://", adapter)

    # https URL 요청에 adapter를 적용한다.
    session.mount("https://", adapter)

    # API 요청에 사용할 기본 헤더를 설정한다.
    session.headers.update(
        {
            "User-Agent": "traffic-prec-api-collector/1.0",  # 서버에 보낼 클라이언트 이름
            "Accept": "application/xml,text/xml,application/json,text/plain,*/*",  # 받을 수 있는 응답 형식
        }
    )

    # 설정이 끝난 세션을 반환한다.
    return session


def request_text(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    timeout: int,
) -> str:
    """
    API에 GET 요청을 보내고 응답 텍스트를 반환하는 함수입니다.

    역할:
    - 주어진 URL과 파라미터로 HTTP GET 요청을 보냅니다.
    - HTTP 에러가 있으면 예외를 발생시킵니다.
    - 인코딩이 이상하면 UTF-8로 보정합니다.
    - 최종 응답 텍스트를 반환합니다.
    """

    # session.get으로 API에 GET 요청을 보낸다.
    response = session.get(url, params=params, timeout=timeout)

    # 4xx, 5xx 상태코드면 예외를 발생시킨다.
    response.raise_for_status()

    # 응답 인코딩이 없거나 latin 계열로 잘못 잡히면 UTF-8로 보정한다.
    if not response.encoding or response.encoding.lower() in ("iso-8859-1", "latin-1"):
        response.encoding = "utf-8"

    # 응답 본문 문자열을 반환한다.
    return response.text


def local_name(tag: str) -> str:
    """
    XML 태그에서 namespace를 제거하고 실제 태그명만 반환하는 함수입니다.

    예:
    - "{namespace}prec" -> "prec"
    - "사건명" -> "사건명"
    """

    # namespace가 있는 태그는 } 뒤쪽만 실제 태그명으로 사용한다.
    if "}" in tag:
        return tag.split("}", 1)[1]

    # namespace가 없으면 원래 태그를 그대로 반환한다.
    return tag


def clean_text(value: Any) -> str:
    """
    API에서 받은 텍스트를 기본 정리하는 함수입니다.

    역할:
    - None을 빈 문자열로 바꿉니다.
    - HTML 엔티티를 일반 문자로 바꿉니다.
    - <br> 태그를 줄바꿈으로 바꿉니다.
    - 나머지 HTML 태그를 제거합니다.
    - 연속 공백을 하나로 줄입니다.
    """

    # 값이 None이면 빈 문자열을 반환한다.
    if value is None:
        return ""

    # 값을 문자열로 변환한다.
    text = str(value)

    # HTML 엔티티를 실제 문자로 변환한다.
    text = html.unescape(text)

    # <br>, <br/>, <br /> 태그를 줄바꿈으로 바꾼다.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)

    # 나머지 HTML 태그를 공백으로 제거한다.
    text = re.sub(r"<[^>]+>", " ", text)

    # 연속된 공백, 줄바꿈, 탭을 하나의 공백으로 줄이고 앞뒤 공백을 제거한다.
    text = re.sub(r"\s+", " ", text).strip()

    # 정리된 문자열을 반환한다.
    return text


def parse_xml(text: str) -> ET.Element:
    """
    XML 문자열을 ElementTree 루트 객체로 파싱하는 함수입니다.

    역할:
    - UTF-8 BOM이 있으면 제거합니다.
    - 앞뒤 공백을 제거합니다.
    - XML 문자열을 ElementTree 객체로 변환합니다.
    """

    # BOM과 앞뒤 공백을 제거한다.
    text = text.lstrip("\ufeff").strip()

    # XML 문자열을 파싱해서 루트 Element를 반환한다.
    return ET.fromstring(text)


def node_to_flat_dict(node: ET.Element) -> Dict[str, str]:
    """
    XML 노드의 바로 아래 자식 태그들을 dict로 평탄화하는 함수입니다.

    역할:
    - XML child tag 이름을 key로 사용합니다.
    - child 내부의 모든 텍스트를 합쳐 value로 사용합니다.
    - attribute가 있으면 @속성명 형태로 저장합니다.
    """

    # 결과를 담을 빈 dict를 만든다.
    data: Dict[str, str] = {}

    # 현재 노드의 바로 아래 child들을 순회한다.
    for child in list(node):
        # namespace를 제거한 태그명을 key로 사용한다.
        key = local_name(child.tag)

        # child 내부의 모든 텍스트를 합치고 정리한다.
        text = clean_text("".join(child.itertext()))

        # key와 text가 있으면 dict에 저장한다.
        if key and text:
            data[key] = text

    # 자식 태그에서 아무 데이터도 못 뽑은 경우 현재 노드 전체 텍스트를 사용한다.
    if not data:
        # 현재 노드 전체 텍스트를 합치고 정리한다.
        text = clean_text("".join(node.itertext()))

        # 텍스트가 있으면 현재 노드 태그명을 key로 저장한다.
        if text:
            data[local_name(node.tag)] = text

    # XML attribute도 dict에 추가한다.
    for key, value in node.attrib.items():
        # attribute는 일반 태그와 구분하기 위해 @를 붙인다.
        data[f"@{key}"] = clean_text(value)

    # 평탄화된 dict를 반환한다.
    return data


def parse_total_count(root: ET.Element) -> int:
    """
    목록 API XML 응답에서 totalCnt 값을 찾아 정수로 반환하는 함수입니다.

    역할:
    - XML 전체를 순회하면서 totalCnt 태그를 찾습니다.
    - totalCnt가 있으면 int로 바꿔 반환합니다.
    - 없거나 변환 실패하면 0을 반환합니다.
    """

    # XML 전체 요소를 순회한다.
    for elem in root.iter():
        # 태그명이 totalCnt인지 확인한다.
        if local_name(elem.tag) == "totalCnt":
            try:
                # totalCnt 텍스트를 정수로 변환해서 반환한다.
                return int(clean_text(elem.text))
            except ValueError:
                # 정수 변환 실패 시 0 반환
                return 0

    # totalCnt 태그를 못 찾으면 0 반환
    return 0


# ============================================================
# 판례 목록 / 상세 본문 파싱 함수
# ============================================================

def parse_list_records(xml_text: str) -> Tuple[int, List[Dict[str, str]]]:
    """
    판례 목록 검색 API 응답 XML을 파싱하는 함수입니다.

    역할:
    - totalCnt를 읽습니다.
    - <prec> 태그들을 찾아 목록 row dict로 변환합니다.
    - API 응답 구조가 다를 경우 보조 방식으로 후보 row를 찾습니다.
    """

    # XML 문자열을 루트 Element로 파싱한다.
    root = parse_xml(xml_text)

    # 전체 검색 결과 수 totalCnt를 파싱한다.
    total = parse_total_count(root)

    # 목록 row를 담을 리스트를 만든다.
    records: List[Dict[str, str]] = []

    # XML 전체 요소를 순회하면서 prec 태그를 찾는다.
    for elem in root.iter():
        # 태그명이 prec이면 판례 목록 row로 본다.
        if local_name(elem.tag).lower() == "prec":
            # 해당 XML 노드를 dict로 변환한다.
            row = node_to_flat_dict(elem)

            # row에 내용이 있으면 결과 리스트에 추가한다.
            if row:
                records.append(row)

    # prec 태그 방식으로 아무 row도 못 찾은 경우 보조 파싱을 수행한다.
    if not records:
        # 판례 목록 row라고 판단할 수 있는 대표 키 목록
        candidate_keys = {"판례일련번호", "사건명", "사건번호", "선고일자", "법원명"}

        # 루트 바로 아래 요소들을 순회한다.
        for elem in root:
            # 현재 요소를 dict로 변환한다.
            row = node_to_flat_dict(elem)

            # 대표 키 중 하나라도 있으면 목록 row로 판단한다.
            if candidate_keys.intersection(row.keys()):
                records.append(row)

    # totalCnt와 목록 row 리스트를 반환한다.
    return total, records


def parse_detail_record(xml_text: str) -> Dict[str, str]:
    """
    판례 상세 조회 API 응답 XML을 파싱하는 함수입니다.

    역할:
    - 상세 판례 XML을 dict로 변환합니다.
    - 판례내용, 판시사항, 판결요지 등 중요한 필드를 다시 찾아 보강합니다.
    """

    # XML 문자열을 루트 Element로 파싱한다.
    root = parse_xml(xml_text)

    # 루트의 바로 아래 자식들을 기본 dict로 변환한다.
    record = node_to_flat_dict(root)

    # 상세 판례에서 반드시 챙기고 싶은 중요 필드 목록
    important_keys = {
        "판례정보일련번호",
        "판례일련번호",
        "사건명",
        "사건번호",
        "선고일자",
        "선고",
        "법원명",
        "법원종류코드",
        "사건종류명",
        "사건종류코드",
        "판결유형",
        "판시사항",
        "판결요지",
        "참조조문",
        "참조판례",
        "판례내용",
    }

    # 중요 필드를 담을 임시 dict를 만든다.
    found: Dict[str, str] = {}

    # XML 전체를 순회하면서 중요 필드를 찾는다.
    for elem in root.iter():
        # namespace를 제거한 태그명을 얻는다.
        key = local_name(elem.tag)

        # 태그명이 중요 필드 목록에 있으면 값을 추출한다.
        if key in important_keys:
            # 해당 요소 내부의 모든 텍스트를 합쳐 정리한다.
            value = clean_text("".join(elem.itertext()))

            # 값이 있으면 found에 저장한다.
            if value:
                found[key] = value

    # 기본 record에 중요 필드 found를 덮어써서 보강한다.
    record.update(found)

    # 상세 판례 dict를 반환한다.
    return record


def get_case_id(row: Dict[str, str]) -> str:
    """
    목록 row 또는 상세 row에서 판례 고유 ID를 가져오는 함수입니다.

    역할:
    - 판례일련번호, 판례정보일련번호, ID, id 순서로 확인합니다.
    - 그래도 없으면 법원명/선고일자/사건번호/사건명을 조합해 임시 ID를 만듭니다.
    """

    # 판례 ID로 사용할 수 있는 key들을 순서대로 확인한다.
    for key in ("판례일련번호", "판례정보일련번호", "ID", "id"):
        # 해당 key의 값이 있으면 문자열로 바꿔 반환한다.
        if row.get(key):
            return str(row[key]).strip()

    # ID가 없는 경우 임시 ID 생성을 위한 구성 요소를 모은다.
    parts = [
        row.get("법원명", ""),  # 법원명
        row.get("선고일자", ""),  # 선고일자
        row.get("사건번호", ""),  # 사건번호
        row.get("사건명", ""),  # 사건명
    ]

    # 구성 요소를 |로 이어 임시 ID를 만든다.
    return "|".join(parts)


# ============================================================
# 참고용 라벨링 함수
# ============================================================
# 이 함수들은 --classify 옵션을 켰을 때 topic_labels를 붙이는 용도입니다.
# 이 버전에서는 이 함수들로 traffic/skipped 파일을 나누지 않습니다.

def merged_text(record: Dict[str, Any]) -> str:
    """
    판례 상세 record에서 라벨링에 사용할 텍스트를 합치는 함수입니다.

    역할:
    - 사건명, 사건번호, 판시사항, 판결요지, 판례내용 등을 하나로 합칩니다.
    - 소문자로 변환해 키워드 포함 검사를 쉽게 합니다.
    """

    # 라벨링에 사용할 필드 목록
    keys = [
        "사건명",
        "사건번호",
        "법원명",
        "사건종류명",
        "판결유형",
        "판시사항",
        "판결요지",
        "참조조문",
        "참조판례",
        "판례내용",
    ]

    # 각 필드 값을 정리한 뒤 공백으로 이어붙이고 소문자로 변환한다.
    return " ".join(clean_text(record.get(key, "")) for key in keys).lower()


def contains_any(text: str, terms: Iterable[str]) -> bool:
    """
    text 안에 terms 중 하나라도 포함되어 있는지 확인하는 함수입니다.

    역할:
    - 키워드 포함 여부를 단순 문자열 포함 방식으로 검사합니다.
    - 하나라도 포함되면 True를 반환합니다.
    """

    # 비교를 쉽게 하기 위해 text를 소문자로 변환한다.
    lower = text.lower()

    # terms 중 하나라도 lower 안에 포함되면 True를 반환한다.
    return any(term.lower() in lower for term in terms)


def classify_record(record: Dict[str, Any]) -> List[str]:
    """
    판례 record에 참고용 topic_labels를 붙이는 함수입니다.

    역할:
    - TRAFFIC_TERMS가 있으면 traffic_case_raw 라벨을 붙입니다.
    - LABEL_RULES에 맞는 키워드가 있으면 해당 라벨을 붙입니다.
    - 중복 라벨은 제거하고 정렬해서 반환합니다.

    주의:
    - 이 결과는 참고용 라벨입니다.
    - 이 코드에서는 이 라벨로 파일을 분리하지 않습니다.
    """

    # 판례 record의 주요 텍스트를 합친다.
    text = merged_text(record)

    # 라벨을 담을 빈 리스트를 만든다.
    labels: List[str] = []

    # 교통 관련 키워드가 있으면 참고 라벨을 붙인다.
    if contains_any(text, TRAFFIC_TERMS):
        labels.append("traffic_case_raw")

    # LABEL_RULES 전체를 돌면서 조건에 맞는 라벨을 붙인다.
    for label, terms in LABEL_RULES.items():
        # 현재 라벨의 키워드 중 하나라도 text에 있으면 라벨 추가
        if contains_any(text, terms):
            labels.append(label)

    # 중복 라벨을 제거하고 정렬해서 반환한다.
    return sorted(set(labels))


# ============================================================
# API 호출 함수
# ============================================================

def fetch_list_page(
    session: requests.Session,
    oc: str,
    keyword: str,
    page: int,
    display: int,
    search_scope: int,
    sort: str,
    from_date: Optional[str],
    to_date: Optional[str],
    timeout: int,
) -> Tuple[int, List[Dict[str, str]]]:
    """
    판례 목록 검색 API에서 특정 키워드의 특정 페이지를 가져오는 함수입니다.

    역할:
    - keyword를 query 파라미터로 넣어 목록 검색을 수행합니다.
    - XML 응답을 파싱해서 totalCnt와 목록 row 리스트를 반환합니다.
    """

    # 국가법령정보센터 목록 검색 API에 전달할 파라미터를 만든다.
    params: Dict[str, Any] = {
        "OC": oc,  # API 인증값
        "target": "prec",  # 판례 검색
        "type": "XML",  # XML 형식으로 응답 받기
        "search": search_scope,  # 검색 범위: 1=판례명, 2=본문
        "query": keyword,  # 실제 검색 키워드
        "display": display,  # 한 페이지에 받을 결과 수
        "page": page,  # 조회할 페이지 번호
        "sort": sort,  # 정렬 기준
    }

    # 시작일과 종료일이 모두 있으면 선고일자 범위 조건을 추가한다.
    if from_date and to_date:
        params["prncYd"] = f"{from_date}~{to_date}"

    # 둘 중 하나만 있으면 잘못된 입력이므로 에러를 발생시킨다.
    elif from_date or to_date:
        raise ValueError("--from-date와 --to-date는 함께 입력해야 합니다. 예: 20150101 20261231")

    # API 요청을 보내고 XML 문자열을 받는다.
    xml_text = request_text(
        session=session,
        url=LIST_URL,
        params=params,
        timeout=timeout,
    )

    # XML 문자열을 목록 row로 파싱해서 반환한다.
    return parse_list_records(xml_text)


def build_source_reference(case_id: str) -> str:
    """
    RAG 근거 추적용 source_reference URL을 만드는 함수입니다.

    역할:
    - API 키 OC를 포함하지 않는 공개 형태의 reference URL을 만듭니다.
    - 나중에 검색 결과에서 어떤 판례인지 추적할 때 사용합니다.
    """

    # reference URL에 들어갈 query 파라미터를 만든다.
    params = {
        "target": "prec",  # 판례 상세 조회
        "ID": case_id,  # 판례 ID
        "type": "XML",  # XML 형식
    }

    # DETAIL_URL 뒤에 query string을 붙여 반환한다.
    return f"{DETAIL_URL}?{urlencode(params, doseq=True)}"


def fetch_detail(
    session: requests.Session,
    oc: str,
    case_id: str,
    timeout: int,
) -> Dict[str, str]:
    """
    판례 상세 조회 API로 특정 case_id의 본문을 가져오는 함수입니다.

    역할:
    - lawService.do API에 case_id를 넣어 상세 판례를 조회합니다.
    - XML 응답을 파싱해 dict로 만듭니다.
    - source_type, source_provider, source_reference를 추가합니다.
    """

    # 상세 조회 API에 전달할 파라미터를 만든다.
    params = {
        "OC": oc,  # API 인증값
        "target": "prec",  # 판례 상세 조회
        "ID": case_id,  # 조회할 판례 ID
        "type": "XML",  # XML 응답
    }

    # 상세 조회 API를 호출하고 XML 문자열을 받는다.
    xml_text = request_text(
        session=session,
        url=DETAIL_URL,
        params=params,
        timeout=timeout,
    )

    # XML 문자열을 상세 판례 dict로 파싱한다.
    record = parse_detail_record(xml_text)

    # 데이터 출처 타입을 추가한다.
    record["source_type"] = "precedent"

    # 데이터 제공자를 추가한다.
    record["source_provider"] = "국가법령정보센터 Open API"

    # API 키가 없는 reference URL을 추가한다.
    record["source_reference"] = build_source_reference(case_id)

    # 상세 판례 record를 반환한다.
    return record


# ============================================================
# 파일 저장 유틸 함수
# ============================================================

def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """
    dict 한 건을 JSONL 파일에 append 저장하는 함수입니다.

    역할:
    - row dict를 JSON 문자열로 바꿉니다.
    - ensure_ascii=False로 한글을 그대로 저장합니다.
    - 파일 끝에 한 줄씩 추가합니다.
    """

    # 파일을 append 모드로 연다.
    with path.open("a", encoding="utf-8") as file:
        # dict를 JSON 문자열로 바꿔 한 줄로 저장한다.
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def remove_existing_outputs(paths: Dict[str, Path]) -> None:
    """
    --fresh 실행 시 기존 출력 파일을 삭제하는 함수입니다.

    역할:
    - paths에 들어 있는 파일들이 이미 존재하면 삭제합니다.
    - 새로 수집할 때 이전 결과가 섞이지 않게 합니다.
    """

    # paths dict의 모든 파일 경로를 순회한다.
    for path in paths.values():
        # 파일이 존재하면 삭제한다.
        if path.exists():
            path.unlink()


def load_keywords(args: argparse.Namespace) -> List[str]:
    """
    실제 API 검색에 사용할 키워드 목록을 만드는 함수입니다.

    역할:
    - DEFAULT_KEYWORDS를 기본으로 사용합니다.
    - --keywords-file이 있으면 파일 안의 키워드를 추가합니다.
    - --keyword가 있으면 명령행에서 받은 키워드를 추가합니다.
    - 중복 키워드를 제거하고 순서를 유지합니다.
    """

    # 기본 검색 키워드를 복사한다.
    keywords = list(DEFAULT_KEYWORDS)

    # 사용자가 키워드 파일을 지정한 경우 처리한다.
    if args.keywords_file:
        # 키워드 파일 경로를 Path 객체로 만든다.
        path = Path(args.keywords_file)

        # 키워드 파일이 없으면 에러를 발생시킨다.
        if not path.exists():
            raise FileNotFoundError(f"keywords file not found: {path}")

        # 키워드 파일을 줄 단위로 읽는다.
        for line in path.read_text(encoding="utf-8").splitlines():
            # 줄 앞뒤 공백을 제거한다.
            line = line.strip()

            # 빈 줄이 아니고 주석이 아니면 키워드로 추가한다.
            if line and not line.startswith("#"):
                keywords.append(line)

    # 사용자가 --keyword를 여러 번 준 경우 모두 추가한다.
    if args.keyword:
        keywords.extend(args.keyword)

    # 중복 제거를 위해 이미 본 키워드를 저장할 set을 만든다.
    seen: Set[str] = set()

    # 중복 제거된 키워드를 저장할 리스트를 만든다.
    unique: List[str] = []

    # 전체 키워드를 순서대로 순회한다.
    for keyword in keywords:
        # 키워드 앞뒤 공백을 제거한다.
        keyword = keyword.strip()

        # 키워드가 비어 있지 않고 아직 본 적이 없으면 추가한다.
        if keyword and keyword not in seen:
            seen.add(keyword)
            unique.append(keyword)

    # 중복 제거된 키워드 목록을 반환한다.
    return unique


@dataclass
class RunStats:
    """
    수집 실행 통계를 저장하는 dataclass입니다.

    역할:
    - 실행 중 카운트를 누적합니다.
    - 마지막에 run_summary.json으로 저장합니다.
    """

    keywords: int = 0  # 사용한 검색 키워드 수
    list_rows_seen: int = 0  # 목록 검색에서 본 row 수
    unique_case_ids: int = 0  # 중복 제거 후 상세 조회 대상 case_id 수
    details_fetched: int = 0  # 상세 조회 성공 수
    all_candidates_saved: int = 0  # all_prec_candidates_raw.jsonl에 저장한 판례 수
    errors: int = 0  # 목록/상세 조회 중 발생한 에러 수


# ============================================================
# 메인 수집 로직
# ============================================================

def collect(args: argparse.Namespace) -> None:
    """
    전체 수집 과정을 실행하는 메인 함수입니다.

    역할:
    1. API 인증값을 확인합니다.
    2. 출력 폴더와 출력 파일 경로를 준비합니다.
    3. DEFAULT_KEYWORDS 기반으로 판례 목록을 검색합니다.
    4. 목록 결과에서 unique case_id를 모읍니다.
    5. 각 case_id의 상세 판례를 조회합니다.
    6. 상세 조회된 모든 판례를 all_prec_candidates_raw.jsonl에 저장합니다.
    7. 실행 요약을 run_summary.json에 저장합니다.
    """

    # 명령행 인자 또는 환경변수에서 API 인증값을 가져온다.
    oc = get_oc_from_args_or_env(args)

    # 출력 폴더 경로를 만든다.
    out_dir = Path(args.out_dir)

    # 출력 폴더가 없으면 생성한다.
    out_dir.mkdir(parents=True, exist_ok=True)

    # 출력 파일 경로를 정의한다.
    paths = {
        "list": out_dir / "list_results.jsonl",  # 목록 검색 결과 저장 파일
        "raw": out_dir / "all_prec_candidates_raw.jsonl",  # 상세 판례 전체 후보 raw 저장 파일
        "errors": out_dir / "errors.jsonl",  # 에러 로그 저장 파일
        "summary": out_dir / "run_summary.json",  # 실행 요약 저장 파일
    }

    # --fresh 옵션이 있으면 기존 출력 파일을 삭제한다.
    if args.fresh:
        remove_existing_outputs(paths)

    # 재시도 설정이 적용된 HTTP session을 만든다.
    session = make_session()

    # 실제 검색에 사용할 키워드 목록을 만든다.
    keywords = load_keywords(args)

    # 실행 통계 객체를 만든다.
    stats = RunStats(keywords=len(keywords))

    # case_id 기준으로 목록 후보를 모을 dict를 만든다.
    case_map: Dict[str, Dict[str, Any]] = {}

    # 목록 수집 시작 메시지를 출력한다.
    print(f"[1/2] 판례 목록 수집 시작: keywords={len(keywords)} display={args.display}")

    # 키워드를 하나씩 순회한다.
    for keyword_index, keyword in enumerate(keywords, 1):
        # 현재 처리 중인 키워드를 출력한다.
        print(f"  - ({keyword_index}/{len(keywords)}) keyword='{keyword}'")

        # 페이지 번호를 1부터 시작한다.
        page = 1

        # API totalCnt를 저장할 변수다.
        total = None

        # 현재 키워드의 모든 페이지를 반복 조회한다.
        while True:
            # 키워드당 최대 페이지 제한이 있고, 현재 페이지가 제한보다 크면 중단한다.
            if args.max_pages_per_keyword and page > args.max_pages_per_keyword:
                break

            try:
                # 현재 키워드와 페이지로 목록 API를 호출한다.
                total_count, rows = fetch_list_page(
                    session=session,
                    oc=oc,
                    keyword=keyword,
                    page=page,
                    display=args.display,
                    search_scope=args.search_scope,
                    sort=args.sort,
                    from_date=args.from_date,
                    to_date=args.to_date,
                    timeout=args.timeout,
                )

                # total이 아직 없으면 첫 응답의 total_count를 저장한다.
                if total is None:
                    total = total_count

                # rows가 비어 있으면 더 이상 볼 페이지가 없으므로 중단한다.
                if not rows:
                    break

                # 현재 페이지의 목록 row들을 하나씩 처리한다.
                for row in rows:
                    # 목록 row 카운트를 증가시킨다.
                    stats.list_rows_seen += 1

                    # row에서 판례 case_id를 추출한다.
                    case_id = get_case_id(row)

                    # 이 row가 어떤 검색 키워드에서 나왔는지 기록한다.
                    row["_matched_keyword"] = keyword

                    # 이 row가 몇 페이지에서 나왔는지 기록한다.
                    row["_list_page"] = page

                    # 목록 검색 결과를 list_results.jsonl에 저장한다.
                    write_jsonl(paths["list"], row)

                    # case_id가 처음 등장한 경우 case_map에 기본 구조를 만든다.
                    if case_id not in case_map:
                        case_map[case_id] = {
                            "case_id": case_id,  # 판례 ID
                            "list_row": row,  # 대표 목록 row
                            "matched_keywords": [],  # 이 판례를 잡은 검색 키워드 목록
                        }

                    # 현재 키워드를 해당 case_id의 matched_keywords에 추가한다.
                    case_map[case_id]["matched_keywords"].append(keyword)

                # 현재 페이지 처리 결과를 출력한다.
                print(f"    page={page}, rows={len(rows)}, total={total_count}")

                # 다음 페이지로 이동한다.
                page += 1

                # API 과호출 방지를 위해 요청 사이 대기한다.
                time.sleep(args.sleep)

                # total_count 기준으로 마지막 페이지까지 봤으면 중단한다.
                if total_count and (page - 1) * args.display >= total_count:
                    break

            except Exception as error:
                # 목록 조회 중 에러가 발생하면 에러 카운트를 증가시킨다.
                stats.errors += 1

                # 에러 로그 row를 만든다.
                err = {
                    "stage": "list",  # 목록 조회 단계 에러
                    "keyword": keyword,  # 에러가 발생한 키워드
                    "page": page,  # 에러가 발생한 페이지
                    "error": repr(error),  # 에러 내용
                }

                # 에러 로그를 errors.jsonl에 저장한다.
                write_jsonl(paths["errors"], err)

                # 콘솔에 에러 메시지를 출력한다.
                print(
                    f"    ERROR list keyword='{keyword}' page={page}: {error}",
                    file=sys.stderr,
                )

                # 현재 키워드는 더 진행하지 않고 다음 키워드로 넘어간다.
                break

    # 중복 제거 후 상세 조회할 case_id 수를 저장한다.
    stats.unique_case_ids = len(case_map)

    # 상세 본문 수집 시작 메시지를 출력한다.
    print(f"[2/2] 판례 본문 수집 시작: unique_case_ids={len(case_map)}")

    # case_map의 각 case_id를 순회하면서 상세 판례를 조회한다.
    for index, (case_id, item) in enumerate(case_map.items(), 1):
        try:
            # 20건마다 진행 상황을 출력한다.
            if index % 20 == 0:
                print(f"  - detail progress {index}/{len(case_map)}")

            # 상세 조회 API로 판례 본문을 가져온다.
            detail = fetch_detail(
                session=session,
                oc=oc,
                case_id=case_id,
                timeout=args.timeout,
            )

            # 상세 조회 성공 카운트를 증가시킨다.
            stats.details_fetched += 1

            # 상세 record에 내부 case_id를 추가한다.
            detail["_case_id"] = case_id

            # 이 판례가 어떤 검색 키워드들로 잡혔는지 추가한다.
            detail["_matched_keywords"] = sorted(set(item.get("matched_keywords", [])))

            # 목록 검색에서 대표로 저장한 row를 함께 보관한다.
            detail["_list_row"] = item.get("list_row", {})

            # 수집 단계에서 파일을 나누지 않는다는 의미의 source_bucket을 기록한다.
            detail["source_bucket"] = "all_prec_candidates_raw"

            # --classify 옵션이 있으면 참고용 topic_labels를 붙인다.
            if args.classify:
                detail["topic_labels"] = classify_record(detail)

            # --classify 옵션이 없으면 빈 라벨 리스트를 넣는다.
            else:
                detail["topic_labels"] = []

            # 상세 조회된 모든 판례를 하나의 raw 후보 파일에 저장한다.
            write_jsonl(paths["raw"], detail)

            # raw 후보 저장 카운트를 증가시킨다.
            stats.all_candidates_saved += 1

            # API 과호출 방지를 위해 요청 사이 대기한다.
            time.sleep(args.sleep)

        except Exception as error:
            # 상세 조회 중 에러가 발생하면 에러 카운트를 증가시킨다.
            stats.errors += 1

            # 에러 로그 row를 만든다.
            err = {
                "stage": "detail",  # 상세 조회 단계 에러
                "case_id": case_id,  # 에러가 발생한 case_id
                "error": repr(error),  # 에러 내용
            }

            # 에러 로그를 errors.jsonl에 저장한다.
            write_jsonl(paths["errors"], err)

            # 콘솔에 에러 메시지를 출력한다.
            print(
                f"  ERROR detail case_id='{case_id}': {error}",
                file=sys.stderr,
            )

    # 실행 통계를 run_summary.json으로 저장한다.
    paths["summary"].write_text(
        json.dumps(asdict(stats), ensure_ascii=False, indent=2),  # dataclass를 dict로 바꿔 JSON 문자열 생성
        encoding="utf-8",  # 한글 저장을 위해 UTF-8 사용
    )

    # 완료 메시지를 출력한다.
    print("\n완료")

    # 실행 통계를 콘솔에 출력한다.
    print(json.dumps(asdict(stats), ensure_ascii=False, indent=2))

    # 저장 위치를 출력한다.
    print(f"\n저장 위치: {out_dir.resolve()}")

    # 목록 결과 파일 경로를 출력한다.
    print(f"- 전체 목록 결과: {paths['list']}")

    # 전체 raw 후보 파일 경로를 출력한다.
    print(f"- 전체 후보 raw 판례: {paths['raw']}")

    # 에러 로그 파일 경로를 출력한다.
    print(f"- 에러 로그: {paths['errors']}")

    # 요약 파일 경로를 출력한다.
    print(f"- 요약: {paths['summary']}")


# ============================================================
# 명령행 인자 파싱
# ============================================================

def parse_args() -> argparse.Namespace:
    """
    명령행 인자를 정의하고 파싱하는 함수입니다.

    역할:
    - API 키, 출력 폴더, 페이지 제한, 검색 범위, 날짜 범위 등을 입력받습니다.
    - argparse.Namespace 형태로 collect 함수에 전달합니다.
    """

    # argparse 파서를 만든다.
    parser = argparse.ArgumentParser(
        description="국가법령정보센터 Open API에서 교통사고 관련 가능성이 있는 판례 후보를 수집하고 하나의 raw 파일로 저장합니다."
    )

    # API 인증값을 직접 입력받는 옵션
    parser.add_argument(
        "--oc",
        help="국가법령정보센터 Open API 인증값. 없으면 .env의 LAW_GO_KR_OC 사용",
    )

    # 출력 폴더 옵션
    parser.add_argument(
        "--out-dir",
        default="etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api",
        help="출력 폴더",
    )

    # 목록 조회 한 페이지 결과 수 옵션
    parser.add_argument(
        "--display",
        type=int,
        default=100,
        help="목록 조회 결과 수. API max=100",
    )

    # 키워드당 최대 페이지 제한 옵션
    parser.add_argument(
        "--max-pages-per-keyword",
        type=int,
        default=0,
        help="키워드당 최대 페이지. 0이면 제한 없음",
    )

    # 검색 범위 옵션
    parser.add_argument(
        "--search-scope",
        type=int,
        default=2,
        choices=[1, 2],
        help="검색범위. 1=판례명 검색, 2=본문 검색. 교통사고 후보 수집은 2 추천",
    )

    # 정렬 기준 옵션
    parser.add_argument(
        "--sort",
        default="ddes",
        help="정렬. ddes=선고일자 내림차순",
    )

    # 선고일자 시작일 옵션
    parser.add_argument(
        "--from-date",
        help="선고일자 시작 YYYYMMDD",
    )

    # 선고일자 종료일 옵션
    parser.add_argument(
        "--to-date",
        help="선고일자 종료 YYYYMMDD",
    )

    # 추가 검색 키워드 옵션
    parser.add_argument(
        "--keyword",
        action="append",
        help="추가 검색 키워드. 여러 번 사용 가능",
    )

    # 키워드 파일 옵션
    parser.add_argument(
        "--keywords-file",
        help="검색 키워드 파일. 한 줄에 하나",
    )

    # 요청 간 대기 시간 옵션
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="요청 간 대기 초",
    )

    # 요청 timeout 옵션
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="요청 timeout 초",
    )

    # 기존 결과 삭제 후 새로 수집하는 옵션
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="기존 결과 파일을 삭제하고 새로 수집",
    )

    # 참고용 topic_labels를 붙이는 옵션
    parser.add_argument(
        "--classify",
        action="store_true",
        help="수집 후 참고용 topic_labels만 붙인다. 파일 분리는 하지 않는다.",
    )

    # 파싱된 인자 객체를 반환한다.
    return parser.parse_args()


# ============================================================
# 프로그램 시작점
# ============================================================

# 이 파일을 직접 실행했을 때만 collect를 실행한다.
if __name__ == "__main__":
    # 명령행 인자를 파싱하고, 그 결과를 collect 함수에 넘긴다.
    collect(parse_args())
