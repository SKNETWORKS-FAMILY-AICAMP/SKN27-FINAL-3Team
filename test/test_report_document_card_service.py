from app.services.report_document_card_service import build_report_document_cards


def test_official_report_builds_three_copyable_document_cards() -> None:
    cards = build_report_document_cards(
        document_variant="fine_notice",
        sections=[
            {"title": "1. 이의신청 취지", "body": "처분 재검토를 요청합니다."},
            {"title": "2. 사실관계", "body": "고지서의 일시와 장소를 확인했습니다."},
            {"title": "4. 관련 법령 및 근거", "body": "관련 조문을 검토합니다."},
            {"title": "5. 첨부자료", "body": "고지서 사본"},
        ],
        document_readiness={"ready_for_docx": True},
        appeal_gate={"blocked": False},
    )

    assert [card["type"] for card in cards] == [
        "objection_draft",
        "fact_summary",
        "insurance_submission",
    ]
    assert all(card["status"] == "ready" for card in cards)
    assert all(card["copy_text"] for card in cards)


def test_blocked_appeal_keeps_reviewable_copy_draft_but_marks_it_partial() -> None:
    cards = build_report_document_cards(
        document_variant="fine_notice",
        sections=[{"title": "1. 이의신청 취지", "body": "처분 재검토를 요청합니다."}],
        document_readiness={"ready_for_docx": True},
        appeal_gate={"blocked": True, "reason": "기한이 지났습니다."},
    )

    objection = cards[0]

    assert objection["type"] == "objection_draft"
    assert objection["status"] == "partial"
    assert "처분 재검토를 요청합니다." in objection["copy_text"]
    assert "기한이 지났습니다." in objection["notice"]
    assert "다운로드" in objection["notice"]


def test_cards_drop_private_section_keys_and_keep_partial_reports_useful() -> None:
    cards = build_report_document_cards(
        document_variant="general",
        sections=[
            {
                "title": "사실관계",
                "body": "공개 가능한 사실관계입니다.",
                "storage_uri": "s3://private/report.json",
                "attachment_id": "att_private",
            }
        ],
        document_readiness={},
        appeal_gate={},
    )

    assert cards[0]["status"] == "unavailable"
    assert cards[1]["status"] == "ready"
    assert cards[1]["sections"] == [
        {
            "title": "사실관계",
            "body": "공개 가능한 사실관계입니다.",
            "items": [],
        }
    ]
    assert "storage_uri" not in repr(cards)
    assert "attachment_id" not in repr(cards)
