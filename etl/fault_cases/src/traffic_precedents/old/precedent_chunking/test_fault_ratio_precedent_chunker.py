from __future__ import annotations

import unittest

from .fault_ratio_precedent_chunker import ChunkConfig, build_case_chunks, split_outline_sections


def sample_row() -> dict[str, object]:
    return {
        "_case_id": "case-1",
        "사건명": "구상금",
        "사건번호": "2024나1",
        "선고일자": "2024-01-01",
        "법원명": "서울중앙지방법원",
        "사건종류명": "민사",
        "판시사항": "교차로에서 자동차가 충돌한 경우의 책임",
        "판결요지": "직진 차량과 좌회전 차량의 주의의무를 판단하였다.",
        "이유": "1. 사고 경위 원고 차량은 직진하고 피고 차량은 좌회전하였다. 2. 판단 양측 과실비율을 30%와 70%로 본다.",
        "판례내용": "이 문자열은 이유가 있을 때 청킹되면 안 된다.",
        "과실비율": "30%, 70%",
        "traffic_verification_final_label": "confirmed_traffic",
        "fault_ratio_verification_final_label": "fault_ratio_confirmed",
        "source_reference": "case_db:case-1",
    }


class FaultRatioPrecedentChunkerTest(unittest.TestCase):
    def test_reason_prevents_duplicate_main_text_chunks(self) -> None:
        chunks = build_case_chunks(sample_row(), ChunkConfig(target_chars=80, max_chars=120))
        self.assertIn("reasoning", {chunk["chunk_type"] for chunk in chunks})
        self.assertNotIn("main_text_fallback", {chunk["chunk_type"] for chunk in chunks})
        self.assertFalse(any("청킹되면 안 된다" in chunk["chunk_text"] for chunk in chunks))

    def test_chunks_are_bounded_and_ids_are_stable(self) -> None:
        config = ChunkConfig(target_chars=50, max_chars=80)
        first = build_case_chunks(sample_row(), config)
        second = build_case_chunks(sample_row(), config)
        self.assertEqual([chunk["chunk_id"] for chunk in first], [chunk["chunk_id"] for chunk in second])
        self.assertTrue(all(chunk["char_count"] <= 80 for chunk in first))

    def test_embedding_text_has_context_without_classifier_terms(self) -> None:
        row = sample_row()
        row["fault_ratio_evidence_terms"] = ["분류기 전용 누출 문자열"]
        chunks = build_case_chunks(row)
        self.assertTrue(all("판례명: 구상금" in chunk["embedding_text"] for chunk in chunks))
        self.assertTrue(all("분류기 전용 누출 문자열" not in chunk["embedding_text"] for chunk in chunks))

    def test_main_text_is_used_only_as_fallback(self) -> None:
        row = sample_row()
        row["이유"] = None
        chunks = build_case_chunks(row)
        self.assertIn("main_text_fallback", {chunk["chunk_type"] for chunk in chunks})

    def test_date_is_not_treated_as_outline_heading(self) -> None:
        sections = split_outline_sections("2022. 10. 13. 선고한 판결이다. 1. 사고 경위 차량이 충돌하였다.")
        self.assertEqual(2, len(sections))
        self.assertTrue(sections[0].startswith("2022. 10. 13."))

    def test_standalone_outline_marker_is_not_emitted(self) -> None:
        row = sample_row()
        row["이유"] = "사고 경위를 판단한다. 1."
        chunks = build_case_chunks(row)
        self.assertFalse(any(chunk["chunk_text"] == "1." for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
