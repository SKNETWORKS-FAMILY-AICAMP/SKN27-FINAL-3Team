import unittest
from unittest.mock import patch

from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.graph import graph
from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.constants import (
    STATUS_SUCCESS,
    STATUS_PARTIAL,
    STATUS_FAILED,
    FAILURE_REASON_UNSUPPORTED_FILE_TYPE,
)

SUCCESS_MOCK_RESPONSE = {
    "document_name": "교통사고사실확인원",
    "detected_labels": ["발생일시", "발생장소", "사고유형", "사고내용", "피해내용"],
    "issuer_labels": ["경찰서장", "발급번호"],
    "page_info": {"page_1_processed": True, "page_2_exists": False},
    "extracted_fields": {
        "receipt_number": "1234-5678",
        "issue_number": "2026-1234",
        "police_station": "서울노원경찰서",
        "accident_datetime": "2026-06-25 14:30",
        "accident_location": "서울시 노원구",
        "accident_type": {"value": "차대차", "raw_text": "차대차"},
        "accident_cause": "안전운전의무불이행",
        "damage": {
            "raw_text": "물적피해",
            "death_count": 0,
            "injury_count": 0,
            "property_damage_amount": 1000
        },
        "usage": "보험회사 제출용",
        "accident_description": "A차량(12가3456)이 B차량(010-1234-5678)을 추돌함",
    },
    "raw_text_redacted": "A차량(12가3456)이 B차량(010-1234-5678)을 추돌함. 차주 900101-1234567",
    "quality": {"ocr_confidence": 0.95, "image_quality": "readable", "warnings": []},
    "limitations": []
}

PARTIAL_MOCK_RESPONSE = {
    "document_name": "교통사고사실확인원",
    "detected_labels": ["발생일시", "발생장소", "사고유형"],
    "issuer_labels": ["경찰서장", "발급번호"],
    "page_info": {"page_1_processed": True, "page_2_exists": False},
    "extracted_fields": {
        "accident_datetime": "2026-06-25 14:30",
        "accident_location": "서울시 노원구",
        "accident_type": {"value": "차대차", "raw_text": "차대차"},
        "accident_description": None,  # Critical field missing
    },
    "raw_text_redacted": "알 수 없음",
    "quality": {"ocr_confidence": 0.9, "image_quality": "readable", "warnings": []},
    "limitations": []
}

class TestTrafficAccidentConfirmationOCRMockGraph(unittest.TestCase):
    
    @patch("etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.agent._call_gpt_vision")
    def test_success_flow(self, mock_call):
        mock_call.return_value = SUCCESS_MOCK_RESPONSE
        
        state = {
            "document_image": "ZmFrZSBkYXRh",
            "document_mime_type": "image/jpeg"
        }
        
        result = graph.invoke(state)
        
        self.assertEqual(result["ocr_status"], STATUS_SUCCESS)
        
        # 1. document_image 제거 확인
        self.assertIsNone(result.get("document_image"), "document_image should be removed")
        
        # 2. agent_results 봉투 확인
        self.assertIn("traffic_accident_confirmation_ocr", result["agent_results"])
        self.assertEqual(result["agent_results"]["traffic_accident_confirmation_ocr"]["status"], STATUS_SUCCESS)
        
        # 3. missing_fields 빈 배열 확인
        self.assertEqual(result["missing_fields"], [])
        
        # 4. 개인정보 마스킹 확인
        masked_desc = result["extracted_fields"]["accident_description"]
        masked_raw = result["raw_text_redacted"]
        self.assertNotIn("12가3456", masked_desc)
        self.assertNotIn("010-1234-5678", masked_desc)
        self.assertNotIn("900101-1234567", masked_raw)
        self.assertIn("[MASKED]", masked_desc)
        self.assertTrue(result["privacy"]["masking_applied"])

    @patch("etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.agent._call_gpt_vision")
    def test_partial_flow(self, mock_call):
        mock_call.return_value = PARTIAL_MOCK_RESPONSE
        
        state = {
            "document_image": "ZmFrZSBkYXRh",
            "document_mime_type": "image/jpeg"
        }
        
        result = graph.invoke(state)
        
        self.assertEqual(result["ocr_status"], STATUS_PARTIAL)
        
        # 1. missing_fields 누락 필드 포함 확인
        self.assertIn("accident_description", result["missing_fields"])
        
        # 2. document_image 제거 및 envelope 상태 확인
        self.assertIsNone(result.get("document_image"))
        self.assertEqual(result["agent_results"]["traffic_accident_confirmation_ocr"]["status"], STATUS_PARTIAL)

    def test_failed_flow_unsupported_mime(self):
        state = {
            "document_image": "ZmFrZSBkYXRh",
            "document_mime_type": "application/pdf"
        }
        
        result = graph.invoke(state)
        
        self.assertEqual(result["ocr_status"], STATUS_FAILED)
        self.assertEqual(result["failure_reason"], FAILURE_REASON_UNSUPPORTED_FILE_TYPE)
        self.assertIsNone(result.get("document_image"))
        self.assertEqual(result["agent_results"]["traffic_accident_confirmation_ocr"]["status"], STATUS_FAILED)

if __name__ == "__main__":
    unittest.main()
