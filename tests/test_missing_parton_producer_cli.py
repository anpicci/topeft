from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "topeft_run2"
    / "missing_parton.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "missing_parton_producer_cli_under_test",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_config(module, *arguments):
    parser = module.build_arg_parser()
    return module.resolve_config(parser.parse_args(list(arguments)))


def test_historical_flags_remain_accepted_and_resolve_legacy_paths():
    module = load_module()

    config = parse_config(
        module,
        "--years",
        "2022",
        "2023",
        "--time",
        "--output-path",
        "/tmp/diagnostics",
        "--var",
        "njets",
        "--dry-run",
    )

    assert config.input_mode == "legacy"
    assert config.central_card_dir == module.LEGACY_CENTRAL_CARD_DIR
    assert config.private_card_dir == module.LEGACY_PRIVATE_CARD_DIR
    assert config.years == ("2022", "2023")
    assert config.time is True
    assert config.output_path == Path("/tmp/diagnostics")
    assert config.var == "njets"


def test_explicit_card_directories_override_legacy_resolution(tmp_path):
    module = load_module()
    central = tmp_path / "central"
    private = tmp_path / "private"

    config = parse_config(
        module,
        "--central-card-dir",
        str(central),
        "--private-card-dir",
        str(private),
        "--dry-run",
    )

    assert config.input_mode == "explicit"
    assert config.central_card_dir == central
    assert config.private_card_dir == private


def test_candidate_cli_aliases_are_additive(tmp_path):
    module = load_module()
    output = tmp_path / "payload.root"

    config = parse_config(
        module,
        "--central-dir",
        str(tmp_path / "central"),
        "--private-dir",
        str(tmp_path / "private"),
        "--output-payload",
        str(output),
        "--allow-overwrite",
        "--dry-run",
    )

    assert config.output_file == output
    assert config.overwrite is True


def test_explicit_card_directories_must_be_supplied_together(tmp_path):
    module = load_module()

    with pytest.raises(module.ConfigError, match="must be supplied together"):
        parse_config(
            module,
            "--central-card-dir",
            str(tmp_path / "central"),
        )


def test_non_njets_observable_is_rejected_after_argument_parsing():
    module = load_module()

    with pytest.raises(module.ConfigError, match="only for --var njets"):
        parse_config(module, "--var", "ptz")


def test_existing_output_is_rejected_without_overwrite(tmp_path):
    module = load_module()
    output = tmp_path / "payload.root"
    output.write_bytes(b"existing")

    with pytest.raises(module.ConfigError, match="Refusing to overwrite"):
        parse_config(module, "--output-file", str(output), "--dry-run")


def test_existing_output_is_accepted_only_with_overwrite(tmp_path):
    module = load_module()
    output = tmp_path / "payload.root"
    output.write_bytes(b"existing")

    config = parse_config(
        module,
        "--output-file",
        str(output),
        "--overwrite",
        "--dry-run",
    )

    assert config.output_file == output
    assert config.overwrite is True


def test_dry_run_builds_complete_plan_and_never_calls_writer(
    monkeypatch,
    tmp_path,
):
    module = load_module()
    calls = []
    expected_plan = module.payload_plan(categories=())
    config = module.ResolvedConfig(
        central_card_dir=tmp_path / "central",
        private_card_dir=tmp_path / "private",
        output_file=tmp_path / "payload.root",
        output_path=tmp_path,
        input_mode="explicit",
        dry_run=True,
        overwrite=False,
        years=("2022",),
        time=False,
        var="njets",
    )

    def build_plan(observed_config):
        calls.append(("build", observed_config))
        return expected_plan

    def fail_writer(*args, **kwargs):
        raise AssertionError("dry-run attempted to write a payload")

    monkeypatch.setattr(module, "build_payload_plan", build_plan)
    monkeypatch.setattr(module, "write_legacy_payload_atomic", fail_writer)

    plan, output_sha256 = module.run_producer(config)

    assert calls == [("build", config)]
    assert plan is expected_plan
    assert output_sha256 is None
    assert not config.output_file.exists()


def test_dry_run_plan_prints_neutralized_physical_bins():
    module = load_module()
    category = module.category_payload_plan(
        base_channel="2lss_m_1tau_onZ",
        central_process_name="tZq_sm",
        private_process_name="tllq_sm",
        central_integral=1.0,
        private_integral=0.0,
        neutralized_physical_njets=(2, 7),
        stored_values=np.zeros(7),
    )

    plan = module.payload_plan(categories=(category,))
    printable = plan.to_printable_dict()

    assert printable["neutralized_bins"] == [
        {"base_channel": "2lss_m_1tau_onZ", "physical_njet": 2},
        {"base_channel": "2lss_m_1tau_onZ", "physical_njet": 7},
    ]
    assert printable["categories"][0]["neutralized_physical_njets"] == [2, 7]


def test_invalid_input_leaves_existing_output_byte_for_byte_unchanged(
    monkeypatch,
    tmp_path,
):
    module = load_module()
    output = tmp_path / "payload.root"
    original = b"pre-existing-payload"
    output.write_bytes(original)
    config = module.ResolvedConfig(
        central_card_dir=tmp_path / "central",
        private_card_dir=tmp_path / "private",
        output_file=output,
        output_path=tmp_path,
        input_mode="explicit",
        dry_run=False,
        overwrite=True,
        years=("2022",),
        time=False,
        var="njets",
    )
    monkeypatch.setattr(
        module,
        "build_payload_plan",
        lambda _: (_ for _ in ()).throw(ValueError("invalid input")),
    )

    with pytest.raises(ValueError, match="invalid input"):
        module.run_producer(config)

    assert output.read_bytes() == original


def test_help_documents_legacy_and_explicit_modes_deterministically():
    module = load_module()

    help_text = module.build_arg_parser().format_help()

    for option in (
        "--years",
        "--time",
        "--output-path",
        "--var",
        "--central-card-dir",
        "--private-card-dir",
        "--output-file",
        "--dry-run",
        "--overwrite",
    ):
        assert option in help_text
    assert "34-TTree" in help_text
