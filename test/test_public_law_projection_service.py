from __future__ import annotations

from app.services.public_law_projection_service import project_public_law_items


def test_public_law_projection_keeps_only_safe_verified_fields() -> None:
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법",
                    "article": "제160조",
                    "summary": "과태료 부과와 관련된 적용 조문입니다.",
                    "provision_text": "원문 전체가 여기에 있다고 가정합니다.",
                    "source_reference": "s3://private/law?sig=secret",
                    "retrieval_score": 0.91,
                }
            ]
        }
    )

    assert public == [
        {
            "law_name": "도로교통법",
            "article": "제160조",
            "summary": "과태료 부과와 관련된 적용 조문입니다.",
        }
    ]
    assert "provision_text" not in repr(public)
    assert "source_reference" not in repr(public)
    assert "s3://" not in repr(public)


def test_public_law_projection_drops_raw_provision_disguised_as_summary() -> None:
    raw_provision = "운전자는 신호 또는 지시에 따라야 한다."
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법",
                    "article": "제5조",
                    "summary": raw_provision,
                    "source_reference": "law:road-traffic:5",
                }
            ],
            "law_provisions": [
                {
                    "source_name": "도로교통법",
                    "article_no": "제5조",
                    "provision_text": raw_provision,
                    "source_reference": "law:road-traffic:5",
                }
            ],
        }
    )

    assert public == [{"law_name": "도로교통법", "article": "제5조"}]
    assert raw_provision not in repr(public)


def test_public_law_projection_omits_summary_with_private_path_or_pii() -> None:
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법",
                    "article": "제160조",
                    "summary": (
                        "내부 자료 s3://private-bucket/chunk와 "
                        "주민번호 900101-1234567을 확인하세요."
                    ),
                    "source_reference": "law:road-traffic:160",
                }
            ]
        }
    )

    assert public == [{"law_name": "도로교통법", "article": "제160조"}]
    assert "s3://" not in repr(public)
    assert "900101-1234567" not in repr(public)


def test_public_law_projection_omits_malformed_pipe_table_summary() -> None:
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법 시행령",
                    "article": "별표10",
                    "summary": "| | 3) 이륜자동차등: 6만원 |\n| | | |",
                    "source_reference": "law:verified:appendix-10",
                }
            ]
        }
    )

    assert public == [{"law_name": "도로교통법 시행령", "article": "별표10"}]
    assert "|" not in repr(public)


def test_public_law_projection_omits_unicode_box_drawing_table_summary() -> None:
    public = project_public_law_items(
        {
            "matched_laws": [
                {
                    "law_name": "도로교통법 시행령",
                    "article": "별표10",
                    "summary": "┏━━━━━━┳━━━━━━┓\n┃ 구분 ┃ 금액 ┃\n├──────┼──────┤",
                    "source_reference": "law:verified:appendix-10",
                }
            ]
        }
    )

    assert public == [{"law_name": "도로교통법 시행령", "article": "별표10"}]
    assert not any(character in repr(public) for character in "┃├┼┌┏│")
