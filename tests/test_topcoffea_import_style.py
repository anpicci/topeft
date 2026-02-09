"""Ensure top-level topcoffea imports follow the namespace style."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXCLUDED_TOP_LEVEL = {"topcoffea", "tests", "build"}
_BANNED_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*from\s+topcoffea\."), "use 'import topcoffea' and attribute access"),
    (re.compile(r"^\s*import\s+topcoffea\.modules"), "import the top-level package instead of submodules"),
    (
        re.compile(r"importlib\.import_module\(\s*[\"']topcoffea\."),
        "load through 'topcoffea.import_module' and attribute access",
    ),
)
_ALLOWED_DIRECT_IMPORTS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*from\s+topcoffea\.modules\.histEFT\s+import\s+HistEFT\s*$"),
)


def _iter_source_files() -> Iterator[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "*.py", "*.ipynb"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        for relative in listed.stdout.splitlines():
            path = _REPO_ROOT / relative
            if not path.exists():
                continue
            if relative.startswith("tests/"):
                continue
            if path.suffix == ".py" and path.name.endswith("_loc.py"):
                continue
            yield path
        return
    except Exception:
        pass

    for pattern in ("*.py", "*.ipynb"):
        for path in _REPO_ROOT.rglob(pattern):
            relative = path.relative_to(_REPO_ROOT)
            if relative.parts and relative.parts[0] in _EXCLUDED_TOP_LEVEL:
                continue
            if path.suffix == ".py" and path.name.endswith("_loc.py"):
                continue
            yield path


def _is_vendor_file(path: Path) -> bool:
    relative = path.relative_to(_REPO_ROOT)
    return relative.parts and relative.parts[0] in _EXCLUDED_TOP_LEVEL


def _scan_text_lines(path: Path, lines: Iterable[str]) -> List[str]:
    violations: List[str] = []
    for lineno, line in enumerate(lines, 1):
        if any(pattern.search(line) for pattern in _ALLOWED_DIRECT_IMPORTS):
            continue
        for pattern, guidance in _BANNED_PATTERNS:
            if pattern.search(line):
                violations.append(
                    f"{path.relative_to(_REPO_ROOT)}:{lineno}: {guidance} -> {line.rstrip()}"
                )
    return violations


def _scan_ipynb(path: Path) -> List[str]:
    data = json.loads(path.read_text())
    lines: List[str] = []
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        lines.extend(cell.get("source", []))
    return _scan_text_lines(path, lines)


def _scan_py(path: Path) -> List[str]:
    return _scan_text_lines(path, path.read_text().splitlines())


def test_topcoffea_import_style() -> None:
    violations: List[str] = []
    for path in _iter_source_files():
        if _is_vendor_file(path):
            continue
        if path.suffix == ".ipynb":
            violations.extend(_scan_ipynb(path))
        else:
            violations.extend(_scan_py(path))
    assert not violations, "\n".join(violations)


def test_topcoffea_not_vendored() -> None:
    import topcoffea

    candidate_paths: List[Path] = []
    module_file = getattr(topcoffea, "__file__", None)
    if module_file:
        candidate_paths.append(Path(module_file))
    for entry in getattr(topcoffea, "__path__", []):
        try:
            candidate_paths.append(Path(entry))
        except TypeError:
            continue

    assert candidate_paths, "topcoffea import should expose __file__ or __path__ entries"

    vendored: List[str] = []
    for path in candidate_paths:
        resolved = path.resolve()
        try:
            resolved.relative_to(_REPO_ROOT)
        except ValueError:
            continue
        vendored.append(resolved.as_posix())

    assert not vendored, f"topcoffea must resolve outside the topeft repository: {vendored}"


def test_topcoffea_package_directory_absent() -> None:
    package_dir = _REPO_ROOT / "topcoffea"
    assert not package_dir.exists(), "vendored topcoffea package directory should be removed"
