"""Exercise the workflow import shims for topcoffea helpers."""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest


def _clear_modules(monkeypatch: pytest.MonkeyPatch, *module_names: str) -> None:
    for name in module_names:
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_workflow_imports_topcoffea_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_modules(
        monkeypatch,
        "analysis.topeft_run2",
        "analysis.topeft_run2.workflow",
        "topcoffea.modules.paths",
        "topcoffea.modules.utils",
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        module = importlib.import_module("analysis.topeft_run2.workflow")

    assert callable(module._import_topcoffea_submodule)
    assert module.topcoffea_utils is not None
    assert "topcoffea.modules.utils" in sys.modules


def test_workflow_imports_missing_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_modules(
        monkeypatch, "analysis.topeft_run2", "analysis.topeft_run2.workflow", "topcoffea.modules.utils"
    )

    real_import_module = importlib.import_module

    def _raise_for_utils(name: str, *args, **kwargs):
        if name.endswith(".modules.utils"):
            raise ModuleNotFoundError("utils module unavailable")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _raise_for_utils)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        with pytest.raises(ImportError, match="coordinated ref"):
            importlib.import_module("analysis.topeft_run2.workflow")
