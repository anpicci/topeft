import sys
from types import ModuleType, SimpleNamespace

import pytest

def _install_topcoffea_stub() -> None:
    if "topcoffea" in sys.modules:
        return
    modules_pkg = ModuleType("topcoffea.modules")
    paths_mod = ModuleType("topcoffea.modules.paths")
    paths_mod.topcoffea_path = lambda relative: relative
    utils_mod = ModuleType("topcoffea.modules.utils")
    utils_mod.get_hist_from_pkl = lambda *args, **kwargs: {}
    utils_mod.dump_to_pkl = lambda *args, **kwargs: None
    remote_env_mod = ModuleType("topcoffea.modules.remote_environment")
    remote_env_mod.PIP_LOCAL_TO_WATCH = {}
    remote_env_mod.get_environment = lambda **kwargs: "env.tar.gz"
    modules_pkg.paths = paths_mod
    modules_pkg.utils = utils_mod
    modules_pkg.remote_environment = remote_env_mod
    modules_pkg.dynamic_data_reduction = ModuleType("topcoffea.modules.dynamic_data_reduction")

    topcoffea_stub = ModuleType("topcoffea")
    topcoffea_stub.modules = modules_pkg
    topcoffea_stub.__path__ = []

    sys.modules["topcoffea"] = topcoffea_stub
    sys.modules["topcoffea.modules"] = modules_pkg
    sys.modules["topcoffea.modules.paths"] = paths_mod
    sys.modules["topcoffea.modules.utils"] = utils_mod
    sys.modules["topcoffea.modules.remote_environment"] = remote_env_mod
    sys.modules["topcoffea.modules.dynamic_data_reduction"] = modules_pkg.dynamic_data_reduction


_install_topcoffea_stub()

from analysis.topeft_run2 import systematics_validation as validation


def _build_plan_with_variations(variations):
    return [SimpleNamespace(variations=variations)]


def test_metadata_non_nominal_bases_detects_entries():
    metadata = {
        "systematics": {
            "nominal": {"applies_to": ["all"]},
            "jer": {"applies_to": ["mc"]},
            "tes": {"applies_to": ["mc"], "tau_only": True},
        }
    }
    bases = validation.metadata_non_nominal_bases(metadata)
    assert bases == {"jer", "tes"}


def test_validate_systematics_errors_when_missing_expected_variations():
    metadata = {
        "systematics": {
            "nominal": {"applies_to": ["all"]},
            "jer": {"applies_to": ["mc"]},
        }
    }
    plan = _build_plan_with_variations(tuple())
    with pytest.raises(ValueError):
        validation.validate_histogram_plan_systematics(
            metadata=metadata,
            tasks=plan,
            do_systs=True,
            has_mc_samples=True,
            has_data_samples=False,
            tau_analysis=False,
            metadata_source="meta.yml",
        )


def test_validate_systematics_accepts_matching_variations():
    metadata = {
        "systematics": {
            "nominal": {"applies_to": ["all"]},
            "jer": {"applies_to": ["mc"]},
        }
    }
    variations = (
        SimpleNamespace(name="jerUp", base="jer"),
        SimpleNamespace(name="jerDown", base="jer"),
    )
    plan = _build_plan_with_variations(variations)
    validation.validate_histogram_plan_systematics(
        metadata=metadata,
        tasks=plan,
        do_systs=True,
        has_mc_samples=True,
        has_data_samples=False,
        tau_analysis=False,
        metadata_source="meta.yml",
    )


def test_validate_systematics_rejects_variations_when_disabled():
    metadata = {
        "systematics": {
            "nominal": {"applies_to": ["all"]},
            "jer": {"applies_to": ["mc"]},
        }
    }
    variations = (SimpleNamespace(name="jerUp", base="jer"),)
    plan = _build_plan_with_variations(variations)
    with pytest.raises(ValueError):
        validation.validate_histogram_plan_systematics(
            metadata=metadata,
            tasks=plan,
            do_systs=False,
            has_mc_samples=True,
            has_data_samples=False,
            tau_analysis=False,
            metadata_source="meta.yml",
        )
