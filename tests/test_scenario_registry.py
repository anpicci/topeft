import sys
from pathlib import Path
from types import ModuleType


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

from analysis.topeft_run2 import scenario_registry
from topeft.modules import run2_scenarios


def _tail_components(path: str, depth: int = 3) -> tuple[str, ...]:
    parts = Path(path).parts
    if len(parts) < depth:
        return parts
    return parts[-depth:]


def test_run2_scenarios_resolve_to_canonical_metadata():
    resolution = scenario_registry.resolve_scenario_choice("TOP_22_006")
    assert _tail_components(resolution.metadata_path) == (
        "topeft",
        "params",
        "metadata.yml",
    )


def test_run2_channel_groups_cover_canonical_and_derived_sets():
    top_channels = run2_scenarios.load_run2_channels_for_scenario("TOP_22_006")
    assert "TOP22_006_CH_LST_SR" in (top_channels.get("groups") or {})

    derived_channels = run2_scenarios.load_run2_channels_for_scenario("all_analysis")
    assert "ALL_CH_LST_SR" in (derived_channels.get("groups") or {})
