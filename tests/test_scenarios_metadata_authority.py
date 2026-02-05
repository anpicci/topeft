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

from analysis.topeft_run2 import metadata_authority


def _tail_components(path: str, depth: int = 3) -> tuple[str, ...]:
    parts = Path(path).parts
    if len(parts) < depth:
        return parts
    return parts[-depth:]


def test_scenarios_resolve_to_canonical_metadata():
    resolved = metadata_authority.resolve_metadata_path(None)
    assert _tail_components(str(resolved)) == (
        "analysis",
        "metadata",
        "metadata.yml",
    )


def test_scenarios_reference_known_metadata_groups():
    scenarios = metadata_authority.load_scenarios()
    for scenario_name in scenarios:
        bundle = metadata_authority.load_metadata_bundle(
            None,
            scenario_name,
            strict=True,
            required_sections=("channels",),
            metadata_source="default",
        )
        assert bundle.channels.get("groups"), (
            f"Scenario {scenario_name!r} should resolve at least one channel group."
        )
