"""Native-backend differential oracle for invocation-local jet build reuse.

The baseline helpers are compiled verbatim from the declared ancestor commit.
No correction factory, selector, random generator or payload is replaced.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import awkward as ak
import numpy as np
import pytest
from coffea.nanoevents.methods import candidate

from analysis.topeft_run2 import analysis_processor as ap
from topeft.modules import corrections as cor
from topcoffea.modules import corrections as tc_cor


baseline_cut = "cefb2f68ab10cc0bb5ce47674bc21fcf55f5b769"
baseline_sha256 = "ae4f962ca99c1cce0aabe92d4c66d1abf3af5c6fe682ed9dd67729e39df47168"
baseline_helper_source_sha256 = '8eb17f5fb852b9719b2edac85061258cf3d83c5a406f94aa7fa98dc75886bc69'
# Verbatim original helpers; no history object or network is needed by tests.
baseline_helper_source = '''
def get_analysis_cleaned_jets(full_jets, leptons, cleaning_taus=None):
    """Apply the established TOP-26-006 lepton and optional tau jet cleaning."""

    jet_lepton_indices = ak.cartesian(
        [ak.local_index(full_jets.pt), leptons.jetIdx], nested=True
    )
    cleaned_jets = full_jets[
        ~ak.any(jet_lepton_indices.slot0 == jet_lepton_indices.slot1, axis=-1)
    ]
    if cleaning_taus is not None:
        cleaned_jets["isTauClean"] = te_os.isClean(
            cleaned_jets, cleaning_taus, drmin=0.5
        )
        cleaned_jets = cleaned_jets[cleaned_jets.isTauClean]
    return cleaned_jets

def build_corrected_jet_view(
    jets,
    jets_rho,
    *,
    year,
    is_data,
    correction_factory,
    syst_var,
    jet_systematics,
    lazy_cache,
):
    """Build one corrected jet view from its own explicit input collection."""

    jet_pt_name = "pt_nom" if hasattr(jets, "pt_nom") else "pt"
    jets["pt_raw"] = (1 - jets.rawFactor) * jets.pt
    jets["mass_raw"] = (1 - jets.rawFactor) * jets.mass
    jets["rho"] = ak.broadcast_arrays(jets_rho, jets.pt)[0]
    if not is_data:
        jets["pt_gen"] = ak.values_astype(
            ak.fill_none(jets.matched_gen.pt, 0), np.float32
        )

    corrected_jets = correction_factory.build(jets, lazy_cache=lazy_cache)
    corrected_jets = apply_maintained_jet_systematic(
        year, corrected_jets, syst_var, jet_systematics
    )
    return corrected_jets, jet_pt_name

def build_analysis_and_hem_jet_views(
    full_jets,
    leptons,
    cleaning_taus,
    jets_rho,
    *,
    year,
    is_data,
    run_era,
    run,
    suppress_forward_eta_stochastic_jer,
    syst_var,
    jet_systematics,
    analysis_lazy_cache,
):
    """Build analysis-cleaned and independent full-jet HEM correction views."""

    analysis_raw_jets = get_analysis_cleaned_jets(
        full_jets, leptons, cleaning_taus
    )
    correction_factory = ApplyJetCorrections(
        year,
        corr_type="jets",
        isData=is_data,
        era=run_era,
        run=run,
        suppress_forward_eta_stochastic_jer=(
            suppress_forward_eta_stochastic_jer
        ),
    )
    analysis_corrected_jets, jet_pt_name = build_corrected_jet_view(
        analysis_raw_jets,
        jets_rho,
        year=year,
        is_data=is_data,
        correction_factory=correction_factory,
        syst_var=syst_var,
        jet_systematics=jet_systematics,
        lazy_cache=analysis_lazy_cache,
    )

    if year == "2018":
        # Keep HEM lazy products isolated from the historical analysis cache.
        hem_corrected_jets, _ = build_corrected_jet_view(
            full_jets,
            jets_rho,
            year=year,
            is_data=is_data,
            correction_factory=correction_factory,
            syst_var=syst_var,
            jet_systematics=jet_systematics,
            lazy_cache={},
        )
    else:
        hem_corrected_jets = analysis_corrected_jets

    return analysis_corrected_jets, hem_corrected_jets, jet_pt_name
'''

years = ("2016APV", "2016", "2017", "2018", "2022", "2022EE", "2023", "2023BPix")
eras = dict(zip(years, ("B", "F", "B", "A", "C", "E", "C1", "D1")))


def baseline_helpers():
    assert hashlib.sha256(baseline_helper_source.encode()).hexdigest() == baseline_helper_source_sha256
    names = {"get_analysis_cleaned_jets", "build_corrected_jet_view",
             "build_analysis_and_hem_jet_views"}
    tree = ast.parse(baseline_helper_source)
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in names]
    assert {node.name for node in selected} == names
    namespace = dict(vars(ap))
    exec(compile(ast.Module(body=selected, type_ignores=[]),
                 baseline_cut + ":analysis_processor.py", "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def fixture_inputs(pt_nom=False, partitioned=False):
    def jet(index, pt, eta, phi, gen):
        row = dict(pt=pt, mass=pt / 10, eta=eta, phi=phi, rawFactor=0.1,
                   area=0.5, matched_gen={"pt": gen}, partonFlavour=(5, 4, 1, 21, 99)[index % 5],
                   hadronFlavour=(5, 4, 0)[index % 3], raw_index=index,
                   jetId=6, puId=7, chEmEF=0.1, neEmEF=0.1,
                   muonSubtrFactor=0.1, btagDeepFlavB=(0.9, 0.3, 0.01)[index % 3],
                   neHEF=0.2, chHEF=0.5, muEF=0.05, nConstituents=20,
                   chMultiplicity=10, neMultiplicity=10)
        if pt_nom:
            row['pt_nom'] = pt
        return row
    rows = [[jet(0, 31., -2., -1., 28.), jet(1, 45., 0.7, 0.4, 0.),
             jet(2, 60., 2.7, 1.4, 0.), jet(3, 80., 4., 2.4, 74.)], [],
            [jet(4, 35., 0.4, -2., 32.), jet(5, 100., -2.7, 0.8, 92.),
             jet(6, 26., 1.2, 1.8, 0.)],
            [jet(7, 52., -0.5, -0.4, 48.), jet(8, 70., 2.6, 2.8, 0.)]]
    jets = ak.with_name(ak.Array(rows), "PtEtaPhiMCandidate", behavior=candidate.behavior)
    for field in ("pt", "mass", "eta", "phi", "rawFactor", "area", "chEmEF", "neEmEF", "muonSubtrFactor", "btagDeepFlavB", "neHEF", "chHEF", "muEF"):
        jets[field] = ak.values_astype(jets[field], np.float32)
    if pt_nom:
        jets["pt_nom"] = ak.values_astype(jets.pt_nom, np.float32)
    if partitioned:
        jets = ak.concatenate([jets[:2], jets[2:]])
    leptons = ak.Array([[{"jetIdx": -1}] for _ in rows])
    taus = ak.with_name(ak.Array([[dict(pt=20.05, mass=1.2, eta=0.7, phi=0.4,
                     decayMode=0, genPartFlav=5)] for _ in rows]),
                     "PtEtaPhiMCandidate", behavior=candidate.behavior)
    muons = ak.with_name(ak.Array([[dict(pt=10., eta=1.7, phi=2.1, mass=.105,
                                      isPFcand=True)] for _ in rows]),
                       "PtEtaPhiMCandidate", behavior=candidate.behavior)
    return jets, leptons, taus, muons


def population(year, *, is_data=False, systematics=True, tau=True):
    jet_labels = cor.get_supported_jet_systematics(year, isData=is_data, era=eras[year])
    met_labels = cor.get_supported_met_systematics(year, isData=is_data, era=eras[year])
    muon_labels = cor.get_supported_muon_momentum_systematics(year, isData=is_data)
    tau_labels = cor.get_supported_tau_energy_systematics(year, isData=is_data) if tau else []
    labels = ["nominal"] + jet_labels + met_labels + muon_labels + tau_labels
    if is_data or not systematics:
        labels = ["nominal"]
    return labels, jet_labels, met_labels, muon_labels, tau_labels


def request_cleaning(year, label, leptons, attached_taus, muon_labels, tau):
    # A FO membership counterexample is supplied at the helper boundary. Full
    # muon calibration/FO event selection is covered separately, not simulated.
    selected_leptons = leptons
    if label in muon_labels:
        selected_leptons = ak.Array([[{"jetIdx": 0}], [{"jetIdx": -1}],
                                     [{"jetIdx": 1}], [{"jetIdx": -1}]])
    cleaning_taus = None
    if tau:
        selected = cor.ApplyTauEnergySystematics(copy.copy(attached_taus), label)
        cleaning_taus = selected[selected.pt > 20.]
    return selected_leptons, cleaning_taus


def type1_inputs(jets, year, is_data):
    rho = np.array([20., 22., 24., 26.])
    prepared = ak.with_field(jets, (1 - jets.rawFactor) * jets.pt, "pt_raw")
    prepared = ak.with_field(prepared, (1 - jets.rawFactor) * jets.mass, "mass_raw")
    prepared = ak.with_field(prepared, ak.broadcast_arrays(rho, jets.pt)[0], "rho")
    if not is_data:
        prepared = ak.with_field(prepared, ak.values_astype(jets.matched_gen.pt, np.float32), "pt_gen")
    corr_t1 = ak.Array([[dict(rawPt=18., eta=.3, phi=.2, area=.4,
                             muonSubtrFactor=.1, rho=float(r))] for r in rho])
    met = ak.Array([dict(pt=100., phi=.2, MetUnclustEnUpDeltaX=2.,
                        MetUnclustEnUpDeltaY=3.) for _ in rho])
    return prepared, corr_t1, met


def array_values(array):
    return ak.to_list(array)


def view_values(view):
    # Consume precisely the active view, including preserved fields. Do not
    # eagerly demand every unused systematic branch while testing lazy reuse.
    return {field: array_values(view[field]) for field in view.fields
            if not field.startswith(("JES_", "JER", "jet_energy_uncertainty_"))}


def run_case(helpers, year, *, reuse=False, is_data=False, systematics=True,
             tau=True, pt_nom=False, consumer=None, demand=None):
    jets, leptons, taus, muons = fixture_inputs(pt_nom=pt_nom)
    frozen_inputs = dict(jets=array_values(jets), leptons=array_values(leptons),
                         taus=array_values(taus), muons=array_values(muons))
    labels, jet_labels, met_labels, muon_labels, tau_labels = population(
        year, is_data=is_data, systematics=systematics, tau=tau)
    if demand is not None:
        labels = demand
    attached_taus = cor.AttachTauEnergyCorrections(year, taus, is_data, vsJetWP="Medium") if tau else None
    run = np.array([319077] * 4) if year.startswith("201") else np.array([367100] * 4)
    if is_data and year == "2022":
        run = np.full(4, 355862)  # Maintained 2022 era-C fixture run.
    rho = np.array([20., 22., 24., 26.])
    frozen_inputs.update(year=year, is_data=is_data, systematics=systematics,
                         tau=tau, pt_nom=pt_nom, run=run.tolist(), rho=rho.tolist(),
                         labels=labels, suppress_forward=year.startswith("202"))
    rows = []
    reporter = SimpleNamespace(mark=lambda phase, **row: rows.append(dict(phase=phase, **row)))
    cache = {}
    prepared, corr_t1, stored_met = type1_inputs(jets, year, is_data)
    with tc_cor.telemetry_context(reporter, "preloop", -1):
        type1 = cor.ApplyJetCorrections(year, corr_type="type1_met", isData=is_data,
            era=eras[year], run=run, suppress_forward_eta_stochastic_jer=year.startswith("202")).build(
                stored_met, stored_met, prepared, corr_t1, lazy_cache=cache)
    state = {}
    outputs = []
    array_types = []
    cache_entries = []
    for index, label in enumerate(labels):
        selected_leptons, cleaning_taus = request_cleaning(
            year, label, leptons, attached_taus, muon_labels, tau)
        extra = dict(build_reuse=state,
                     reuse_analysis=label in ["nominal"] + jet_labels + met_labels) if reuse else {}
        with tc_cor.telemetry_context(reporter, label, index):
            analysis, hem, pt_name = helpers.build_analysis_and_hem_jet_views(
                jets, selected_leptons, cleaning_taus, rho, year=year,
                is_data=is_data, run_era=eras[year], run=run,
                suppress_forward_eta_stochastic_jer=year.startswith("202"),
                syst_var=label, jet_systematics=jet_labels, analysis_lazy_cache=cache, **extra)
            active_met = cor.ApplyMETSystematics(type1, label)
            array_types.append(dict(label=label, analysis=str(ak.type(analysis)),
                                    hem=str(ak.type(hem)),
                                    analysis_class=str(type(analysis)),
                                    hem_class=str(type(hem))))
            record = dict(label=label, analysis=view_values(analysis), hem=view_values(hem),
                          jet_pt_name=pt_name, offsets=array_values(ak.num(analysis)),
                          met=array_values(active_met),
                          hem_mask=array_values(ap.get_hem2018_event_mask(
                              hem, muons, np.arange(4, dtype=np.uint64), run, year, is_data)),
                          hem_alias=analysis is hem)
            if consumer is not None:
                record["consumer"] = consumer(analysis, active_met, hem, muons,
                                               pt_name, year, is_data, run)
            # Field replacement must never annotate another returned view/base.
            analysis["reuse_test_annotation"] = ak.ones_like(analysis.pt)
            if reuse and "analysis_base" in state:
                assert "reuse_test_annotation" not in state["analysis_base"].fields
            outputs.append(record)
            cache_entries.append(dict(analysis=len(cache), hem=len(state.get("hem_lazy_cache", {}))))
    counts = {}
    for row in rows:
        if row["operation"] == "CorrectedJetsFactory.build.total":
            key = "type1" if row["syst_var"] == "preloop" else "analysis_and_hem"
            counts[key] = counts.get(key, 0) + row["calls"]
    result = dict(year=year, labels=labels, jet_labels=jet_labels, met_labels=met_labels,
                  muon_labels=muon_labels, tau_labels=tau_labels, outputs=outputs,
                  counts=counts, total_builds=sum(counts.values()), cache_entries=cache_entries,
                  state_keys=sorted(state), input_sha256=hashlib.sha256(
                      json.dumps(array_values(fixture_inputs(pt_nom=pt_nom)[0]), sort_keys=True).encode()).hexdigest())
    result["array_types"] = array_types
    result["input_configuration"] = frozen_inputs
    result["request_input_sha256"] = hashlib.sha256(
        json.dumps(frozen_inputs, sort_keys=True).encode()).hexdigest()
    state.clear()
    return result


def capture_baseline(destination):
    helpers = baseline_helpers()
    results = [run_case(helpers, year) for year in years]
    Path(destination).write_text(json.dumps(results, indent=2, allow_nan=False) + "\n")
    reopened = json.loads(Path(destination).read_text())
    assert len(reopened) == len(years)
    return [dict(year=r["year"], builds=r["total_builds"], labels=len(r["labels"])) for r in reopened]


@pytest.mark.parametrize("year", years)
def test_native_all_views_match_exact_baseline(year):
    before = run_case(baseline_helpers(), year)
    after = run_case(ap, year, reuse=True)
    assert after["input_sha256"] == before["input_sha256"]
    assert after["outputs"] == before["outputs"]
    assert after["jet_labels"] == before["jet_labels"]
    assert after["total_builds"] < before["total_builds"]
    labels, jet_labels, met_labels, muon_labels, tau_labels = population(year)
    assert after["total_builds"] == 1 + 1 + len(muon_labels) + len(tau_labels) + (year == "2018")
    assert before["total_builds"] == 1 + len(labels) * (1 + (year == "2018"))


@pytest.mark.parametrize("year", ("2018", "2022"))
@pytest.mark.parametrize("options", (dict(is_data=True), dict(systematics=False), dict(tau=False), dict(pt_nom=True)))
def test_nominal_data_tau_off_and_pt_nom(year, options):
    before = run_case(baseline_helpers(), year, **options)
    after = run_case(ap, year, reuse=True, **options)
    assert after["outputs"] == before["outputs"]
    if options.get("is_data") or options.get("systematics") is False:
        assert after["total_builds"] == before["total_builds"]


@pytest.mark.parametrize("demand", (
    ["JER_2018Down", "nominal", "JER_2018Up", "JER_2018Down"],
    ["JES_FlavorQCDUp", "JES_FlavorQCDDown", "nominal", "JES_FlavorQCDUp"],
    ["nominal"],
))
def test_repeated_and_reordered_lazy_demands(demand):
    before = run_case(baseline_helpers(), "2018", tau=False, demand=demand)
    after = run_case(ap, "2018", reuse=True, tau=False, demand=demand)
    assert after["outputs"] == before["outputs"]


def test_fo_and_tau_thresholds_change_membership():
    jets, leptons, taus, _ = fixture_inputs()
    attached = cor.AttachTauEnergyCorrections("2022", taus, False, vsJetWP="Medium")
    label = "CMS_scale_t_DeepTau2018v2p5_DM0_genTau_2022Up"
    nominal = cor.ApplyTauEnergySystematics(copy.copy(attached), "nominal")
    varied = cor.ApplyTauEnergySystematics(copy.copy(attached), label)
    assert nominal.pt[0, 0] < 20. < varied.pt[0, 0]
    before = ap.get_analysis_cleaned_jets(jets, leptons, nominal[nominal.pt > 20.])
    after = ap.get_analysis_cleaned_jets(jets, leptons, varied[varied.pt > 20.])
    assert ak.to_list(before.raw_index)[0] == [0, 1, 2, 3]
    assert ak.to_list(after.raw_index)[0] == [0, 2, 3]
    fo = ak.Array([[{"jetIdx": 0}], [{"jetIdx": -1}], [{"jetIdx": -1}], [{"jetIdx": -1}]])
    assert ak.to_list(ap.get_analysis_cleaned_jets(jets, fo).raw_index)[0] == [1, 2, 3]


def test_flat_empty_jer_preserves_baseline_exception():
    jets, _, _, _ = fixture_inputs()
    empty = jets[:0]
    factory = cor.ApplyJetCorrections("2018", corr_type="jets", era="A", isData=False, run=np.array([], dtype=int))
    kwargs = dict(year="2018", is_data=False, correction_factory=factory,
                  syst_var="nominal", jet_systematics=[], lazy_cache={})
    with pytest.raises(IndexError):
        baseline_helpers().build_corrected_jet_view(empty, np.array([]), **kwargs)
    with pytest.raises(IndexError):
        ap.build_corrected_jet_view(empty, np.array([]), **kwargs, build_reuse={}, reuse_key="analysis_base")


def test_reuse_isolates_wrappers_and_keeps_caches_alive():
    import gc
    import weakref
    jets, _, _, _ = fixture_inputs()
    factory = cor.ApplyJetCorrections("2018", corr_type="jets", era="A", isData=False, run=np.full(4, 319077))
    cache = {"foreign_sentinel": object()}
    sentinel = cache["foreign_sentinel"]
    state = {}
    kwargs = dict(year="2018", is_data=False, correction_factory=factory,
                  jet_systematics=cor.get_supported_jet_systematics("2018"),
                  lazy_cache=cache, build_reuse=state, reuse_key="analysis_base")
    root, _ = ap.build_corrected_jet_view(jets, np.full(4, 20.), syst_var="nominal", **kwargs)
    root_reference = weakref.ref(state["analysis_base"])
    root_pt = ak.to_list(root.pt)
    sibling, _ = ap.build_corrected_jet_view(jets, np.full(4, 20.), syst_var="JER_2018Down", **kwargs)
    sibling_pt = ak.to_list(sibling.pt)
    flavour, _ = ap.build_corrected_jet_view(jets, np.full(4, 20.), syst_var="JES_FlavorQCDUp", **kwargs)
    flavour["annotation"] = ak.ones_like(flavour.pt)
    root["pt"] = root.pt + 1.
    assert "annotation" not in state["analysis_base"].fields
    assert ak.to_list(state["analysis_base"].pt) == root_pt
    assert ak.to_list(sibling.pt) == sibling_pt
    assert cache["foreign_sentinel"] is sentinel
    cache_size = len(cache)
    state.clear()
    gc.collect()
    assert root_reference() is None
    assert len(cache) == cache_size  # Never evict shared event-cache products.
    assert cache["foreign_sentinel"] is sentinel
    assert ak.to_list(sibling.pt) == sibling_pt


def test_factory_reuse_does_not_mutate_factory_configuration():
    jets, leptons, _, _ = fixture_inputs()
    state = {}
    kwargs = dict(year="2022", is_data=False, run_era="C", run=np.full(4, 355862),
                  suppress_forward_eta_stochastic_jer=True,
                  jet_systematics=cor.get_supported_jet_systematics("2022"),
                  analysis_lazy_cache={}, build_reuse=state, reuse_analysis=True)
    ap.build_analysis_and_hem_jet_views(jets, leptons, None, np.full(4, 20.),
                                      syst_var="nominal", **kwargs)
    factory = state["correction_factory"]
    config = (dict(factory.name_map), factory.jec_stack, factory.run.copy(),
              factory.suppress_forward_eta_stochastic_jer)
    ap.build_analysis_and_hem_jet_views(jets, leptons, None, np.full(4, 20.),
                                      syst_var="JER_2022Up", **kwargs)
    assert state["correction_factory"] is factory
    assert factory.name_map == config[0]
    assert factory.jec_stack is config[1]
    np.testing.assert_array_equal(factory.run, config[2])
    assert factory.suppress_forward_eta_stochastic_jer == config[3]


def test_partitioned_input_preserves_native_contract():
    jets, _, _, _ = fixture_inputs()
    partitioned = ak.Array(ak.partition.IrregularlyPartitionedArray(
        [jets[:2].layout, jets[2:].layout]), behavior=jets.behavior)
    factory = cor.ApplyJetCorrections("2018", corr_type="jets", era="A", isData=False, run=np.full(4, 319077))
    kwargs = dict(year="2018", is_data=False, correction_factory=factory,
                  syst_var="nominal", jet_systematics=cor.get_supported_jet_systematics("2018"))
    try:
        original, name = baseline_helpers().build_corrected_jet_view(
            copy.copy(partitioned), np.full(4, 20.), lazy_cache={}, **kwargs)
        original_values = view_values(original)
    except (TypeError, ValueError, AttributeError) as error:
        # Unsupported native input is a baseline contract limit, not a new
        # scientific discrepancy. The candidate must preserve that exception.
        with pytest.raises(type(error)):
            ap.build_corrected_jet_view(copy.copy(partitioned), np.full(4, 20.),
                lazy_cache={}, build_reuse={}, reuse_key="analysis_base", **kwargs)
    else:
        state = {}
        for _ in range(2):
            actual, actual_name = ap.build_corrected_jet_view(
                copy.copy(partitioned), np.full(4, 20.), lazy_cache={},
                build_reuse=state, reuse_key="analysis_base", **kwargs)
            assert actual_name == name
            assert view_values(actual) == original_values


def test_native_full_hem_remains_separate_when_fo_removes_hem_jet():
    jets, _, _, muons = fixture_inputs()
    leptons = ak.Array([[{"jetIdx": 0}], [{"jetIdx": -1}],
                        [{"jetIdx": -1}], [{"jetIdx": -1}]])
    kwargs = dict(year="2018", is_data=False, run_era="A", run=np.full(4, 319077),
                  suppress_forward_eta_stochastic_jer=False,
                  jet_systematics=cor.get_supported_jet_systematics("2018"))
    state = {}
    for label in ("nominal", "JER_2018Up", "JES_FlavorQCDDown"):
        before = baseline_helpers().build_analysis_and_hem_jet_views(
            copy.copy(jets), leptons, None, np.full(4, 20.),
            syst_var=label, analysis_lazy_cache={}, **kwargs)
        after = ap.build_analysis_and_hem_jet_views(
            copy.copy(jets), leptons, None, np.full(4, 20.),
            syst_var=label, analysis_lazy_cache={}, build_reuse=state,
            reuse_analysis=True, **kwargs)
        for expected, actual in zip(before[:2], after[:2]):
            assert view_values(expected) == view_values(actual)
        analysis, full = after[:2]
        assert ak.to_list(analysis.raw_index)[0] == [1, 2, 3]
        assert ak.to_list(full.raw_index)[0] == [0, 1, 2, 3]
        data_run = np.full(4, 319077)
        numbers = np.arange(4, dtype=np.uint64)
        assert not ap.get_hem2018_event_mask(full, muons, numbers, data_run, "2018", True)[0]
        assert ap.get_hem2018_event_mask(analysis, muons, numbers, data_run, "2018", True)[0]
    assert state["analysis_base"] is not state["hem_base"]
    assert state["hem_lazy_cache"]


def test_buffers_are_shared_and_inplace_writes_are_outside_contract():
    jets, _, _, _ = fixture_inputs()
    factory = cor.ApplyJetCorrections("2018", corr_type="jets", era="A", isData=False, run=np.full(4, 319077))
    state = {}
    kwargs = dict(year="2018", is_data=False, correction_factory=factory,
                  syst_var="nominal", jet_systematics=[], lazy_cache={},
                  build_reuse=state, reuse_key="analysis_base")
    first, _ = ap.build_corrected_jet_view(jets, np.full(4, 20.), **kwargs)
    second, _ = ap.build_corrected_jet_view(jets, np.full(4, 20.), **kwargs)
    left = ak.to_numpy(ak.flatten(first.pt))
    right = ak.to_numpy(ak.flatten(second.pt))
    assert np.shares_memory(left, right)
    original = left[0].copy()
    left[0] += 1.
    assert right[0] == left[0]
    left[0] = original  # Restore only this fixture-owned buffer.
    assert right[0] == original


@pytest.mark.parametrize("year", ("2018", "2022"))
def test_native_build_callsite_counts(year, tmp_path):
    import sys
    observations = {}
    factory_code = cor.CorrectedJetsFactory.build.__code__
    for name, helpers, reuse in (("baseline", baseline_helpers(), False), ("candidate", ap, True)):
        counts = dict(analysis=0, hem=0, type1=0)
        previous = sys.getprofile()
        def observe(frame, event, arg):
            if event == "call" and frame.f_code is factory_code:
                caller = frame.f_back
                if caller.f_code.co_name == "build_corrected_jet_view":
                    parent = caller.f_back
                    role = "hem" if caller.f_locals["jets"] is parent.f_locals["full_jets"] else "analysis"
                elif caller.f_code.co_name == "_build_corrected_jets_for_variations":
                    role = "type1"
                else:
                    raise AssertionError("unclassified native factory caller")
                counts[role] += 1
        try:
            sys.setprofile(observe)
            result = run_case(helpers, year, reuse=reuse)
        finally:
            sys.setprofile(previous)
        assert sum(counts.values()) == result["total_builds"]
        observations[name] = counts
    path = tmp_path / "callsite_counts.json"
    path.write_text(json.dumps(dict(year=year, counts=observations)))
    reopened = json.loads(path.read_text())
    labels, _, _, muon_labels, tau_labels = population(year)
    assert reopened["counts"]["baseline"] == dict(
        analysis=len(labels), hem=len(labels) if year == "2018" else 0, type1=1)
    assert reopened["counts"]["candidate"] == dict(
        analysis=1 + len(muon_labels) + len(tau_labels), hem=int(year == "2018"), type1=1)


@pytest.mark.parametrize("year", years)
def test_native_collection_types_and_forms(year, tmp_path):
    labels = cor.get_supported_jet_systematics(year)
    demand = ["nominal", labels[0], labels[2]]
    baseline = run_case(baseline_helpers(), year, demand=demand)
    candidate = run_case(ap, year, reuse=True, demand=demand)
    evidence = dict(year=year, demand=demand, baseline=baseline["array_types"],
                    candidate=candidate["array_types"],
                    baseline_input_sha256=baseline["request_input_sha256"],
                    candidate_input_sha256=candidate["request_input_sha256"])
    path = tmp_path / "array_types.json"
    path.write_text(json.dumps(evidence, indent=2))
    reopened = json.loads(path.read_text())
    assert reopened["baseline"] == reopened["candidate"]
    assert reopened["baseline_input_sha256"] == reopened["candidate_input_sha256"]
    assert baseline["outputs"] == candidate["outputs"]
