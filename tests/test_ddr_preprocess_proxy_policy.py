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


def test_stage_ddr_proxy_copies_to_proxy_pem(tmp_path: Path) -> None:
    source_proxy = tmp_path / "user_proxy.pem"
    source_proxy.write_text("proxy-data", encoding="utf-8")
    staging_dir = tmp_path / "staging"

    staged_proxy = stage_ddr_proxy(str(source_proxy), staging_dir=staging_dir)

    assert staged_proxy == staging_dir / "proxy.pem"
    assert staged_proxy.exists()
    assert staged_proxy.read_text(encoding="utf-8") == "proxy-data"


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
    assert str(ddr_kwargs["x509_proxy"]).endswith("proxy.pem")
    assert any(str(path).endswith("proxy.pem") for path in extra_files)
