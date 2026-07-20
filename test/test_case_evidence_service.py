from __future__ import annotations

from app.services.case_evidence_service import build_case_evidence


def test_case_evidence_separates_material_facts_claims_and_unknowns() -> None:
    evidence = build_case_evidence(
        facts={
            "road_layout": "four_way_intersection",
            "vehicle_actions": "ego_straight_other_left_turn",
            "signal_priority": "ego_green",
        },
        sources=[
            {
                "field": "road_layout",
                "source_type": "official_document",
                "source_ref": "att_police_001",
            },
            {
                "field": "vehicle_actions",
                "source_type": "user_confirmation",
                "source_ref": "case-form",
            },
            {
                "field": "signal_priority",
                "source_type": "user_statement",
                "source_ref": "msg_001",
            },
        ],
        conflicts=[
            {
                "field": "vehicle_actions",
                "values": ["straight", "left_turn"],
            }
        ],
    )

    assert evidence["schema_version"] == "case_evidence.v1"
    assert evidence["facts"] == {
        "road_layout": {
            "value": "four_way_intersection",
            "evidence_source": {
                "field": "road_layout",
                "source_type": "official_document",
                "source_ref": "att_police_001",
            },
        }
    }
    assert evidence["claims"]["signal_priority"]["value"] == "ego_green"
    assert "vehicle_actions" not in evidence["facts"]
    assert "vehicle_actions" not in evidence["claims"]
    assert evidence["evidence_source"]["road_layout"]["source_type"] == "official_document"
    assert evidence["unknowns"] == [
        {
            "field": "collision_location",
            "reason": "missing_fact",
            "evidence_source": None,
        },
        {
            "field": "vehicle_actions",
            "reason": "conflicting_claim",
            "evidence_source": {
                "field": "vehicle_actions",
                "source_type": "user_confirmation",
                "source_ref": "case-form",
            },
        },
    ]


def test_case_evidence_treats_user_confirmation_as_claim_not_material_fact() -> None:
    evidence = build_case_evidence(
        facts={"road_layout": "four_way_intersection"},
        sources=[{"source_type": "user_confirmation", "source_ref": "case-form"}],
        conflicts=[],
    )

    assert evidence["facts"] == {}
    assert evidence["claims"] == {
        "road_layout": {
            "value": "four_way_intersection",
            "evidence_source": {
                "source_type": "user_confirmation",
                "source_ref": "case-form",
            },
        }
    }


def test_case_evidence_requires_a_bound_material_source_reference_when_provided() -> None:
    evidence = build_case_evidence(
        facts={"road_layout": "four_way_intersection"},
        sources=[{"source_type": "official_document", "source_ref": "att_unbound"}],
        conflicts=[],
        material_source_refs={"att_ready"},
    )

    assert evidence["facts"] == {}
    assert evidence["claims"]["road_layout"]["evidence_source"]["source_ref"] == "att_unbound"
