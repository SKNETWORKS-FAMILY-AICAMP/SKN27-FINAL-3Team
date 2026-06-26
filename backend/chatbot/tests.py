from django.test import Client, TestCase


class ChatbotMockApiTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_check_returns_scenarios(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            {item["scenario"] for item in body["available_scenarios"]},
            {"fine_notice", "fault_ratio"},
        )

    def test_submit_fine_notice_message(self):
        session_response = self.client.post(
            "/api/mock/chat/sessions/",
            data={"user_id": "usr_mock"},
            content_type="application/json",
        )
        session_id = session_response.json()["session_id"]

        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": session_id,
                "user_text": "이 고지서로 이의신청서를 만들 수 있을까요?",
                "mock_scenario": "fine_notice",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mock_scenario"], "fine_notice")
        self.assertEqual(body["routing_intent"], "objection_request")
        self.assertIn("report_links", body)

    def test_submit_fault_ratio_message(self):
        response = self.client.post(
            "/api/mock/chat/messages/",
            data={
                "session_id": "ses_fault",
                "user_text": "신호 없는 교차로 사고 과실비율을 확인하고 싶어요.",
                "mock_scenario": "fault_ratio",
                "mock_status": "success",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["routing_intent"], "fault_ratio")
        self.assertIn("structured_result", body)
        self.assertIn("similar_cases", body["structured_result"])

    def test_report_download_returns_attachment(self):
        response = self.client.get("/api/mock/reports/rep_mock/download/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

