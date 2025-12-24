"""Lightweight helpers for configuring Python logging in run_analysis."""

from __future__ import annotations

import logging
from typing import Optional

try:  # pragma: no cover - tqdm is bundled with coffea
    from tqdm.contrib.logging import TqdmLoggingHandler
except Exception:  # pragma: no cover - fallback when tqdm is unavailable
    TqdmLoggingHandler = None  # type: ignore[assignment]

from .run_analysis_helpers import VALID_LOG_LEVELS, VALID_LOG_LEVELS_DISPLAY

logger = logging.getLogger(__name__)
_configured = False
_project_handler: Optional[logging.Handler] = None

LOG_LEVEL_MAP = {
    "NONE": logging.CRITICAL + 10,
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _level_name_to_numeric(level_name: str) -> int:
    resolved = LOG_LEVEL_MAP.get(level_name.strip().upper())
    if resolved is None:
        raise ValueError(f"Unknown logging level '{level_name}'.")
    return resolved


def configure_logging(
    level_name: str,
    *,
    formatter: Optional[str] = None,
    allow_dev_debug: bool = True,
    dev_debug_enabled: Optional[bool] = None,
) -> None:
    """Configure root logging handlers with a consistent format.

    The helper intentionally keeps the configuration minimal: a single stream
    handler with timestamps and module names. In multi-process futures runs
    the configuration only applies to the main process for now—workers inherit
    coffea's defaults until we plumb per-process hooks.

    Args:
        level_name: Normalized log level string (NONE/INFO/WARNING/ERROR).
        formatter: Optional format string for the handler.
        allow_dev_debug: When True, ``dev_debug_enabled`` may force DEBUG on
            project loggers even if the requested level is higher.
        dev_debug_enabled: Explicitly enable developer debug overrides. This is
            provided by the centralized logging policy entrypoint.
    """

    global _configured

    normalized_level = (level_name or "").strip().upper()
    if normalized_level not in VALID_LOG_LEVELS:
        raise ValueError(
            f"log level '{level_name}' is not in {VALID_LOG_LEVELS_DISPLAY}"
        )

    dev_debug_enabled = bool(dev_debug_enabled) and allow_dev_debug
    effective_level_name = (
        "DEBUG" if (normalized_level == "DEBUG" or dev_debug_enabled) else normalized_level
    )
    mute_project_loggers = normalized_level == "NONE"
    project_level = (
        _level_name_to_numeric(effective_level_name)
        if not mute_project_loggers
        else _level_name_to_numeric("NONE")
    )
    root_level = (
        _level_name_to_numeric("NONE")
        if mute_project_loggers
        else _level_name_to_numeric("INFO")
    )

    root = logging.getLogger()

    # Avoid stacking multiple handlers when run_analysis.py is imported or invoked
    # repeatedly; reuse existing root handlers whenever they are present.
    attach_handler = not root.handlers
    format_string = formatter or "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if attach_handler:
        # Prefer tqdm-aware logging so progress bars and INFO lines do not stomp
        # on each other; fall back to a plain stream handler if tqdm is missing.
        if TqdmLoggingHandler is not None:
            handler: logging.Handler = TqdmLoggingHandler()
        else:
            handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(format_string))
        root.addHandler(handler)
        logger.debug(
            "configure_logging applied (effective_level=%s)", effective_level_name
        )

    # Root already had handlers (for example when run_analysis.py is imported in a
    # larger application); reuse them instead of stacking duplicates and update
    # their levels to follow the latest CLI request.
    for handler in root.handlers:
        handler.setLevel(root_level)
        handler.setFormatter(logging.Formatter(format_string))

    global _project_handler
    if _project_handler is None:
        if TqdmLoggingHandler is not None:
            _project_handler = TqdmLoggingHandler()
        else:
            _project_handler = logging.StreamHandler()
    _project_handler.setFormatter(logging.Formatter(format_string))
    _project_handler.setLevel(project_level)

    project_logger_names = (
        "topeft",
        "topcoffea",
        "analysis",
        "analysis.topeft_run2",
    )
    for name in project_logger_names:
        project_logger = logging.getLogger(name)
        project_logger.setLevel(project_level)
        project_logger.disabled = mute_project_loggers and not dev_debug_enabled
        project_logger.propagate = False
        if _project_handler not in project_logger.handlers:
            project_logger.addHandler(_project_handler)

    root.setLevel(root_level)
    if dev_debug_enabled and not mute_project_loggers:
        logger.info(
            "TOPEFT_DEV_DEBUG detected: forcing project loggers to DEBUG (root remains INFO)."
        )
    _configured = True
