"""Differential consumers using exact processor statements and native payloads."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import awkward as ak
import hist
import numpy as np
import pytest

from test_jet_build_reuse import ap, baseline_helpers, run_case, years
from topcoffea.modules.histEFT import HistEFT
from topcoffea.modules.sparseHist import SparseHist


def processor_jet_consumers():
    """Compile the maintained processor's actual post-build jet statements.

    This is a bounded consumer probe, not a full process(events) execution.
    Lepton event/category selection and trigger weights are not exercised.
    """
    source = Path(ap.__file__).read_text()
    tree = ast.parse(source)
    process = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "process")
    jet_block = next(node for node in ast.walk(process) if isinstance(node, ast.With)
                     and any(isinstance(child, ast.Assign) and any(
                         isinstance(target, ast.Name) and target.id == "vetos_tocleanjets"
                         for target in child.targets) for child in node.body))
    start = next(index for index, node in enumerate(jet_block.body)
                 if isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id == "hem2018_mask"
                     for target in node.targets))
    btag_block = next(node for node in ast.walk(process) if isinstance(node, ast.With)
                     and any(isinstance(child, ast.Assign) and any(
                         isinstance(target, ast.Name) and target.id == "isBtagJetsLoose"
                         for target in child.targets) for child in node.body))
    return compile(ast.Module(body=copy.deepcopy(jet_block.body[start:] + btag_block.body),
                              type_ignores=[]), str(ap.__file__) + ":jet_consumers", "exec")


def histogram_key(histogram, key):
    # SparseHist's generated namedtuple class name contains id(histogram).
    # Preserve categorical axis identity and values, excluding that object ID.
    assert len(key) == len(histogram.categorical_axes)
    return json.dumps({axis.name: value for axis, value in
                       zip(histogram.categorical_axes, key)}, sort_keys=True)


def histogram_values(histogram):
    return {histogram_key(histogram, key): np.asarray(value).tolist()
            for key, value in histogram.view(flow=True, as_dict=True).items()}


def consume_jets(analysis, met, hem, muons, pt_name, year, is_data, run):
    namespace = dict(vars(ap))
    namespace.update(cleanedJets=analysis, hem_corrected_jets=hem, mu=muons,
        jetptname=pt_name, year=year, isData=is_data, run=run,
        is_run3=year.startswith("202"), is_run2=year.startswith("201"),
        met=met, met_raw=met, type1_met=met, syst_var="nominal", btagAlgo="btagDeepFlavB",
        events=SimpleNamespace(event=np.arange(4, dtype=np.uint64)),
        self=SimpleNamespace(fwd_eta_band_pt_apply="on"))
    exec(processor_jet_consumers(), namespace)
    names = ("hem2018_mask", "veto_map_input_jets", "veto_map_array", "veto_map_mask",
             "cleanedJets", "goodJets", "fwdJets", "njets", "nfwdj", "ht", "j0", "fwd0",
             "isBtagJetsLoose", "isBtagJetsMedium", "nbtagsl", "nbtagsm")
    result = {name: ak.to_list(namespace[name]) for name in names}
    good = namespace["goodJets"]
    # Real b-tag payload consumers and method-1a, including flavour association.
    event_weight = np.ones(4)
    if not is_data:
        for flavour in ("light", "bc"):
            flavour_mask = good.hadronFlavour == 0 if flavour == "light" else good.hadronFlavour > 0
            selected = good[flavour_mask]
            year_sf = "2016APV" if year == "2016" and flavour == "light" else year
            method = "deepJet_" + ("incl" if year.startswith("201") else "light") if flavour == "light" else "deepJet_comb"
            eff_m = ap.GetBtagEff(selected, year, "medium", "btagDeepFlavB")
            eff_l = ap.GetBtagEff(selected, year, "loose", "btagDeepFlavB")
            sf_m = ap.tc_cor.btag_sf_eval(selected, "M", year_sf, method, "central")
            sf_l = ap.tc_cor.btag_sf_eval(selected, "L", year_sf, method, "central")
            medium = namespace["isBtagJetsMedium"][flavour_mask]
            loose = namespace["isBtagJetsLoose"][flavour_mask]
            p_data, p_mc = ap.tc_cor.get_method1a_wgt_doublewp(
                eff_m, eff_l, sf_m, sf_l, medium, loose & ~medium, ~loose)
            event_weight *= np.asarray(p_data / p_mc)
    event_weight *= np.array([1., -2., .5, 3.])
    mask = np.asarray(namespace["hem2018_mask"] & namespace["veto_map_mask"])
    coefficients = np.array([[1., 2., 3.], [-1., 4., 2.], [.5, -2., 1.], [3., 0., -1.]])
    axis = hist.axis.Regular(3, 0., 3., name="njets")
    categories = [hist.axis.StrCategory([], name=name, growth=True)
                  for name in ("process", "channel", "systematic", "appl")]
    scalar = SparseHist(*categories, axis, storage="Double")
    eft = HistEFT(*categories, axis, wc_names=["ctG"])
    sumw2 = SparseHist(*categories, axis, storage="Double")
    coords = dict(process="fixture", channel="jet_probe", systematic="active", appl="probe",
                  njets=np.asarray(namespace["njets"])[mask])
    scalar.fill(**coords, weight=event_weight[mask])
    eft.fill(**coords, weight=event_weight[mask], eft_coeff=coefficients[mask])
    sumw2.fill(**coords, weight=ap.calculate_sm_sumw2_weights(event_weight[mask], coefficients[mask]))
    result.update(weights=event_weight.tolist(), mask=mask.tolist(), wc_names=eft._wc_names,
                  coefficients=coefficients.tolist(), scalar=histogram_values(scalar),
                  eft=histogram_values(eft), sumw2=histogram_values(sumw2),
                  eft_sm={histogram_key(eft, k): np.asarray(v).tolist() for k,v in eft.eval({}).items()},
                  axis_names=[axis.name for axis in scalar.axes])
    return result


@pytest.mark.parametrize("year", years)
def test_native_jet_consumers_and_histograms(year, tmp_path):
    baseline = run_case(baseline_helpers(), year, consumer=consume_jets)
    candidate = run_case(ap, year, reuse=True, consumer=consume_jets)
    evidence_path = tmp_path / "candidate.json"
    evidence_path.write_text(json.dumps(candidate, allow_nan=False))
    candidate = json.loads(evidence_path.read_text())
    assert baseline["outputs"] == candidate["outputs"]
    assert baseline["input_sha256"] == candidate["input_sha256"]

    assert baseline["request_input_sha256"] == candidate["request_input_sha256"]
    assert baseline["array_types"] == candidate["array_types"]


def test_histogram_keys_preserve_axis_values_across_instances():
    results = []
    for _ in range(2):
        histogram = SparseHist(
            hist.axis.StrCategory([], name="process", growth=True),
            hist.axis.Regular(2, 0., 2., name="probe"), storage="Double")
        histogram.fill(process="fixture", probe=np.array([.5, 3.]),
                       weight=np.array([2., -1.]))
        results.append(histogram_values(histogram))
    assert results[0] == results[1]
    assert results[0] == {json.dumps({"process": "fixture"}, sort_keys=True):
                          [0., 2., 0., -1.]}
