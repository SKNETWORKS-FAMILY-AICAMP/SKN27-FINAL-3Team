from app.services.law_ground_contract import (
    LAW_RETRIEVAL_CONTRACT_VERSION,
    normalize_law_evidence,
    normalize_law_structured_result,
)


def test_failed_retrieval_removes_preexisting_source_backed_law_matches() -> None:
    structured = normalize_law_structured_result(
        {
            "matched_laws": [
                {
                    "law_name": "Road Traffic Act",
                    "article": "Article 5",
                    "source_reference": "law:road-traffic:5",
                }
            ],
            "retrieval": {
                "backend": "postgres_pgvector",
                "status": "failed",
            },
        }
    )

    assert structured["matched_laws"] == []
    assert structured["retrieval"] == {
        "backend": "postgres_pgvector",
        "status": "failed",
        "attempted_backends": ["postgres_pgvector"],
        "contract_version": LAW_RETRIEVAL_CONTRACT_VERSION,
    }


def test_legacy_source_alias_is_accepted_only_at_the_contract_boundary() -> None:
    structured = normalize_law_structured_result(
        {
            "matched_laws": [
                {
                    "law_name": "Road Traffic Act",
                    "article": "Article 5",
                    "summary": "Signal compliance",
                    "source_ref": "law:road-traffic:5",
                }
            ],
            "retrieval": {"backend": "postgres_pgvector", "status": "ready"},
        }
    )
    evidence = normalize_law_evidence(
        [{"source_type": "law", "source_ref": "law:road-traffic:5"}]
    )

    assert structured["matched_laws"][0]["source_reference"] == "law:road-traffic:5"
    assert "source_ref" not in structured["matched_laws"][0]
    assert structured["retrieval"] == {
        "backend": "postgres_pgvector",
        "status": "ready",
        "attempted_backends": ["postgres_pgvector"],
        "contract_version": LAW_RETRIEVAL_CONTRACT_VERSION,
    }
    assert evidence == [
        {"source_type": "law", "source_reference": "law:road-traffic:5"}
    ]


def test_unproven_law_hits_are_removed_and_ready_status_is_closed_to_empty() -> None:
    structured = normalize_law_structured_result(
        {
            "law_provisions": [
                {
                    "source_name": "Unproven law",
                    "provision_text": "No source reference is available.",
                }
            ],
            "matched_laws": [{"law_name": "Also unproven"}],
            "retrieval": {"status": "ready", "attempted_backends": []},
        }
    )

    assert structured["law_provisions"] == []
    assert structured["matched_laws"] == []
    assert structured["retrieval"]["status"] == "empty"
    assert "backend" in structured["retrieval"]
    assert structured["retrieval"]["backend"] is None
    assert structured["retrieval"]["contract_version"] == LAW_RETRIEVAL_CONTRACT_VERSION
    assert structured["retrieval_quality"] == "unavailable"
    assert normalize_law_evidence([{"source_type": "law", "title": "No source"}]) == []


def test_internal_retrieval_metadata_is_lifted_out_of_law_provisions() -> None:
    structured = normalize_law_structured_result(
        {
            "law_provisions": [
                {
                    "source_ref": "law:road-traffic:32",
                    "source_name": "Road Traffic Act",
                    "article_no": "Article 32",
                    "provision_text": "Stopping restrictions.",
                    "_retrieval": {
                        "backend": "postgres_pgvector",
                        "status": "ready",
                    },
                }
            ]
        }
    )

    assert structured["retrieval"]["backend"] == "postgres_pgvector"
    assert structured["law_provisions"][0]["source_reference"] == "law:road-traffic:32"
    assert "source_ref" not in structured["law_provisions"][0]
    assert "_retrieval" not in structured["law_provisions"][0]
