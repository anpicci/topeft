from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.topeft_run2 import workflow as workflow_module
from analysis.topeft_run2.run_analysis_helpers import RunConfig
from analysis.topeft_run2.workflow import (
    RunWorkflow,
    TaskVineContext,
    _resolve_ddr_preprocess_paths,
    stage_ddr_proxy,
)


class _DummyExecutorFactory:
    def __init__(self, context: TaskVineContext) -> None:
        self._context = context

    def taskvine_context(
        self,
        executor: str,
        *,
        processor_path: Path | None = None,
        use_environment_file: bool = True,
    ) -> TaskVineContext:
        assert executor == "taskvine"
        _ = processor_path
        _ = use_environment_file
        return self._context


class _DummyManager:
    def enable_monitoring(self, watchdog: bool = False) -> None:
        _ = watchdog

    def tune(self, *_args, **_kwargs) -> None:
        return

    def shutdown(self) -> None:
        return


class _DummyManagerNoShutdown:
    def enable_monitoring(self, watchdog: bool = False) -> None:
        _ = watchdog

    def tune(self, *_args, **_kwargs) -> None:
        return


def test_stage_ddr_proxy_copies_to_proxy_pem(tmp_path: Path) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    staging_dir = tmp_path / "staging"

    staged_proxy = stage_ddr_proxy(str(source_proxy), staging_dir=staging_dir)

    assert staged_proxy == staging_dir / "proxy.pem"
    assert staged_proxy.exists()
    assert staged_proxy.read_text(encoding="utf-8") == "proxy-data"
    assert (staged_proxy.stat().st_mode & 0o777) == 0o600


def test_stage_ddr_proxy_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        stage_ddr_proxy(str(tmp_path / "missing_proxy.pem"), staging_dir=tmp_path / "staging")


def test_preprocess_paths_auto_save_defaults_to_results_dir(tmp_path: Path) -> None:
    config = RunConfig(executor="taskvine")
    preprocessed_data_path, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert preprocessed_data_path is None
    assert save_path == str((tmp_path / "ddr_preprocessed_data.json").resolve())


def test_preprocess_paths_explicit_save_overrides_auto(tmp_path: Path) -> None:
    explicit_save = tmp_path / "custom-preprocessed.json"
    config = RunConfig(
        executor="taskvine",
        ddr_save_preprocess=str(explicit_save),
    )
    _, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert save_path == str(explicit_save)


def test_preprocess_paths_reuse_mode_disables_auto_save(tmp_path: Path) -> None:
    config = RunConfig(
        executor="taskvine",
        ddr_preprocessed_data=str(tmp_path / "existing-preprocessed.json"),
        ddr_auto_save_preprocess=True,
    )
    preprocessed_data_path, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert preprocessed_data_path == str(tmp_path / "existing-preprocessed.json")
    assert save_path is None


def test_preprocess_paths_reuse_mode_keeps_explicit_save(tmp_path: Path) -> None:
    explicit_save = tmp_path / "explicit-save.json"
    config = RunConfig(
        executor="taskvine",
        ddr_preprocessed_data=str(tmp_path / "existing-preprocessed.json"),
        ddr_save_preprocess=str(explicit_save),
    )
    _, save_path = _resolve_ddr_preprocess_paths(
        config,
        results_dir=tmp_path,
    )

    assert save_path == str(explicit_save)


def test_execute_ddr_sets_proxy_env_var_to_proxy_pem_basename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    staging_dir = tmp_path / "staging"
    logs_dir = tmp_path / "logs" / "taskvine"
    logs_dir.mkdir(parents=True, exist_ok=True)

    context = TaskVineContext(
        executor="taskvine",
        port_range=(9123, 9123),
        staging_dir=staging_dir,
        logs_dir=logs_dir,
        manager_name="test-manager",
        manager_template="test-manager-{pid}",
        manager_source="config",
        environment_file=None,
        extra_input_files=(),
    )
    config = RunConfig(
        executor="taskvine",
        ddr_x509_proxy=str(source_proxy),
        nworkers=8,
    )

    workflow = RunWorkflow(
        config=config,
        metadata={},
        sample_loader=SimpleNamespace(),
        channel_planner=SimpleNamespace(),
        histogram_planner=SimpleNamespace(),
        executor_factory=_DummyExecutorFactory(context),
        weight_variations=(),
        metadata_path="metadata.yml",
    )
    monkeypatch.setattr(
        workflow,
        "_build_ddr_processors",
        lambda **_kwargs: {"proc": object()},
    )
    monkeypatch.setattr(
        workflow,
        "_create_ddr_manager",
        lambda _context: _DummyManager(),
    )
    monkeypatch.setattr(
        workflow_module,
        "taskvine_log_configurator",
        lambda _logs_dir: (lambda _manager: None),
    )

    captured: dict[str, object] = {}

    def _fake_build_ddr_data(_flist, *, object_path: str = "Events"):
        _ = object_path
        return {"sampleA": {"files": {"/tmp/input.root": {"object_path": "Events"}}}}

    def _fake_run_ddr(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "build_ddr_data_from_flist",
        _fake_build_ddr_data,
    )
    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "run_ddr",
        _fake_run_ddr,
    )

    workflow._execute_ddr(
        histogram_plan=SimpleNamespace(tasks=()),
        samplesdict={},
        flist={},
        golden_jsons={},
        ecut_threshold=None,
        analysis_processor_module=SimpleNamespace(),
        processor_file=processor_file,
        processor_module_name="analysis_processor",
        coffea_processor_module=SimpleNamespace(),
    )

    ddr_kwargs = captured["ddr_kwargs"]
    preprocess_kwargs = captured["preprocess_kwargs"]
    extra_files = captured["extra_files"]
    assert isinstance(ddr_kwargs, dict)
    assert isinstance(preprocess_kwargs, dict)
    assert isinstance(extra_files, list)

    assert ddr_kwargs["resources_processing"]["cores"] == 1
    assert ddr_kwargs["environment_variables"]["X509_USER_PROXY"] == "proxy.pem"
    assert preprocess_kwargs["environment_variables"]["X509_USER_PROXY"] == "proxy.pem"
    assert ddr_kwargs["x509_proxy"] == "proxy.pem"
    assert preprocess_kwargs["x509_proxy"] == "proxy.pem"
    assert any(str(path).endswith("proxy.pem") for path in extra_files)


def test_execute_ddr_overrides_absolute_proxy_env_to_sandbox_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    staging_dir = tmp_path / "staging"
    logs_dir = tmp_path / "logs" / "taskvine"
    logs_dir.mkdir(parents=True, exist_ok=True)

    context = TaskVineContext(
        executor="taskvine",
        port_range=(9123, 9123),
        staging_dir=staging_dir,
        logs_dir=logs_dir,
        manager_name="test-manager",
        manager_template="test-manager-{pid}",
        manager_source="config",
        environment_file=None,
        extra_input_files=(),
    )
    config = RunConfig(
        executor="taskvine",
        ddr_x509_proxy=str(source_proxy),
        ddr_environment_variables={
            "X509_USER_PROXY": "/tmp/absolute_proxy_should_not_be_used.pem",
            "FOO": "BAR",
        },
        nworkers=8,
    )

    workflow = RunWorkflow(
        config=config,
        metadata={},
        sample_loader=SimpleNamespace(),
        channel_planner=SimpleNamespace(),
        histogram_planner=SimpleNamespace(),
        executor_factory=_DummyExecutorFactory(context),
        weight_variations=(),
        metadata_path="metadata.yml",
    )
    monkeypatch.setattr(
        workflow,
        "_build_ddr_processors",
        lambda **_kwargs: {"proc": object()},
    )
    monkeypatch.setattr(
        workflow,
        "_create_ddr_manager",
        lambda _context: _DummyManager(),
    )
    monkeypatch.setattr(
        workflow_module,
        "taskvine_log_configurator",
        lambda _logs_dir: (lambda _manager: None),
    )

    captured: dict[str, object] = {}

    def _fake_build_ddr_data(_flist, *, object_path: str = "Events"):
        _ = object_path
        return {"sampleA": {"files": {"/tmp/input.root": {"object_path": "Events"}}}}

    def _fake_run_ddr(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "build_ddr_data_from_flist",
        _fake_build_ddr_data,
    )
    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "run_ddr",
        _fake_run_ddr,
    )

    workflow._execute_ddr(
        histogram_plan=SimpleNamespace(tasks=()),
        samplesdict={},
        flist={},
        golden_jsons={},
        ecut_threshold=None,
        analysis_processor_module=SimpleNamespace(),
        processor_file=processor_file,
        processor_module_name="analysis_processor",
        coffea_processor_module=SimpleNamespace(),
    )

    ddr_kwargs = captured["ddr_kwargs"]
    preprocess_kwargs = captured["preprocess_kwargs"]
    assert isinstance(ddr_kwargs, dict)
    assert isinstance(preprocess_kwargs, dict)

    assert ddr_kwargs["x509_proxy"] == "proxy.pem"
    assert preprocess_kwargs["x509_proxy"] == "proxy.pem"
    assert ddr_kwargs["environment_variables"]["X509_USER_PROXY"] == "proxy.pem"
    assert preprocess_kwargs["environment_variables"]["X509_USER_PROXY"] == "proxy.pem"
    assert ddr_kwargs["environment_variables"]["FOO"] == "BAR"
    assert preprocess_kwargs["environment_variables"]["FOO"] == "BAR"


def test_execute_ddr_runs_worker_probe_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    staging_dir = tmp_path / "staging"
    logs_dir = tmp_path / "logs" / "taskvine"
    logs_dir.mkdir(parents=True, exist_ok=True)

    context = TaskVineContext(
        executor="taskvine",
        port_range=(9123, 9123),
        staging_dir=staging_dir,
        logs_dir=logs_dir,
        manager_name="test-manager",
        manager_template="test-manager-{pid}",
        manager_source="config",
        environment_file=None,
        extra_input_files=(),
    )
    config = RunConfig(
        executor="taskvine",
        ddr_x509_proxy=str(source_proxy),
        nworkers=8,
    )

    workflow = RunWorkflow(
        config=config,
        metadata={},
        sample_loader=SimpleNamespace(),
        channel_planner=SimpleNamespace(),
        histogram_planner=SimpleNamespace(),
        executor_factory=_DummyExecutorFactory(context),
        weight_variations=(),
        metadata_path="metadata.yml",
    )
    monkeypatch.setattr(
        workflow,
        "_build_ddr_processors",
        lambda **_kwargs: {"proc": object()},
    )
    monkeypatch.setattr(
        workflow,
        "_create_ddr_manager",
        lambda _context: _DummyManager(),
    )
    monkeypatch.setattr(
        workflow_module,
        "taskvine_log_configurator",
        lambda _logs_dir: (lambda _manager: None),
    )

    captured_probe: dict[str, object] = {}

    def _fake_probe(
        _manager,
        *,
        extra_files,
        environment_variables,
        run_info_path,
        test_url,
        timeout_seconds,
    ):
        captured_probe["extra_files"] = list(extra_files)
        captured_probe["environment_variables"] = dict(environment_variables)
        captured_probe["run_info_path"] = str(run_info_path)
        captured_probe["test_url"] = test_url
        captured_probe["timeout_seconds"] = timeout_seconds
        return {
            "status": "completed",
            "successful": True,
            "report_path": str(Path(run_info_path) / "ddr_worker_probe.txt"),
            "task_id": 1,
        }

    captured_run_ddr: dict[str, object] = {}

    def _fake_build_ddr_data(_flist, *, object_path: str = "Events"):
        _ = object_path
        return {"sampleA": {"files": {"/tmp/input.root": {"object_path": "Events"}}}}

    def _fake_run_ddr(**kwargs):
        captured_run_ddr.update(kwargs)
        return {}

    monkeypatch.setattr(workflow_module, "_run_ddr_worker_cert_probe_task", _fake_probe)
    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "build_ddr_data_from_flist",
        _fake_build_ddr_data,
    )
    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "run_ddr",
        _fake_run_ddr,
    )
    monkeypatch.setenv("TOPEFT_DDR_DEBUG", "1")
    monkeypatch.setenv("TOPEFT_DDR_WORKER_PROBE", "1")

    workflow._execute_ddr(
        histogram_plan=SimpleNamespace(tasks=()),
        samplesdict={},
        flist={},
        golden_jsons={},
        ecut_threshold=None,
        analysis_processor_module=SimpleNamespace(),
        processor_file=processor_file,
        processor_module_name="analysis_processor",
        coffea_processor_module=SimpleNamespace(),
    )

    assert "extra_files" in captured_probe
    assert any(str(path).endswith("proxy.pem") for path in captured_probe["extra_files"])
    env_map = captured_probe["environment_variables"]
    assert isinstance(env_map, dict)
    assert env_map["X509_USER_PROXY"] == "proxy.pem"
    assert "ddr_kwargs" in captured_run_ddr


def test_execute_ddr_preserves_original_error_when_manager_has_no_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    staging_dir = tmp_path / "staging"
    logs_dir = tmp_path / "logs" / "taskvine"
    logs_dir.mkdir(parents=True, exist_ok=True)

    context = TaskVineContext(
        executor="taskvine",
        port_range=(9123, 9123),
        staging_dir=staging_dir,
        logs_dir=logs_dir,
        manager_name="test-manager",
        manager_template="test-manager-{pid}",
        manager_source="config",
        environment_file=None,
        extra_input_files=(),
    )
    config = RunConfig(
        executor="taskvine",
        nworkers=8,
    )

    workflow = RunWorkflow(
        config=config,
        metadata={},
        sample_loader=SimpleNamespace(),
        channel_planner=SimpleNamespace(),
        histogram_planner=SimpleNamespace(),
        executor_factory=_DummyExecutorFactory(context),
        weight_variations=(),
        metadata_path="metadata.yml",
    )
    monkeypatch.setattr(
        workflow,
        "_build_ddr_processors",
        lambda **_kwargs: {"proc": object()},
    )
    monkeypatch.setattr(
        workflow,
        "_create_ddr_manager",
        lambda _context: _DummyManagerNoShutdown(),
    )
    monkeypatch.setattr(
        workflow_module,
        "taskvine_log_configurator",
        lambda _logs_dir: (lambda _manager: None),
    )

    def _fake_build_ddr_data(_flist, *, object_path: str = "Events"):
        _ = object_path
        return {"sampleA": {"files": {"/tmp/input.root": {"object_path": "Events"}}}}

    def _fake_run_ddr(**_kwargs):
        raise RuntimeError("ddr boom")

    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "build_ddr_data_from_flist",
        _fake_build_ddr_data,
    )
    monkeypatch.setattr(
        workflow_module.topcoffea.modules.dynamic_data_reduction,
        "run_ddr",
        _fake_run_ddr,
    )

    with pytest.raises(RuntimeError, match="ddr boom"):
        workflow._execute_ddr(
            histogram_plan=SimpleNamespace(tasks=()),
            samplesdict={},
            flist={},
            golden_jsons={},
            ecut_threshold=None,
            analysis_processor_module=SimpleNamespace(),
            processor_file=processor_file,
            processor_module_name="analysis_processor",
            coffea_processor_module=SimpleNamespace(),
        )
