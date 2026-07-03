"""Demo persona catalog for pre-agent end-to-end product flows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_PERSONA_ID = "school_zone_fine_notice_parent"

PERSONA_CATALOG: dict[str, dict[str, Any]] = {
    DEFAULT_PERSONA_ID: {
        "persona": {
            "persona_id": DEFAULT_PERSONA_ID,
            "name": "정민서",
            "age": 34,
            "role": "학부모 운전자",
            "tone": "당황했지만 차분히 사실관계를 정리하려는 사용자",
            "case_type": "어린이보호구역 정차 과태료 이의제기",
            "goal": "고지서 내용을 이해하고 의견제출서 초안 작성 가능성을 확인",
        },
        "scenario": "fine_notice",
        "routing_intent": "objection_request",
        "stage": "draft_ready",
        "progress_label": "데모 페르소나 상담이 의견제출서 초안 직전까지 진행되었습니다.",
        "sample_user_text": "어린이보호구역 정차 과태료 고지서를 받았고 아이가 아파 잠깐 정차했습니다.",
        "case_snapshot": {
            "notice_type": "어린이보호구역 정차 과태료",
            "notice_amount": "120,000원",
            "notice_received_at": "2026-06-28",
            "incident_at": "2026-06-24 15:10",
            "location": "초등학교 후문 앞 편도 1차로",
            "claimed_fact": "차량이 약 4분간 정차한 것으로 단속됨",
            "user_context": "동승한 아이가 갑자기 구토해 비상등을 켜고 가장자리로 정차했다고 주장",
        },
        "turns": [
            {
                "role": "persona_user",
                "speaker": "정민서",
                "message": "어린이보호구역 정차 과태료 12만원 고지서를 받았어요. 아이가 갑자기 토해서 잠깐 세운 건데 이의제기가 가능할까요?",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "먼저 제출기한과 정차 사유를 나눠서 보겠습니다. 지금 단계에서는 단속 자체를 부정하기보다 긴급 정차 사유와 정차 시간이 쟁점입니다.",
            },
            {
                "role": "persona_user",
                "speaker": "정민서",
                "message": "고지서에는 6월 24일 오후 3시 10분, 초등학교 후문 앞이라고 되어 있고 사진은 한 장만 있어요.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "사진이 한 장이면 실제 정차 시간과 긴급 사유 입증이 중요합니다. 블랙박스 원본, 약국 영수증, 당시 통화기록을 함께 보겠습니다.",
            },
            {
                "role": "persona_user",
                "speaker": "정민서",
                "message": "블랙박스는 있고 병원은 바로 가지 않았지만 약국에서 산 영수증은 있어요. 의견제출서 초안을 만들 수 있나요?",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "초안까지는 가능합니다. 다만 처분 취소를 보장하지 않고 긴급 상황 설명과 증빙 목록을 정리하는 방식으로 작성해야 합니다.",
            },
        ],
        "cards": [
            {
                "card_type": "persona_case_summary",
                "title": "정민서 님 사건 요약",
                "status": "success",
                "summary": "초등학교 후문 앞 긴급 정차 과태료에 대해 고지서, 블랙박스, 영수증을 중심으로 검토합니다.",
                "evidence_refs": [],
            },
            {
                "card_type": "persona_next_questions",
                "title": "추가 확인 질문",
                "status": "partial",
                "summary": "블랙박스 원본 보유 여부, 정차 시작·종료 시각, 약국 영수증 시간을 확인해야 합니다.",
                "evidence_refs": [],
            },
            {
                "card_type": "persona_draft_outline",
                "title": "의견제출서 초안 방향",
                "status": "partial",
                "summary": "긴급 정차 사유, 실제 정차 시간, 제출 증빙 목록을 중심으로 초안을 구성합니다.",
                "evidence_refs": [],
            },
        ],
        "pending_questions": [
            {
                "field": "blackbox_original",
                "question": "블랙박스 원본에서 정차 시작과 출발 시각이 확인되나요?",
            },
            {
                "field": "receipt_time",
                "question": "약국 영수증 시간이 단속 시점과 가까운가요?",
            },
        ],
        "next_reply_suggestions": [
            "의견제출서에 들어갈 문장으로 정리해줘",
            "증빙자료 목록을 체크리스트로 만들어줘",
            "저장하지 않고 이번 상담만 이어갈게",
        ],
        "expected_nodes": [
            "fine_notice_analysis",
            "law_ground_search",
            "objection_report_generation",
            "agent_result_validation",
        ],
        "report_action_ready": True,
    },
    "accident_scene_photo_driver": {
        "persona": {
            "persona_id": "accident_scene_photo_driver",
            "name": "박도윤",
            "age": 41,
            "role": "출근길 운전자",
            "tone": "사고 직후 사진을 토대로 과실 쟁점을 빠르게 알고 싶은 사용자",
            "case_type": "사고 현장 사진 기반 과실비율 상담",
            "goal": "현장 사진과 설명으로 과실 쟁점, 추가 증거, 다음 행동 확인",
        },
        "scenario": "fault_ratio",
        "routing_intent": "fault_ratio",
        "stage": "analysis_ready",
        "progress_label": "사고 사진 persona 상담이 과실 쟁점 리포트 직전까지 진행되었습니다.",
        "sample_user_text": "신호 없는 교차로에서 직진 중 우측 차량과 접촉했고 현장 사진이 있습니다.",
        "case_snapshot": {
            "notice_type": "accident_scene_photo",
            "incident_at": "2026-07-01 08:25",
            "location": "신호 없는 주택가 교차로",
            "claimed_fact": "본인 차량은 직진, 상대 차량은 우측 골목에서 진입",
            "user_context": "현장 사진 3장과 보험 접수 번호를 보유",
        },
        "turns": [
            {
                "role": "persona_user",
                "speaker": "박도윤",
                "message": "신호 없는 교차로에서 직진하다가 우측에서 나온 차와 부딪혔어요. 현장 사진은 있습니다.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "사진은 시야, 정지선, 차량 위치를 보는 보조 자료입니다. 과실비율 수치를 확정하지 않고 쟁점부터 정리하겠습니다.",
            },
            {
                "role": "persona_user",
                "speaker": "박도윤",
                "message": "상대가 더 늦게 들어온 것 같은데 제 블랙박스는 없습니다. 보험 접수는 했어요.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "선진입, 감속 여부, 시야 제한, 사고 직후 사진의 각도를 함께 봐야 합니다. 보험 접수 내역과 상대 진술도 필요합니다.",
            },
        ],
        "cards": [
            {
                "card_type": "persona_case_summary",
                "title": "사고 사진 기반 쟁점",
                "status": "success",
                "summary": "신호 없는 교차로 접촉사고로 선진입, 감속, 시야 제한이 핵심 쟁점입니다.",
                "evidence_refs": [],
            },
            {
                "card_type": "persona_media_boundary",
                "title": "사진 분석 한계",
                "status": "partial",
                "summary": "실제 vision agent 전까지는 사진 metadata와 사용자 설명을 contract fixture로 대체합니다.",
                "evidence_refs": [],
            },
        ],
        "pending_questions": [
            {
                "field": "photo_angles",
                "question": "현장 사진에 정지선, 차선, 충돌 위치가 함께 보이나요?",
            }
        ],
        "next_reply_suggestions": [
            "사진 기준으로 쟁점만 정리해줘",
            "보험사에 제출할 자료 목록을 알려줘",
        ],
        "expected_nodes": [
            "vision_media_analysis",
            "text_ml_case_search",
            "law_ground_search",
            "agent_result_validation",
        ],
        "report_action_ready": True,
    },
    "blackbox_video_fault_driver": {
        "persona": {
            "persona_id": "blackbox_video_fault_driver",
            "name": "이현우",
            "age": 38,
            "role": "블랙박스 보유 운전자",
            "tone": "영상 원본은 있지만 어떤 장면이 중요한지 모르는 사용자",
            "case_type": "블랙박스 영상 기반 과실비율 상담",
            "goal": "영상 key frame 후보와 과실 쟁점을 정리",
        },
        "scenario": "fault_ratio",
        "routing_intent": "fault_ratio",
        "stage": "analysis_ready",
        "progress_label": "블랙박스 영상 persona 상담이 key frame 확인 직전까지 진행되었습니다.",
        "sample_user_text": "블랙박스 원본이 있고 상대 차량이 갑자기 차선 변경했습니다.",
        "case_snapshot": {
            "notice_type": "blackbox_video",
            "incident_at": "2026-06-30 19:40",
            "location": "왕복 6차로 간선도로",
            "claimed_fact": "상대 차량이 방향지시등 없이 차선 변경",
            "user_context": "블랙박스 원본과 보험사 접수 내역 보유",
        },
        "turns": [
            {
                "role": "persona_user",
                "speaker": "이현우",
                "message": "블랙박스 원본이 있는데 상대가 갑자기 끼어들었습니다. 과실을 볼 수 있을까요?",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "영상에서는 차선 변경 시작 시점, 방향지시등, 차간거리, 감속 여부를 key frame 후보로 분리해야 합니다.",
            },
            {
                "role": "persona_user",
                "speaker": "이현우",
                "message": "보험사에는 접수했고 상대가 제 속도가 빨랐다고 주장합니다.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "속도 단정은 피하고 영상 원본, GPS/속도 표시 여부, 사고 전후 10초 구간을 중심으로 정리하겠습니다.",
            },
        ],
        "cards": [
            {
                "card_type": "persona_case_summary",
                "title": "블랙박스 영상 쟁점",
                "status": "success",
                "summary": "차선 변경 시작 시점, 방향지시등, 차간거리, 감속 여부가 핵심입니다.",
                "evidence_refs": [],
            },
            {
                "card_type": "persona_media_boundary",
                "title": "영상 분석 한계",
                "status": "partial",
                "summary": "실제 video/vision agent 연결 전까지 key frame 후보는 mock contract로 표시합니다.",
                "evidence_refs": [],
            },
        ],
        "pending_questions": [
            {
                "field": "video_window",
                "question": "사고 전후 10초 구간이 포함된 원본 파일이 있나요?",
            }
        ],
        "next_reply_suggestions": [
            "블랙박스에서 봐야 할 장면을 알려줘",
            "보험사 설명용으로 정리해줘",
        ],
        "expected_nodes": [
            "vision_media_analysis",
            "text_ml_case_search",
            "law_ground_search",
            "agent_result_validation",
        ],
        "report_action_ready": True,
    },
    "traffic_law_question_citizen": {
        "persona": {
            "persona_id": "traffic_law_question_citizen",
            "name": "최서연",
            "age": 29,
            "role": "법령 근거를 먼저 확인하려는 사용자",
            "tone": "판단보다 근거 조항과 적용 한계를 알고 싶어 함",
            "case_type": "교통 법령 근거 단독 질문",
            "goal": "관련 법령 후보, 적용 한계, 추가 확인 사항 확인",
        },
        "scenario": "law_question",
        "routing_intent": "law_question",
        "stage": "law_ground_ready",
        "progress_label": "법령 질문 persona 상담이 근거 후보 확인 단계까지 진행되었습니다.",
        "sample_user_text": "어린이보호구역 정차 과태료에서 긴급 정차 예외 근거가 있는지 법령만 보고 싶습니다.",
        "case_snapshot": {
            "notice_type": "law_question",
            "claimed_fact": "긴급 정차 예외 또는 의견제출 근거 확인",
            "user_context": "사건 자료 없이 법령 근거와 적용 한계를 먼저 질문",
        },
        "turns": [
            {
                "role": "persona_user",
                "speaker": "최서연",
                "message": "어린이보호구역 정차 과태료에서 긴급 정차 예외 같은 근거가 있나요?",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "법령 후보와 의견제출 절차는 안내할 수 있지만, 구체 사건의 취소 가능성은 자료 확인 전 단정하지 않겠습니다.",
            },
            {
                "role": "persona_user",
                "speaker": "최서연",
                "message": "그럼 조문 후보와 제가 더 확인해야 할 자료를 분리해서 알려주세요.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "법령 근거 후보, 적용 한계, 필요한 사실관계를 나눠 표시하겠습니다. 실제 RAG 적재 전에는 mock evidence임을 명시합니다.",
            },
        ],
        "cards": [
            {
                "card_type": "persona_law_summary",
                "title": "법령 근거 후보",
                "status": "partial",
                "summary": "도로교통법/시행령/의견제출 절차 후보를 표시하되 실제 RAG 검색 전까지 mock 근거입니다.",
                "evidence_refs": [],
            },
            {
                "card_type": "persona_next_questions",
                "title": "적용 전 확인 사항",
                "status": "partial",
                "summary": "고지서 종류, 위반 장소, 긴급 사유, 증빙자료가 있어야 사건별 적용 가능성을 검토할 수 있습니다.",
                "evidence_refs": [],
            },
        ],
        "pending_questions": [
            {
                "field": "violation_text",
                "question": "적용하려는 위반 내용이나 고지서 문구가 있나요?",
            }
        ],
        "next_reply_suggestions": [
            "근거 조항 후보만 표로 보여줘",
            "실제 사건에 적용하려면 어떤 자료가 필요한지 알려줘",
        ],
        "expected_nodes": [
            "law_ground_search",
            "agent_result_validation",
        ],
        "report_action_ready": False,
    },
    "saved_report_returning_user": {
        "persona": {
            "persona_id": "saved_report_returning_user",
            "name": "오지훈",
            "age": 45,
            "role": "저장 리포트를 다시 내려받으려는 사용자",
            "tone": "이미 상담을 마쳤고 제출 전 리포트 파일을 다시 찾는 사용자",
            "case_type": "저장 리포트 재다운로드",
            "goal": "저장된 사건, 리포트 metadata, 다운로드 권한 흐름 확인",
        },
        "scenario": "report_redownload",
        "routing_intent": "report_redownload",
        "stage": "report_download_ready",
        "progress_label": "리포트 재다운로드 persona가 저장/다운로드 경계 확인 단계까지 진행되었습니다.",
        "sample_user_text": "지난번 저장한 사고 리포트를 다시 내려받고 싶습니다.",
        "case_snapshot": {
            "notice_type": "saved_report",
            "claimed_fact": "이전 상담 리포트 재다운로드 요청",
            "user_context": "MyPage와 History에서 저장 사건을 확인한 뒤 다운로드",
        },
        "turns": [
            {
                "role": "persona_user",
                "speaker": "오지훈",
                "message": "지난번 저장한 사고 리포트를 다시 내려받고 싶습니다.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "저장된 리포트는 로그인/소유자 확인 뒤 metadata를 조회하고 다운로드 권한을 확인해야 합니다.",
            },
            {
                "role": "persona_user",
                "speaker": "오지훈",
                "message": "내 사건에서 바로 열 수 있어야 합니다.",
            },
            {
                "role": "assistant",
                "speaker": "AI 상담",
                "message": "MyPage summary, History event, Report metadata, download endpoint까지 이어지는 경계를 확인하겠습니다.",
            },
        ],
        "cards": [
            {
                "card_type": "persona_report_summary",
                "title": "저장 리포트 재다운로드",
                "status": "success",
                "summary": "리포트 metadata, 소유자 권한, 다운로드 endpoint 연결을 확인하는 persona입니다.",
                "evidence_refs": [],
            }
        ],
        "pending_questions": [],
        "next_reply_suggestions": [
            "내 사건에서 리포트를 찾아줘",
            "다운로드 권한을 확인해줘",
        ],
        "expected_nodes": [
            "agent_result_validation",
        ],
        "report_action_ready": True,
    },
}


def list_demo_personas() -> list[dict[str, Any]]:
    """Return stable persona summaries for UI/test selection."""

    return [
        {
            "persona_id": persona_id,
            "name": config["persona"]["name"],
            "role": config["persona"]["role"],
            "case_type": config["persona"]["case_type"],
            "scenario": config["scenario"],
            "routing_intent": config["routing_intent"],
            "stage": config["stage"],
            "sample_user_text": config["sample_user_text"],
            "expected_nodes": list(config["expected_nodes"]),
            "report_action_ready": bool(config.get("report_action_ready")),
        }
        for persona_id, config in PERSONA_CATALOG.items()
    ]


def get_demo_persona(persona_id: str | None) -> dict[str, Any] | None:
    """Return a deep copy so callers can safely annotate the run."""

    if not persona_id:
        return None
    config = PERSONA_CATALOG.get(str(persona_id).strip())
    return deepcopy(config) if config else None


def default_demo_persona() -> dict[str, Any]:
    return deepcopy(PERSONA_CATALOG[DEFAULT_PERSONA_ID])


def demo_persona_ids() -> set[str]:
    return set(PERSONA_CATALOG)
