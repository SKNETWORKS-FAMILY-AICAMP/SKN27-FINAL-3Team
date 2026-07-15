"""공공데이터와 OSM 로더에서 함께 쓰는 공통 유틸리티."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from json import JSONDecodeError

from app.config import Settings, get_settings


class PublicDataApiError(RuntimeError):
    """공공데이터 API 호출 실패 정보를 서비스키 없이 전달하는 예외입니다."""


def ensure_data_dirs(settings: Settings | None = None) -> None:
    """데이터 로더가 사용하는 기본 폴더(raw/snapshots/rejected)를 생성한다."""
    selected = settings or get_settings()
    base_dir = Path(selected.road_data_dir)
    for child in ("raw", "raw/api_samples", "raw/reference", "snapshots", "rejected"):
        (base_dir / child).mkdir(parents=True, exist_ok=True)


def data_path(*parts: str, settings: Settings | None = None) -> Path:
    """ROAD_DATA_DIR 아래의 파일 또는 폴더 경로를 안전하게 조립한다."""
    selected = settings or get_settings()
    return Path(selected.road_data_dir).joinpath(*parts)


def require_value(value: str, name: str) -> str:
    """필수 설정값이 비어 있으면 알아보기 쉬운 오류를 발생시킨다."""
    if not value:
        raise RuntimeError(f"{name} 값이 필요합니다. road-mcp/.env 설정을 확인하세요.")
    return value


def build_public_data_params(
    settings: Settings,
    page_no: int = 1,
    num_of_rows: int | None = None,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """공공데이터포털 API 호출에 공통으로 필요한 쿼리 파라미터를 만든다."""
    params: dict[str, Any] = {
        "serviceKey": require_value(settings.public_data_api_key, "PUBLIC_DATA_API_KEY"),
        "pageNo": page_no,
        "numOfRows": num_of_rows or settings.public_data_default_num_of_rows,
    }
    if extra_params:
        # API마다 추가 필수값이 다르므로 호출자가 넘긴 값을 마지막에 합친다.
        params.update({key: value for key, value in extra_params.items() if value not in (None, "")})
    return params


async def fetch_public_data_page(
    api_url: str,
    page_no: int = 1,
    num_of_rows: int | None = None,
    extra_params: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """공공데이터포털 API를 한 페이지 호출하고 JSON 응답을 반환한다."""
    selected = settings or get_settings()
    require_value(api_url, "공공데이터 API URL")
    params = build_public_data_params(selected, page_no, num_of_rows, extra_params)

    async with httpx.AsyncClient(timeout=selected.public_data_request_timeout_seconds) as client:
        for attempt in range(1, selected.public_data_max_retries + 2):
            try:
                response = await client.get(api_url, params=params, headers={"accept": "application/json"})
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt > selected.public_data_max_retries:
                    content_type = exc.response.headers.get("content-type", "")
                    body_preview = mask_secret(exc.response.text[:500], selected.public_data_api_key)
                    raise PublicDataApiError(
                        "공공데이터 API가 오류 상태를 반환했습니다. "
                        f"status_code={exc.response.status_code}, api_url={api_url!r}, "
                        f"content-type={content_type!r}, body_preview={body_preview!r}"
                    ) from None
                wait_seconds = selected.public_data_retry_backoff_seconds * attempt
                print(f"[retry] page={page_no} status={exc.response.status_code} retry_after={wait_seconds}s")
                await asyncio.sleep(wait_seconds)
            except httpx.HTTPError as exc:
                if attempt > selected.public_data_max_retries:
                    error_detail = str(exc) or repr(exc)
                    raise PublicDataApiError(
                        "공공데이터 API 요청 중 네트워크 오류가 발생했습니다. "
                        f"api_url={api_url!r}, error_type={type(exc).__name__}, "
                        f"error={mask_secret(error_detail, selected.public_data_api_key)!r}"
                    ) from None
                wait_seconds = selected.public_data_retry_backoff_seconds * attempt
                print(f"[retry] page={page_no} error_type={type(exc).__name__} retry_after={wait_seconds}s")
                await asyncio.sleep(wait_seconds)
        try:
            return response.json()
        except JSONDecodeError as exc:
            content_type = response.headers.get("content-type", "")
            body_preview = mask_secret(response.text[:500], selected.public_data_api_key)
            raise RuntimeError(
                "공공데이터 API 응답을 JSON으로 파싱하지 못했습니다. "
                f"content-type={content_type!r}, body_preview={body_preview!r}"
            ) from exc


def mask_secret(text: str, secret: str) -> str:
    """오류 메시지에 인증키가 노출되지 않도록 응답 문자열에서 키를 가린다."""
    if not secret:
        return text
    return text.replace(secret, "***")


async def iter_public_data_pages(
    api_url: str,
    num_of_rows: int | None = None,
    extra_params: dict[str, Any] | None = None,
    max_pages: int | None = None,
    start_page: int = 1,
    settings: Settings | None = None,
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    """공공데이터포털 API를 pageNo=1부터 순서대로 호출하는 비동기 반복자다."""
    selected = settings or get_settings()
    rows_per_page = num_of_rows or selected.public_data_default_num_of_rows
    page_no = max(start_page, 1)

    while True:
        payload = await fetch_public_data_page(
            api_url=api_url,
            page_no=page_no,
            num_of_rows=rows_per_page,
            extra_params=extra_params,
            settings=selected,
        )
        yield page_no, payload

        records = find_record_list(payload)
        total_count = find_total_count(payload)
        reached_total = total_count is not None and page_no * rows_per_page >= total_count
        no_more_records = records is not None and len(records) == 0
        no_data_response = is_no_data_response(payload)
        reached_limit = max_pages is not None and (page_no - start_page + 1) >= max_pages

        if reached_total or no_more_records or no_data_response or reached_limit:
            break
        page_no += 1


def save_json(payload: dict[str, Any], path: Path) -> Path:
    """JSON 데이터를 UTF-8 파일로 저장하고 저장 경로를 반환한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_api_sample(source_name: str, payload: dict[str, Any], suffix: str = "page1") -> Path:
    """API 미리보기 응답을 data/raw/api_samples 폴더에 저장한다."""
    safe_source_name = source_name.replace(" ", "_")
    output_path = data_path("raw", "api_samples", f"{safe_source_name}_{suffix}.json")
    return save_json(payload, output_path)


def snapshot_path(source_name: str, page_no: int, suffix: str = "json") -> Path:
    """원본 응답 스냅샷을 날짜가 붙은 소스 폴더 아래에 저장하기 위한 경로를 만든다."""
    today = datetime.now().strftime("%y%m%d")
    safe_source_name = source_name.replace(" ", "_")
    dated_source_name = f"{safe_source_name}_{today}"
    return data_path("snapshots", dated_source_name, f"page_{page_no:05d}.{suffix}")


def latest_snapshot_page(source_name: str, settings: Settings | None = None) -> int | None:
    """오늘 날짜가 붙은 소스 폴더에서 가장 마지막 페이지 번호를 찾는다."""
    today = datetime.now().strftime("%y%m%d")
    safe_source_name = source_name.replace(" ", "_")
    snapshot_dir = data_path("snapshots", f"{safe_source_name}_{today}", settings=settings)
    if not snapshot_dir.exists():
        return None

    page_numbers: list[int] = []
    for path in snapshot_dir.glob("page_*.json"):
        page_text = path.stem.removeprefix("page_")
        try:
            page_numbers.append(int(page_text))
        except ValueError:
            continue
    return max(page_numbers) if page_numbers else None


def find_first_key(payload: Any, candidate_keys: tuple[str, ...]) -> Any:
    """중첩 JSON에서 후보 키 중 처음 발견되는 값을 재귀적으로 찾는다."""
    if isinstance(payload, dict):
        for key in candidate_keys:
            if key in payload:
                return payload[key]
        for value in payload.values():
            found = find_first_key(value, candidate_keys)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = find_first_key(item, candidate_keys)
            if found is not None:
                return found
    return None


def find_total_count(payload: dict[str, Any]) -> int | None:
    """응답 JSON에서 전체 건수로 보이는 값을 찾아 정수로 반환한다."""
    value = find_first_key(payload, ("totalCount", "totalCnt", "total_count", "total", "count"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_result_code(payload: dict[str, Any]) -> str | None:
    """공공데이터 응답 JSON에서 resultCode 값을 찾는다."""
    value = find_first_key(payload, ("resultCode", "result_code", "code"))
    return str(value) if value is not None else None


def is_no_data_response(payload: dict[str, Any]) -> bool:
    """공공데이터 응답이 조회 결과 0건을 뜻하는지 확인한다."""
    result_code = find_result_code(payload)
    total_count = find_total_count(payload)
    return result_code == "ERR_03" or total_count == 0


def find_record_list(payload: dict[str, Any]) -> list[Any] | None:
    """응답 JSON에서 실제 데이터 목록으로 보이는 배열을 추정한다."""
    candidate = find_first_key(payload, ("items", "item", "data", "list", "rows"))
    if isinstance(candidate, list):
        return candidate
    if isinstance(candidate, dict):
        nested = find_record_list(candidate)
        if nested is not None:
            return nested
        return [candidate]
    return None


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """응답 구조 파악을 위해 전체 건수와 목록 건수를 간단히 요약한다."""
    records = find_record_list(payload)
    return {
        "total_count": find_total_count(payload),
        "record_count": len(records) if records is not None else None,
        "top_level_keys": list(payload.keys()),
    }


async def preview_public_data_api(
    source_name: str,
    api_url: str,
    extra_params: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """공공데이터 API를 1건만 호출하고 샘플 JSON 파일까지 저장한다."""
    selected = settings or get_settings()
    ensure_data_dirs(selected)
    payload = await fetch_public_data_page(
        api_url=api_url,
        page_no=1,
        num_of_rows=1,
        extra_params=extra_params,
        settings=selected,
    )
    saved_path = save_api_sample(source_name, payload)
    summary = summarize_payload(payload)
    print(f"[{source_name}] sample saved: {saved_path}")
    print(f"[{source_name}] summary: {summary}")
    return payload
