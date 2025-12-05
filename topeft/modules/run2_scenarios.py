"""Deprecated shim for :mod:`topeft.modules.scenario_groups`."""

from .scenario_groups import *  # noqa: F401,F403
import warnings

warnings.warn(
    "topeft.modules.run2_scenarios is deprecated; use topeft.modules.scenario_groups instead.",
    DeprecationWarning,
    stacklevel=2,
)
