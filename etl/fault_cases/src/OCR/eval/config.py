"""eval 설정 모음.

모델 목록, 가격표, 샘플 경로, Gate 기준값 등 모든 평가 모듈이 공유하는 상수를 정의한다.
경로는 이 파일 위치를 기준으로 자동 계산하므로 실행 위치와 무관하게 동작한다.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
_EVAL_DIR = Path(__file__).resolve().parent        # .../OCR/eval/
_OCR_DIR = _EVAL_DIR.parent                        # .../OCR/
_FAULT_CASES_DIR = _OCR_DIR.parent.parent          # .../fault_cases/

SAMPLE_DIR: Path = _OCR_DIR / "raw" / "1page"
RESULTS_DIR: Path = _FAULT_CASES_DIR / "artifacts" / "eval_results"

# ---------------------------------------------------------------------------
# 평가 모델 목록 및 가격표 (USD per 1M tokens)
# ---------------------------------------------------------------------------
MODEL_PRICES: dict[str, dict[str, float]] = {
    "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
    "gpt-5.4-nano": {"input": 0.20,  "output": 1.25},
    "gpt-5.4-mini": {"input": 0.75,  "output": 4.50},
    "gpt-4o":       {"input": 2.50,  "output": 10.00},
    "gpt-5.4":      {"input": 2.50,  "output": 15.00},
}

EVAL_MODELS: list[str] = list(MODEL_PRICES.keys())

# ---------------------------------------------------------------------------
# 평가 샘플 파일 목록
# ---------------------------------------------------------------------------
SAMPLE_FILES: list[str] = [
    "17-10-16-서울노원구.png",
    "24-00-00-경기도부천시.jpg",
    "15-07-18-광주광역시.jpg",
    "23-07-18-서울송파구.png",
    "24-08-26-충청남도.png",
]

# ---------------------------------------------------------------------------
# Critical / Important 필드 정의
# ---------------------------------------------------------------------------
CRITICAL_FIELDS: list[str] = [
    "accident_datetime",
    "accident_location",
    "accident_type.value",
    "accident_description",
]

IMPORTANT_FIELDS: list[str] = [
    "receipt_number",
    "issue_number",
    "police_station",
    "accident_cause",
    "damage.raw_text",
    "usage",
]

# ---------------------------------------------------------------------------
# Gate 통과 기준
# ---------------------------------------------------------------------------
# 5장 평균 Critical 필드 추출률 최솟값
GATE_MIN_CRITICAL_RATE: float = 0.80

# 5장 중 문서 판별 성공 최솟값
GATE_MIN_DOCUMENT_DETECT: int = 4

# ---------------------------------------------------------------------------
# 최종 점수 가중치
# ---------------------------------------------------------------------------
WEIGHT_COST:      float = 0.40
WEIGHT_PERF:      float = 0.45
WEIGHT_SPEED:     float = 0.10
WEIGHT_STABILITY: float = 0.05
