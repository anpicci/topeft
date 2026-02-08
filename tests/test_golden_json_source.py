import sys
from types import ModuleType

import pytest

from analysis.topeft_run2 import metadata_authority


def _install_topcoffea_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    modules_pkg = ModuleType("topcoffea.modules")
    paths_mod = ModuleType("topcoffea.modules.paths")
    paths_mod.topcoffea_path = lambda relative: f"/abs/{relative}"
    modules_pkg.paths = paths_mod

    topcoffea_stub = ModuleType("topcoffea")
    topcoffea_stub.modules = modules_pkg
    topcoffea_stub.__path__ = []

    monkeypatch.setitem(sys.modules, "topcoffea", topcoffea_stub)
    monkeypatch.setitem(sys.modules, "topcoffea.modules", modules_pkg)
    monkeypatch.setitem(sys.modules, "topcoffea.modules.paths", paths_mod)


def test_golden_json_for_year_uses_metadata_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_topcoffea_stub(monkeypatch)
    metadata = {
        "golden_jsons": {
            "2017": "data/goldenJsons/Cert_2017.txt",
        }
    }

    result = metadata_authority.golden_json_for_year(metadata, "2017")

    assert result == "/abs/data/goldenJsons/Cert_2017.txt"


def test_golden_json_for_year_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_topcoffea_stub(monkeypatch)
    metadata = {"golden_jsons": {"2017": "data/goldenJsons/Cert_2017.txt"}}

    with pytest.raises(KeyError, match="2018"):
        metadata_authority.golden_json_for_year(metadata, "2018")
