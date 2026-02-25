import importlib.util
import sys
from pathlib import Path

import pytest

from topeft.modules.logging_config import configure_topeft_logging

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
        configure_topeft_logging("INFO", executor="taskvine")


def test_debug_log_level_allowed():
    assert run_analysis_helpers.coerce_log_level("debug") == "DEBUG"


def test_coerce_log_level_none_normalized():
    result = run_analysis_helpers.coerce_log_level("none")
    assert result == "NONE"


class DummyConfig:
    def __init__(self, log_level):
        self.log_level = log_level


def test_resolve_effective_log_level_defaults_to_info():
    cfg = DummyConfig(log_level=None)
    assert run_analysis_helpers._resolve_effective_log_level(cfg) == "INFO"


def test_resolve_effective_log_level_accepts_warning():
    cfg = DummyConfig(log_level="WARNING")
    assert run_analysis_helpers._resolve_effective_log_level(cfg) == "WARNING"


def test_non_taskvine_executor_allows_any_level():
    configure_topeft_logging("INFO", executor="futures")
    configure_topeft_logging("NONE", executor="futures")
