from __future__ import annotations

from types import SimpleNamespace

from analysis.topeft_run2 import run_analysis


def test_run_analysis_executor_cli_uses_topeft_remote_environment(monkeypatch) -> None:
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

    parser = run_analysis.build_parser()
    args = parser.parse_args(["--executor", "taskvine", "--environment-file", "auto"])
    config = run_analysis.EXECUTOR_CLI.parse_args(args)

    assert run_analysis.remote_environment.__name__ == "topeft.modules.remote_environment"
    assert config.environment_file == "/tmp/topeft-wrapper-env.tar.gz"
    assert calls["extra_pip_local"]["topeft"] == ["topeft", "setup.py"]
    assert calls["extra_pip_local"]["dynamic_data_reduction"] == ["src", "pyproject.toml"]
