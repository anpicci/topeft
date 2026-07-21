import base64
import gzip
import importlib.util
import json
import pickle
from pathlib import Path

import hist
import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "analysis/diboson_njets/diboson_sf_run3.py"
CONFIG_PATH = REPO_ROOT / "analysis/diboson_njets/diboson_sf_run3_config.yml"
FIXTURE_PATH = Path(__file__).resolve().parent / "data/run3_histogram.pkl.gz.base64"

spec = importlib.util.spec_from_file_location("diboson_sf_run3", MODULE_PATH)
diboson_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(diboson_module)


def _materialize_histogram_fixture(tmp_path: Path) -> Path:
    fixture_path = tmp_path / "run3_histogram.pkl.gz"
    fixture_path.write_bytes(base64.b64decode(FIXTURE_PATH.read_text().strip()))
    return fixture_path


def _roles():
    config = diboson_module.load_diboson_config(CONFIG_PATH)
    return diboson_module._normalize_process_roles(config)


def _run_fixture(tmp_path, *, enabled=True, cache=None):
    fixture = _materialize_histogram_fixture(tmp_path)
    return diboson_module.process_year(
        str(fixture),
        "2022",
        "njets",
        "3l_CR",
        [0, 1, 2, 3, 4, 5, 6],
        process_roles=_roles(),
        propagation_enabled=enabled,
        configuration_source="config",
        cache=cache,
    )


def _write_payload(path, payload):
    with gzip.open(path, "wb") as stream:
        pickle.dump(payload, stream, protocol=5)


def _companion_with_axes(payload, mutation):
    nominal = payload["njets"]
    processes = [str(value) for value in nominal.axes["process"]]
    channels = [str(value) for value in nominal.axes["channel"]]
    years = [str(value) for value in nominal.axes["year"]]
    edges = nominal.axes["njets"].edges.tolist()
    underflow = False
    overflow = False
    if mutation == "category":
        processes = processes[:-1]
    elif mutation == "edge":
        edges[1] = 0.4
    elif mutation == "flow":
        overflow = True
    axes = [
        hist.axis.StrCategory(processes, name="process"),
        hist.axis.StrCategory(channels, name="channel"),
        hist.axis.StrCategory(years, name="year"),
        hist.axis.Variable(
            edges,
            name="njets_sumw2",
            underflow=underflow,
            overflow=overflow,
        ),
    ]
    if mutation == "axis":
        axes[0], axes[1] = axes[1], axes[0]
    return hist.Hist(*axes, storage=hist.storage.Double())


def test_current_fixture_reopens_and_cache_extractor_completes(tmp_path):
    fixture = _materialize_histogram_fixture(tmp_path)
    histograms = diboson_module.load_pkl_file(str(fixture))
    assert set(histograms) == {"njets", "njets_sumw2"}
    assert [axis.name for axis in histograms["njets"].axes] == [
        "process",
        "channel",
        "year",
        "njets",
    ]
    result = _run_fixture(tmp_path)
    assert result["scale_factors"][0] > 0
    membership = result["provenance"]["source_to_final_bin_membership"]
    assert membership["final_bin_source_indices"][0] == [0, 1]


def test_get_yields_preserves_sparse_hist_support_when_disabled(tmp_path):
    from topcoffea.modules.sparseHist import SparseHist

    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    dense = payload["njets"]
    sparse = SparseHist(*dense.axes)
    values = dense.values(flow=False)
    for process_index, process in enumerate(dense.axes["process"]):
        for source_index, center in enumerate(dense.axes["njets"].centers):
            weight = float(values[process_index, 0, 0, source_index])
            if weight:
                sparse.fill(
                    process=process,
                    channel="3l_CR",
                    year="2022",
                    njets=center,
                    weight=weight,
                )
    sparse_payload = {"njets": sparse}
    processes = ["data_a_2022", "WZTo3LNu_2022"]
    dense_yields = diboson_module.get_yields_in_bins(
        payload,
        processes,
        [0, 1, 2, 3, 4, 5, 6],
        "njets",
        "3l_CR",
        extra_slices={"year": "2022"},
    )
    sparse_yields = diboson_module.get_yields_in_bins(
        sparse_payload,
        processes,
        [0, 1, 2, 3, 4, 5, 6],
        "njets",
        "3l_CR",
        extra_slices={"year": "2022"},
    )
    assert sparse_yields == dense_yields


def test_analytic_statistics_use_all_roles_and_aggregate_before_ratio(tmp_path):
    result = _run_fixture(tmp_path)

    # Independent primitive arithmetic for the first two 0.5-wide source bins.
    data = (30 + 34) + (5 + 6)
    background = (5 + 6) + (1 + 2)
    diboson = (8 + 9) + (2 + 3)
    var_data = (50 + 52) + (12 + 13)
    var_background = (9 + 10) + (3 + 4)
    var_diboson = (14 + 15) + (5 + 6)
    expected_central = (data - background) / diboson
    expected_variance = (var_data + var_background) / diboson**2 + (
        (data - background) ** 2 / diboson**4
    ) * var_diboson

    assert data != var_data  # weighted/non-Poisson data is observable
    assert result["data"][0] == data
    assert result["other"][0] == background
    assert result["diboson"][0] == diboson
    assert result["scale_factors"][0] == pytest.approx(expected_central)
    assert result["scale_factor_statistical_variances"][0] == pytest.approx(
        expected_variance
    )
    assert result["scale_factor_statistical_uncertainties"][0] == pytest.approx(
        expected_variance**0.5
    )

    # These deliberately wrong alternatives distinguish the frozen formula.
    source_ratio_average = np.mean([(35 - 6) / 10, (40 - 8) / 12])
    poisson_data_variance = (data + var_background) / diboson**2 + (
        (data - background) ** 2 / diboson**4
    ) * var_diboson
    no_background_variance = var_data / diboson**2 + (
        (data - background) ** 2 / diboson**4
    ) * var_diboson
    no_diboson_variance = (var_data + var_background) / diboson**2
    assert result["scale_factors"][0] != pytest.approx(source_ratio_average)
    assert expected_variance != pytest.approx(poisson_data_variance)
    assert expected_variance != pytest.approx(no_background_variance)
    assert expected_variance != pytest.approx(no_diboson_variance)


@pytest.mark.parametrize(
    ("data", "background", "diboson", "expected_central", "positive_variance"),
    [
        ([7.0], [7.0], [2.0], 0.0, True),
        ([2.0], [6.0], [2.0], -2.0, True),
    ],
)
def test_cancelled_and_negative_numerators(
    data, background, diboson, expected_central, positive_variance
):
    components = {
        "data": data,
        "background": background,
        "diboson": diboson,
        "var_data": [3.0],
        "var_background": [5.0],
        "var_diboson": [7.0],
    }
    central, variances, uncertainties = (
        diboson_module.compute_scale_factor_statistics(
            components,
            [0, 1],
            input_path="primitive",
            year="2022",
            channel="3l_CR",
            propagation_enabled=True,
        )
    )
    numerator = data[0] - background[0]
    expected_variance = (3 + 5) / diboson[0] ** 2 + (
        numerator**2 / diboson[0] ** 4
    ) * 7
    assert central == pytest.approx([expected_central])
    assert variances == pytest.approx([expected_variance])
    assert uncertainties == pytest.approx([expected_variance**0.5])
    assert (variances[0] > 0) is positive_variance


@pytest.mark.parametrize("denominator", [0.0, -1.0, float("nan")])
def test_invalid_denominator_is_structured(denominator):
    components = {
        "data": [4.0],
        "background": [1.0],
        "diboson": [denominator],
        "var_data": [2.0],
        "var_background": [1.0],
        "var_diboson": [1.0],
    }
    with pytest.raises(
        diboson_module.DibosonContractError,
        match=r"input='fixture'.*year='2022'.*channel='3l_CR'.*final_bin=\[0.0, 1.0\]",
    ):
        diboson_module.compute_scale_factor_statistics(
            components,
            [0, 1],
            input_path="fixture",
            year="2022",
            channel="3l_CR",
            propagation_enabled=True,
        )


@pytest.mark.parametrize("missing_key", ["njets", "njets_sumw2"])
def test_enabled_mode_requires_nominal_and_companion(tmp_path, missing_key):
    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    del payload[missing_key]
    with pytest.raises(diboson_module.DibosonContractError, match="[Oo]rphan|Missing"):
        diboson_module.process_year(
            str(fixture),
            "2022",
            "njets",
            "3l_CR",
            [0, 1, 2, 3, 4, 5, 6],
            process_roles=_roles(),
            propagation_enabled=True,
            configuration_source="config",
            cache={str(fixture): payload},
        )


@pytest.mark.parametrize("mutation", ["axis", "category", "edge", "flow"])
def test_enabled_mode_rejects_companion_structure_mismatch(tmp_path, mutation):
    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    payload["njets_sumw2"] = _companion_with_axes(payload, mutation)
    with pytest.raises(
        diboson_module.DibosonContractError,
        match="axes/categories/edges/flow differ",
    ):
        diboson_module.process_year(
            str(fixture),
            "2022",
            "njets",
            "3l_CR",
            [0, 1, 2, 3, 4, 5, 6],
            process_roles=_roles(),
            propagation_enabled=True,
            configuration_source="config",
            cache={str(fixture): payload},
        )


@pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf")])
def test_enabled_mode_rejects_invalid_second_moment(tmp_path, bad_value):
    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    payload["njets_sumw2"].view(flow=False)[0, 0, 0, 0] = bad_value
    with pytest.raises(diboson_module.DibosonContractError, match="Invalid second moments"):
        diboson_module.process_year(
            str(fixture),
            "2022",
            "njets",
            "3l_CR",
            [0, 1, 2, 3, 4, 5, 6],
            process_roles=_roles(),
            propagation_enabled=True,
            configuration_source="config",
            cache={str(fixture): payload},
        )


def test_nonfinite_nominal_is_rejected(tmp_path):
    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    payload["njets"].view(flow=False)[0, 0, 0, 0] = np.nan
    with pytest.raises(diboson_module.DibosonContractError, match="Nonfinite nominal"):
        diboson_module.process_year(
            str(fixture),
            "2022",
            "njets",
            "3l_CR",
            [0, 1, 2, 3, 4, 5, 6],
            process_roles=_roles(),
            propagation_enabled=True,
            configuration_source="config",
            cache={str(fixture): payload},
        )


@pytest.mark.parametrize(
    ("roles", "message"),
    [
        (
            {
                "data": ["data_a_2022", "data_a_2022"],
                "background": ["ttbar_2022"],
                "diboson": ["WZTo3LNu_2022"],
                "ignored": [],
            },
            "duplicate",
        ),
        (
            {
                "data": ["data_a_2022"],
                "background": ["data_a_2022"],
                "diboson": ["WZTo3LNu_2022"],
                "ignored": [],
            },
            "pairwise disjoint",
        ),
        (
            {
                "data": ["data_a_2022", "data_b_2022"],
                "background": ["ttbar_2022", "zjets_2022"],
                "diboson": ["WZTo3LNu_2022", "ZZTo2L2Nu_2022"],
                "ignored": [],
            },
            "unclassified",
        ),
    ],
)
def test_process_roles_reject_duplicates_overlap_and_unclassified(
    tmp_path, roles, message
):
    fixture = _materialize_histogram_fixture(tmp_path)
    with pytest.raises(diboson_module.DibosonContractError, match=message):
        diboson_module.process_year(
            str(fixture),
            "2022",
            "njets",
            "3l_CR",
            [0, 1, 2, 3, 4, 5, 6],
            process_roles=roles,
            propagation_enabled=True,
            configuration_source="config",
        )


def test_disabled_mode_never_accesses_companion(tmp_path):
    class PoisonCompanion:
        def __getattribute__(self, name):
            raise AssertionError(f"disabled mode accessed companion attribute {name}")

    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    payload["njets_sumw2"] = PoisonCompanion()
    result = _run_fixture(
        tmp_path, enabled=False, cache={str(fixture): payload}
    )
    assert result["scale_factor_statistical_variances"] is None
    assert result["scale_factor_statistical_uncertainties"] is None
    assert result["provenance"]["statistical_inputs_consumed"] is False


def test_propagation_resolution_precedence():
    assert diboson_module.resolve_propagation_state({}, None) == (True, "default")
    assert diboson_module.resolve_propagation_state(
        {"propagate_statistical_uncertainties": False}, None
    ) == (False, "config")
    assert diboson_module.resolve_propagation_state(
        {"propagate_statistical_uncertainties": False}, True
    ) == (True, "cli")
    assert diboson_module.resolve_propagation_state(
        {"propagate_statistical_uncertainties": True}, False
    ) == (False, "cli")


def test_enabled_json_and_plot_align_with_analytic_arrays(tmp_path):
    result = _run_fixture(tmp_path)
    output = tmp_path / "enabled"
    json_path = diboson_module.make_diboson_sf_json(
        [0, 1, 2, 3, 4, 5, 6], result, "2022", str(output)
    )
    plot = diboson_module.save_scale_factor_plot(
        "2022",
        "3l_CR",
        result["bin_centers"],
        result["scale_factors"],
        result["fitted_values"],
        result["scale_factor_statistical_uncertainties"],
        propagation_enabled=True,
        output_dir=str(output),
    )
    payload = json.loads(Path(json_path).read_text())
    propagation = payload["statistical_uncertainty_propagation"]
    assert propagation["enabled"] is True
    assert propagation["formula"] == (
        "independent_data_minus_background_over_diboson_v1"
    )
    assert propagation["configuration_source"] == "config"
    assert payload["scale_factor_statistical_variances"] == pytest.approx(
        result["scale_factor_statistical_variances"]
    )
    assert payload["scale_factor_statistical_uncertainties"] == pytest.approx(
        result["scale_factor_statistical_uncertainties"]
    )
    assert plot["statistical_error_bars"] is True
    assert plot["y_errors"] == pytest.approx(
        result["scale_factor_statistical_uncertainties"]
    )
    assert any(value > 0 for value in plot["y_errors"])
    assert Path(plot["path"]).is_file()


def test_disabled_json_and_plot_contract(tmp_path):
    result = _run_fixture(tmp_path, enabled=False)
    output = tmp_path / "disabled"
    json_path = diboson_module.make_diboson_sf_json(
        [0, 1, 2, 3, 4, 5, 6], result, "2022", str(output)
    )
    plot = diboson_module.save_scale_factor_plot(
        "2022",
        "3l_CR",
        result["bin_centers"],
        result["scale_factors"],
        result["fitted_values"],
        result["scale_factor_statistical_uncertainties"],
        propagation_enabled=False,
        output_dir=str(output),
    )
    payload = json.loads(Path(json_path).read_text())
    propagation = payload["statistical_uncertainty_propagation"]
    assert propagation["enabled"] is False
    assert propagation["formula"] is None
    assert propagation["statistical_inputs_consumed"] is False
    assert payload["scale_factor_statistical_variances"] is None
    assert payload["scale_factor_statistical_uncertainties"] is None
    assert plot["statistical_error_bars"] is False
    assert plot["y_errors"] is None
    assert plot["annotation"] == "statistical uncertainties disabled"
    assert Path(plot["path"]).is_file()


@pytest.mark.parametrize("denominator", [0.0, -1.0])
def test_cli_blocking_error_writes_no_partial_output(tmp_path, denominator):
    fixture = _materialize_histogram_fixture(tmp_path)
    payload = diboson_module.load_pkl_file(str(fixture))
    diboson_indices = [4, 5]
    payload["njets"].view(flow=False)[diboson_indices, 0, 0, 0:2] = (
        denominator / 4
    )
    bad_path = tmp_path / "bad.pkl.gz"
    _write_payload(bad_path, payload)
    output = tmp_path / "out"
    with pytest.raises(diboson_module.DibosonContractError, match="denominator"):
        diboson_module.main(
            [
                "--pkl",
                str(bad_path),
                "--config",
                str(CONFIG_PATH),
                "--channel",
                "3l_CR",
                "--year",
                "2022",
                "--output-dir",
                str(output),
            ]
        )
    assert not output.exists()


def test_cli_override_records_source_and_writes_outputs(tmp_path):
    fixture = _materialize_histogram_fixture(tmp_path)
    output = tmp_path / "cli"
    result = diboson_module.main(
        [
            "--pkl",
            str(fixture),
            "--config",
            str(CONFIG_PATH),
            "--channel",
            "3l_CR",
            "--year",
            "2022",
            "--output-dir",
            str(output),
            "--no-propagate-statistical-uncertainties",
        ]
    )["2022"]
    payload = json.loads((output / "2022/diboson_sf_2022.json").read_text())
    assert result["configuration_source"] == "cli"
    assert payload["statistical_uncertainty_propagation"][
        "configuration_source"
    ] == "cli"
    assert payload["scale_factor_statistical_variances"] is None
    assert (output / "2022/diboson_sf_2022.png").is_file()
