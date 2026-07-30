from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


RAG_READY = "ready"
RAG_EXCLUDED = "excluded"

HIGH_SIGNAL_REASON_CHARS = 6000
MAX_EVIDENCE_SNIPPETS = 5
FAULT_TRAFFIC_LINK_RADIUS = 900

TRAFFIC_ACTOR_PATTERN = re.compile(
    r"자동차|차량|승용차|승합차|화물차|트럭|버스|택시|오토바이|이륜차|"
    r"자전거|보행자|운전자|피보험차량|가해차량|피해차량"
)
TRAFFIC_EVENT_PATTERN = re.compile(
    r"교통사고|충돌|추돌|접촉|들이받|부딪|차로변경|진로변경|좌회전|우회전|"
    r"직진|횡단보도|중앙선|신호위반|과속|급정거|안전거리|교차로|전복|추락|미끄러"
)
ACCIDENT_MECHANICS_PATTERN = re.compile(
    r"충돌|추돌|접촉|들이받|부딪|차로변경|진로변경|좌회전|우회전|직진|"
    r"횡단보도|중앙선|신호위반|과속|급정거|안전거리|교차로|전복|추락|미끄러"
)
DIRECT_TRAFFIC_PATTERN = re.compile(
    r"교통사고|자동차\s*사고|차량\s*사고|차량\s*간\s*(?:충돌|추돌|접촉)|"
    r"자동차\s*간\s*(?:충돌|추돌|접촉)"
)
DIRECT_TRAFFIC_FAULT_TITLE_PATTERN = re.compile(
    r"(?:쌍방과실|과실\s*비율|책임\s*비율).{0,40}교통사고|"
    r"교통사고.{0,40}(?:쌍방과실|과실\s*비율|책임\s*비율)"
)

RATIO_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|퍼센트)|\d{1,3}\s*[:：]\s*\d{1,3}|"
    r"\d{1,2}\s*대\s*\d{1,2}|\d{1,2}\s*할(?:\s*\d{1,2}\s*푼)?"
)
EXPLICIT_FAULT_PATTERN = re.compile(
    r"과실비율|과실\s*비율|책임비율|책임\s*비율|책임분담비율|쌍방과실|"
    r"과실상계|(?:원고|피고|피해자|가해자|운전자|차량)의?\s*과실|"
    r"(?:원고|피고|피해자|가해자|운전자|차량)의?\s*책임.{0,30}(?:제한|부담)|"
    r"책임을\s*\d+(?:\.\d+)?\s*(?:%|퍼센트).{0,15}제한|"
    r"과실을\s*\d+(?:\.\d+)?\s*(?:%|퍼센트).{0,15}(?:참작|인정)"
)
FAULT_PARTY_PATTERN = re.compile(
    r"원고|피고|피해자|가해자|망인|운전자|차량|보험자|피보험자"
)
FAULT_DECISION_PATTERN = re.compile(r"과실|책임|참작|제한|분담|상계")
RATIO_NOISE_PATTERN = re.compile(
    r"소송비용|소송총비용|지연손해금|지연이자|법정이율|소송촉진|"
    r"연\s*\d+(?:\.\d+)?\s*%|장해율|상실률|노동능력|상여수당|성과급|"
    r"근무시간|업무시간|지분율|배당률|수수료율|세율"
)

NON_TRAFFIC_MAIN_PATTERNS: dict[str, re.Pattern[str]] = {
    "labor_employment": re.compile(
        r"근로자지위|근로자파견|직접고용|부당해고|해고무효|임금청구|퇴직금|근로계약"
    ),
    "medical_malpractice": re.compile(
        r"손해배상\(의\)|의료과오|의료사고|진료과오|수술상 과실|의사의 주의의무|"
        r"의사.{0,40}(?:진단|검사|치료|전원)|의료기관.{0,30}(?:진료|치료)|"
        r"병원.{0,30}시설하자|의사.{0,30}간호사.{0,30}과실"
    ),
    "defamation_publication": re.compile(
        r"회고록|출판.{0,10}금지|명예훼손|인격권|표현의 자유|기사 게재"
    ),
    "corporate_dispute": re.compile(
        r"주주지위|주주총회|이사해임|신주발행|경영권 분쟁"
    ),
    "industrial_accident": re.compile(
        r"손해배상\(산\)|산업재해|산재보험|업무상 재해|광업소.{0,30}낙반|낙반사고"
    ),
    "maritime_disaster": re.compile(
        r"세월호|선박|선원|해상여객|해양사고|해상운송|한진해운|화물운송계약"
    ),
    "property_noise": re.compile(r"방음설비|소음피해|일조권|조망권"),
    "school_safety_accident": re.compile(r"공제급여|학교안전|교육활동 중 사고"),
    "vehicle_repair_service": re.compile(r"용역대금|정비공임|자동차정비업|수리비 청구"),
    "insurance_coverage_only": re.compile(
        r"가족운전자.{0,15}(?:한정|특약)|부담보특약|고지의무 위반|보험금 지급사유|"
        r"(?:음주|무면허)운전.{0,20}면책|자기신체사고|무보험자동차\s*상해"
    ),
    "legal_malpractice": re.compile(
        r"변호사.{0,40}(?:항소|상고|소송수행)|항소기간.{0,30}(?:도과|경과)|법률사무소"
    ),
    "public_custody_or_enforcement": re.compile(
        r"경찰관.{0,50}(?:직무위반|구호조치|병원 후송)|형집행장|노역장|유치장"
    ),
    "travel_contract": re.compile(
        r"여행계약|여행업자|기획여행|패키지.{0,10}여행|정글투어|국외인솔자"
    ),
    "product_or_premises_liability": re.compile(
        r"생산물배상|제조물책임|공작물책임|광고사업.{0,20}계약"
    ),
    "surety_or_employee_fraud": re.compile(
        r"신원보증|신원보증인|보증책임|업무상횡령"
    ),
    "fire_property_damage": re.compile(
        r"화재사고|화재로.{0,30}(?:연소|소실)|방화시설|실화책임"
    ),
    "workplace_or_leisure_accident": re.compile(
        r"공사현장|건설현장|작업\s*중.{0,30}(?:추락|붕괴|감전)|"
        r"스키장|놀이기구|골프장|승마.{0,20}사고|"
        r"크레인.{0,40}(?:조작|아웃트리거|인양대)"
    ),
    "pedestrian_facility_accident": re.compile(
        r"자동차\s*진입억제용\s*말뚝|볼라드|보도블록.{0,30}(?:걸려|넘어)"
    ),
    "weather_traffic_disruption": re.compile(
        r"폭설.{0,80}(?:고립|교통정체)|고속도로.{0,40}고립"
    ),
    "civil_procedure_only": re.compile(
        r"재심대상판결|재심사유|민사소송법.{0,30}재판이 변경|"
        r"손해배상청구권.{0,30}소멸시효|시효(?:가|의)?\s*(?:중단|진행)|부대상고"
    ),
    "pension_or_benefit_offset": re.compile(
        r"퇴직연금|직무상유족연금|사학연금|공무원연금.{0,30}공제"
    ),
}

# Recall-first corpus policy: exclusion requires an unmistakable non-road case type
# in the case title itself. Broader indicators are retained as review metadata.
DEFINITE_NON_TRAFFIC_TITLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "employment_status_case": re.compile(
        r"근로자지위|근로자파견|직접고용|부당해고|해고무효"
    ),
    "medical_malpractice_case": re.compile(
        r"손해배상\(의\)|의료과오|진료과오"
    ),
    "defamation_case": re.compile(r"명예훼손|출판.{0,10}금지"),
    "corporate_governance_case": re.compile(r"주주지위|주주총회"),
    "school_safety_benefit_case": re.compile(r"공제급여|학교안전"),
    "vehicle_service_fee_case": re.compile(r"용역대금"),
    "family_driver_coverage_case": re.compile(r"가족운전자.{0,15}(?:한정|특약)"),
}


@dataclass(frozen=True)
class RagEligibilityResult:
    status: str
    reasons: list[str]
    review_flags: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = normalize_text(row.get(key))
        if value:
            return value
    return ""


def _snippet(text: str, start: int, end: int, radius: int = 140) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].strip()


def _unique_limited(values: list[str], limit: int = MAX_EVIDENCE_SNIPPETS) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]


def find_traffic_snippets(text: str, near_window: int = 140) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    snippets = [
        _snippet(normalized, match.start(), match.end())
        for match in DIRECT_TRAFFIC_PATTERN.finditer(normalized)
    ]
    actors = list(TRAFFIC_ACTOR_PATTERN.finditer(normalized))
    events = list(TRAFFIC_EVENT_PATTERN.finditer(normalized))
    for actor in actors:
        for event in events:
            if abs(actor.start() - event.start()) > near_window:
                continue
            start = min(actor.start(), event.start())
            end = max(actor.end(), event.end())
            snippets.append(_snippet(normalized, start, end))
            break
    return _unique_limited(snippets)


def find_accident_fact_snippets(text: str, near_window: int = 140) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    snippets: list[str] = []
    actors = list(TRAFFIC_ACTOR_PATTERN.finditer(normalized))
    mechanics = list(ACCIDENT_MECHANICS_PATTERN.finditer(normalized))
    for actor in actors:
        for event in mechanics:
            if abs(actor.start() - event.start()) > near_window:
                continue
            start = min(actor.start(), event.start())
            end = max(actor.end(), event.end())
            snippets.append(_snippet(normalized, start, end))
            break
    return _unique_limited(snippets)


def find_fault_ratio_evidence(text: str) -> tuple[list[str], list[str]]:
    normalized = normalize_text(text)
    if not normalized:
        return [], []

    valid: list[str] = []
    noise: list[str] = []

    for match in EXPLICIT_FAULT_PATTERN.finditer(normalized):
        context = _snippet(normalized, match.start(), match.end(), radius=180)
        if RATIO_NOISE_PATTERN.search(context) and not re.search(
            r"과실비율|과실상계|책임비율|책임분담비율|쌍방과실", context
        ):
            noise.append(context)
        else:
            valid.append(context)

    for match in RATIO_PATTERN.finditer(normalized):
        context = _snippet(normalized, match.start(), match.end(), radius=180)
        has_fault_decision = bool(FAULT_DECISION_PATTERN.search(context))
        has_party = bool(FAULT_PARTY_PATTERN.search(context))
        is_noise = bool(RATIO_NOISE_PATTERN.search(context))
        has_direct_fault = bool(
            re.search(
                r"과실\s*비율|과실상계|책임\s*비율|책임분담비율|쌍방과실",
                context,
            )
        )

        if (
            has_fault_decision
            and (has_party or has_direct_fault)
            and (not is_noise or has_direct_fault)
        ):
            valid.append(context)
        elif is_noise:
            noise.append(context)

    return _unique_limited(valid), _unique_limited(noise)


def find_traffic_linked_fault_ratio_evidence(
    text: str,
    fault_ratio_snippets: list[str],
) -> list[str]:
    normalized = normalize_text(text)
    linked: list[str] = []
    for snippet in fault_ratio_snippets:
        search_from = 0
        while True:
            start = normalized.find(snippet, search_from)
            if start < 0:
                break
            context = _snippet(
                normalized,
                start,
                start + len(snippet),
                radius=FAULT_TRAFFIC_LINK_RADIUS,
            )
            if DIRECT_TRAFFIC_PATTERN.search(
                context
            ) or find_accident_fact_snippets(context):
                linked.append(snippet)
                break
            search_from = start + max(1, len(snippet))
    return _unique_limited(linked)


def find_non_traffic_indicators(text: str) -> list[str]:
    normalized = normalize_text(text)
    indicators: list[str] = []
    for label, pattern in NON_TRAFFIC_MAIN_PATTERNS.items():
        if pattern.search(normalized):
            indicators.append(label)
    return indicators


def find_definite_non_traffic_title_indicators(case_name: str) -> list[str]:
    normalized = normalize_text(case_name)
    return [
        label
        for label, pattern in DEFINITE_NON_TRAFFIC_TITLE_PATTERNS.items()
        if pattern.search(normalized)
    ]


def assess_rag_eligibility(
    row: dict[str, Any],
    fault_ratio_label: str,
) -> RagEligibilityResult:
    if fault_ratio_label != "fault_ratio_confirmed":
        return RagEligibilityResult(
            status=RAG_EXCLUDED,
            reasons=["fault_ratio_evidence_not_confirmed"],
            review_flags=[],
            evidence={},
        )

    case_name = first_text(row, "사건명", "case_name")
    holding = first_text(row, "판시사항", "holding")
    summary = first_text(row, "판결요지", "summary")
    reason = first_text(row, "이유", "main_text", "판례내용")

    core_text = " ".join(value for value in [case_name, holding, summary] if value)
    intro_text = " ".join(
        value for value in [core_text, reason[:HIGH_SIGNAL_REASON_CHARS]] if value
    )
    full_text = " ".join(value for value in [core_text, reason] if value)

    core_traffic = find_traffic_snippets(core_text)
    intro_traffic = find_traffic_snippets(intro_text)
    full_traffic = find_traffic_snippets(full_text)
    core_accident_facts = find_accident_fact_snippets(core_text)
    intro_accident_facts = find_accident_fact_snippets(intro_text)
    full_accident_facts = find_accident_fact_snippets(full_text)
    fault_evidence, ratio_noise = find_fault_ratio_evidence(full_text)
    linked_fault_evidence = find_traffic_linked_fault_ratio_evidence(
        full_text,
        fault_evidence,
    )
    non_traffic_indicators = find_non_traffic_indicators(
        " ".join(
            value
            for value in [core_text, reason[:HIGH_SIGNAL_REASON_CHARS], *fault_evidence]
            if value
        )
    )
    definite_non_traffic_title_indicators = (
        find_definite_non_traffic_title_indicators(case_name)
    )

    strong_main_traffic = bool(
        core_accident_facts
        or intro_accident_facts
        or DIRECT_TRAFFIC_FAULT_TITLE_PATTERN.search(case_name)
    )
    any_traffic = bool(full_traffic)
    has_fault_evidence = bool(fault_evidence)
    has_linked_fault_evidence = bool(linked_fault_evidence)

    evidence = {
        "traffic_core_snippets": core_traffic,
        "traffic_intro_snippets": intro_traffic,
        "traffic_full_snippets": full_traffic,
        "accident_fact_core_snippets": core_accident_facts,
        "accident_fact_intro_snippets": intro_accident_facts,
        "accident_fact_full_snippets": full_accident_facts,
        "fault_ratio_snippets": fault_evidence,
        "traffic_linked_fault_ratio_snippets": linked_fault_evidence,
        "ratio_noise_snippets": ratio_noise,
        "non_traffic_indicators": non_traffic_indicators,
        "definite_non_traffic_title_indicators": (
            definite_non_traffic_title_indicators
        ),
    }

    if definite_non_traffic_title_indicators:
        return RagEligibilityResult(
            status=RAG_EXCLUDED,
            reasons=[
                "explicit_non_traffic_case_title",
                *definite_non_traffic_title_indicators,
            ],
            review_flags=[],
            evidence=evidence,
        )

    review_flags: list[str] = []
    review_flags.extend(
        f"suspected_non_traffic_issue:{label}"
        for label in non_traffic_indicators
    )
    if not strong_main_traffic:
        review_flags.append("traffic_evidence_outside_high_signal_fields")
    if not any_traffic:
        review_flags.append("weak_or_missing_road_traffic_expression")
    if not has_fault_evidence:
        review_flags.append("fault_ratio_evidence_requires_review")
    elif not has_linked_fault_evidence:
        review_flags.append("fault_ratio_not_linked_to_traffic_expression")
    if ratio_noise:
        review_flags.append("contains_ratio_noise")
    review_flags = list(dict.fromkeys(review_flags))

    if strong_main_traffic and has_linked_fault_evidence:
        return RagEligibilityResult(
            status=RAG_READY,
            reasons=["verified_traffic_main_issue", "verified_fault_ratio_evidence"],
            review_flags=review_flags,
            evidence=evidence,
        )

    return RagEligibilityResult(
        status=RAG_READY,
        reasons=["retained_by_recall_first_corpus_policy"],
        review_flags=review_flags,
        evidence=evidence,
    )
