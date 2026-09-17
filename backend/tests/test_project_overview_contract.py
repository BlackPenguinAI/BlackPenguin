from app.modules.projects.schemas import ProjectOverviewResponse
from app.modules.projects.services import normalized_project_locations


def test_project_overview_normalizes_multiple_model_home_addresses():
    extracted = [
        {"label": "40' Villa model home", "address": "18201 Petipa Point, Conroe, TX 77302"},
        {"label": "60' Collins model home", "address": "17709 Coronation Street, Conroe, TX 77302"},
    ]

    locations = normalized_project_locations(extracted, "Fallback address")
    response = ProjectOverviewResponse(
        id="project-1",
        name="Evergreen",
        address=locations[0]["address"],
        locations=locations,
    )

    assert response.address == "18201 Petipa Point, Conroe, TX 77302"
    assert [item["label"] for item in response.locations] == [
        "40' Villa model home", "60' Collins model home",
    ]


def test_project_overview_keeps_legacy_scalar_address_compatible():
    locations = normalized_project_locations("123 Main Street", None)
    assert locations == [{"label": "Primary location", "address": "123 Main Street"}]
    assert normalized_project_locations(None, "456 Legacy Avenue")[0]["address"] == "456 Legacy Avenue"
