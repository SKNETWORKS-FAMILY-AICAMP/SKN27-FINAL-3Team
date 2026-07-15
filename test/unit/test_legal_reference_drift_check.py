from __future__ import annotations

from unittest.mock import patch

from etl.legal.reference_drift_check import check_reference_drift, main


def _fake_pinned_references():
    return [
        ("도로교통법 시행규칙", "폴백 원문 A"),
        ("질서위반행위규제법", "폴백 원문 B"),
    ]


def _embed_stub(text: str, **_kwargs) -> list[float]:
    """텍스트 자체를 벡터로 취급 — 같은 문자열이면 코사인 유사도 1.0, 다르면
    구성한 벡터 값에 따라 낮게 나오도록 결정론적으로 매핑한다."""
    vectors = {
        "폴백 원문 A": [1.0, 0.0],
        "도로교통법 시행규칙 폴백 원문 A": [1.0, 0.0],       # RAG 매칭 원문 == 폴백과 동일(정상)
        "도로교통법 시행규칙 살짝 다른 표현": [0.99, 0.14107],  # 소폭 개정(정상, 여전히 유사)
        "도로교통법 시행규칙 완전히 다른 조문 내용": [0.0, 1.0],  # 재편 의심(드리프트)
        "폴백 원문 B": [1.0, 0.0],
        "질서위반행위규제법 폴백 원문 B": [1.0, 0.0],
    }
    if text not in vectors:
        raise AssertionError(f"예상치 못한 임베딩 호출: {text!r}")
    return vectors[text]


class TestCheckReferenceDrift:
    def test_RAG매칭원문이_폴백과_동일하면_ok(self):
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES",
            [("도로교통법 시행규칙", "폴백 원문 A")],
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match",
            return_value={"provision_text": "폴백 원문 A"},
        ), patch(
            "etl.legal.reference_drift_check.embed_query_with_openai", side_effect=_embed_stub,
        ):
            results = check_reference_drift()

        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].similarity == 1.0

    def test_소폭_개정은_ok_유지(self):
        """조문 문구가 살짝만 바뀐 정상적인 법 개정은 유사도가 임계값 이상으로
        유지돼야 한다 — 드리프트 경고는 "완전히 다른 내용"일 때만 나와야 한다."""
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES",
            [("도로교통법 시행규칙", "폴백 원문 A")],
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match",
            return_value={"provision_text": "살짝 다른 표현"},
        ), patch(
            "etl.legal.reference_drift_check.embed_query_with_openai", side_effect=_embed_stub,
        ):
            results = check_reference_drift()

        assert results[0].status == "ok"

    def test_완전히_다른_내용이면_drifted(self):
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES",
            [("도로교통법 시행규칙", "폴백 원문 A")],
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match",
            return_value={"provision_text": "완전히 다른 조문 내용"},
        ), patch(
            "etl.legal.reference_drift_check.embed_query_with_openai", side_effect=_embed_stub,
        ):
            results = check_reference_drift()

        assert results[0].status == "drifted"
        assert results[0].similarity < 0.75
        assert "재검토" in results[0].detail

    def test_신뢰도_미달로_매칭없으면_fallback(self):
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES",
            [("도로교통법 시행규칙", "폴백 원문 A")],
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match", return_value=None,
        ), patch(
            "etl.legal.reference_drift_check.embed_query_with_openai",
        ) as mock_embed:
            results = check_reference_drift()

        assert results[0].status == "fallback"
        mock_embed.assert_not_called()  # 매칭 자체가 없으면 임베딩 비용을 쓸 필요 없다

    def test_RAG조회_예외시_error(self):
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES",
            [("도로교통법 시행규칙", "폴백 원문 A")],
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match",
            side_effect=ConnectionError("DB 연결 실패"),
        ):
            results = check_reference_drift()

        assert results[0].status == "error"

    def test_여러_조문_섞여있으면_전부_개별_판정(self):
        with patch(
            "etl.legal.reference_drift_check.PINNED_REFERENCES", _fake_pinned_references(),
        ), patch(
            "etl.legal.reference_drift_check._resolve_provision_match",
            side_effect=[
                {"provision_text": "폴백 원문 A"},
                {"provision_text": "폴백 원문 B"},
            ],
        ), patch(
            "etl.legal.reference_drift_check.embed_query_with_openai", side_effect=_embed_stub,
        ):
            results = check_reference_drift()

        assert [r.status for r in results] == ["ok", "ok"]


class TestMain:
    def test_문제없으면_exit_0(self, capsys):
        with patch(
            "etl.legal.reference_drift_check.check_reference_drift",
            return_value=[__import__(
                "etl.legal.reference_drift_check", fromlist=["DriftResult"]
            ).DriftResult("법", "제1조", "ok", 1.0)],
        ):
            exit_code = main()
        assert exit_code == 0
        assert "전부 정상" in capsys.readouterr().out

    def test_드리프트있으면_exit_1(self, capsys):
        from etl.legal.reference_drift_check import DriftResult

        with patch(
            "etl.legal.reference_drift_check.check_reference_drift",
            return_value=[DriftResult("법", "제1조", "drifted", 0.3, "재편 의심")],
        ):
            exit_code = main()
        assert exit_code == 1
        assert "재검토 필요" in capsys.readouterr().out

    def test_fallback상태도_재검토_필요로_집계(self, capsys):
        """fallback(신뢰도 미달로 폴백만 사용 중)은 위험한 조용한 실패는 아니지만,
        RAG가 해당 조문을 전혀 못 찾고 있다는 뜻이라 사람이 확인해야 한다."""
        from etl.legal.reference_drift_check import DriftResult

        with patch(
            "etl.legal.reference_drift_check.check_reference_drift",
            return_value=[DriftResult("법", "제1조", "fallback", None, "매칭 없음")],
        ):
            exit_code = main()
        assert exit_code == 1
        assert "재검토 필요" in capsys.readouterr().out
