from typing import Any

import httpx

from app.config import Settings, get_settings


class VWorldClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def search(self, query: str) -> list[dict[str, Any]]:
        if not self.settings.vworld_api_key:
            return []

        params = {
            "service": "search",
            "request": "search",
            "version": "2.0",
            "crs": "EPSG:4326",
            "size": 10,
            "page": 1,
            "query": query,
            "type": "PLACE",
            "format": "json",
            "errorformat": "json",
            "key": self.settings.vworld_api_key,
        }
        timeout = self.settings.vworld_request_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(self.settings.vworld_search_url, params=params)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("response", {}).get("result", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]

        candidates: list[dict[str, Any]] = []
        for item in items:
            point = item.get("point") or {}
            try:
                lat = float(point.get("y"))
                lon = float(point.get("x"))
            except (TypeError, ValueError):
                continue
            candidates.append(
                {
                    "이름": item.get("title") or item.get("id"),
                    "주소": item.get("address", {}).get("road") or item.get("address", {}).get("parcel"),
                    "좌표": {"위도": lat, "경도": lon},
                    "원천": "VWorld 검색 API",
                }
            )
        return candidates
