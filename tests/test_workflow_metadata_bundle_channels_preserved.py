import sys
from types import ModuleType

import yaml


def _install_topcoffea_stub() -> None:
    if "topcoffea" in sys.modules:
        return
    modules_pkg = ModuleType("topcoffea.modules")
    modules_pkg.__path__ = []

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


def _install_numpy_stub() -> None:
    if "numpy" in sys.modules:
        return
    numpy_stub = ModuleType("numpy")
    numpy_stub.__version__ = "0.0.0"
    numpy_stub.array = lambda *args, **kwargs: args
    numpy_stub.asarray = lambda *args, **kwargs: args
    numpy_stub.zeros = lambda *args, **kwargs: []
    numpy_stub.ones = lambda *args, **kwargs: []
    numpy_stub.dtype = type("DummyDType", (), {})  # type: ignore[misc]
    numpy_stub.AxisError = type("AxisError", (Exception,), {})
    numpy_stub.exceptions = type("NumpyExceptions", (), {"AxisError": numpy_stub.AxisError})
    numpy_stub.bool_ = bool
    numpy_stub.seterr = lambda *args, **kwargs: None
    sys.modules["numpy"] = numpy_stub


def _install_coffea_stub() -> None:
    if "coffea" in sys.modules:
        return
    coffea_pkg = ModuleType("coffea")
    nanoevents_mod = ModuleType("coffea.nanoevents")
    factory_mod = ModuleType("coffea.nanoevents.factory")

    class _Factory:
        @staticmethod
        def from_root(*args, **kwargs):
            return None

    nanoevents_mod.NanoEventsFactory = _Factory
    factory_mod.NanoEventsFactory = _Factory

    coffea_pkg.nanoevents = nanoevents_mod
    sys.modules["coffea"] = coffea_pkg
    sys.modules["coffea.nanoevents"] = nanoevents_mod
    sys.modules["coffea.nanoevents.factory"] = factory_mod


_install_topcoffea_stub()
_install_numpy_stub()
_install_coffea_stub()

from analysis.topeft_run2 import metadata_authority
from analysis.topeft_run2 import workflow as workflow_mod
from analysis.topeft_run2.run_analysis_helpers import RunConfig
from topeft.modules import channel_metadata as channel_metadata_mod


def test_run_workflow_preserves_metadata_bundle_channels(monkeypatch, tmp_path) -> None:
    metadata_path = tmp_path / "metadata.yml"
    metadata_path.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "schema_version": 3,
                    "group_aliases": {"SR": "TOP22_006_CH_LST_SR"},
                    "groups": {
                        "TOP22_006_CH_LST_SR": {"categories": []},
                        "CH_LST_CR": {"categories": []},
                    },
                },
                "variables": {"lj0pt": {"variable": [0, 1]}},
            }
        ),
        encoding="utf-8",
    )

    bundle = metadata_authority.load_metadata_bundle(
        str(metadata_path),
        "TOP_22_006",
        strict=True,
        required_sections=("channels", "variables"),
        metadata_source="explicit",
    )

    captured = {}

    class DummyHelper:
        def __init__(self, channels):
            captured["channels"] = channels

    monkeypatch.setattr(channel_metadata_mod, "ChannelMetadataHelper", DummyHelper)
    monkeypatch.setattr(workflow_mod.RunWorkflow, "run", lambda self: None)

    config = RunConfig(
        json_files=[],
        metadata_path=str(metadata_path),
        scenario_names=["TOP_22_006"],
        pretend=True,
    )

    workflow_mod.run_workflow(config, metadata_bundle=bundle)

    channels = captured["channels"]
    assert channels["schema_version"] == 3
    assert channels["group_aliases"] == {"SR": "TOP22_006_CH_LST_SR"}
    assert set(channels["groups"].keys()) == {"TOP22_006_CH_LST_SR", "CH_LST_CR"}
