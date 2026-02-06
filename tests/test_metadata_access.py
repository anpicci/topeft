from __future__ import annotations

from analysis.topeft_run2 import metadata_authority
from topeft.modules import metadata_access


def _minimal_metadata(scenario_name: str, golden_path: str) -> dict[str, object]:
    scenarios = metadata_authority.load_scenarios()
    scenario_def = scenarios[scenario_name]
    groups = {name: {"categories": []} for name in scenario_def.groups}
    return {
        "channels": {"groups": groups},
        "golden_jsons": {"2017": golden_path},
    }


def test_metadata_access_inmemory_wins(tmp_path) -> None:
    scenarios = metadata_authority.load_scenarios()
    scenario_name = next(iter(scenarios))
    golden_path = str(tmp_path / "golden.json")
    metadata = _minimal_metadata(scenario_name, golden_path)

    bundle = metadata_access.load_metadata_bundle_for_processor(
        metadata=metadata,
        metadata_path="does/not/exist.yml",
        scenario_name=scenario_name,
        required_sections=("channels",),
    )

    assert bundle.metadata is metadata
    assert str(bundle.metadata_path).endswith("does/not/exist.yml")
    assert metadata_access.golden_json_for_year(bundle, "2017") == golden_path
