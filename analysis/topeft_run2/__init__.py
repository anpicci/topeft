"""Run 2 analysis scripts and workflow helpers."""

from __future__ import annotations

from importlib import import_module as _import_module
from typing import Any

_QUICKSTART_EXPORTS = (
    "PreparedSamples",
    "prepare_samples",
    "run_quickstart",
)
_WORKFLOW_EXPORTS = (
    "ChannelPlanner",
    "ExecutorFactory",
    "HistogramPlan",
    "HistogramPlanner",
    "HistogramTask",
    "RunWorkflow",
    "normalize_jet_category",
    "run_workflow",
)

__all__ = [*_QUICKSTART_EXPORTS, *_WORKFLOW_EXPORTS]


def __getattr__(name: str) -> Any:
    if name in _QUICKSTART_EXPORTS:
        module = _import_module("analysis.topeft_run2.quickstart")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _WORKFLOW_EXPORTS:
        module = _import_module("analysis.topeft_run2.workflow")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'analysis.topeft_run2' has no attribute {name!r}")
