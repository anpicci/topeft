from __future__ import annotations

import numpy as np
import pytest

from topeft.modules import datacard_tools
from topeft.modules.datacard_tools import DatacardMaker


class _fake_branch:
    def __init__(self, values):
        self.values = values

    def array(self):
        return np.asarray(self.values, dtype=float)


class _fake_missing_parton_file:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def keys(self):
        return ["3l_onZ_1b"]

    def __getitem__(self, key):
        assert key == "3l_onZ_1b/tllq"
        return _fake_branch(self.values)


def _systematics_loader(*, years, do_nuisance=True, skip=False):
    maker = object.__new__(DatacardMaker)
    maker.do_nuisance = do_nuisance
    maker.skip_missing_parton_rate_syst = skip
    maker.year_lst = list(years)
    return maker


@pytest.mark.parametrize("year", ("UL16", "UL16APV", "UL17", "UL18"))
def test_all_supported_run2_card_years_resolve_to_one_nuisance(year):
    assert DatacardMaker.missing_parton_run_era(year) == "run2"
    assert DatacardMaker.missing_parton_nuisance_name(year) == "missing_parton"


@pytest.mark.parametrize("year", ("2022", "2022EE", "2023", "2023BPix"))
def test_all_supported_run3_card_years_resolve_to_one_nuisance(year):
    assert DatacardMaker.missing_parton_run_era(year) == "run3"
    assert DatacardMaker.missing_parton_nuisance_name(year) == "missing_parton"


@pytest.mark.parametrize("year", ("", "2018", "UL18_extra"))
def test_malformed_or_unsupported_years_are_rejected(year):
    with pytest.raises(ValueError, match="canonical year or period|Unsupported canonical"):
        DatacardMaker.missing_parton_nuisance_name(year)


def test_mixed_era_years_fail_with_original_labels_and_resolved_eras():
    with pytest.raises(ValueError, match="one explicit missing-parton payload source") as exc_info:
        DatacardMaker.missing_parton_nuisance_name_for_years(
            ("UL18", "2022"),
            payload_path="run2.root",
        )

    message = str(exc_info.value)
    assert "UL18" in message
    assert "2022" in message
    assert "run2" in message
    assert "run3" in message
    assert "run2.root" in message
    assert "different nuisance names" not in message.lower()


def test_mixed_era_loader_fails_before_opening_the_payload(monkeypatch):
    maker = _systematics_loader(years=("UL18", "2022"))

    def fail_if_opened(_):
        raise AssertionError("mixed-era resolution should happen before payload loading")

    monkeypatch.setattr(datacard_tools.uproot, "open", fail_if_opened)

    with pytest.raises(ValueError, match="one explicit missing-parton payload source"):
        maker.load_systematics("params/rate_systs_run3.json", "synthetic.root")


@pytest.mark.parametrize(
    ("years", "payload_values"),
    (
        (("UL16", "UL18"), (0.2, 0.3)),
        (("2022", "2023BPix"), (0.4, 0.5)),
    ),
)
def test_loader_uses_era_specific_name_and_preserves_process_scope(
    monkeypatch,
    years,
    payload_values,
):
    monkeypatch.setattr(
        datacard_tools.uproot,
        "open",
        lambda _: _fake_missing_parton_file(payload_values),
    )
    maker = _systematics_loader(years=years)

    systematics = maker.load_systematics(
        "params/rate_systs_run3.json",
        "synthetic.root",
    )

    assert set(systematics).isdisjoint({"missing_parton_run2", "missing_parton_run3"})
    missing_parton = systematics["missing_parton"]
    assert missing_parton.name == "missing_parton"
    assert missing_parton.get_process("tllq") == {
        "3l_onZ_1b": pytest.approx(np.asarray(payload_values) + 1.0)
    }
    assert missing_parton.get_process("tHq") == missing_parton.get_process("tllq")
    for excluded_process in ("tZq", "ttll", "ttH", "unrelated"):
        assert missing_parton.get_process(excluded_process) == "-"


def test_shared_identity_keeps_explicit_payload_factors_distinct(monkeypatch):
    payload_values_by_path = {
        "run2.root": (0.2, 0.3),
        "run3.root": (0.4, 0.5),
    }
    monkeypatch.setattr(
        datacard_tools.uproot,
        "open",
        lambda path: _fake_missing_parton_file(
            payload_values_by_path[str(path).rsplit("/", 1)[-1]]
        ),
    )

    run2 = _systematics_loader(years=("UL18",)).load_systematics(
        "params/rate_systs_run2.json",
        "run2.root",
    )["missing_parton"]
    run3 = _systematics_loader(years=("2023",)).load_systematics(
        "params/rate_systs_run3.json",
        "run3.root",
    )["missing_parton"]

    assert run2.name == run3.name == "missing_parton"
    assert run2.get_process("tllq")["3l_onZ_1b"][0] == pytest.approx(1.2)
    assert run3.get_process("tllq")["3l_onZ_1b"][0] == pytest.approx(1.4)
    assert run2.get_process("tHq") == run2.get_process("tllq")
    assert run3.get_process("tHq") == run3.get_process("tllq")


def test_skip_bypasses_payload_loading_and_mixed_era_resolution(monkeypatch):
    maker = _systematics_loader(years=("UL18", "2022"), skip=True)

    def fail_if_opened(_):
        raise AssertionError("missing-parton payload was opened despite suppression")

    monkeypatch.setattr(datacard_tools.uproot, "open", fail_if_opened)
    systematics = maker.load_systematics(
        "params/rate_systs_run3.json",
        "does-not-exist.root",
    )

    assert "diboson_njets" in systematics
    assert "missing_parton" not in systematics


def test_disabled_nuisances_bypass_payload_loading_and_era_resolution(monkeypatch):
    maker = _systematics_loader(years=("UL18", "2022"), do_nuisance=False)

    def fail_if_opened(_):
        raise AssertionError("missing-parton payload was opened while nuisances were disabled")

    monkeypatch.setattr(datacard_tools.uproot, "open", fail_if_opened)

    assert maker.load_systematics("params/rate_systs_run3.json", "does-not-exist.root") == {}
