import importlib
import inspect
import sys
import types
from pathlib import Path

import coffea  # ensure the real coffea package is available during tests

import pytest

from analysis.topeft_run2.run_analysis_helpers import RunConfig


@pytest.fixture
def stub_remote_environment(monkeypatch):
    import types

    topcoffea_pkg = types.ModuleType("topcoffea")
    modules_pkg = types.ModuleType("topcoffea.modules")
    modules_pkg.__path__ = []  # Mark as package for importlib submodule resolution.
    remote_env_mod = types.ModuleType("topcoffea.modules.remote_environment")
    utils_mod = types.ModuleType("topcoffea.modules.utils")
    remote_env_mod.get_environment = lambda **_: None
    utils_mod.load_sample_json_file = lambda *args, **kwargs: {}
    utils_mod.read_cfg_file = lambda *args, **kwargs: {}
    utils_mod.update_cfg = lambda *args, **kwargs: {}

    modules_pkg.remote_environment = remote_env_mod
    modules_pkg.utils = utils_mod
    topcoffea_pkg.modules = modules_pkg

    monkeypatch.setitem(sys.modules, "topcoffea", topcoffea_pkg)
    monkeypatch.setitem(sys.modules, "topcoffea.modules", modules_pkg)
    monkeypatch.setitem(sys.modules, "topcoffea.modules.remote_environment", remote_env_mod)
    monkeypatch.setitem(sys.modules, "topcoffea.modules.utils", utils_mod)

    sys.modules.pop("analysis.topeft_run2.workflow", None)

    yield

    for module_name in [
        "topcoffea.modules.remote_environment",
        "topcoffea.modules.utils",
        "topcoffea.modules",
        "topcoffea",
    ]:
        sys.modules.pop(module_name, None)
    sys.modules.pop("analysis.topeft_run2.workflow", None)


def test_executor_factory_futures_instantiates(monkeypatch, stub_remote_environment):
    workflow = importlib.import_module("analysis.topeft_run2.workflow")
    workflow = importlib.reload(workflow)

    config = RunConfig(
        executor="futures",
        environment_file=None,
        nworkers=3,
        futures_status=False,
        futures_tail_timeout=180,
    )
    factory = workflow.ExecutorFactory(config)
    runner = factory.create_runner()

    import coffea.processor as processor
    from coffea.nanoevents import NanoAODSchema

    assert isinstance(runner.executor, processor.FuturesExecutor)
    assert runner.executor.workers == 3
    assert runner.executor.status is False
    assert runner.executor.tailtimeout == 180
    assert runner.schema is NanoAODSchema


def test_executor_factory_iterative_instantiates(monkeypatch, stub_remote_environment):
    workflow = importlib.import_module("analysis.topeft_run2.workflow")
    workflow = importlib.reload(workflow)

    config = RunConfig(executor="iterative", environment_file=None)
    factory = workflow.ExecutorFactory(config)
    runner = factory.create_runner()

    import coffea.processor as processor

    assert isinstance(runner.executor, processor.IterativeExecutor)


def test_executor_factory_taskvine_instantiates(tmp_path, monkeypatch, stub_remote_environment):
    workflow = importlib.import_module("analysis.topeft_run2.workflow")
    workflow = importlib.reload(workflow)

    processor = pytest.importorskip("coffea.processor")
    taskvine_cls = getattr(processor, "TaskVineExecutor", None)
    if taskvine_cls is None:
        pytest.skip("TaskVineExecutor not available in this Coffea installation.")

    signature = inspect.signature(taskvine_cls)
    accepts_kwargs = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    )
    expected_keys = {
        "filepath",
        "extra_input_files",
        "retries",
        "compression",
        "fast_terminate_workers",
        "verbose",
        "print_stdout",
        "custom_init",
    }
    missing_keys = [
        key
        for key in expected_keys
        if key not in signature.parameters and not accepts_kwargs
    ]
    if missing_keys:
        pytest.fail(
            "TaskVineExecutor signature missing expected parameters: "
            + ", ".join(sorted(missing_keys))
        )

    call_args: dict = {}
    executor_base_cls = pytest.importorskip("coffea.processor.executor").ExecutorBase

    class RecordingTaskVineExecutor(executor_base_cls):
        def __init__(self, *args, **kwargs):
            call_args["args"] = args
            call_args["kwargs"] = kwargs
            self.kwargs = kwargs
            self.manager_name = kwargs.get("manager_name")
            self.filepath = kwargs.get("filepath")

        def __call__(self, items, function, accumulator):
            return accumulator

    monkeypatch.setattr(processor, "TaskVineExecutor", RecordingTaskVineExecutor)

    scratch_dir = tmp_path / "staging"
    config = RunConfig(
        executor="taskvine",
        environment_file=None,
        scratch_dir=str(scratch_dir),
        negotiate_manager_port=False,
        manager_name="test-taskvine",
    )

    factory = workflow.ExecutorFactory(config)
    runner = factory.create_runner()

    assert isinstance(runner.executor, processor.TaskVineExecutor)
    assert runner.executor.manager_name == "test-taskvine"
    assert runner.executor.filepath == str(scratch_dir)
    assert runner.skipbadfiles is True
    assert runner.xrootdtimeout == 300

    kwargs = call_args.get("kwargs", {})
    assert kwargs.get("manager_name") == "test-taskvine"
    assert kwargs.get("filepath") == str(scratch_dir)
    assert isinstance(kwargs.get("custom_init"), types.FunctionType)
    extra_input_files = kwargs.get("extra_input_files")
    assert isinstance(extra_input_files, list)
    assert extra_input_files
    assert "analysis_processor.py" in [Path(path).name for path in extra_input_files]
    assert kwargs.get("retries") == 15
    assert kwargs.get("compression") == 8
    assert kwargs.get("fast_terminate_workers") == 0
    assert kwargs.get("verbose") is True
    assert kwargs.get("print_stdout") is True


def test_executor_factory_collects_processor_helpers(tmp_path, stub_remote_environment):
    workflow = importlib.import_module("analysis.topeft_run2.workflow")
    workflow = importlib.reload(workflow)

    package_dir = tmp_path / "processor_pkg"
    helpers_dir = package_dir / "analysis_processor_helpers"
    helpers_dir.mkdir(parents=True)
    (package_dir / "analysis_processor.py").write_text("# stub\n")
    (helpers_dir / "__init__.py").write_text("# pkg\n")
    (helpers_dir / "utilities.py").write_text("# helper\n")
    init_path = package_dir / "__init__.py"
    init_path.write_text("# package\n")

    config = RunConfig(
        executor="taskvine",
        environment_file=None,
        processor=str(package_dir / "analysis_processor.py"),
    )
    factory = workflow.ExecutorFactory(config)

    extras = factory._processor_extra_input_files()
    assert extras == [
        str((package_dir / "analysis_processor.py").resolve()),
        str((helpers_dir / "utilities.py").resolve()),
    ]
