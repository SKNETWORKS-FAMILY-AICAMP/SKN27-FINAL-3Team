"""법률 데이터를 외부 API(law.go.kr) 또는 오프라인 캐시에서 수집하고 버전 관리 및 원본 저장을 담당하는 통합 수집 모듈입니다."""

from __future__ import annotations

import os
import time
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol
import yaml


# ==========================================
# 1. 매니페스트(Manifest) 검증 및 로드 영역
# ==========================================

# 수집 가능한 법령 타입 정의
ALLOWED_SOURCE_TYPES = {
    "law",
    "enforcement_decree",
    "enforcement_rule",
    "administrative_rule",
    "notice",
}

# RAG 법률 근거 외의 타 도메인 데이터 타입 (검색 대상에서 차단)
BLOCKED_SOURCE_TYPES = {
    "precedent",
    "case",
    "administrative_appeal",
    "news",
    "blog",
    "community",
    "insurance_case",
    "accident_case",
    "caption_case",
    "review_case",
    "fine_rule",
}

# 법령 명세서의 필수 키값 항목
REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "source_name",
    "source_type",
    "provider",
    "enabled",
    "priority",
}


def load_manifest(path: str | Path) -> list[dict[str, Any]]:
    """매니페스트 YAML 파일을 열어 수집 대상 법령 목록을 가져옵니다."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest 파일을 찾을 수 없습니다: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sources") or []


def validate_manifest(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """매니페스트 정보의 누락 필드, 데이터 중복 및 비정상 타입을 검증하고 우선순위 순으로 정렬하여 반환합니다."""
    validated = []
    seen_ids: set[str] = set()

    for source in sources:
        missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
        if missing:
            raise ValueError(f"Manifest 소스 정보에 필수 필드가 누락되었습니다: {', '.join(missing)}")

        source_id = str(source["source_id"])
        source_type = str(source["source_type"])

        if source_id in seen_ids:
            raise ValueError(f"Manifest 내 중복된 source_id가 발견되었습니다: {source_id}")
        seen_ids.add(source_id)

        if source_type in BLOCKED_SOURCE_TYPES:
            raise ValueError(f"법령 RAG 외부 도메인 타입입니다: {source_type}")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(f"지원하지 않는 법령 source_type입니다: {source_type}")

        # 활성화(enabled=True)된 법령만 수집 대상으로 선정
        if bool(source["enabled"]):
            validated.append(source)

    # 우선순위 정렬 후 수집 아이디 순서로 정렬
    return sorted(validated, key=lambda row: (int(row["priority"]), str(row["source_id"])))


# ==========================================
# 2. 법률 API 클라이언트 영역 (API Client)
# ==========================================

class LawApiClient(Protocol):
    """법률 데이터를 가져오기 위한 API 클라이언트 프로토콜 인터페이스 규격입니다."""
    def search_law_versions(
        self, source: dict, base_date: str, history_years: int
    ) -> list[dict]:
        ...

    def fetch_law_document(self, source: dict, version: dict) -> dict:
        ...


class OfflineLawApiClient:
    """오프라인 및 테스트 구동 환경을 위한 가상 API 클라이언트입니다."""

    def search_law_versions(
        self, source: dict, base_date: str, history_years: int
    ) -> list[dict]:
        version_id = f"{source['source_id']}:{base_date}:offline"
        return [
            {
                "source_version_id": version_id,
                "mst": "offline",
                "law_serial_no": None,
                "promulgation_date": None,
                "promulgation_no": None,
                "enforce_date": base_date,
                "expire_date": None,
                "version_status": "current",
            }
        ]

    def fetch_law_document(self, source: dict, version: dict) -> dict:
        text = (
            f"제1조 목적\n"
            f"이 법령은 {source['source_name']}의 교통 안전 관련 기준을 정한다.\n"
            f"제2조 적용 범위\n"
            f"이 법령의 세부 적용은 관련 시행일과 공식 출처를 기준으로 한다."
        )
        return {
            "source_id": source["source_id"],
            "source_version_id": version["source_version_id"],
            "raw_format": "txt",
            "content": text,
            "source_url": f"offline://law/{source['source_id']}",
        }


class LawGoKrApiClient:
    """법제처(law.go.kr) 오픈 API 공식 연동 클라이언트입니다."""

    SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
    SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

    def __init__(
        self,
        oc: str | None = None,
        timeout_seconds: int = 20,
        retry_count: int = 2,
        retry_sleep_seconds: float = 0.5,
    ) -> None:
        load_local_env()
        self.oc = oc or os.getenv("LAW_GO_KR_OC") or os.getenv("LAW_API_KEY")
        if not self.oc:
            raise ValueError("LAW_GO_KR_OC 혹은 LAW_API_KEY 환경변수가 설정되지 않았습니다.")
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.retry_sleep_seconds = retry_sleep_seconds

    def search_law_versions(
        self, source: dict, base_date: str, history_years: int
    ) -> list[dict]:
        """법령의 시행일 범위 내에 효력이 있었던 버전들의 연혁 및 일련번호 목록을 검색합니다."""
        target = "admrul" if source["source_type"] == "administrative_rule" else "law"
        query = source.get("provider_source_id") or source["source_name"]
        
        if target == "law":
            law_id = self._find_law_id(source, query)
            if law_id:
                versions = self._search_effective_law_versions(
                    source, law_id, base_date, history_years
                )
                if versions:
                    return versions

        params_list = [
            {
                "OC": self.oc,
                "target": target,
                "type": "XML",
                "query": query,
                "display": "100",
            }
        ]
        if target == "law":
            params_list.append(
                {
                    "OC": self.oc,
                    "target": target,
                    "type": "XML",
                    "query": query,
                    "display": "100",
                    "efYd": _history_window(base_date, history_years),
                }
            )

        versions_by_id = {}
        for params in params_list:
            for payload in self._request_xml_pages(self.SEARCH_URL, params):
                items = self._find_items(payload, "admrul" if target == "admrul" else "law")
                for item in items:
                    row = self._parse_search_item(item, source, target)
                    if row and row["source_version_id"] not in versions_by_id:
                        versions_by_id[row["source_version_id"]] = row

        versions = list(versions_by_id.values())

        if not versions:
            raise ValueError(f"법제처 검색 결과에서 법령을 찾지 못했습니다: {source['source_name']}")
        return versions

    def fetch_law_document(self, source: dict, version: dict) -> dict:
        """지정된 연혁 버전의 법령 본문 XML을 다운로드하여 딕셔너리로 반환합니다."""
        target = version.get("service_target") or (
            "admrul" if source["source_type"] == "administrative_rule" else "law"
        )
        id_key = "MST" if target == "law" else "ID"
        if target == "eflaw":
            id_key = "MST"
            id_value = version.get("mst")
        else:
            id_value = version.get("mst") if target == "law" else version.get("law_serial_no")
        if not id_value:
            raise ValueError(f"법령 본문을 다운로드하기 위한 고유 일련번호(ID)가 누락되었습니다: {source['source_id']}")

        params = {
            "OC": self.oc,
            "target": target,
            "type": "XML",
            id_key: id_value,
        }
        if target == "eflaw" and version.get("enforce_date"):
            params["efYd"] = str(version["enforce_date"]).replace("-", "")
            
        content = self._request_text(self.SERVICE_URL, params)
        return {
            "source_id": source["source_id"],
            "source_version_id": version["source_version_id"],
            "raw_format": "xml",
            "content": content,
            "source_url": self._public_source_url(target, id_key, id_value),
        }

    def _request_xml(self, url: str, params: dict[str, str]) -> ET.Element:
        text = self._request_text(url, params)
        try:
            return ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            raise ValueError(f"법제처가 잘못된 XML을 반환했습니다: {exc}") from exc

    def _request_xml_pages(self, url: str, params: dict[str, str]) -> list[ET.Element]:
        pages = []
        page = 1
        total_count = None
        display = int(params.get("display", "100"))

        while True:
            payload = self._request_xml(url, {**params, "page": str(page)})
            pages.append(payload)
            if total_count is None:
                total_count = _int_or_none(_descendant_text(payload, "totalCnt"))
            if total_count is None or page * display >= total_count:
                break
            page += 1
        return pages

    def _find_law_id(self, source: dict, query: str) -> str | None:
        for payload in self._request_xml_pages(
            self.SEARCH_URL,
            {
                "OC": self.oc,
                "target": "law",
                "type": "XML",
                "query": query,
                "display": "100",
            },
        ):
            for item in self._find_items(payload, "law"):
                values = {
                    _strip_namespace(child.tag): (child.text or "").strip()
                    for child in item
                }
                if _first_value(values, ["법령명한글"]) == source["source_name"]:
                    return _first_value(values, ["법령ID"])
        return None

    def _search_effective_law_versions(
        self, source: dict, law_id: str, base_date: str, history_years: int
    ) -> list[dict]:
        versions_by_id = {}
        for payload in self._request_xml_pages(
            self.SEARCH_URL,
            {
                "OC": self.oc,
                "target": "eflaw",
                "type": "XML",
                "LID": law_id,
                "display": "100",
                "nw": "1,3",
            },
        ):
            for item in self._find_items(payload, "law"):
                row = self._parse_search_item(item, source, "law")
                if row:
                    row["service_target"] = "eflaw"
                    versions_by_id[row["source_version_id"]] = row
        return _filter_history_window(
            list(versions_by_id.values()), base_date, history_years
        )

    def _request_text(self, url: str, params: dict[str, str]) -> str:
        encoded = urllib.parse.urlencode(params, doseq=True)
        request_url = f"{url}?{encoded}"
        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                with urllib.request.urlopen(request_url, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                return raw.decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.retry_count:
                    time.sleep(self.retry_sleep_seconds * (attempt + 1))
        raise RuntimeError(f"법제처 API 요청에 실패했습니다: {last_error}") from last_error

    def _find_items(self, root: ET.Element, item_tag: str) -> list[ET.Element]:
        return [element for element in root.iter() if _strip_namespace(element.tag) == item_tag]

    def _parse_search_item(
        self, item: ET.Element, source: dict, target: str
    ) -> dict | None:
        values = {_strip_namespace(child.tag): (child.text or "").strip() for child in item}
        if target == "admrul":
            serial_no = _first_value(values, ["행정규칙일련번호", "일련번호"])
            law_id = _first_value(values, ["행정규칙ID"])
            enforce_date = _format_yyyymmdd(_first_value(values, ["시행일자", "발령일자"]))
            if not law_id and not serial_no:
                return None
            version_id = f"{source['source_id']}:{enforce_date or 'unknown'}:{law_id or serial_no}"
            return {
                "source_version_id": version_id,
                "source_group_id": f"{source['source_id']}:{law_id or serial_no}",
                "source_id": source["source_id"],
                "mst": serial_no,
                "law_id": law_id,
                "law_serial_no": serial_no,
                "promulgation_date": _format_yyyymmdd(_first_value(values, ["발령일자"])),
                "promulgation_no": _first_value(values, ["발령번호"]),
                "enforce_date": enforce_date,
                "expire_date": None,
                "version_status": _first_value(values, ["현행연혁구분"]) or "current",
            }

        law_name = _first_value(values, ["법령명한글"])
        if law_name and law_name != source["source_name"]:
            return None
        mst = _first_value(values, ["법령일련번호"])
        law_id = _first_value(values, ["법령ID"])
        enforce_date = _format_yyyymmdd(_first_value(values, ["시행일자", "공포일자"]))
        if not mst and not law_id:
            return None
        version_id = f"{source['source_id']}:{enforce_date or 'unknown'}:{mst or law_id}"
        return {
            "source_version_id": version_id,
            "source_group_id": source["source_id"],
            "source_id": source["source_id"],
            "mst": mst,
            "law_id": law_id,
            "law_serial_no": mst,
            "promulgation_date": _format_yyyymmdd(_first_value(values, ["공포일자"])),
            "promulgation_no": _first_value(values, ["공포번호"]),
            "enforce_date": enforce_date,
            "expire_date": None,
            "version_status": _first_value(values, ["현행연혁코드"]) or "current",
        }

    def _public_source_url(self, target: str, id_key: str, id_value: str) -> str:
        return f"{self.SERVICE_URL}?target={target}&type=HTML&{id_key}={urllib.parse.quote(str(id_value))}"


def create_law_api_client(name: str = "auto") -> LawApiClient:
    """설정에 따라 실시간 법제처 API용 클라이언트 또는 오프라인 Mock 클라이언트를 생성합니다."""
    load_local_env()
    if name == "offline":
        return OfflineLawApiClient()
    if name == "law_go_kr":
        return LawGoKrApiClient()
    if os.getenv("LAW_GO_KR_OC") or os.getenv("LAW_API_KEY"):
        return LawGoKrApiClient()
    return OfflineLawApiClient()


def load_local_env(path: str = ".env") -> None:
    """로컬의 .env 파일에 등록된 KEY=VALUE를 가져와 시스템 환경변수에 설정합니다."""
    from etl.common.utils import load_env_file
    load_env_file(path)


# ==========================================
# 3. 데이터 원본 백업/저장 영역 (Raw Store)
# ==========================================

def save_raw_documents(raw_documents: list[dict], output_dir: str | Path) -> list[dict]:
    """수집된 전체 원본 데이터들을 지정 디렉토리 아래 'raw/'에 파일로 저장합니다."""
    raw_dir = Path(output_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return [save_raw_document(raw, raw_dir) for raw in raw_documents]


def save_raw_document(raw: dict, raw_dir: str | Path) -> dict:
    """개별 법령 XML 원본 텍스트를 파일로 저장하고 백업 메타데이터 레코드를 생성합니다."""
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)

    content = str(raw.get("content", ""))
    raw_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    ext = str(raw.get("raw_format") or "txt")
    filename = f"{_safe(raw['source_id'])}_{_safe(raw['source_version_id'])}.{ext}"
    file_path = raw_path / filename
    file_path.write_text(content, encoding="utf-8")

    return {
        "raw_document_id": f"raw:{raw['source_version_id']}",
        "source_id": raw["source_id"],
        "source_version_id": raw["source_version_id"],
        "raw_format": ext,
        "raw_path": str(Path("raw") / filename),
        "raw_hash": raw_hash,
        "source_url": raw.get("source_url"),
        "content": content,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "success",
        "fetch_error": None,
    }


def _safe(value: str) -> str:
    """파일명으로 사용하기 어려운 특수문자들을 정제합니다."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


# ==========================================
# 4. 버전 정규화 영역 (Version Normalizer)
# ==========================================

def normalize_versions(
    raw_versions: list[dict], base_date: date, history_years: int
) -> list[dict]:
    """수집된 전체 연혁 버전 중, 유효성 시작일(enforce_date)과 만료일(expire_date)을 비교해 기간 내 법률만 분류합니다."""
    versions = compute_expire_dates(raw_versions)
    window_start = date(base_date.year - history_years, base_date.month, base_date.day)
    window_end = base_date

    normalized = []
    for version in versions:
        enforce_date = _parse_date(version.get("enforce_date"))
        expire_date = _parse_date(version.get("expire_date"))
        # 효력일자가 기준 수집 윈도우 기간과 겹치는 경우에만 파이프라인 대상에 포함
        if enforce_date and enforce_date <= window_end and (
            expire_date is None or expire_date >= window_start
        ):
            raw_document_id = f"raw:{version['source_version_id']}"
            normalized.append({**version, "raw_document_id": raw_document_id})
    return normalized


def compute_expire_dates(versions: list[dict]) -> list[dict]:
    """다음 개정판의 시행일(enforce_date) 전날을 이전 판의 만료일(expire_date)로 지정해 적용 한계 기간을 조립합니다."""
    grouped: dict[str, list[dict]] = {}
    for version in versions:
        grouped.setdefault(version.get("source_group_id") or version["source_id"], []).append(dict(version))

    result: list[dict] = []
    for source_versions in grouped.values():
        ordered = sorted(source_versions, key=lambda row: str(row.get("enforce_date") or ""))
        for index, version in enumerate(ordered):
            # 다음 버전 정보가 있는 경우 그 전날이나 시행일을 바탕으로 만료일 계산
            if version.get("expire_date") is None and index + 1 < len(ordered):
                next_date = _parse_date(ordered[index + 1].get("enforce_date"))
                version["expire_date"] = next_date.isoformat() if next_date else None
            result.append(version)
    return result


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value))


# ==========================================
# 5. 수집 실행 오케스트레이션 영역 (Collector)
# ==========================================

def collect_sources(
    sources: list[dict],
    base_date: str,
    history_years: int,
    client: LawApiClient | None = None,
) -> dict:
    """지정된 API 클라이언트를 통해 각 대상 법령의 제개정 버전 연혁과 원본 법령 데이터를 수집합니다."""
    api_client = client or OfflineLawApiClient()
    versions: list[dict] = []
    raw_documents: list[dict] = []
    failed_items: list[dict] = []

    for source in sources:
        try:
            source_versions = api_client.search_law_versions(
                source, base_date, history_years
            )
            for version in source_versions:
                versions.append({**version, "source_id": source["source_id"]})
                raw_documents.append(api_client.fetch_law_document(source, version))
        except Exception as exc:  # pragma: no cover
            failed_items.append(
                {
                    "source_id": source.get("source_id"),
                    "stage": "collect",
                    "error": str(exc),
                }
            )

    return {
        "sources": sources,
        "versions": versions,
        "raw_documents": raw_documents,
        "failed_items": failed_items,
    }


# Helper utilities for internal use

def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_value(values: dict[str, str], keys: list[str]) -> str | None:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return None


def _format_yyyymmdd(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _history_window(base_date: str, history_years: int) -> str:
    end = date.fromisoformat(base_date)
    start = date(end.year - history_years, end.month, end.day)
    return f"{start:%Y%m%d}~{end:%Y%m%d}"


def _filter_history_window(
    versions: list[dict], base_date: str, history_years: int
) -> list[dict]:
    end = date.fromisoformat(base_date)
    start = date(end.year - history_years, end.month, end.day)
    dated = []
    for version in versions:
        enforce_date = _date_or_none(version.get("enforce_date"))
        if enforce_date:
            dated.append((enforce_date, version))

    included = [version for enforce_date, version in dated if start <= enforce_date <= end]
    before_start = [item for item in dated if item[0] < start]
    if before_start:
        included.append(max(before_start, key=lambda item: item[0])[1])

    unique = {version["source_version_id"]: version for version in included}
    return sorted(unique.values(), key=lambda row: str(row.get("enforce_date") or ""))


def _date_or_none(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _descendant_text(element: ET.Element, tag_name: str) -> str | None:
    for child in element.iter():
        if _strip_namespace(child.tag) == tag_name and child.text:
            return child.text.strip()
    return None


def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
