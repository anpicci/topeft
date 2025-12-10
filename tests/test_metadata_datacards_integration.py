import gzip
import pickle
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
