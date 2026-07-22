"""공통 유틸리티 (이전 build_canonical_profiles.py, run_abc.py에서 이관)"""

from __future__ import annotations
from typing import Any

def normalize_party_type(value: object) -> str | None:
    text = str(value or "").lower()
    if text in {"car", "vehicle", "자동차", "승용차", "대형차"}:
        return "vehicle"
    if "pm" in text or "개인형" in text:
        return "pm"
    if "pedestrian" in text or "보행" in text:
        return "pedestrian"
    if "motorcycle" in text or "이륜" in text:
        return "motorcycle"
    return None

def normalize_signal(value: object) -> str | None:
    text = str(value or "")
    if "적색점멸" in text:
        return "red_flash"
    if "황색점멸" in text:
        return "yellow_flash"
    if "녹색화살표" in text or "녹색 화살표" in text:
        return "green_arrow"
    if "적색" in text:
        return "red"
    if "황색" in text:
        return "yellow"
    if "녹색" in text:
        return "green"
    return None

def normalize_movement(value: object) -> str | None:
    text = str(value or "")
    if "차로변경" in text or "진로변경" in text:
        return "lane_change"
    if "합류" in text:
        return "merge"
    if "전진출차" in text or "전진 출차" in text:
        return "forward_exit"
    if "후진출차" in text or "후진 출차" in text:
        return "reverse_exit"
    if "후진" in text:
        return "reverse"
    if "횡단" in text:
        return "cross"
    if "비보호" in text and "좌회전" in text:
        return "unprotected_left_turn"
    if "좌회전" in text:
        return "left_turn"
    if "우회전" in text:
        return "right_turn"
    if "직진" in text:
        return "straight"
    if "회전" in text:
        return "circulate"
    if "진입" in text:
        return "entry"
    return None

def compact(value: object) -> str:
    return str(value).replace(" ", "")

def flat_facts(row: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    source = row.get("structured_facts") if isinstance(row.get("structured_facts"), dict) else row
    for scope in ("scene", "user", "opponent"):
        fields = source.get(scope, {}) if isinstance(source, dict) else {}
        if not isinstance(fields, dict):
            continue
        for key, value in fields.items():
            if value is None:
                continue
            if key == "party_type":
                normal = normalize_party_type(value)
            elif key in {"signal_state", "start_signal", "impact_signal", "entry_signal"}:
                normal = normalize_signal(value)
                key = "signal_state" if key == "signal_state" else key
            elif key == "movement":
                normal = normalize_movement(value)
            else:
                normal = compact(value).lower() if isinstance(value, bool) else compact(value)
            if normal is not None:
                output[f"{scope}.{key}"] = str(normal)
    return output
