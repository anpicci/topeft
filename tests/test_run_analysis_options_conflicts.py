import argparse

import pytest

from analysis.topeft_run2.run_analysis_helpers import (
    enforce_options_single_source,
    find_options_conflicts,
    options_allowlist,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--options")
    parser.add_argument("--metadata")
    parser.add_argument("--executor", "-x")
    parser.add_argument("--chunksize", "-s")
    return parser


def test_options_with_metadata_errors(capsys: pytest.CaptureFixture[str]) -> None:
    parser = _build_parser()
    allowlist = options_allowlist(parser)
    argv = ["--options", "opts.yml", "--metadata", "meta.yml"]
    conflicts = find_options_conflicts(argv, parser, allowlist)
    assert conflicts == ["--metadata"]
    with pytest.raises(SystemExit) as excinfo:
        enforce_options_single_source(parser, argv, allowlist)
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "--metadata" in captured.err
    assert "--options" in captured.err
    assert "cannot be used" in captured.err


def test_options_with_executor_errors() -> None:
    parser = _build_parser()
    allowlist = options_allowlist(parser)
    argv = ["--options", "opts.yml", "-x", "taskvine"]
    conflicts = find_options_conflicts(argv, parser, allowlist)
    assert conflicts == ["--executor"]
    with pytest.raises(SystemExit) as excinfo:
        enforce_options_single_source(parser, argv, allowlist)
    assert excinfo.value.code == 2


def test_options_only_is_allowed() -> None:
    parser = _build_parser()
    allowlist = options_allowlist(parser)
    argv = ["--options", "opts.yml"]
    conflicts = find_options_conflicts(argv, parser, allowlist)
    assert conflicts == []


def test_options_with_help_is_allowed() -> None:
    parser = _build_parser()
    allowlist = options_allowlist(parser)
    argv = ["--options", "opts.yml", "--help"]
    conflicts = find_options_conflicts(argv, parser, allowlist)
    assert conflicts == []
