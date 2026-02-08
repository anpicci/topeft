import sys
from types import ModuleType

import pytest
import yaml

_STUBBED_MODULE_NAMES = (
    "topcoffea",
    "topcoffea.modules",
    "topcoffea.modules.paths",
    "topcoffea.modules.utils",
    "topcoffea.modules.remote_environment",
    "topcoffea.modules.dynamic_data_reduction",
    "topcoffea.modules.HistEFT",
    "topcoffea.modules.get_param_from_jsons",
    "topcoffea.modules.HTMLGenerator",
    "topcoffea.scripts",
    "topcoffea.scripts.make_html",
    "numpy",
    "matplotlib",
    "matplotlib.pyplot",
    "mplhep",
    "hist",
    "cycler",
    "boost_histogram",
    "boost_histogram.storage",
    "uproot",
    "coffea",
    "coffea.nanoevents",
    "coffea.nanoevents.factory",
    "coffea.hist",
)
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _STUBBED_MODULE_NAMES}


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
    utils_mod.regex_match = lambda choices, patterns: list(choices)
    remote_env_mod = ModuleType("topcoffea.modules.remote_environment")
    remote_env_mod.PIP_LOCAL_TO_WATCH = {}
    remote_env_mod.get_environment = lambda **kwargs: "env.tar.gz"
    modules_pkg.paths = paths_mod
    modules_pkg.utils = utils_mod
    modules_pkg.remote_environment = remote_env_mod
    modules_pkg.dynamic_data_reduction = ModuleType("topcoffea.modules.dynamic_data_reduction")
    hist_mod = ModuleType("topcoffea.modules.HistEFT")
    hist_mod.HistEFT = type("HistEFT", (), {})
    modules_pkg.HistEFT = hist_mod
    get_param_mod = ModuleType("topcoffea.modules.get_param_from_jsons")
    get_param_mod.GetParam = lambda *args, **kwargs: lambda key: 1.0
    modules_pkg.get_param_from_jsons = get_param_mod
    html_mod = ModuleType("topcoffea.modules.HTMLGenerator")
    html_mod.make_html = lambda *args, **kwargs: None
    modules_pkg.HTMLGenerator = html_mod
    scripts_pkg = ModuleType("topcoffea.scripts")
    scripts_pkg.__path__ = []
    make_html_mod = ModuleType("topcoffea.scripts.make_html")
    make_html_mod.make_html = lambda *args, **kwargs: None
    scripts_pkg.make_html = make_html_mod

    topcoffea_stub = ModuleType("topcoffea")
    topcoffea_stub.modules = modules_pkg
    topcoffea_stub.scripts = scripts_pkg
    topcoffea_stub.__path__ = []

    sys.modules["topcoffea"] = topcoffea_stub
    sys.modules["topcoffea.modules"] = modules_pkg
    sys.modules["topcoffea.modules.paths"] = paths_mod
    sys.modules["topcoffea.modules.utils"] = utils_mod
    sys.modules["topcoffea.modules.remote_environment"] = remote_env_mod
    sys.modules["topcoffea.modules.dynamic_data_reduction"] = modules_pkg.dynamic_data_reduction
    sys.modules["topcoffea.modules.HistEFT"] = hist_mod
    sys.modules["topcoffea.modules.get_param_from_jsons"] = get_param_mod
    sys.modules["topcoffea.modules.HTMLGenerator"] = html_mod
    sys.modules["topcoffea.scripts"] = scripts_pkg
    sys.modules["topcoffea.scripts.make_html"] = make_html_mod


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
    numpy_stub.exceptions = type(
        "NumpyExceptions", (), {"AxisError": numpy_stub.AxisError}
    )
    numpy_stub.bool_ = bool
    numpy_stub.seterr = lambda *args, **kwargs: None
    sys.modules["numpy"] = numpy_stub


_install_topcoffea_stub()
_install_numpy_stub()
def _install_matplotlib_stubs() -> None:
    if "matplotlib" not in sys.modules:
        matplotlib_mod = ModuleType("matplotlib")
        matplotlib_mod.use = lambda *args, **kwargs: None
        sys.modules["matplotlib"] = matplotlib_mod
    if "matplotlib.pyplot" not in sys.modules:
        pyplot_mod = ModuleType("matplotlib.pyplot")
        pyplot_mod.figure = lambda *args, **kwargs: None
        pyplot_mod.subplots = lambda *args, **kwargs: (None, None)
        pyplot_mod.savefig = lambda *args, **kwargs: None
        sys.modules["matplotlib.pyplot"] = pyplot_mod
    if "mplhep" not in sys.modules:
        mplhep_mod = ModuleType("mplhep")
        mplhep_mod.histplot = lambda *args, **kwargs: None
        sys.modules["mplhep"] = mplhep_mod
    if "hist" not in sys.modules:
        hist_mod = ModuleType("hist")
        hist_mod.Hist = type("DummyHist", (), {})
        axis_mod = ModuleType("hist.axis")
        axis_mod.Variable = lambda *args, **kwargs: None
        axis_mod.Regular = lambda *args, **kwargs: None
        hist_mod.axis = axis_mod
        sys.modules["hist"] = hist_mod
    if "cycler" not in sys.modules:
        cycler_mod = ModuleType("cycler")
        cycler_mod.cycler = lambda *args, **kwargs: None
        sys.modules["cycler"] = cycler_mod


_install_matplotlib_stubs()
def _install_boost_histogram_stub() -> None:
    if "boost_histogram" in sys.modules:
        return
    module = ModuleType("boost_histogram")
    storage_mod = ModuleType("boost_histogram.storage")
    storage_mod.Weight = lambda *args, **kwargs: object()
    module.storage = storage_mod
    sys.modules["boost_histogram"] = module
    sys.modules["boost_histogram.storage"] = storage_mod


def _install_uproot_stub() -> None:
    if "uproot" in sys.modules:
        return
    uproot_mod = ModuleType("uproot")
    uproot_mod.open = lambda *args, **kwargs: object()
    sys.modules["uproot"] = uproot_mod


_install_boost_histogram_stub()
_install_uproot_stub()
def _install_coffea_stub() -> None:
    if "coffea" in sys.modules:
        return
    coffea_pkg = ModuleType("coffea")
    nanoevents_mod = ModuleType("coffea.nanoevents")
    factory_mod = ModuleType("coffea.nanoevents.factory")
    hist_mod = ModuleType("coffea.hist")
    class _Bin:
        def __init__(self, *args, **kwargs):
            pass

    class _Factory:
        @staticmethod
        def from_root(*args, **kwargs):
            return None

    nanoevents_mod.NanoEventsFactory = _Factory
    factory_mod.NanoEventsFactory = _Factory
    hist_mod.Bin = _Bin

    coffea_pkg.nanoevents = nanoevents_mod
    coffea_pkg.hist = hist_mod
    sys.modules["coffea"] = coffea_pkg
    sys.modules["coffea.nanoevents"] = nanoevents_mod
    sys.modules["coffea.nanoevents.factory"] = factory_mod
    sys.modules["coffea.hist"] = hist_mod


_install_coffea_stub()

from analysis.topeft_run2 import metadata_authority
from analysis.topeft_run2 import datacards_post_processing as dpp
from analysis.topeft_run2 import make_cr_and_sr_plots as plots
from analysis.topeft_run2 import comp as comp_module


@pytest.fixture(scope="module", autouse=True)
def _restore_stubbed_modules_after_module():
    yield
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def test_load_metadata_prefers_custom_file(tmp_path):
    metadata_file = tmp_path / "custom_meta.yml"
    metadata_file.write_text(
        yaml.safe_dump(
            {
                "channels": {"groups": {"example": {"categories": []}}},
                "variables": {"foo": {"variable": [0, 1]}},
            }
        ),
        encoding="utf-8",
    )

    resolved_path, payload = metadata_authority.load_metadata_payload(
        metadata_file,
        required_sections=("channels", "variables"),
    )

    assert resolved_path == metadata_file.resolve()
    assert "foo" in (payload.get("variables") or {})


def test_scenario_channels_use_provided_metadata(tmp_path):
    metadata_file = tmp_path / "channels.yml"
    metadata_file.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "groups": {
                        "TOP22_006_CH_LST_SR": {"categories": []},
                        "CH_LST_CR": {"categories": []},
                    }
                },
                "variables": {"ptz": {"variable": [0, 1]}},
            }
        ),
        encoding="utf-8",
    )

    bundle = metadata_authority.load_metadata_bundle(
        str(metadata_file),
        "TOP_22_006",
        strict=True,
        required_sections=("channels",),
        metadata_source="explicit",
    )

    assert "TOP22_006_CH_LST_SR" in bundle.channels["groups"]
    assert "CH_LST_CR" in bundle.channels["groups"]


def test_resolve_scenario_metadata_respects_override(tmp_path, monkeypatch):
    metadata_file = tmp_path / "custom_override.yml"
    payload = {
        "channels": {
            "groups": {
                "TOP22_006_CH_LST_SR": {"categories": []},
                "CH_LST_CR": {"categories": []},
            }
        },
        "variables": {"ptz": {"variable": [0, 1]}},
    }
    metadata_file.write_text(yaml.safe_dump(payload), encoding="utf-8")

    captured = {}

    class DummyHelper:
        def __init__(self, data):
            captured["data"] = data

    monkeypatch.setattr(dpp, "ChannelMetadataHelper", DummyHelper)
    scenario_name, bundle, _ = dpp.resolve_scenario_metadata(
        ["TOP_22_006"],
        metadata_path=str(metadata_file),
        require_variables=True,
    )

    assert scenario_name == "TOP_22_006"
    assert bundle.metadata_path == metadata_file.resolve()
    assert captured["data"]["groups"]


def test_plot_helpers_accept_axes_metadata(monkeypatch):
    monkeypatch.setattr(plots, "_AXES_INFO", None, raising=False)
    axes = {
        "ptz": {"variable": [0, 1]},
        "lj0pt": {"variable": [0, 1]},
    }

    plots._set_axes_info(axes)

    assert plots._require_axes_info() == axes


def test_comp_helper_uses_metadata_binning(tmp_path, monkeypatch):
    metadata_file = tmp_path / "comp_meta.yml"
    metadata_file.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "groups": {
                        "TOP22_006_CH_LST_SR": {"categories": []},
                        "CH_LST_CR": {"categories": []},
                    }
                },
                "variables": {"test": {"variable": [0, 2, 4]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(comp_module, "BINNING", {}, raising=False)
    comp_module._set_binning(str(metadata_file))

    assert comp_module.BINNING["test"] == [0, 2, 4]
