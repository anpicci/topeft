"""Lightweight helpers for configuring Python logging in run_analysis."""

from __future__ import annotations

import logging
import os
from typing import Optional

try:  # pragma: no cover - tqdm is bundled with coffea
    from tqdm.contrib.logging import TqdmLoggingHandler
except Exception:  # pragma: no cover - fallback when tqdm is unavailable
    TqdmLoggingHandler = None  # type: ignore[assignment]

from .run_analysis_helpers import VALID_LOG_LEVELS, VALID_LOG_LEVELS_DISPLAY

logger = logging.getLogger(__name__)
_configured = False


def _level_name_to_numeric(level_name: str) -> int:
    resolved = getattr(logging, level_name.upper(), None)
    if not isinstance(resolved, int):
        raise ValueError(f"Unknown logging level '{level_name}'.")
    return resolved


def _is_truthy_env(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configure_logging(
    level_name: str,
    *,
    formatter: Optional[str] = None,
    allow_dev_debug: bool = True,
) -> None:
    """Configure root logging handlers with a consistent format.

    The helper intentionally keeps the configuration minimal: a single stream
    handler with timestamps and module names. In multi-process futures runs
    the configuration only applies to the main process for now—workers inherit
    coffea's defaults until we plumb per-process hooks.

    Args:
        level_name: Normalized log level string (NONE/INFO/WARNING/ERROR).
        formatter: Optional format string for the handler.
        allow_dev_debug: When True, TOPEFT_DEV_DEBUG=1 forces DEBUG on project
            loggers even if the requested level is higher. Ignored when False.
    """

    global _configured

    normalized_level = (level_name or "").strip().upper()
    if normalized_level not in VALID_LOG_LEVELS:
        raise ValueError(
            f"log level '{level_name}' is not in {VALID_LOG_LEVELS_DISPLAY}"
        )

    dev_debug_enabled = allow_dev_debug and _is_truthy_env(
        os.environ.get("TOPEFT_DEV_DEBUG"),
    )
    mute_project_loggers = normalized_level == "NONE" and not dev_debug_enabled

    effective_level_name = "DEBUG" if dev_debug_enabled else normalized_level
    project_level = (
        logging.CRITICAL + 10 if mute_project_loggers else _level_name_to_numeric(effective_level_name)
    )
    root_level = (
        _level_name_to_numeric("WARNING")
        if mute_project_loggers
        else _level_name_to_numeric(effective_level_name)
    )

    root = logging.getLogger()

    # Avoid stacking multiple handlers when run_analysis.py is imported or invoked
    # repeatedly; reuse existing root handlers whenever they are present.
    attach_handler = not root.handlers
    if attach_handler:
        # Prefer tqdm-aware logging so progress bars and INFO lines do not stomp
        # on each other; fall back to a plain stream handler if tqdm is missing.
        if TqdmLoggingHandler is not None:
            handler: logging.Handler = TqdmLoggingHandler()
        else:
            handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                formatter or "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        root.addHandler(handler)
        logger.debug(
            "configure_logging applied (effective_level=%s)", effective_level_name
        )

    # Root already had handlers (for example when run_analysis.py is imported in a
    # larger application); reuse them instead of stacking duplicates and update
    # their levels to follow the latest CLI request.
    for handler in root.handlers:
        handler.setLevel(root_level)

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
        project_logger.propagate = True

    root.setLevel(root_level)
    _configured = True
