"""Regression checks for TaskVine manager/project name propagation."""

from analysis.topeft_run2.run_processor_vineReduce_light import (
    resolve_light_manager_project_name,
    resolve_light_manager_project_name_with_source,
)
from analysis.topeft_run2.workflow import (
    resolve_taskvine_manager_project_name,
    resolve_taskvine_manager_project_name_with_source,
)


def test_std_resolve_taskvine_manager_project_name_prefers_config() -> None:
    result = resolve_taskvine_manager_project_name(
        configured_manager_name="configured-manager",
        default_manager_name="default-manager",
    )
    assert result == "configured-manager"


def test_std_resolve_taskvine_manager_project_name_falls_back_to_config() -> None:
    result = resolve_taskvine_manager_project_name(
        configured_manager_name="configured-manager",
        default_manager_name="default-manager",
    )
    assert result == "configured-manager"


def test_std_resolve_taskvine_manager_project_name_falls_back_to_default() -> None:
    result = resolve_taskvine_manager_project_name(
        configured_manager_name="",
        default_manager_name="default-manager",
    )
    assert result == "default-manager"


def test_std_resolve_taskvine_manager_project_name_with_source_prefers_config() -> None:
    result, source = resolve_taskvine_manager_project_name_with_source(
        configured_manager_name="configured-manager",
        default_manager_name="default-manager",
    )
    assert result == "configured-manager"
    assert source == "config"


def test_std_resolve_taskvine_manager_project_name_with_source_uses_config() -> None:
    result, source = resolve_taskvine_manager_project_name_with_source(
        configured_manager_name="configured-manager",
        default_manager_name="default-manager",
    )
    assert result == "configured-manager"
    assert source == "config"


def test_std_resolve_taskvine_manager_project_name_with_source_uses_default() -> None:
    result, source = resolve_taskvine_manager_project_name_with_source(
        configured_manager_name="",
        default_manager_name="default-manager",
    )
    assert result == "default-manager"
    assert source == "default"


def test_light_resolve_manager_project_name_uses_cli_argument() -> None:
    result = resolve_light_manager_project_name(
        "apiccine-taskvine-coffea-light-smoke-run",
        default_manager="default-manager",
    )
    assert result == "apiccine-taskvine-coffea-light-smoke-run"


def test_light_resolve_manager_project_name_uses_default_when_missing() -> None:
    result = resolve_light_manager_project_name(
        None,
        default_manager="default-manager",
    )
    assert result == "default-manager"


def test_light_resolve_manager_project_name_uses_default_when_blank() -> None:
    result = resolve_light_manager_project_name(
        "   ",
        default_manager="default-manager",
    )
    assert result == "default-manager"


def test_light_resolve_manager_project_name_with_source_uses_config() -> None:
    result, source = resolve_light_manager_project_name_with_source(
        "apiccine-taskvine-coffea-light-smoke-run",
        default_manager="default-manager",
    )
    assert result == "apiccine-taskvine-coffea-light-smoke-run"
    assert source == "config"


def test_light_resolve_manager_project_name_with_source_uses_default() -> None:
    result, source = resolve_light_manager_project_name_with_source(
        "   ",
        default_manager="default-manager",
    )
    assert result == "default-manager"
    assert source == "default"
