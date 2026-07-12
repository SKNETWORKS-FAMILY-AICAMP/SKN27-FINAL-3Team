"""OCR 단건 호출 래퍼.

OpenAI Vision API를 직접 호출하여 처리 시간(ms), input/output 토큰 수,
1장당 비용을 함께 반환한다.
운영 파이프라인(agent.py)과는 별도로 eval 전용으로만 사용한다.
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

from .config import MODEL_PRICES


# 확장자 → MIME 타입 매핑
_MIME_MAP: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
}


def load_image_base64(image_path: Path) -> tuple[str, str]:
    """이미지 파일을 base64 문자열과 MIME 타입으로 반환."""
    mime = _MIME_MAP.get(image_path.suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return b64, mime


def call_ocr_with_metrics(
    image_path: Path,
    model: str,
    prompt: str,
) -> dict[str, Any]:
    """단건 OCR 호출. 처리 시간과 토큰 사용량을 함께 반환한다.

    Returns:
        {
            "parsed":        dict,   # JSON 파싱 결과
            "input_tokens":  int,
            "output_tokens": int,
            "elapsed_ms":    int,    # API 응답까지 걸린 시간 (ms)
            "cost_usd":      float,  # 1장당 비용 (USD)
            "json_success":  bool,
            "error":         str | None,
        }
    """
    from openai import OpenAI

    b64_image, mime_type = load_image_base64(image_path)
    client = OpenAI()

    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=1600,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                        },
                    ],
                }
            ],
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        raw_content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens  = usage.prompt_tokens     if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        cost_usd = _calc_cost(model, input_tokens, output_tokens)
        parsed, json_success = _parse_json(raw_content)

        return {
            "parsed":        parsed,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "elapsed_ms":    elapsed_ms,
            "cost_usd":      cost_usd,
            "json_success":  json_success,
            "error":         None,
        }

    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "parsed":        {},
            "input_tokens":  0,
            "output_tokens": 0,
            "elapsed_ms":    elapsed_ms,
            "cost_usd":      0.0,
            "json_success":  False,
            "error":         str(exc),
        }


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = MODEL_PRICES.get(model, {"input": 0.0, "output": 0.0})
    return (
        input_tokens  / 1_000_000 * price["input"]
        + output_tokens / 1_000_000 * price["output"]
    )


def _parse_json(raw_content: str) -> tuple[dict[str, Any], bool]:
    """JSON 파싱. 실패 시 정규식으로 JSON 블록을 추출 재시도."""
    cleaned = raw_content.strip()
    try:
        parsed = json.loads(cleaned)
        return (parsed if isinstance(parsed, dict) else {}), True
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return (parsed if isinstance(parsed, dict) else {}), True
            except json.JSONDecodeError:
                pass
    return {}, False
