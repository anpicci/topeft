from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
import uproot

from topeft.modules.missing_parton_contract import (
    LEGACY_MISSING_PARTON_BASE_CHANNELS,
    LEGACY_MISSING_PARTON_BRANCH,
    legacy_missing_parton_payload_lengths,
    validate_legacy_missing_parton_payload,
)


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "topeft_run2"
    / "missing_parton.py"
)
PUBLIC_RUN3_PAYLOAD = (
    Path(__file__).resolve().parents[1]
    / "topeft"
    / "data"
    / "missing_parton"
    / "missing_parton_run3.root"
)
YAWEN_RUN3_PAYLOAD = Path(
    "/groups/klannon/ywan2/forAndrea/missing_parton/"
    "missing_parton_run3_fix.root"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "missing_parton_payload_schema_under_test",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_payload(*, offset=0.0):
    lengths = legacy_missing_parton_payload_lengths()
    return {
        category: np.linspace(
            offset,
            offset + 0.01 * (lengths[category] - 1),
            lengths[category],
            dtype=np.float64,
        )
        for category in LEGACY_MISSING_PARTON_BASE_CHANNELS
    }


def test_synthetic_writer_produces_exact_public_34_tree_schema(tmp_path):
    module = load_module()
    output = tmp_path / "missing_parton.root"

    output_sha256 = module.write_legacy_payload_atomic(
        output,
        synthetic_payload(),
    )
    validated = validate_legacy_missing_parton_payload(output)

    assert len(output_sha256) == 64
    assert list(validated) == list(LEGACY_MISSING_PARTON_BASE_CHANNELS)
    with uproot.open(output) as payload_file:
        assert payload_file.keys(recursive=False, cycle=False) == list(
            LEGACY_MISSING_PARTON_BASE_CHANNELS
        )
        assert set(
            payload_file.classnames(recursive=False, cycle=False).values()
        ) == {"TTree"}
        for category in LEGACY_MISSING_PARTON_BASE_CHANNELS:
            tree = payload_file[category]
            assert tree.keys() == [LEGACY_MISSING_PARTON_BRANCH]
            assert tree[LEGACY_MISSING_PARTON_BRANCH].typename == "double"


def test_writer_has_no_extra_directories_or_scalar_histograms(tmp_path):
    module = load_module()
    output = tmp_path / "missing_parton.root"
    module.write_legacy_payload_atomic(output, synthetic_payload())

    with uproot.open(output) as payload_file:
        classnames = payload_file.classnames(
            recursive=True,
            cycle=False,
        )

    assert all(classname in {"TTree", "TBranch"} for classname in classnames.values())
    assert not any(classname.startswith("TH1") for classname in classnames.values())
    assert len(
        [
            key
            for key, classname in classnames.items()
            if classname == "TTree"
        ]
    ) == 34


def test_132_key_scalar_schema_is_rejected(tmp_path):
    output = tmp_path / "scalar_payload.root"
    with uproot.recreate(output) as payload_file:
        for index in range(132):
            payload_file[f"final_channel_{index}"] = (
                np.asarray([0.1]),
                np.asarray([0.0, 1.0]),
            )

    with pytest.raises(ValueError, match="132-final-channel scalar schema"):
        validate_legacy_missing_parton_payload(output)


def test_existing_output_rejected_without_overwrite_and_replaced_with_opt_in(
    tmp_path,
):
    module = load_module()
    output = tmp_path / "missing_parton.root"
    first_sha256 = module.write_legacy_payload_atomic(
        output,
        synthetic_payload(offset=0.0),
    )

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        module.write_legacy_payload_atomic(
            output,
            synthetic_payload(offset=0.2),
        )

    second_sha256 = module.write_legacy_payload_atomic(
        output,
        synthetic_payload(offset=0.2),
        overwrite=True,
    )

    assert first_sha256 != second_sha256
    validated = validate_legacy_missing_parton_payload(output)
    assert validated["2los_onZ_1tau"][0] == pytest.approx(0.2)


def test_invalid_payload_leaves_existing_output_unchanged(tmp_path):
    module = load_module()
    output = tmp_path / "missing_parton.root"
    module.write_legacy_payload_atomic(output, synthetic_payload())
    original = output.read_bytes()
    invalid = synthetic_payload()
    invalid["2los_onZ_1tau"] = np.asarray([0.0, -0.1, 0.0, 0.0])

    with pytest.raises(ValueError, match="Negative stored"):
        module.write_legacy_payload_atomic(
            output,
            invalid,
            overwrite=True,
        )

    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp.root"))


def test_checked_in_public_run3_payload_validates_read_only():
    validated = validate_legacy_missing_parton_payload(PUBLIC_RUN3_PAYLOAD)

    assert len(validated) == 34
    assert list(validated) == list(LEGACY_MISSING_PARTON_BASE_CHANNELS)

def test_yawen_fixed_run3_payload_validates_read_only():
    if not YAWEN_RUN3_PAYLOAD.is_file():
        pytest.skip("Yawen fixed Run 3 benchmark payload is unavailable")

    validated = validate_legacy_missing_parton_payload(YAWEN_RUN3_PAYLOAD)

    assert len(validated) == 34
    assert list(validated) == list(LEGACY_MISSING_PARTON_BASE_CHANNELS)
