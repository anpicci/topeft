import logging

import pytest

from topeft.modules.logging_config import configure_topeft_logging


def _snapshot_logger(logger: logging.Logger) -> dict:
    return {
        "level": logger.level,
        "handlers": list(logger.handlers),
        "propagate": logger.propagate,
        "disabled": logger.disabled,
    }


def _restore_logger(logger: logging.Logger, snapshot: dict) -> None:
    logger.handlers[:] = []
    for handler in snapshot["handlers"]:
        logger.addHandler(handler)
    logger.setLevel(snapshot["level"])
    logger.propagate = snapshot["propagate"]
    logger.disabled = snapshot["disabled"]


@pytest.fixture
def logging_state():
    tracked = {
        "root": logging.getLogger(),
        "topeft": logging.getLogger("topeft"),
        "topcoffea": logging.getLogger("topcoffea"),
        "analysis": logging.getLogger("analysis"),
        "analysis.topeft_run2": logging.getLogger("analysis.topeft_run2"),
    }
    snapshots = {name: _snapshot_logger(logger) for name, logger in tracked.items()}
    yield
    for name, logger in tracked.items():
        _restore_logger(logger, snapshots[name])


def test_root_vs_project_split(monkeypatch, logging_state) -> None:
    monkeypatch.delenv("TOPEFT_DEV_DEBUG", raising=False)

    effective = configure_topeft_logging("debug", executor="futures")

    root_logger = logging.getLogger()
    project_logger = logging.getLogger("topeft")
    assert effective == "DEBUG"
    assert root_logger.level == logging.INFO
    assert project_logger.level == logging.DEBUG


def test_none_mutes_everything(monkeypatch, logging_state) -> None:
    monkeypatch.delenv("TOPEFT_DEV_DEBUG", raising=False)

    effective = configure_topeft_logging("none", executor="futures")

    root_logger = logging.getLogger()
    project_logger = logging.getLogger("topeft")
    assert effective == "NONE"
    assert root_logger.level > logging.CRITICAL
    assert project_logger.disabled is True


def test_taskvine_policy_warning_only(monkeypatch, logging_state) -> None:
    monkeypatch.delenv("TOPEFT_DEV_DEBUG", raising=False)
    effective = configure_topeft_logging("INFO", executor="taskvine")
    assert effective == "INFO"
