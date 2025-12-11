import sys
from types import ModuleType

import pytest

from tests.test_metadata_single_source import (
    _install_coffea_stub,
    _install_numpy_stub,
    _install_topcoffea_stub,
)

_install_topcoffea_stub()
_install_numpy_stub()
_install_coffea_stub()
# Provide a minimal corrections stub so SystematicsHelper import succeeds.
topcoffea_modules = sys.modules.get("topcoffea.modules")
if topcoffea_modules and not hasattr(topcoffea_modules, "corrections"):
    corrections_mod = ModuleType("topcoffea.modules.corrections")
    topcoffea_modules.corrections = corrections_mod
    sys.modules["topcoffea.modules.corrections"] = corrections_mod

from analysis.topeft_run2.systematics_validation import (  # noqa: E402
    validate_histogram_plan_systematics,
)
from topeft.modules.systematics import SystematicsHelper  # noqa: E402


def _nominal_metadata():
    return {
        "systematics": {
            "nominal": {
                "type": "nominal",
                "applies_to": ["all"],
                "variations": [{"value": "nominal"}],
            }
        }
    }


def _metadata_with_weight_systematic():
    metadata = _nominal_metadata()
    metadata["systematics"].update(
        {
            "lepton_sf": {
                "type": "weight",
                "applies_to": ["mc"],
                "variations": [
                    {"value": "leptonSFUp", "direction": "Up"},
                    {"value": "leptonSFDown", "direction": "Down"},
                ],
            }
        }
    )
    return metadata


def _metadata_with_object_systematic():
    metadata = _nominal_metadata()
    metadata["systematics"].update(
        {
            "jer": {
                "type": "object",
                "applies_to": ["mc"],
                "year_dependent": False,
                "directions": ["Up", "Down"],
                "template": "JER{direction}",
            }
        }
    )
    return metadata


class _DummyTask:
    def __init__(self, variations):
        self.variations = variations


class _DummyVariation:
    def __init__(self, name, base):
        self.name = name
        self.base = base


def test_nominal_run_skips_variations_when_disabled():
    helper = SystematicsHelper(_metadata_with_weight_systematic(), sample_years=["2022"])
    sample = {"isData": False, "year": "2022"}

    variations = helper.variations_for_sample(sample, include_systematics=False)
    assert [var.name for var in variations] == ["nominal"]


def test_systematic_enabled_in_metadata_is_scheduled():
    helper = SystematicsHelper(_metadata_with_weight_systematic(), sample_years=["2022"])
    sample = {"isData": False, "year": "2022"}

    variation_names = {var.name for var in helper.variations_for_sample(sample, include_systematics=True)}
    assert variation_names == {"nominal", "leptonSFUp", "leptonSFDown"}


def test_missing_metadata_variation_triggers_validation_error():
    metadata = _nominal_metadata()
    fake_variations = [_DummyVariation("FakeUp", "fake")]
    tasks = [_DummyTask(fake_variations)]

    with pytest.raises(ValueError, match="no metadata variations are expected"):
        validate_histogram_plan_systematics(
            metadata=metadata,
            tasks=tasks,
            do_systs=True,
            has_mc_samples=True,
            has_data_samples=False,
            tau_analysis=False,
            metadata_source="inline",
        )


def test_metadata_variations_pass_validation():
    metadata = _metadata_with_object_systematic()
    helper = SystematicsHelper(metadata, sample_years=["2022"])
    sample = {"isData": False, "year": "2022"}
    variations = helper.variations_for_sample(sample, include_systematics=True)
    tasks = [_DummyTask(variations)]

    validate_histogram_plan_systematics(
        metadata=metadata,
        tasks=tasks,
        do_systs=True,
        has_mc_samples=True,
        has_data_samples=False,
        tau_analysis=False,
        metadata_source="inline",
    )


def test_variation_planning_is_deterministic():
    metadata = _metadata_with_weight_systematic()
    sample = {"isData": False, "year": "2022"}

    helper_a = SystematicsHelper(metadata, sample_years=["2022"])
    helper_b = SystematicsHelper(metadata, sample_years=["2022"])

    grouped_a = helper_a.grouped_variations_for_sample(sample, include_systematics=True)
    grouped_b = helper_b.grouped_variations_for_sample(sample, include_systematics=True)

    names_a = [var.name for vars_in_group in grouped_a.values() for var in vars_in_group]
    names_b = [var.name for vars_in_group in grouped_b.values() for var in vars_in_group]

    assert names_a == names_b


def test_data_samples_never_get_mc_systematics():
    """MC-only systematics must never be scheduled for data samples."""
    metadata = _metadata_with_weight_systematic()
    helper = SystematicsHelper(metadata, sample_years=["2022"])
    data_sample = {"isData": True, "year": "2022"}

    variation_names = {var.name for var in helper.variations_for_sample(data_sample, include_systematics=True)}
    assert variation_names == {"nominal"}
