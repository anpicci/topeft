import gzip
import json
import pickle
import sys
from pathlib import Path

import pytest

from tests import test_metadata_single_source as metadata_stubs

# Ensure the lightweight stubs used in the metadata-single-source tests are also
# active here so DatacardMaker can be exercised without heavy dependencies.
metadata_stubs._install_topcoffea_stub()
metadata_stubs._install_numpy_stub()
metadata_stubs._install_matplotlib_stubs()
metadata_stubs._install_boost_histogram_stub()
metadata_stubs._install_uproot_stub()
metadata_stubs._install_coffea_stub()

from analysis.topeft_run2 import datacards_post_processing as dpp  # noqa: E402
from topeft.modules import datacard_tools  # noqa: E402  (imports after stubs)


def _write_empty_histogram_pickle(path: Path) -> None:
    with gzip.open(path, "wb") as handle:
        pickle.dump({}, handle)


def test_datacard_maker_uses_injected_metadata(tmp_path, monkeypatch):
    dummy_hist = tmp_path / "dummy.pkl.gz"
    _write_empty_histogram_pickle(dummy_hist)

    metadata_payload = {
        "variables": {"custom_pt": {"variable": [0.0, 1.0, 2.0]}},
        "channels": {},
    }

    monkeypatch.setattr(datacard_tools.DatacardMaker, "load_systematics", lambda self, *_: {})

    maker = datacard_tools.DatacardMaker(str(dummy_hist), metadata=metadata_payload)

    assert "custom_pt" in maker.variable_binning
    assert maker.variable_binning["custom_pt"] == [0.0, 1.0, 2.0]


def test_datacard_maker_requires_variable_definitions(tmp_path, monkeypatch):
    dummy_hist = tmp_path / "dummy.pkl.gz"
    _write_empty_histogram_pickle(dummy_hist)
    monkeypatch.setattr(datacard_tools.DatacardMaker, "load_systematics", lambda self, *_: {})

    with pytest.raises(ValueError):
        datacard_tools.DatacardMaker(str(dummy_hist), metadata={"channels": {}})


def test_datacards_cli_respects_metadata_override(tmp_path, monkeypatch):
    cards_dir = tmp_path / "cards"
    cards_dir.mkdir()
    (cards_dir / "job_logs").mkdir()

    scalings_file = cards_dir / "scalings-preselect.json"
    scalings_file.write_text(json.dumps([{"channel": "dummy_channel"}]), encoding="utf-8")
    for suffix in ("txt", "root"):
        path = cards_dir / f"ttx_multileptons_dummy_channel.{suffix}"
        path.write_text("placeholder", encoding="utf-8")
    (cards_dir / "selectedWCs.txt").write_text("{}", encoding="utf-8")

    metadata_file = tmp_path / "meta.yml"
    metadata_file.write_text(
        "\n".join(
            [
                "channels:",
                "  groups:",
                "    TOP22_006_CH_LST_SR:",
                "      regions: []",
                "    CH_LST_CR:",
                "      regions: []",
                "variables:",
                "  ptz:",
                "    variable: [0.0, 1.0]",
            ]
        ),
        encoding="utf-8",
    )

    calls = {}
    original_loader = dpp.metadata_authority.load_metadata_bundle

    def spy_loader(path, scenario, **kwargs):
        calls["path"] = Path(path)
        return original_loader(path, scenario, **kwargs)

    monkeypatch.setattr(dpp.metadata_authority, "load_metadata_bundle", spy_loader)
    monkeypatch.setattr(dpp, "ChannelMetadataHelper", lambda data: data)
    monkeypatch.setattr(dpp, "collect_datacard_channels", lambda helper, scenario: ["dummy_channel"])
    monkeypatch.setattr(dpp, "EXPECTED_FILE_COUNTS", {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "datacards_post_processing.py",
            str(cards_dir),
            "--scenario",
            "TOP_22_006",
            "--metadata",
            str(metadata_file),
        ],
    )

    dpp.main()

    assert calls["path"] == metadata_file.resolve()
