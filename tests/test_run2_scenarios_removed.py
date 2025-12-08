import importlib

import pytest


def test_run2_scenarios_import_raises_runtime_error():
    with pytest.raises(RuntimeError) as excinfo:
        importlib.import_module("topeft.modules.run2_scenarios")

    message = str(excinfo.value)
    assert "run2_scenarios" in message
    assert "scenario_groups" in message
