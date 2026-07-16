from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from topeft.modules.missing_parton_contract import (
    validate_legacy_missing_parton_values,
)


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "topeft_run2"
    / "missing_parton.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "missing_parton_numerics_under_test",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def errors(size, *, down=0.0, up=0.0):
    return np.full(size, down), np.full(size, up)


def calculate(module, private, central, *, down=0.0, up=0.0):
    private = np.asarray(private, dtype=float)
    central = np.asarray(central, dtype=float)
    down_values, up_values = errors(len(private), down=down, up=up)
    return module.calculate_missing_parton_per_bin(
        private,
        central,
        down_values,
        up_values,
        base_channel="test_channel",
    )


def test_ordinary_positive_ratio_preserves_public_formula():
    module = load_module()

    parton, fraction = calculate(module, [10.0], [4.0], down=2.0)

    assert parton.tolist() == pytest.approx([math.sqrt(32.0)])
    assert fraction.tolist() == pytest.approx([math.sqrt(32.0) / 10.0])


def test_upward_private_error_is_selected_when_central_is_larger():
    module = load_module()

    parton, fraction = calculate(module, [10.0], [14.0], down=1.0, up=3.0)

    assert parton.tolist() == pytest.approx([math.sqrt(7.0)])
    assert fraction.tolist() == pytest.approx([math.sqrt(7.0) / 10.0])


def test_equal_private_and_central_rates_are_neutral():
    module = load_module()

    parton, fraction = calculate(module, [7.0], [7.0])

    assert parton.tolist() == pytest.approx([0.0])
    assert fraction.tolist() == pytest.approx([0.0])


def test_both_zero_or_effectively_zero_rates_are_neutral():
    module = load_module()

    parton, fraction = calculate(
        module,
        [0.0, 0.5e-5],
        [0.0, -0.5e-5],
    )

    assert parton.tolist() == pytest.approx([0.0, 0.0])
    assert fraction.tolist() == pytest.approx([0.0, 0.0])


def test_near_zero_positive_private_with_nonzero_central_is_neutral():
    module = load_module()

    parton, fraction = calculate(module, [0.5e-5], [1.0])

    assert parton.tolist() == [0.0]
    assert fraction.tolist() == [0.0]
    assert 1.0 + fraction[0] == 1.0


def test_near_zero_negative_private_with_nonzero_central_is_neutral():
    module = load_module()

    parton, fraction = calculate(module, [-0.5e-5], [1.0])

    assert parton.tolist() == [0.0]
    assert fraction.tolist() == [0.0]
    assert 1.0 + fraction[0] == 1.0


def test_effectively_zero_private_never_uses_threshold_as_denominator():
    module = load_module()

    _, fraction = calculate(module, [0.25e-5], [1.0e6])

    assert fraction.tolist() == [0.0]


def test_private_value_at_threshold_uses_ordinary_formula():
    module = load_module()

    parton, fraction = calculate(module, [1.0e-5], [0.0])

    assert parton.tolist() == pytest.approx([1.0e-5])
    assert fraction.tolist() == pytest.approx([1.0])


def test_zero_or_near_zero_central_with_positive_private_is_supported():
    module = load_module()

    _, fraction = calculate(module, [10.0, 10.0], [0.0, 0.5e-5])

    assert fraction.tolist() == pytest.approx([1.0, 1.0])


@pytest.mark.parametrize("bad_value", (np.nan, np.inf, -np.inf))
def test_nonfinite_numerical_inputs_fail(bad_value):
    module = load_module()

    with pytest.raises(ValueError, match="Non-finite"):
        calculate(module, [10.0], [bad_value])


def test_materially_negative_private_denominator_fails_without_absolute_value():
    module = load_module()

    with pytest.raises(
        ValueError, match="Materially negative private denominator"
    ) as exc_info:
        calculate(module, [-0.5], [0.0])

    assert "no clipping or absolute-value fallback" in str(exc_info.value)


def test_uncertainty_larger_than_rate_difference_yields_neutral_fraction():
    module = load_module()

    parton, fraction = calculate(module, [10.0], [9.0], down=2.0)

    assert parton.tolist() == pytest.approx([0.0])
    assert fraction.tolist() == pytest.approx([0.0])


def test_merged_tail_uses_sum_of_per_bin_missing_parton_amounts():
    module = load_module()
    private = np.asarray([10.0, 10.0, 10.0, 10.0, 10.0, 2.0, 3.0, 4.0])
    parton = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, 1.0, 1.0, 2.0])
    fractions = parton / private

    stored = module.merge_legacy_payload_tail(
        base_channel="3l_onZ_1b",
        private_values=private,
        missing_parton_values=parton,
        per_bin_fractions=fractions,
        expected_length=6,
    )

    assert stored[:5].tolist() == pytest.approx(fractions[:5])
    assert stored[5] == pytest.approx(4.0 / 9.0)


def test_physical_njet_indices_are_preserved_before_merged_tail():
    module = load_module()
    private = np.full(8, 10.0)
    parton = np.arange(1.0, 9.0)
    fractions = parton / private

    stored = module.merge_legacy_payload_tail(
        base_channel="2lss_m_1tau_onZ",
        private_values=private,
        missing_parton_values=parton,
        per_bin_fractions=fractions,
        expected_length=7,
    )

    assert stored.shape == (7,)
    assert stored[3] == pytest.approx(fractions[3])
    assert stored[5] == pytest.approx(fractions[5])
    assert stored[6] == pytest.approx((parton[6] + parton[7]) / 20.0)


def test_numerical_array_shape_mismatch_fails():
    module = load_module()

    with pytest.raises(ValueError, match="array mismatch"):
        module.calculate_missing_parton_per_bin(
            np.ones(8),
            np.ones(7),
            np.zeros(8),
            np.zeros(8),
            base_channel="test_channel",
        )


def test_invalid_stored_fraction_and_kappa_are_rejected():
    with pytest.raises(ValueError, match="Negative stored"):
        validate_legacy_missing_parton_values(
            [0.0, -0.1],
            base_channel="test_channel",
            expected_length=2,
        )


def test_nonfinite_stored_fraction_is_rejected():
    with pytest.raises(ValueError, match="Non-finite"):
        validate_legacy_missing_parton_values(
            [0.0, np.inf],
            base_channel="test_channel",
            expected_length=2,
        )
