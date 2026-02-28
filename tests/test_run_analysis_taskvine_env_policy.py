from __future__ import annotations

import sys
import types
from pathlib import Path

from analysis.topeft_run2 import run_analysis
from analysis.topeft_run2.run_analysis_helpers import RunConfig


def test_equivalent_cli_includes_environment_file_for_taskvine() -> None:
    config = RunConfig(
        executor="taskvine",
        environment_file="/tmp/model-s-env.tar.gz",
    )

    rendered = run_analysis._build_equivalent_cli_call(
        config,
        scenario_name="TOP_22_006",
        metadata_path="/tmp/metadata.yml",
    )

    assert "--environment-file" in rendered
    assert "/tmp/model-s-env.tar.gz" in rendered


def test_main_warns_for_taskvine_environment_file_but_keeps_value(
    monkeypatch,
    tmp_path: Path,
) -> None:
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")

    captured: dict[str, object] = {}
    metadata_bundle = types.SimpleNamespace(metadata_path=tmp_path / "metadata.yml")

    def _fake_run_workflow(config, metadata_bundle):
        captured["config"] = config
        captured["metadata_bundle"] = metadata_bundle

    fake_workflow_module = types.ModuleType("analysis.topeft_run2.workflow")
    fake_workflow_module.run_workflow = _fake_run_workflow
    warning_messages: list[str] = []

    def _record_warning(message: str, *args, **_kwargs) -> None:
        warning_messages.append(message % args if args else message)

    monkeypatch.setattr(run_analysis, "_verify_numpy_abi", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "_apply_scenario_metadata_defaults",
        lambda _config, _metadata_cli: ("TOP_22_006", metadata_bundle, "test"),
    )
    monkeypatch.setattr(
        run_analysis,
        "configure_topeft_logging",
        lambda *_args, **_kwargs: "info",
    )
    monkeypatch.setattr(run_analysis.logger, "warning", _record_warning)
    monkeypatch.setitem(sys.modules, "analysis.topeft_run2.workflow", fake_workflow_module)

    run_analysis.main(
        [
            "--executor",
            "taskvine",
            "--environment-file",
            "/tmp/model-s-env.tar.gz",
            "--processor",
            str(processor_file),
        ]
    )

    assert any(
        "TaskVine DDR Model S recommends worker '--python-env <tarball>' submission."
        in message
        for message in warning_messages
    )
    assert captured["config"].environment_file == "/tmp/model-s-env.tar.gz"
