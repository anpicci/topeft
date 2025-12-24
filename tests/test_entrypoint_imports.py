import importlib
import sys
from types import ModuleType


ENTRYPOINTS = [
    "analysis.topeft_run2.parse_datacard_templates",
    "analysis.topeft_run2.make_1d_quad_plots",
    "analysis.topeft_run2.make_1d_quad_plots_from_template_histos",
    "analysis.topeft_run2.datacards_post_processing",
    "analysis.topeft_run2.quick_check",
    "analysis.topeft_run2.make_cards",
    "analysis.topeft_run2.get_yield_json",
    "analysis.topeft_run2.update_json_sow",
    "analysis.topeft_run2.make_cr_and_sr_plots",
    "analysis.topeft_run2.get_datacard_yields",
    "analysis.topeft_run2.comp_yields",
    "analysis.topeft_run2.make_skim_jsons",
    "analysis.topeft_run2.make_jsons",
    "analysis.topeft_run2.tauFitter",
    "topeft.quickstart",
    "topeft.conda_shim",
    "topeft.modules.dataDrivenEstimation",
    "topeft.modules.get_renormfact_envelope",
]


def _install_stub(name: str, *, package: bool = False) -> ModuleType:
    module = sys.modules.get(name)
    if module is not None:
        return module
    module = ModuleType(name)
    if package:
        module.__path__ = []
    sys.modules[name] = module
    return module


def _install_numpy_stub() -> None:
    if "numpy" in sys.modules:
        return
    numpy_stub = _install_stub("numpy")
    numpy_stub.__version__ = "0.0.0"
    numpy_stub.array = lambda *args, **kwargs: []
    numpy_stub.asarray = lambda *args, **kwargs: []
    numpy_stub.zeros = lambda *args, **kwargs: []
    numpy_stub.ones = lambda *args, **kwargs: []
    numpy_stub.dtype = type("DummyDType", (), {})
    numpy_stub.AxisError = type("AxisError", (Exception,), {})
    numpy_stub.exceptions = type(
        "NumpyExceptions", (), {"AxisError": numpy_stub.AxisError}
    )
    numpy_stub.bool_ = bool
    numpy_stub.int8 = int
    numpy_stub.seterr = lambda *args, **kwargs: None

    linalg_stub = _install_stub("numpy.linalg")
    linalg_stub.eig = lambda *args, **kwargs: ([], [])


def _install_scipy_stub() -> None:
    if "scipy" in sys.modules:
        return
    _install_stub("scipy", package=True)
    optimize_stub = _install_stub("scipy.optimize")
    optimize_stub.curve_fit = lambda *args, **kwargs: ((0, 0), None)

    odr_stub = _install_stub("scipy.odr")
    odr_stub.Model = lambda *args, **kwargs: None
    odr_stub.RealData = lambda *args, **kwargs: None

    class _DummyOutput:
        def Output(self):
            return (0, 0, None)

    class _DummyODR:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            return _DummyOutput()

    odr_stub.ODR = _DummyODR


def _install_root_stub() -> None:
    if "ROOT" in sys.modules:
        return
    root_stub = _install_stub("ROOT")
    root_stub.TFile = type("TFile", (), {"Open": staticmethod(lambda *a, **k: None)})
    root_stub.TCanvas = lambda *args, **kwargs: object()
    root_stub.gROOT = type("gROOT", (), {"SetBatch": staticmethod(lambda *a, **k: None)})()


def _install_matplotlib_stub() -> None:
    if "matplotlib" not in sys.modules:
        mpl_stub = _install_stub("matplotlib", package=True)
        mpl_stub.use = lambda *args, **kwargs: None
    if "matplotlib.pyplot" not in sys.modules:
        pyplot_stub = _install_stub("matplotlib.pyplot")
        pyplot_stub.figure = lambda *args, **kwargs: None
        pyplot_stub.subplots = lambda *args, **kwargs: (None, None)
        pyplot_stub.savefig = lambda *args, **kwargs: None
        pyplot_stub.close = lambda *args, **kwargs: None
    if "mplhep" not in sys.modules:
        mplhep_stub = _install_stub("mplhep")
        mplhep_stub.histplot = lambda *args, **kwargs: None
    if "hist" not in sys.modules:
        hist_stub = _install_stub("hist")
        axis_stub = _install_stub("hist.axis")
        axis_stub.Variable = lambda *args, **kwargs: None
        axis_stub.Regular = lambda *args, **kwargs: None
        hist_stub.axis = axis_stub
    if "cycler" not in sys.modules:
        cycler_stub = _install_stub("cycler")
        cycler_stub.cycler = lambda *args, **kwargs: None


def _install_coffea_stub() -> None:
    if "coffea" in sys.modules:
        return
    coffea_pkg = _install_stub("coffea", package=True)
    nanoevents_mod = _install_stub("coffea.nanoevents", package=True)

    class _Factory:
        @staticmethod
        def from_root(*args, **kwargs):
            return None

    nanoevents_mod.NanoEventsFactory = _Factory
    coffea_pkg.nanoevents = nanoevents_mod

    hist_mod = _install_stub("coffea.hist")
    coffea_pkg.hist = hist_mod


def _install_topcoffea_stub() -> None:
    if "topcoffea" in sys.modules:
        return
    topcoffea_stub = _install_stub("topcoffea", package=True)
    modules_pkg = _install_stub("topcoffea.modules", package=True)
    scripts_pkg = _install_stub("topcoffea.scripts", package=True)

    paths_mod = _install_stub("topcoffea.modules.paths")
    paths_mod.topcoffea_path = lambda relative: relative

    utils_mod = _install_stub("topcoffea.modules.utils")
    utils_mod.regex_match = lambda choices, patterns: list(choices)
    utils_mod.clean_dir = lambda *args, **kwargs: None
    utils_mod.dict_comp = lambda *args, **kwargs: None
    utils_mod.get_list_of_wc_names = lambda *args, **kwargs: []
    utils_mod.load_sample_json_file = lambda *args, **kwargs: {}
    utils_mod.get_files = lambda *args, **kwargs: []
    utils_mod.get_hist_from_pkl = lambda *args, **kwargs: {}

    qft_mod = _install_stub("topcoffea.modules.quad_fit_tools")
    qft_mod.get_summed_quad_fit_arr = lambda *args, **kwargs: None
    qft_mod.get_quad_fit_dict = lambda *args, **kwargs: {}
    qft_mod.scale_to_sm = lambda *args, **kwargs: {}
    qft_mod.get_1d_fit = lambda *args, **kwargs: None
    qft_mod.find_where_fit_crosses_threshold = lambda *args, **kwargs: []
    qft_mod.ARXIV1901_LIMS = {}
    qft_mod.TOP19001_LIMS = {}
    qft_mod.make_1d_quad_plot = lambda *args, **kwargs: None

    sample_lst_mod = _install_stub("topcoffea.modules.sample_lst_jsons_tools")

    hist_mod = _install_stub("topcoffea.modules.HistEFT")
    hist_mod.HistEFT = type("HistEFT", (), {})

    get_param_mod = _install_stub("topcoffea.modules.get_param_from_jsons")
    get_param_mod.GetParam = lambda *args, **kwargs: (lambda key=None: 1.0)

    mlt_mod = _install_stub("topcoffea.modules.MakeLatexTable")
    mlt_mod.print_latex_yield_table = lambda *args, **kwargs: None

    update_json_mod = _install_stub("topcoffea.modules.update_json")
    update_json_mod.update_json = lambda *args, **kwargs: None

    remote_env_mod = _install_stub("topcoffea.modules.remote_environment")
    remote_env_mod.PIP_LOCAL_TO_WATCH = {}
    remote_env_mod.get_environment = lambda **kwargs: "env.tar.gz"

    ddr_mod = _install_stub("topcoffea.modules.dynamic_data_reduction")

    make_html_mod = _install_stub("topcoffea.scripts.make_html")
    make_html_mod.make_html = lambda *args, **kwargs: None

    modules_pkg.paths = paths_mod
    modules_pkg.utils = utils_mod
    modules_pkg.quad_fit_tools = qft_mod
    modules_pkg.sample_lst_jsons_tools = sample_lst_mod
    modules_pkg.HistEFT = hist_mod
    modules_pkg.get_param_from_jsons = get_param_mod
    modules_pkg.MakeLatexTable = mlt_mod
    modules_pkg.update_json = update_json_mod
    modules_pkg.remote_environment = remote_env_mod
    modules_pkg.dynamic_data_reduction = ddr_mod

    scripts_pkg.make_html = make_html_mod

    topcoffea_stub.modules = modules_pkg
    topcoffea_stub.scripts = scripts_pkg


def _install_topeft_module_stubs() -> None:
    yield_mod = _install_stub("topeft.modules.yield_tools")
    yield_mod.YieldTools = type("YieldTools", (), {})

    _install_stub("topeft.modules.datacard_tools")
    _install_stub("topeft.modules.get_rate_systs")
    combine_batch = _install_stub("topeft.modules.combine_json_batch")
    combine_batch.combine_json_batch = lambda *args, **kwargs: None
    combine_ext = _install_stub("topeft.modules.combine_json_ext")
    combine_ext.combine_json_ext = lambda *args, **kwargs: None


def _install_misc_stubs() -> None:
    _install_stub("get_datacard_yields")
    _install_stub("path_to_your_file", package=True)
    path_mod = _install_stub("path_to_your_file.file_name")
    path_mod.template_vals_dict = {}

    nanohelpers = _install_stub("analysis.topeft_run2.nanoevents_helpers")
    nanohelpers.ensure_factory_mode = lambda factory: factory

    workflow_stub = _install_stub("analysis.topeft_run2.workflow")
    workflow_stub.DEFAULT_SCENARIO_NAME = "TOP_22_006"
    workflow_stub.ChannelPlanner = object
    workflow_stub.ExecutorFactory = object
    workflow_stub.HistogramPlanner = object
    workflow_stub.RunWorkflow = object


def _install_stubs() -> None:
    _install_numpy_stub()
    _install_scipy_stub()
    _install_root_stub()
    _install_matplotlib_stub()
    _install_coffea_stub()
    _install_topcoffea_stub()
    _install_topeft_module_stubs()
    _install_misc_stubs()


def test_entrypoints_importable() -> None:
    _install_stubs()
    for module_name in ENTRYPOINTS:
        importlib.import_module(module_name)
