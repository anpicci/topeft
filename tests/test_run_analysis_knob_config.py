from __future__ import annotations

from pathlib import Path

import pytest

from analysis.topeft_run2 import run_analysis
from analysis.topeft_run2.run_analysis_helpers import (
    RunConfigBuilder,
    enforce_options_single_source,
    options_allowlist,
)


def test_cli_knobs_map_to_run_config_fields() -> None:
    parser = run_analysis.build_parser()
    defaults = parser.parse_args([])
    args = parser.parse_args(
        [
            "--taskvine-manager-name",
            "apiccine-taskvine-cli",
            "--taskvine-proxy-path",
            "/tmp/proxy.pem",
            "--ddr-debug",
            "--ddr-worker-probe-enabled",
            "--ddr-worker-probe-url",
            "root://example.invalid//store/sample.root",
            "--ddr-worker-probe-timeout",
            "17",
            "--driver-log-path",
            "/tmp/driver.log",
            "--exit-marker-path",
            "/tmp/exit.marker",
            "--exit-debug",
        ]
    )

    config = RunConfigBuilder(defaults).build(args, getattr(args, "options", None))

    assert config.manager_name == "apiccine-taskvine-cli"
    assert config.ddr_x509_proxy == "/tmp/proxy.pem"
    assert config.ddr_debug is True
    assert config.ddr_worker_probe_enabled is True
    assert config.ddr_worker_probe_url == "root://example.invalid//store/sample.root"
    assert config.ddr_worker_probe_timeout == 17
    assert config.driver_log_path == "/tmp/driver.log"
    assert config.exit_marker_path == "/tmp/exit.marker"
    assert config.exit_debug is True


def test_yaml_knobs_map_to_run_config_fields(tmp_path: Path) -> None:
    options_file = tmp_path / "knobs.yml"
    options_file.write_text(
        "\n".join(
            [
                "defaults:",
                "  taskvine_manager_name: apiccine-taskvine-yaml",
                "  taskvine_proxy_path: /tmp/yaml_proxy.pem",
                "  ddr_debug: true",
                "  ddr_worker_probe_enabled: true",
                "  ddr_worker_probe_url: root://example.invalid//store/yaml.root",
                "  ddr_worker_probe_timeout: 29",
                "  driver_log_path: /tmp/yaml_driver.log",
                "  exit_marker_path: /tmp/yaml_exit.marker",
                "  exit_debug: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parser = run_analysis.build_parser()
    defaults = parser.parse_args([])
    args = parser.parse_args(["--options", str(options_file)])
    config = RunConfigBuilder(defaults).build(args, getattr(args, "options", None))

    assert config.options_path == str(options_file)
    assert config.manager_name == "apiccine-taskvine-yaml"
    assert config.ddr_x509_proxy == "/tmp/yaml_proxy.pem"
    assert config.ddr_debug is True
    assert config.ddr_worker_probe_enabled is True
    assert config.ddr_worker_probe_url == "root://example.invalid//store/yaml.root"
    assert config.ddr_worker_probe_timeout == 29
    assert config.driver_log_path == "/tmp/yaml_driver.log"
    assert config.exit_marker_path == "/tmp/yaml_exit.marker"
    assert config.exit_debug is True


def test_options_mode_rejects_new_knob_flags(capsys: pytest.CaptureFixture[str]) -> None:
    parser = run_analysis.build_parser()
    argv = [
        "--options",
        "configs/fullR2_run.yml:cr",
        "--ddr-debug",
    ]
    with pytest.raises(SystemExit) as excinfo:
        enforce_options_single_source(parser, argv, options_allowlist(parser))
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "--ddr-debug" in captured.err
    assert "--options" in captured.err


@pytest.mark.parametrize(
    ("legacy_key", "replacement_key"),
    [
        ("manager_name", "taskvine_manager_name"),
        ("manager_name_template", "taskvine_manager_name_template"),
        ("ddr_x509_proxy", "taskvine_proxy_path"),
    ],
)
def test_yaml_legacy_knobs_are_rejected(
    tmp_path: Path,
    legacy_key: str,
    replacement_key: str,
) -> None:
    options_file = tmp_path / "legacy_knob.yml"
    options_file.write_text(
        "\n".join(
            [
                "defaults:",
                f"  {legacy_key}: /tmp/legacy-value",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    parser = run_analysis.build_parser()
    defaults = parser.parse_args([])
    args = parser.parse_args(["--options", str(options_file)])

    with pytest.raises(KeyError) as excinfo:
        RunConfigBuilder(defaults).build(args, getattr(args, "options", None))
    assert legacy_key in str(excinfo.value)
    assert replacement_key in str(excinfo.value)
