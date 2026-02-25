"""Centralized logging configuration for topeft."""

from __future__ import annotations

import logging
import os
from typing import Optional

from analysis.topeft_run2 import logging_utils
from analysis.topeft_run2.run_analysis_helpers import (
    VALID_LOG_LEVELS,
    VALID_LOG_LEVELS_DISPLAY,
)

logger = logging.getLogger(__name__)
_TASKVINE_LOG_NOISE_WARNING_EMITTED = False


def _is_truthy_env(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_log_level(log_level: Optional[str]) -> str:
    normalized = (log_level or "INFO").strip().upper()
    if normalized not in VALID_LOG_LEVELS:
        raise ValueError(
            f"log level '{normalized}' is not supported. Use one of: {VALID_LOG_LEVELS_DISPLAY}."
        )
    return normalized


def _normalize_executor_name(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _warn_taskvine_logging_policy(executor: str, log_level: str) -> None:
    global _TASKVINE_LOG_NOISE_WARNING_EMITTED
    if executor != "taskvine":
        return
    normalized_level = (log_level or "").strip().upper()
    if normalized_level == "NONE" or _TASKVINE_LOG_NOISE_WARNING_EMITTED:
        return
    logger.warning(
        "TaskVine worker output can be noisy at --log-level %s. "
        "Using '--log-level none' is optional; consider "
        "'--no-taskvine-print-stdout' to suppress forwarded worker stdout.",
        normalized_level.lower(),
    )
    _TASKVINE_LOG_NOISE_WARNING_EMITTED = True


def dev_debug_enabled(*, allow_dev_debug: bool = True) -> bool:
    """Return whether TOPEFT_DEV_DEBUG should force debug logging."""

    if not allow_dev_debug:
        return False
    return _is_truthy_env(os.environ.get("TOPEFT_DEV_DEBUG"))


def configure_topeft_logging(
    log_level: Optional[str],
    *,
    executor: Optional[str] = None,
    allow_dev_debug: bool = True,
) -> str:
    """Configure logging and return the effective log level name."""

    normalized_level = _normalize_log_level(log_level)
    normalized_executor = _normalize_executor_name(executor)
    if normalized_executor:
        _warn_taskvine_logging_policy(normalized_executor, normalized_level)
    if normalized_executor == "taskvine":
        allow_dev_debug = False

    dev_debug = dev_debug_enabled(allow_dev_debug=allow_dev_debug)
    logging_utils.configure_logging(
        normalized_level,
        allow_dev_debug=allow_dev_debug,
        dev_debug_enabled=dev_debug,
    )

    if normalized_level == "NONE":
        effective_level = "NONE"
    elif dev_debug or normalized_level == "DEBUG":
        effective_level = "DEBUG"
    else:
        effective_level = normalized_level

    return effective_level


__all__ = ["configure_topeft_logging", "dev_debug_enabled"]
