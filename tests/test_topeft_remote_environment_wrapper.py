from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from topeft.modules import remote_environment as topeft_remote_environment


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _create_fake_ddr_repo(parent: Path) -> Path:
    ddr_root = parent / "dynamic_data_reduction"
    (ddr_root / "src").mkdir(parents=True)
    (ddr_root / "pyproject.toml").write_text(
        "[project]\nname = 'dynamic_data_reduction'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    return ddr_root


def _write_stub_topcoffea(tmp_path: Path, *, should_fail: bool, env_path: str) -> tuple[Path, Path]:
    stub_root = tmp_path / "stub_pkgs"
    modules_dir = stub_root / "topcoffea" / "modules"
    modules_dir.mkdir(parents=True)
    ddr_root = _create_fake_ddr_repo(tmp_path)
    (stub_root / "topcoffea" / "__init__.py").write_text(
        "import importlib\n"
        "def import_module(name):\n"
        "    return importlib.import_module(name)\n",
        encoding="utf-8",
    )
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")
    if should_fail:
        body = (
            "def get_environment(**kwargs):\n"
            "    raise RuntimeError('stub remote env failure')\n"
        )
    else:
        body = (
            "def get_environment(**kwargs):\n"
            f"    return {env_path!r}\n"
        )
    (modules_dir / "remote_environment.py").write_text(body, encoding="utf-8")
    return stub_root, ddr_root


def _run_wrapper(*args: str, stub_root: Path, ddr_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    repo_root = _repo_root()
    existing_pythonpath = env.get("PYTHONPATH")
    entries = [str(stub_root), str(repo_root)]
    if existing_pythonpath:
        entries.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    if ddr_root is not None:
        env["TOPEFT_DDR_REPO"] = str(ddr_root)
    return subprocess.run(
        [sys.executable, "-m", "topeft.modules.remote_environment", *args],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_remote_environment_wrapper_default_print_mode(tmp_path: Path) -> None:
    expected_path = "/tmp/test-env-spec.tar.gz"
    stub_root, ddr_root = _write_stub_topcoffea(
        tmp_path,
        should_fail=False,
        env_path=expected_path,
    )
    completed = _run_wrapper(stub_root=stub_root, ddr_root=ddr_root)
    assert completed.returncode == 0, completed.stderr
    non_empty_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert non_empty_lines == [expected_path]
    assert completed.stderr.strip() == f"[topeft.remote_environment] OK: {expected_path}"


def test_remote_environment_wrapper_print_both_mode(tmp_path: Path) -> None:
    expected_path = "/tmp/test-env-spec.tar.gz"
    stub_root, ddr_root = _write_stub_topcoffea(
        tmp_path,
        should_fail=False,
        env_path=expected_path,
    )
    completed = _run_wrapper("--print", "both", stub_root=stub_root, ddr_root=ddr_root)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"[topeft.remote_environment] OK: {expected_path}"
    assert completed.stderr.strip() == ""


def test_remote_environment_wrapper_failure_exits_nonzero(tmp_path: Path) -> None:
    stub_root, ddr_root = _write_stub_topcoffea(
        tmp_path,
        should_fail=True,
        env_path="/tmp/unused.tar.gz",
    )
    completed = _run_wrapper(stub_root=stub_root, ddr_root=ddr_root)
    assert completed.returncode != 0
    assert "[topeft.remote_environment] ERROR: stub remote env failure" in completed.stderr


def test_get_environment_applies_topeft_defaults_and_merges(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_get_environment(**kwargs):
        captured.update(kwargs)
        return "/tmp/delegated-env.tar.gz"

    fake_remote = SimpleNamespace(get_environment=_fake_get_environment)
    monkeypatch.setattr(
        topeft_remote_environment.topcoffea,
        "import_module",
        lambda name: fake_remote,
    )
    ddr_root = _create_fake_ddr_repo(tmp_path)
    monkeypatch.setenv("TOPEFT_DDR_REPO", str(ddr_root))

    path = topeft_remote_environment.get_environment(
        extra_pip_local={
            "topeft": ["override", "setup.py"],
            "custom_pkg": ["pkg", "pyproject.toml"],
        },
        extra_conda=["xrootd"],
        force=True,
    )

    assert path == "/tmp/delegated-env.tar.gz"
    assert captured["force"] is True
    assert captured["extra_pip_local"] == {
        "topeft": ["override", "setup.py"],
        "dynamic_data_reduction": [
            str(ddr_root / "src"),
            str(ddr_root / "pyproject.toml"),
        ],
        "custom_pkg": ["pkg", "pyproject.toml"],
    }
    assert captured["extra_conda"] == ["pyyaml", "xrootd"]


def test_get_environment_resolves_sibling_ddr_repo(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_get_environment(**kwargs):
        captured.update(kwargs)
        return "/tmp/delegated-env.tar.gz"

    fake_remote = SimpleNamespace(get_environment=_fake_get_environment)
    monkeypatch.setattr(
        topeft_remote_environment.topcoffea,
        "import_module",
        lambda name: fake_remote,
    )
    monkeypatch.delenv("TOPEFT_DDR_REPO", raising=False)

    topeft_root = tmp_path / "topeft"
    topeft_root.mkdir(parents=True)
    ddr_root = _create_fake_ddr_repo(tmp_path)
    monkeypatch.setattr(topeft_remote_environment, "_find_topeft_repo_root", lambda: topeft_root)

    path = topeft_remote_environment.get_environment()

    assert path == "/tmp/delegated-env.tar.gz"
    assert captured["extra_pip_local"]["dynamic_data_reduction"] == [
        str(ddr_root / "src"),
        str(ddr_root / "pyproject.toml"),
    ]


def test_get_environment_fails_when_ddr_repo_missing(monkeypatch, tmp_path: Path) -> None:
    fake_remote = SimpleNamespace(get_environment=lambda **_: "/tmp/unused.tar.gz")
    monkeypatch.setattr(
        topeft_remote_environment.topcoffea,
        "import_module",
        lambda name: fake_remote,
    )
    monkeypatch.delenv("TOPEFT_DDR_REPO", raising=False)

    topeft_root = tmp_path / "topeft"
    topeft_root.mkdir(parents=True)
    monkeypatch.setattr(topeft_remote_environment, "_find_topeft_repo_root", lambda: topeft_root)

    try:
        topeft_remote_environment.get_environment()
    except FileNotFoundError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected FileNotFoundError when DDR repository is missing")

    assert "dynamic_data_reduction" in message
    assert "TOPEFT_DDR_REPO" in message
