import ast
from pathlib import Path
import sys

import awkward as ak
import hist
import numpy as np
import pytest
from coffea.analysis_tools import Weights

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "analysis" / "topeft_run2"))

from analysis.topeft_run2.analysis_processor import (
    AnalysisProcessor,
    calculate_sm_sumw2_weights,
)
from analysis.topeft_run2.make_cr_and_sr_plots import (
    CR_GRP_PATTERNS,
    SR_GRP_PATTERNS,
    populate_group_map,
)
from analysis.topeft_run2.run_analysis_excluded_mc_ul18 import (
    _configure_wq_categories,
    _resolve_category_group_selection,
)
from topcoffea.modules.utils import read_cfg_file
from topeft.modules.axes import info as axes_info
from topeft.modules.axes import info_2d as axes_info_2d
from topeft.modules.nonprompt_policy import (
    EXPLICIT_NONPROMPT_EXCLUSION,
    certify_active_nonprompt_policy,
)
from topeft.modules.sumw2_policy import resolve_sumw2_storage_policy, sumw2_target
from topcoffea.modules.get_param_from_jsons import GetParam
from topeft.modules.paths import topeft_path


CFG_DIR = REPO_ROOT / "input_samples" / "cfgs"

RUN2_ERAS = {"2016APV", "2016", "2017", "2018"}
RUN3_ERAS = {"2022", "2022EE", "2023", "2023BPix"}


def load_probe_cfg(name):
    return read_cfg_file(str(CFG_DIR / name), cfg={})


@pytest.mark.parametrize(
    ("cfg_name", "expected_eras", "expected_count"),
    (
        ("excluded_mc_run2_sr_probe.cfg", RUN2_ERAS, 36),
        ("excluded_mc_run3_sr_probe.cfg", RUN3_ERAS, 72),
    ),
)
def test_cfg_selects_exact_excluded_mc_universe(cfg_name, expected_eras, expected_count):
    samples = load_probe_cfg(cfg_name)

    assert len(samples) == expected_count
    assert {sample["year"] for sample in samples.values()} == expected_eras
    assert all(sample["isData"] is False for sample in samples.values())
    assert all(sample["WCnames"] == [] for sample in samples.values())

    counts_by_era = {
        era: sum(sample["year"] == era for sample in samples.values())
        for era in expected_eras
    }
    expected_per_era = 9 if expected_count == 36 else 18
    assert set(counts_by_era.values()) == {expected_per_era}

    def family(sample_key):
        if "DY" in sample_key:
            return "dy"
        if "ZG" in sample_key:
            return "zgamma"
        if "WJets" in sample_key:
            return "wjets"
        if "ST_" in sample_key or "_tW_" in sample_key or "_tbarW_" in sample_key:
            return "single_top"
        return "outside_scope"

    assert {family(sample_key) for sample_key in samples} == {
        "dy",
        "single_top",
        "zgamma",
        "wjets",
    }
    assert all(family(sample_key) != "outside_scope" for sample_key in samples)


@pytest.mark.parametrize(
    "cfg_name",
    ("excluded_mc_run2_sr_probe.cfg", "excluded_mc_run3_sr_probe.cfg"),
)
def test_sumw2_policy_covers_every_dataset_and_reaches_processor(cfg_name):
    samples = load_probe_cfg(cfg_name)
    config = {
        "mode": "full_custom",
        "rules": [{"variables": ["njets"]}],
    }
    policy = resolve_sumw2_storage_policy(
        config,
        samples=samples,
        runtime_families=["njets"],
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        sumw2_storage_present=True,
    )

    assert len(policy.resolved_targets) == len(samples)
    assert {target.dataset for target in policy.resolved_targets} == set(samples)
    assert {target.family for target in policy.resolved_targets} == {"njets"}
    if cfg_name == "excluded_mc_run2_sr_probe.cfg":
        for dataset, process in (
            ("UL17_DY10to50_NDSkim", "DY10to50_centralUL17"),
            ("UL17_DY50_NDSkim", "DY50_centralUL17"),
        ):
            assert samples[dataset]["histAxisName"] == process
            assert sumw2_target(dataset, process, "njets") in policy.resolved_targets

    processor = AnalysisProcessor(
        samples,
        hist_lst=["njets"],
        fill_sumw2_hist=True,
        skip_control_regions=True,
        all_analysis=True,
        sumw2_policy=policy,
    )
    assert processor._selected_sumw2_families == frozenset({"njets"})
    assert "njets_sumw2" in processor.accumulator


def test_sumw2_policy_rejects_empty_and_incomplete_targets():
    samples = load_probe_cfg("excluded_mc_run2_sr_probe.cfg")
    with pytest.raises(ValueError, match="SUMW2-E002"):
        resolve_sumw2_storage_policy(
            {"mode": "full_custom", "rules": []},
            samples=samples,
            runtime_families=["njets"],
            axes_info=axes_info,
            axes_info_2d=axes_info_2d,
            sumw2_storage_present=True,
        )

    dataset_names = sorted(samples)
    required = [
        sumw2_target(dataset, samples[dataset]["histAxisName"], "njets")
        for dataset in dataset_names
    ]
    with pytest.raises(ValueError, match="SUMW2-E010"):
        resolve_sumw2_storage_policy(
            {
                "mode": "full_custom",
                "rules": [
                    {
                        "dataset_names": [dataset_names[0]],
                        "variables": ["njets"],
                    }
                ],
            },
            samples=samples,
            runtime_families=["njets"],
            axes_info=axes_info,
            axes_info_2d=axes_info_2d,
            sumw2_storage_present=True,
            consumer_requirements=required,
        )


@pytest.mark.parametrize(
    ("groups", "expected_groups"),
    (
        (["2l", "2los_1tau"], {"2l", "2los_1tau"}),
        (["3l_onZ_tau"], {"3l_onZ_tau"}),
    ),
)
def test_reference_block_categories_use_native_sr_groups(groups, expected_groups):
    resolved = _resolve_category_group_selection(
        category_groups=groups,
        offz_3l_split=False,
        tau_h_analysis=False,
        fwd_analysis=False,
        all_analysis=True,
        skip_sr=False,
        skip_cr=True,
    )
    assert resolved["resolved_sr_block_name"] == "ALL_CH_LST_SR"
    assert set(resolved["sr_category_dict"]) == expected_groups
    if "2los_1tau" in expected_groups:
        p0 = resolved["sr_category_dict"]["2los_1tau"]
        assert p0["jet_lst"] == [">3"]
        assert p0["lep_chan_lst"][0][0] == "2los_onZ_1tau"


def test_ul17_dy_distinct_labels_preserve_nominal_and_second_moments():
    samples = load_probe_cfg("excluded_mc_run2_sr_probe.cfg")
    low = samples["UL17_DY10to50_NDSkim"]
    high = samples["UL17_DY50_NDSkim"]
    assert low["histAxisName"] == "DY10to50_centralUL17"
    assert high["histAxisName"] == "DY50_centralUL17"

    low_weights = Weights(2)
    low_weights.add("norm", np.array([2.0, -1.0]) * 2.0)
    high_weights = Weights(2)
    high_weights.add("norm", np.array([3.0, -4.0]) * 0.5)
    contributions = np.concatenate((low_weights.weight(), high_weights.weight()))

    expected_nominal = 1.5
    expected_sumw2 = 26.25
    assert np.sum(contributions) == pytest.approx(expected_nominal)
    assert np.sum(calculate_sm_sumw2_weights(contributions)) == pytest.approx(
        expected_sumw2
    )
    assert expected_sumw2 != pytest.approx(expected_nominal**2)

    nominal = hist.Hist(
        hist.axis.StrCategory([], growth=True, name="process"),
        storage=hist.storage.Double(),
    )
    nominal.fill(process=[low["histAxisName"]] * 2, weight=low_weights.weight())
    nominal.fill(process=[high["histAxisName"]] * 2, weight=high_weights.weight())

    second_moment = hist.Hist(
        hist.axis.StrCategory([], growth=True, name="process"),
        storage=hist.storage.Double(),
    )
    second_moment.fill(
        process=[low["histAxisName"]] * 2,
        weight=calculate_sm_sumw2_weights(low_weights.weight()),
    )
    second_moment.fill(
        process=[high["histAxisName"]] * 2,
        weight=calculate_sm_sumw2_weights(high_weights.weight()),
    )

    assert set(nominal.axes[0]) == {low["histAxisName"], high["histAxisName"]}
    assert nominal[low["histAxisName"]] == pytest.approx(2.0)
    assert nominal[high["histAxisName"]] == pytest.approx(-0.5)
    assert second_moment[low["histAxisName"]] == pytest.approx(20.0)
    assert second_moment[high["histAxisName"]] == pytest.approx(6.25)
    assert np.sum(nominal.values()) == pytest.approx(expected_nominal)
    assert np.sum(second_moment.values()) == pytest.approx(expected_sumw2)


def _native_sample_type(processor_path, process, is_data=False):
    source = processor_path.read_text()
    tree = ast.parse(source)
    process_method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "process"
    )
    for index, node in enumerate(process_method.body):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "sampleType"
            and isinstance(node.value, ast.Constant)
            and node.value.value == "prompt"
        ):
            branch = process_method.body[index + 1]
            assert isinstance(branch, ast.If)
            break
    else:
        pytest.fail(f"Native sampleType branch missing from {processor_path}")

    # Compile the complete original assignment and conditional, with no rewritten predicate.
    block = ast.fix_missing_locations(ast.Module(body=[node, branch], type_ignores=[]))
    lookup = GetParam(topeft_path("params/params.json"))
    scope = {
        "histAxisName": process,
        "isData": is_data,
        "get_te_param": lookup,
    }
    exec(compile(block, str(processor_path), "exec"), scope)
    return scope["sampleType"]


def _native_matching_mask(lepton_count, sample_type):
    source_path = REPO_ROOT / "topeft" / "modules" / "event_selection.py"
    tree = ast.parse(source_path.read_text())
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == f"add{lepton_count}lMaskAndSFs"
    )
    branch = next(
        node for node in function.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "sampleType"
    )
    block = ast.fix_missing_locations(ast.Module(body=[branch], type_ignores=[]))
    flavors = ([1] * lepton_count, [1] * (lepton_count - 1) + [22], [5] * lepton_count)
    leptons = ak.Array([
        [
            {"genPartFlav": flavor, "gen_pdgId": 11, "pdgId": 11}
            for flavor in event_flavors
        ]
        for event_flavors in flavors
    ])
    scope = {
        "sampleType": sample_type,
        "padded_FOs": leptons,
        "mask": np.ones(3, dtype=bool),
        "ak": ak,
    }
    exec(compile(block, str(source_path), "exec"), scope)
    return ak.to_list(scope["mask"])


@pytest.mark.parametrize(
    "processor_name",
    ("analysis_processor.py", "analysis_processor_diboson.py"),
)
def test_ul17_dy_nominal_classification_and_matching(processor_name):
    samples = load_probe_cfg("excluded_mc_run2_sr_probe.cfg")
    processor_path = REPO_ROOT / "analysis" / "topeft_run2" / processor_name
    old_type = _native_sample_type(processor_path, "DYJetsToLL_centralUL17")
    new_types = [
        _native_sample_type(processor_path, samples[dataset]["histAxisName"])
        for dataset in ("UL17_DY10to50_NDSkim", "UL17_DY50_NDSkim")
    ]
    assert new_types == [old_type, old_type]

    for control in (
        "DY10to50_centralUL16APV",
        "DY50_centralUL16",
        "DY10to50_centralUL18",
        "DY50_centralUL18",
        "DYJetsToLL_MLL-50_central2022",
    ):
        assert _native_sample_type(processor_path, control) == old_type
    prompt_type = _native_sample_type(processor_path, "WJetsToLNu_centralUL17")
    conversion_type = _native_sample_type(processor_path, "ZGToLLG_centralUL17")
    assert prompt_type != old_type
    assert conversion_type != old_type
    assert _native_sample_type(processor_path, "DY10to50_centralUL17", True) == "data"

    for lepton_count in (1, 2, 3):
        old_mask = _native_matching_mask(lepton_count, old_type)
        assert old_mask == [True, True, False]
        assert all(
            _native_matching_mask(lepton_count, sample_type) == old_mask
            for sample_type in new_types
        )
        assert _native_matching_mask(lepton_count, prompt_type) == [True, False, False]
        assert _native_matching_mask(lepton_count, conversion_type) == [False, True, False]
        assert _native_matching_mask(lepton_count, "data") == [True, True, True]


def test_ul17_dy_nonprompt_policy_accepts_split_labels():
    samples = load_probe_cfg("excluded_mc_run2_sr_probe.cfg")
    certificate = certify_active_nonprompt_policy(
        samples,
        configuration_source="excluded_mc_run2_sr_probe.cfg",
    )
    rows = {row.raw_process_label: row for row in certificate.resolutions}
    for dataset in ("UL17_DY10to50_NDSkim", "UL17_DY50_NDSkim"):
        assert rows[samples[dataset]["histAxisName"]].policy_role == EXPLICIT_NONPROMPT_EXCLUSION
    legacy = certify_active_nonprompt_policy(
        ("DYJetsToLL_centralUL17",),
        configuration_source="legacy_ul17_dy_label",
    )
    assert legacy.resolutions[0].policy_role == EXPLICIT_NONPROMPT_EXCLUSION


def test_ul17_dy_cr_plotter_routing_recognizes_distinct_labels():
    samples = load_probe_cfg("excluded_mc_run2_sr_probe.cfg")
    processes = [
        samples[dataset]["histAxisName"]
        for dataset in ("UL17_DY10to50_NDSkim", "UL17_DY50_NDSkim")
    ]
    cr_map = populate_group_map(processes, CR_GRP_PATTERNS)

    assert cr_map["DY"] == processes
    assert all(sum(process in members for members in cr_map.values()) == 1 for process in processes)


def test_excluded_mc_runtime_category_reservations():
    class queue_recorder:
        def __init__(self):
            self.calls = []

        def specify_category_max_resources(self, category, resources):
            self.calls.append(("maximum", category, resources))

        def specify_category_min_resources(self, category, resources):
            self.calls.append(("minimum", category, resources))

    queue = queue_recorder()
    _configure_wq_categories(
        queue,
        processing_cores=1,
        accumulating_memory_mb=32000,
        accumulating_cores=2,
    )
    assert queue.calls == [
        ("maximum", "processing", {"cores": 1}),
        ("minimum", "accumulating", {"memory": 32000, "cores": 2}),
    ]
