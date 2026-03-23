from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from analysis.topeft_run2 import run_analysis


def _create_fake_ddr_repo(parent: Path) -> Path:
    ddr_root = parent / "dynamic_data_reduction"
    (ddr_root / "src").mkdir(parents=True)
    (ddr_root / "pyproject.toml").write_text(
        "[project]\nname = 'dynamic_data_reduction'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    return ddr_root


def test_run_analysis_executor_cli_uses_topeft_remote_environment(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def _fake_delegate_get_environment(**kwargs):
        calls.update(kwargs)
        return "/tmp/topeft-wrapper-env.tar.gz"

    fake_delegate = SimpleNamespace(get_environment=_fake_delegate_get_environment)
    monkeypatch.setattr(
        run_analysis.remote_environment.topcoffea,
        "import_module",
        lambda name: fake_delegate,
    )
    ddr_root = _create_fake_ddr_repo(tmp_path)
    monkeypatch.setenv("TOPEFT_DDR_REPO", str(ddr_root))

    parser = run_analysis.build_parser()
    args = parser.parse_args(["--executor", "taskvine", "--environment-file", "auto"])
    config = run_analysis.EXECUTOR_CLI.parse_args(args)

    assert run_analysis.remote_environment.__name__ == "topeft.modules.remote_environment"
    assert config.environment_file == "/tmp/topeft-wrapper-env.tar.gz"
    assert calls["extra_pip_local"]["topeft"] == ["topeft", "setup.py"]
    assert calls["extra_pip_local"]["dynamic_data_reduction"] == [
        str(ddr_root / "src"),
        str(ddr_root / "pyproject.toml"),
    ]
