from __future__ import annotations

from pathlib import Path

from topeft.modules import taskvine_probe as wrapper
from topcoffea.modules import taskvine_probe as topcoffea_probe


def test_taskvine_probe_wrapper_parses_and_delegates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_probe(*, project_pattern: str, timeout: float, repeat: int, sleep_seconds: float):
        captured["project_pattern"] = project_pattern
        captured["timeout"] = timeout
        captured["repeat"] = repeat
        captured["sleep_seconds"] = sleep_seconds
        return [
            topcoffea_probe.ProbeSample(
                timestamp="2026-03-02T00:00:00+00:00",
                pattern=project_pattern,
                matched_project="apiccine-taskvine-coffea-std-1234",
                workers_connected=0,
                tasks_waiting=3,
                tasks_running=0,
                tasks_done=0,
                note="source=test",
            )
        ]

    monkeypatch.setattr(topcoffea_probe, "run_probe", _fake_run_probe)

    output_path = tmp_path / "probe.csv"
    rc = wrapper.main(
        [
            "--project-pattern",
            r"apiccine-taskvine-coffea-std-.*",
            "--timeout",
            "7",
            "--repeat",
            "1",
            "--sleep",
            "0",
            "--out",
            str(output_path),
        ]
    )

    assert rc == 0
    assert captured == {
        "project_pattern": r"apiccine-taskvine-coffea-std-.*",
        "timeout": 7.0,
        "repeat": 1,
        "sleep_seconds": 0.0,
    }

    csv_lines = output_path.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "timestamp,pattern,matched_project,workers_connected,tasks_waiting,tasks_running,tasks_done,note"
    assert "apiccine-taskvine-coffea-std-1234" in csv_lines[1]
