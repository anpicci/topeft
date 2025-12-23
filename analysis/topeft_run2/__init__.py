"""Run 2 analysis scripts and workflow helpers."""

try:
    from .workflow import (
        ChannelPlanner,
        ExecutorFactory,
        HistogramPlan,
        HistogramPlanner,
        HistogramTask,
        RunWorkflow,
        normalize_jet_category,
        run_workflow,
    )
    _WORKFLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - optional workflow helper
    ChannelPlanner = None  # type: ignore[assignment]
    ExecutorFactory = None  # type: ignore[assignment]
    HistogramPlan = None  # type: ignore[assignment]
    HistogramPlanner = None  # type: ignore[assignment]
    HistogramTask = None  # type: ignore[assignment]
    normalize_jet_category = None  # type: ignore[assignment]
    run_workflow = None  # type: ignore[assignment]
    RunWorkflow = None  # type: ignore[assignment]
    _WORKFLOW_AVAILABLE = False
from .quickstart import PreparedSamples, prepare_samples, run_quickstart

__all__ = ["PreparedSamples", "prepare_samples", "run_quickstart"]
if _WORKFLOW_AVAILABLE:
    __all__.extend(
        [
            "ChannelPlanner",
            "ExecutorFactory",
            "HistogramPlan",
            "HistogramPlanner",
            "HistogramTask",
            "normalize_jet_category",
            "run_workflow",
        ]
    )
    if RunWorkflow is not None:
        __all__.append("RunWorkflow")
