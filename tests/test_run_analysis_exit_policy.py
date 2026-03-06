from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from analysis.topeft_run2 import run_analysis


def _install_minimal_runtime_stubs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    run_workflow_impl,
) -> None:
    metadata_bundle = types.SimpleNamespace(metadata_path=tmp_path / "metadata.yml")
    fake_workflow_module = types.ModuleType("analysis.topeft_run2.workflow")
    fake_workflow_module.run_workflow = run_workflow_impl
    monkeypatch.setattr(run_analysis, "_verify_numpy_abi", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "_apply_scenario_metadata_defaults",
        lambda _config, _metadata_cli: ("TOP_22_006", metadata_bundle, "test"),
    )
    monkeypatch.setattr(
        run_analysis,
        "configure_topeft_logging",
        lambda *_args, **_kwargs: "INFO",
    )
    monkeypatch.setitem(sys.modules, "analysis.topeft_run2.workflow", fake_workflow_module)


def test_main_options_conflict_exits_with_code_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        run_analysis.main(["--options", "configs/fullR2_run.yml:cr", "--ddr-debug"])
    assert excinfo.value.code == 2


def test_main_metadata_error_uses_exit_code_2_and_writes_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker_path = tmp_path / "metadata_error.exit"
    monkeypatch.setattr(run_analysis, "_verify_numpy_abi", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "_apply_scenario_metadata_defaults",
        lambda _config, _metadata_cli: (_ for _ in ()).throw(ValueError("bad metadata config")),
    )

    with pytest.raises(SystemExit) as excinfo:
        run_analysis.main(["--exit-marker-path", str(marker_path)])

    assert excinfo.value.code == 2
    assert marker_path.read_text(encoding="utf-8").strip() == "2"


def test_main_keyboard_interrupt_maps_to_130_and_writes_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker_path = tmp_path / "keyboard_interrupt.exit"
    _install_minimal_runtime_stubs(
        monkeypatch,
        tmp_path,
        run_workflow_impl=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        run_analysis.main(
            [
                "--executor",
                "futures",
                "--exit-marker-path",
                str(marker_path),
                "--exit-debug",
            ]
        )

    captured = capsys.readouterr()
    assert "driver_status=130" in captured.err
    assert marker_path.read_text(encoding="utf-8").strip() == "130"


def test_main_runtime_exception_maps_to_1_and_writes_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker_path = tmp_path / "runtime_error.exit"
    _install_minimal_runtime_stubs(
        monkeypatch,
        tmp_path,
        run_workflow_impl=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        run_analysis.main(
            [
                "--executor",
                "futures",
                "--exit-marker-path",
                str(marker_path),
                "--exit-debug",
            ]
        )

    captured = capsys.readouterr()
    assert "driver_status=1" in captured.err
    assert marker_path.read_text(encoding="utf-8").strip() == "1"
