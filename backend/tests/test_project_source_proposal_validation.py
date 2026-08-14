from types import SimpleNamespace

from app.modules.projects.source_service import serialize_proposal


def proposal(field: str, value: str):
    return SimpleNamespace(
        id="proposal-id",
        field_key=field,
        value=value,
        evidence="Source evidence",
        confidence="high",
        status=SimpleNamespace(value="pending"),
    )


def test_short_extracted_project_proposal_exposes_actionable_validation():
    serialized = serialize_proposal(
        proposal("target_audience", "Families and individuals seeking new homes"),
    )

    assert serialized["validation"] == {
        "code": "minimum_words",
        "field": "target_audience",
        "message": "Enter at least 8 words.",
        "minimum_words": 8,
    }


def test_complete_extracted_project_proposal_is_confirmable():
    serialized = serialize_proposal(
        proposal(
            "target_audience",
            "Families seeking newly built homes with practical layouts and community amenities",
        ),
    )

    assert serialized["validation"] is None
