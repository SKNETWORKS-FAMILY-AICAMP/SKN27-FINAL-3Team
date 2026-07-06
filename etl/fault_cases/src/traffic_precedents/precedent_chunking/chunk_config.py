from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size_chars: int = 1500
    chunk_overlap_chars: int = 250
    strategy: str = "structured_1500_250"


DEFAULT_CHUNK_CONFIG = ChunkConfig()


FAULT_RATIO_EVIDENCE_TERMS = [
    "과실비율",
    "책임비율",
    "과실상계",
    "원고의 과실",
    "피고의 과실",
    "피해자의 과실",
    "망인의 과실",
    "손해배상책임",
    "구상금",
    "전방주시의무",
    "안전운전의무",
    "신호위반",
    "중앙선 침범",
    "무단횡단",
    "차로변경",
    "진로변경",
]
