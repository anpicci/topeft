import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

_HELPERS_PATH = Path(__file__).resolve().parents[1] / "analysis" / "topeft_run2" / "run_analysis_helpers.py"
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "analysis.topeft_run2.run_analysis_helpers",
    _HELPERS_PATH,
)
assert _HELPERS_SPEC and _HELPERS_SPEC.loader
run_analysis_helpers = importlib.util.module_from_spec(_HELPERS_SPEC)
sys.modules[_HELPERS_SPEC.name] = run_analysis_helpers
_HELPERS_SPEC.loader.exec_module(run_analysis_helpers)


def test_taskvine_requires_silent_log_level():
    with pytest.raises(
        ValueError,
        match="TaskVine runs require '--log-level none'",
    ):
        run_analysis_helpers._enforce_taskvine_logging_policy("taskvine", "INFO")


def test_debug_log_level_rejected():
    with pytest.raises(
        ValueError,
        match="DEBUG log level is reserved for internal development",
    ):
        run_analysis_helpers.coerce_log_level("debug")


def test_legacy_debug_flags_fail():
    with pytest.raises(
        ValueError,
        match="--debug-logging flag has been removed",
    ):
        run_analysis_helpers._reject_legacy_debug_flags(
            argparse.Namespace(debug_logging=True, processor_debug=False),
        )

    with pytest.raises(
        ValueError,
        match="--processor-debug flag has been removed",
    ):
        run_analysis_helpers._reject_legacy_debug_flags(
            argparse.Namespace(debug_logging=False, processor_debug=True),
        )
