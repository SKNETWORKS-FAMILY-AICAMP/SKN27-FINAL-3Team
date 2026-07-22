from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable


CHUNK_STRATEGY = "fault_ratio_precedent_v2"


@dataclass(frozen=True)
class ChunkConfig:
    """Shared chunk settings to freeze before embedding model A/B tests."""

    target_chars: int = 900
    max_chars: int = 1200
    overlap_units: int = 1
    strategy: str = CHUNK_STRATEGY

    def __post_init__(self) -> None:
        if self.target_chars <= 0:
            raise ValueError("target_chars must be positive")
        if self.max_chars < self.target_chars:
            raise ValueError("max_chars must be greater than or equal to target_chars")
        if self.overlap_units < 0:
            raise ValueError("overlap_units must be zero or positive")


DEFAULT_CHUNK_CONFIG = ChunkConfig()


@dataclass(frozen=True)
class SourceChunk:
    chunk_type: str
    source_field: str
    text: str


OUTLINE_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])"
    r"(?P<marker>"
    r"(?:[IVXLC]{1,5}|(?:[1-9]|[12]\d|30)|[가-하])\."
    r"|\((?:\d{1,2}|[가-하])\)"
    r"|(?:\d{1,2}|[가-하])\)"
    r")"
    r"\s+(?=[가-힣A-Za-z【(])"
)

SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[가-힣A-Z【(])")
DATE_PREFIX_PATTERN = re.compile(r"\d{4}\.\s+\d{1,2}\.\s*$")

RATIO_EXPRESSION_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|퍼센트)|\d{1,3}\s*:\s*\d{1,3}"
)
FAULT_RATIO_CONTEXT_PATTERN = re.compile(
    r"과실비율|과실상계|책임비율|쌍방과실|과실을\s*참작|책임을\s*\d+(?:\.\d+)?\s*(?:%|퍼센트).*제한"
)

TRAFFIC_ACTOR_PATTERN = re.compile(
    r"자동차|차량|승용차|화물차|버스|택시|오토바이|이륜차|자전거|보행자|운전자"
)
TRAFFIC_ACTION_PATTERN = re.compile(
    r"교통사고|충돌|추돌|접촉|차로변경|진로변경|좌회전|우회전|직진|횡단|운행|주행"
)

SOURCE_FIELDS = (
    ("holding", "판시사항"),
    ("summary", "판결요지"),
    ("reasoning", "이유"),
)

SOURCE_LABELS = {
    "holding": "판시사항",
    "summary": "판결요지",
    "reasoning": "이유",
    "main_text_fallback": "판례내용(이유 폴백)",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_date_fragment(text: str, marker_start: int, marker: str) -> bool:
    if not marker[:-1].isdigit():
        return False
    prefix = text[max(0, marker_start - 14) : marker_start]
    return bool(DATE_PREFIX_PATTERN.search(prefix))


def split_outline_sections(text: str) -> list[str]:
    """Split flattened legal text at conservative outline markers."""

    normalized = normalize_text(text)
    if not normalized:
        return []

    starts: list[int] = []
    for match in OUTLINE_PATTERN.finditer(normalized):
        if _is_date_fragment(normalized, match.start(), match.group("marker")):
            continue
        starts.append(match.start())

    if not starts:
        return [normalized]

    boundaries = sorted({0, *starts, len(normalized)})
    sections = [normalize_text(normalized[start:end]) for start, end in zip(boundaries, boundaries[1:])]
    return [section for section in sections if section]


def split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    return [part.strip() for part in SENTENCE_BOUNDARY_PATTERN.split(normalized) if part.strip()]


def hard_split(text: str, max_chars: int) -> list[str]:
    """Bound a single long unit without cutting earlier than 60% when possible."""

    remaining = normalize_text(text)
    chunks: list[str] = []
    min_break = int(max_chars * 0.6)

    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        candidates = [
            window.rfind("\n", min_break),
            window.rfind("다. ", min_break),
            window.rfind(". ", min_break),
            window.rfind("; ", min_break),
        ]
        split_at = max(candidates)
        if split_at < min_break:
            split_at = max_chars
        elif window[split_at : split_at + 3] == "다. ":
            split_at += 2
        else:
            split_at += 1

        part = remaining[:split_at].strip()
        if part:
            chunks.append(part)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


def _atomic_units(text: str, config: ChunkConfig) -> list[str]:
    units: list[str] = []
    for section in split_outline_sections(text):
        candidates = [section]
        if len(section) > config.target_chars:
            candidates = split_sentences(section)

        for candidate in candidates:
            if len(candidate) <= config.max_chars:
                units.append(candidate)
            else:
                units.extend(hard_split(candidate, config.max_chars))
    return units


def pack_units(units: Iterable[str], config: ChunkConfig) -> list[str]:
    bounded = [normalize_text(unit) for unit in units if normalize_text(unit)]
    if not bounded:
        return []

    chunks: list[str] = []
    current: list[str] = []

    for unit in bounded:
        candidate = " ".join([*current, unit]).strip()
        should_flush = bool(current) and (
            len(candidate) > config.max_chars
            or len(" ".join(current)) >= config.target_chars
        )
        if should_flush:
            chunks.append(" ".join(current).strip())
            overlap = current[-config.overlap_units :] if config.overlap_units else []
            current = list(overlap)
            while current and len(" ".join([*current, unit])) > config.max_chars:
                current.pop(0)

        current.append(unit)

    if current:
        chunks.append(" ".join(current).strip())

    chunks = _merge_short_chunks(chunks, config.max_chars)

    unique_chunks: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if len(chunk) > config.max_chars:
            raise ValueError(f"chunk exceeds max_chars: {len(chunk)} > {config.max_chars}")
        digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            unique_chunks.append(chunk)
    return unique_chunks


def _has_substantive_text(text: str) -> bool:
    marker_only = re.fullmatch(
        r"\s*(?:[IVXLC]{1,5}|\d{1,2}|[가-하])\.|"
        r"\s*\((?:\d{1,2}|[가-하])\)|"
        r"\s*(?:\d{1,2}|[가-하])\)\s*",
        text,
    )
    return marker_only is None


def _merge_short_chunks(chunks: list[str], max_chars: int, min_chars: int = 120) -> list[str]:
    """Remove empty outline markers and attach short tails to nearby chunks."""

    cleaned = [chunk for chunk in chunks if _has_substantive_text(chunk)]
    if len(cleaned) <= 1:
        return cleaned

    merged: list[str] = []
    for chunk in cleaned:
        if merged and len(chunk) < min_chars and len(merged[-1]) + 1 + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)

    if len(merged) > 1 and len(merged[0]) < min_chars:
        candidate = f"{merged[0]} {merged[1]}"
        if len(candidate) <= max_chars:
            merged = [candidate, *merged[2:]]
    return merged


def split_source_text(
    text: Any,
    chunk_type: str,
    source_field: str,
    config: ChunkConfig = DEFAULT_CHUNK_CONFIG,
) -> list[SourceChunk]:
    chunks = pack_units(_atomic_units(normalize_text(text), config), config)
    return [SourceChunk(chunk_type=chunk_type, source_field=source_field, text=chunk) for chunk in chunks]


def validate_input_row(row: dict[str, Any]) -> None:
    required = {
        "_case_id": row.get("_case_id"),
        "사건명": row.get("사건명"),
        "판례내용 또는 이유": row.get("이유") or row.get("판례내용"),
    }
    missing = [name for name, value in required.items() if not normalize_text(value)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    traffic_label = normalize_text(row.get("traffic_verification_final_label"))
    fault_label = normalize_text(row.get("fault_ratio_verification_final_label"))
    if traffic_label and traffic_label != "confirmed_traffic":
        raise ValueError(f"unexpected traffic_verification_final_label: {traffic_label}")
    if fault_label and fault_label != "fault_ratio_confirmed":
        raise ValueError(f"unexpected fault_ratio_verification_final_label: {fault_label}")


def case_quality_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not normalize_text(row.get("이유")):
        flags.append("missing_reason_uses_main_text_fallback")
    if not normalize_text(row.get("판시사항")) and not normalize_text(row.get("판결요지")):
        flags.append("missing_holding_and_summary")
    if not normalize_text(row.get("과실비율")):
        flags.append("missing_structured_fault_ratio")
    if len(normalize_text(row.get("이유"))) > 30000:
        flags.append("very_long_reason")

    high_signal_text = " ".join(
        [
            normalize_text(row.get("사건명")),
            normalize_text(row.get("판시사항")),
            normalize_text(row.get("판결요지")),
            normalize_text(row.get("이유"))[:5000],
        ]
    )
    if not (TRAFFIC_ACTOR_PATTERN.search(high_signal_text) and TRAFFIC_ACTION_PATTERN.search(high_signal_text)):
        flags.append("needs_traffic_case_review")
    return flags


def build_embedding_text(row: dict[str, Any], source_chunk: SourceChunk) -> str:
    header_parts = [
        f"판례명: {normalize_text(row.get('사건명'))}",
        f"문서구역: {SOURCE_LABELS[source_chunk.chunk_type]}",
    ]
    category = normalize_text(row.get("사건종류명"))
    if category:
        header_parts.append(f"사건종류: {category}")
    return "\n".join([*header_parts, source_chunk.text])


def extract_ratio_expressions(text: str, structured_ratio: Any = None) -> list[str]:
    values = [normalize_text(value) for value in RATIO_EXPRESSION_PATTERN.findall(text)]
    if normalize_text(structured_ratio):
        values.insert(0, normalize_text(structured_ratio))
    return list(dict.fromkeys(value for value in values if value))


def build_case_chunks(
    row: dict[str, Any],
    config: ChunkConfig = DEFAULT_CHUNK_CONFIG,
) -> list[dict[str, Any]]:
    validate_input_row(row)
    case_id = normalize_text(row.get("_case_id"))
    source_chunks: list[SourceChunk] = []

    for chunk_type, source_field in SOURCE_FIELDS[:2]:
        source_chunks.extend(split_source_text(row.get(source_field), chunk_type, source_field, config))

    reason = normalize_text(row.get("이유"))
    if reason:
        source_chunks.extend(split_source_text(reason, "reasoning", "이유", config))
    else:
        source_chunks.extend(
            split_source_text(row.get("판례내용"), "main_text_fallback", "판례내용", config)
        )

    quality_flags = case_quality_flags(row)
    chunks: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for chunk_index, source_chunk in enumerate(source_chunks):
        text_hash = hashlib.sha256(source_chunk.text.encode("utf-8")).hexdigest()
        base_chunk_id = f"{case_id}:{config.strategy}:{source_chunk.chunk_type}:{text_hash[:12]}"
        chunk_id = base_chunk_id
        duplicate_index = 1
        while chunk_id in used_ids:
            duplicate_index += 1
            chunk_id = f"{base_chunk_id}:{duplicate_index}"
        used_ids.add(chunk_id)

        embedding_text = build_embedding_text(row, source_chunk)
        ratio_expressions = extract_ratio_expressions(
            source_chunk.text,
            row.get("과실비율") if FAULT_RATIO_CONTEXT_PATTERN.search(source_chunk.text) else None,
        )
        chunks.append(
            {
                "chunk_id": chunk_id,
                "case_id": case_id,
                "chunk_index": chunk_index,
                "chunk_type": source_chunk.chunk_type,
                "chunk_strategy": config.strategy,
                "chunk_text": source_chunk.text,
                "embedding_text": embedding_text,
                "char_count": len(source_chunk.text),
                "embedding_char_count": len(embedding_text),
                "text_hash": text_hash,
                "source_fields": [source_chunk.source_field],
                "metadata": {
                    "source_type": "fault_ratio_precedent",
                    "case_name": normalize_text(row.get("사건명")),
                    "case_number": normalize_text(row.get("사건번호")),
                    "decision_date": normalize_text(row.get("선고일자")),
                    "court_name": normalize_text(row.get("법원명")),
                    "case_category": normalize_text(row.get("사건종류명")),
                    "source_reference": normalize_text(row.get("source_reference")),
                    "structured_fault_ratio": normalize_text(row.get("과실비율")),
                    "ratio_expressions": ratio_expressions,
                    "contains_fault_ratio_context": bool(
                        FAULT_RATIO_CONTEXT_PATTERN.search(source_chunk.text) or ratio_expressions
                    ),
                    "contains_traffic_facts": bool(
                        TRAFFIC_ACTOR_PATTERN.search(source_chunk.text)
                        and TRAFFIC_ACTION_PATTERN.search(source_chunk.text)
                    ),
                    "quality_flags": quality_flags,
                },
            }
        )
    return chunks


def config_as_dict(config: ChunkConfig) -> dict[str, Any]:
    return asdict(config)
