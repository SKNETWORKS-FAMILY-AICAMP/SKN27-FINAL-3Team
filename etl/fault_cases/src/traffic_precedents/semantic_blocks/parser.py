"""문장 파편이 아닌 문맥 단위의 보수적 의미 블록 파서."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


PARSER_VERSION = "semantic_context_blocks_v2.4.0"
RATIO_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
CASE_CITATION_RE = re.compile(
    r"(?:대법원|고등법원|지방법원).{0,50}?선고.{0,40}?판결"
)
SENTENCE_RE = re.compile(r".+?(?:[.!?](?=\s|$)|\n+|$)", re.DOTALL)

PARTY_CLAIM_CUES = (
    "원고의 주장",
    "피고의 주장",
    "주장한다",
    "주장하므로",
    "항변한다",
    "항변하므로",
    "다투고 있다",
    "청구원인",
)
COURT_DECISION_CUES = (
    "인정된다",
    "인정할 수 있다",
    "판단한다",
    "판단된다",
    "타당하다",
    "상당하다",
    "이유 없다",
    "배척한다",
    "참작한다",
    "제한함이",
    "책임을 진다",
    "책임이 있다",
    "과실이 있다",
    "과실이 인정",
    "보아야 한다",
)
PARTICIPANTS = (
    "원고 차량",
    "피고 차량",
    "가해차량",
    "피해차량",
    "차량",
    "자동차",
    "승용차",
    "화물차",
    "버스",
    "택시",
    "오토바이",
    "이륜차",
    "자전거",
    "운전자",
    "운전수",
    "운전사",
    "운전병",
    "보행자",
)
ROAD_CUES = (
    "도로",
    "교차로",
    "차로",
    "횡단보도",
    "중앙선",
    "신호등",
    "갓길",
    "주차장",
)
TRAFFIC_ACTIONS = (
    "진행",
    "직진",
    "좌회전",
    "우회전",
    "유턴",
    "차로변경",
    "추월",
    "후진",
    "정차",
    "급정지",
    "서행",
    "횡단",
    "진입",
    "운전",
    "추격",
)
COLLISION_CUES = (
    "충돌",
    "추돌",
    "접촉",
    "들이받",
    "부딪",
    "역과",
    "교통사고",
    "사고",
)
FAULT_CUES = (
    "과실",
    "주의의무",
    "전방주시",
    "안전운전의무",
    "신호위반",
    "과실상계",
    "책임제한",
    "책임 비율",
)
DAMAGE_PROCEDURE_CUES = (
    "소송비용",
    "지연손해금",
    "치료비",
    "일실수입",
    "손해액",
    "위자료",
    "보험금",
    "구상금",
    "가집행",
    "상고를 기각",
    "파기환송",
)
ABSTRACT_CUES = (
    "일반적으로",
    "원칙적으로",
    "법리는",
    "취지는",
    "의미한다",
    "해석하여야",
)
CURRENT_CASE_CUES = (
    "이 사건",
    "본건",
    "원심은",
    "원심이",
    "기록에 의하면",
    "기록에 비추어",
    "채용한 증거",
    "사실을 인정",
    "위 사고",
    "이 사고",
)
TRAFFIC_CASE_TITLE_CUES = (
    "손해배상(자)",
    "교통사고",
    "도로교통",
    "자동차손해배상",
)


@dataclass
class SemanticBlock:
    block_id: str
    record_id: str
    block_type: str
    semantic_role: str
    speaker_role: str
    evidence_scope: str
    source_scope: str
    section_name: str
    text: str
    start_offset: int
    end_offset: int
    linked_entities: dict[str, list[str]]
    ratio_mentions: list[dict[str, Any]]
    sentence_ids: list[str]
    incident_id: str | None
    reason_codes: list[str]
    parser_version: str
    confidence: float
    is_valid_evidence: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unique_matches(text: str, candidates: tuple[str, ...]) -> list[str]:
    return [candidate for candidate in candidates if candidate in text]


def _case_has_road_traffic_context(record: dict[str, Any]) -> bool:
    """의료·산재 과실 판단을 도로교통 과실 판단으로 승인하지 않게 합니다."""

    title = str(record.get("사건명") or "")
    if any(cue in title for cue in TRAFFIC_CASE_TITLE_CUES):
        return True
    text = str(record.get("full_text") or record.get("reason_text") or "")
    has_participant = bool(_unique_matches(text, PARTICIPANTS))
    has_movement_or_collision = bool(
        _unique_matches(text, TRAFFIC_ACTIONS)
        or _unique_matches(text, COLLISION_CUES)
    )
    has_road_or_collision = bool(
        _unique_matches(text, ROAD_CUES)
        or _unique_matches(text, COLLISION_CUES)
    )
    return has_participant and has_movement_or_collision and has_road_or_collision


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    """문장 offset을 보존하되, 최종 블록은 여러 문장을 다시 결합합니다."""

    sentences: list[tuple[str, int, int]] = []
    for match in SENTENCE_RE.finditer(text):
        raw = match.group()
        left = len(raw) - len(raw.lstrip())
        sentence = raw.strip()
        if len(sentence) < 4:
            continue
        start = match.start() + left
        sentences.append((sentence, start, start + len(sentence)))
    return sentences


def build_context_units(
    text: str,
    target_chars: int = 800,
    max_chars: int = 1200,
) -> list[tuple[str, int, int, list[int]]]:
    """인접한 2~여러 문장을 최대 길이 안에서 문맥 블록으로 조립합니다."""

    sentences = split_sentences(text)
    if not sentences and text.strip():
        start = text.find(text.strip())
        return [(text.strip(), start, start + len(text.strip()), [1])]

    units: list[tuple[str, int, int, list[int]]] = []
    current: list[tuple[int, str, int, int]] = []

    def flush() -> None:
        if not current:
            return
        start = current[0][2]
        end = current[-1][3]
        units.append(
            (
                text[start:end].strip(),
                start,
                end,
                [item[0] for item in current],
            )
        )
        current.clear()

    for sentence_index, (sentence, start, end) in enumerate(sentences, 1):
        if len(sentence) > max_chars:
            flush()
            for chunk_start in range(0, len(sentence), target_chars):
                chunk = sentence[chunk_start : chunk_start + target_chars]
                units.append(
                    (
                        chunk,
                        start + chunk_start,
                        start + chunk_start + len(chunk),
                        [sentence_index],
                    )
                )
            continue

        projected_start = current[0][2] if current else start
        projected_length = end - projected_start
        if current and projected_length > max_chars:
            flush()
        current.append((sentence_index, sentence, start, end))
        if end - current[0][2] >= target_chars:
            flush()
    flush()
    return units


def classify_ratio_mentions(text: str) -> list[dict[str, Any]]:
    """퍼센트를 과실·이자·장해·기왕증 등 문맥으로 구분합니다."""

    mentions: list[dict[str, Any]] = []
    for match in RATIO_RE.finditer(text):
        window = text[max(0, match.start() - 80) : min(len(text), match.end() + 80)]
        if any(cue in window for cue in ("연 ", "다 갚는 날", "지연손해금")):
            context = "INTEREST_RATE"
        elif any(cue in window for cue in ("노동능력상실", "장해율", "후유장해")):
            context = "DISABILITY_RATE"
        elif "기왕증" in window:
            context = "PREEXISTING_CONDITION_RATE"
        elif any(cue in window for cue in ("환자", "수술", "의료", "검사")):
            context = "MEDICAL_STATISTIC"
        elif any(cue in window for cue in FAULT_CUES) or any(
            cue in window
            for cue in (
                "책임을 제한",
                "책임 비율",
                "과실을 참작",
                "이를 참작",
                "그 비율은",
            )
        ):
            context = "FAULT_RATIO"
        elif any(cue in window for cue in ("손해액", "공제", "배상액")):
            context = "DAMAGE_CALCULATION_RATE"
        else:
            context = "OTHER_PERCENT"
        mentions.append(
            {
                "value": match.group(0).replace(" ", ""),
                "context": context,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return mentions


def _is_citation_dominant(text: str) -> bool:
    """인용 판결 한 개 때문에 현재 사건 문단 전체를 인용문으로 보지 않습니다."""

    citations = list(CASE_CITATION_RE.finditer(text))
    if not citations:
        return False
    starts_as_citation = citations[0].start() <= 20
    has_current_case_cue = any(cue in text for cue in CURRENT_CASE_CUES)
    has_court_adoption = any(
        cue in text
        for cue in (
            "정당하다",
            "수긍이 간다",
            "판단하였다",
            "판단은",
            "인정한 사실",
        )
    )
    return starts_as_citation and not has_current_case_cue and not has_court_adoption


def _speaker_role(text: str, section: str) -> tuple[str, list[str]]:
    if section == "ORDER":
        return "COURT_JUDGMENT", ["ORDER_IS_COURT_TEXT"]
    if section in {"HOLDING", "SUMMARY"}:
        return "COURT_JUDGMENT", ["OFFICIAL_COURT_SUMMARY"]
    if any(cue in text for cue in PARTY_CLAIM_CUES) and not any(
        cue in text for cue in ("배척한다", "이유 없다", "인정된다")
    ):
        return "PARTY_CLAIM", ["PARTY_CLAIM_CUE"]
    if _is_citation_dominant(text):
        return "THIRD_PARTY_OR_CITING", ["CASE_CITATION_DOMINANT"]
    if section == "REASON_JUDGMENT":
        reasons = ["REASON_SECTION_COURT_AUTHORED"]
        if CASE_CITATION_RE.search(text):
            reasons.append("INLINE_CITATION_PRESENT_NOT_DOMINANT")
        return "COURT_JUDGMENT", reasons
    if any(cue in text for cue in COURT_DECISION_CUES):
        return "COURT_JUDGMENT", ["COURT_DECISION_CUE"]
    return "UNKNOWN", ["NO_RELIABLE_SPEAKER_CUE"]


def _source_scope(
    text: str,
    section: str,
    speaker: str,
    participants: list[str],
    actions: list[str],
) -> str:
    if speaker == "THIRD_PARTY_OR_CITING":
        return "CITED_CASE"
    has_traffic_context = bool(participants) and (
        bool(actions)
        or any(cue in text for cue in ROAD_CUES)
        or any(cue in text for cue in COLLISION_CUES)
    )
    if any(cue in text for cue in CURRENT_CASE_CUES) or has_traffic_context:
        return "CURRENT_CASE"
    if section in {"HOLDING", "SUMMARY"} and participants and any(
        cue in text for cue in FAULT_CUES
    ):
        return "CURRENT_CASE"
    if any(cue in text for cue in ABSTRACT_CUES):
        return "ABSTRACT_PRINCIPLE"
    return "UNKNOWN"


def _classify_role(
    text: str,
    section: str,
    speaker: str,
    source_scope: str,
    ratios: list[dict[str, Any]],
) -> tuple[str, float, list[str], dict[str, list[str]]]:
    subjects = _unique_matches(text, PARTICIPANTS)
    roads = _unique_matches(text, ROAD_CUES)
    actions = _unique_matches(text, TRAFFIC_ACTIONS)
    collisions = _unique_matches(text, COLLISION_CUES)
    faults = _unique_matches(text, FAULT_CUES)
    decisions = _unique_matches(text, COURT_DECISION_CUES)
    damages = _unique_matches(text, DAMAGE_PROCEDURE_CUES)
    entities = {
        "subjects": subjects,
        "roads": roads,
        "actions": actions,
        "collisions": collisions,
        "fault_terms": faults,
        "fault_ratios": [
            mention["value"]
            for mention in ratios
            if mention["context"] == "FAULT_RATIO"
        ],
    }

    if section == "ORDER":
        return "OTHER", 0.99, ["ORDER_SECTION_NOT_EVIDENCE"], entities
    if section == "BODY_PREAMBLE":
        return "OTHER", 0.99, ["CASE_METADATA_NOT_EVIDENCE"], entities
    if speaker == "PARTY_CLAIM":
        return "PARTY_ARGUMENT", 0.90, ["PARTY_SPEAKER_CONFIRMED"], entities
    if speaker == "THIRD_PARTY_OR_CITING":
        return "INLINE_CITATION", 0.88, ["CITED_CASE_SCOPE"], entities

    traffic_fact = bool(subjects) and bool(actions or collisions) and bool(
        roads or collisions
    )
    fault_ratio = any(
        mention["context"] == "FAULT_RATIO" for mention in ratios
    )
    fault_decision = (
        speaker == "COURT_JUDGMENT"
        and bool(faults or fault_ratio)
        and bool(decisions or fault_ratio)
    )
    if fault_decision:
        return (
            "FAULT_DECISION",
            0.92 if decisions and faults else 0.84,
            ["COURT_FAULT_RELATION_CONFIRMED"],
            entities,
        )
    if traffic_fact:
        signal_count = sum(bool(value) for value in (subjects, roads, actions, collisions))
        return (
            "ACCIDENT_FACT",
            min(0.95, 0.68 + signal_count * 0.06),
            ["TRAFFIC_PARTICIPANT_ACTION_RELATION"],
            entities,
        )
    if damages:
        return (
            "INSURANCE_DAMAGE_PROCEDURE",
            0.86,
            ["DAMAGE_OR_PROCEDURE_CONTEXT"],
            entities,
        )
    if any(cue in text for cue in ABSTRACT_CUES):
        return (
            "GENERAL_LEGAL_PRINCIPLE",
            0.80,
            ["ABSTRACT_LEGAL_CUE"],
            entities,
        )
    return "OTHER", 0.55, ["INSUFFICIENT_SEMANTIC_EVIDENCE"], entities


def parse_semantic_blocks(record: dict[str, Any]) -> list[SemanticBlock]:
    """전처리 구역별로 문맥 블록을 만들고 보수적인 의미 역할을 부여합니다."""

    record_id = str(
        record.get("판례정보일련번호")
        or record.get("판례일련번호")
        or record.get("_case_id")
        or "unknown"
    )
    full_offsets = record.get("full_text_section_offsets") or {}
    section_fields = [
        ("HOLDING", "판시사항", "holding_text"),
        ("SUMMARY", "판결요지", "summary_text"),
        ("BODY_PREAMBLE", "본문머리", "body_preamble_text"),
        ("ORDER", "주문", "order_text"),
        ("REASON_JUDGMENT", "이유", "reason_text"),
        ("UNLABELED_BODY", "미분류본문", "unlabeled_body_text"),
    ]
    blocks: list[SemanticBlock] = []
    case_has_road_traffic_context = _case_has_road_traffic_context(record)

    for section, full_name, field in section_fields:
        text = str(record.get(field) or "")
        if not text:
            continue
        base_offset = int((full_offsets.get(full_name) or {}).get("start", 0))
        for unit_text, local_start, local_end, sentence_numbers in build_context_units(text):
            block_number = len(blocks) + 1
            speaker, speaker_reasons = _speaker_role(unit_text, section)
            ratios = classify_ratio_mentions(unit_text)
            subjects = _unique_matches(unit_text, PARTICIPANTS)
            actions = _unique_matches(unit_text, TRAFFIC_ACTIONS)
            source_scope = _source_scope(
                unit_text,
                section,
                speaker,
                subjects,
                actions,
            )
            role, confidence, role_reasons, entities = _classify_role(
                unit_text,
                section,
                speaker,
                source_scope,
                ratios,
            )
            if role in {"ACCIDENT_FACT", "FAULT_DECISION"}:
                evidence_scope = (
                    "CONCRETE_CASE_FACT"
                    if source_scope == "CURRENT_CASE"
                    else "UNRESOLVED_CASE_SCOPE"
                )
            elif role == "GENERAL_LEGAL_PRINCIPLE":
                evidence_scope = "GENERAL_LEGAL_PRINCIPLE"
            elif role in {"INSURANCE_DAMAGE_PROCEDURE", "OTHER"}:
                evidence_scope = "NON_DIRECT_EVIDENCE"
            else:
                evidence_scope = "UNVERIFIED_EVIDENCE"

            is_valid = (
                role == "ACCIDENT_FACT"
                and speaker not in {"PARTY_CLAIM", "THIRD_PARTY_OR_CITING"}
                and source_scope == "CURRENT_CASE"
                and case_has_road_traffic_context
                and confidence >= 0.80
            ) or (
                role == "FAULT_DECISION"
                and speaker == "COURT_JUDGMENT"
                and source_scope == "CURRENT_CASE"
                and case_has_road_traffic_context
                and confidence >= 0.84
            )
            case_context_reason = (
                "CASE_ROAD_TRAFFIC_CONTEXT_CONFIRMED"
                if case_has_road_traffic_context
                else "CASE_ROAD_TRAFFIC_CONTEXT_MISSING"
            )
            incident_id = (
                "incident_01"
                if source_scope == "CURRENT_CASE"
                and role in {"ACCIDENT_FACT", "FAULT_DECISION"}
                else None
            )
            blocks.append(
                SemanticBlock(
                    block_id=f"{record_id}_blk_{block_number:05d}",
                    record_id=record_id,
                    block_type=role,
                    semantic_role=role,
                    speaker_role=speaker,
                    evidence_scope=evidence_scope,
                    source_scope=source_scope,
                    section_name=section,
                    text=unit_text,
                    start_offset=base_offset + local_start,
                    end_offset=base_offset + local_end,
                    linked_entities=entities,
                    ratio_mentions=ratios,
                    sentence_ids=[
                        f"{record_id}_{section}_s_{number:05d}"
                        for number in sentence_numbers
                    ],
                    incident_id=incident_id,
                    reason_codes=speaker_reasons
                    + role_reasons
                    + [case_context_reason],
                    parser_version=PARSER_VERSION,
                    confidence=round(confidence, 4),
                    is_valid_evidence=is_valid,
                )
            )
    return blocks
