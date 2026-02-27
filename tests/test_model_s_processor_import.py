from __future__ import annotations

import sys
from pathlib import Path

import pytest

from analysis.topeft_run2.workflow import (
    _collect_processor_extra_files,
    _load_processor_module_from_file,
    _resolve_processor_file_path,
)


def test_resolve_processor_file_path_rejects_non_python_file() -> None:
    with pytest.raises(ValueError):
        _resolve_processor_file_path("analysis_processor.txt")


def test_resolve_processor_file_path_finds_relative_processor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processor_file = tmp_path / "dummy_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_processor_file_path("dummy_processor.py")
    assert resolved == processor_file.resolve()


def test_load_processor_module_from_file_imports_by_stem(tmp_path: Path) -> None:
    module_name = "dummy_model_s_processor"
    processor_file = tmp_path / f"{module_name}.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    sys.modules.pop(module_name, None)

    module, resolved_name = _load_processor_module_from_file(processor_file.resolve())

    assert resolved_name == module_name
    assert module.AnalysisProcessor.__module__ == module_name
    assert "analysis." not in module.AnalysisProcessor.__module__
    sys.modules.pop(module_name, None)


def test_load_processor_module_from_file_requires_symbol(tmp_path: Path) -> None:
    module_name = "missing_symbol_processor"
    processor_file = tmp_path / f"{module_name}.py"
    processor_file.write_text("VALUE = 1\n", encoding="utf-8")
    sys.modules.pop(module_name, None)

    with pytest.raises(AttributeError):
        _load_processor_module_from_file(processor_file.resolve())
    sys.modules.pop(module_name, None)


def test_collect_processor_extra_files_includes_processor_and_helpers(tmp_path: Path) -> None:
    processor_file = tmp_path / "analysis_processor.py"
    processor_file.write_text("class AnalysisProcessor: pass\n", encoding="utf-8")
    helpers_dir = tmp_path / "analysis_processor_helpers"
    helpers_dir.mkdir(parents=True)
    helper_file = helpers_dir / "utility.py"
    helper_file.write_text("VALUE = 1\n", encoding="utf-8")

    extras = _collect_processor_extra_files(processor_file)
    assert extras[0] == str(processor_file.resolve())
    assert str(helper_file.resolve()) in extras
