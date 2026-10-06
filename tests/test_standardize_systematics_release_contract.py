import hashlib
import json

import hist
import pytest
import uproot

from analysis.topeft_run2.standardize_systematics import (
    SYST_NAMING_MAP,
    _preflight_package,
    resolve_nuisance_name,
    standardize_package,
)


@pytest.mark.parametrize(
    "run,domain", (("run2", "13TeV"), ("run3", "13p6TeV"))
)
def test_pu_met_and_accepted_aliases(run, domain):
    assert resolve_nuisance_name("PU", run) == f"CMS_pileup_{domain}"
    assert resolve_nuisance_name("MET_UnclusteredEnergy", run) == (
        f"CMS_scale_met_Unclustred_energy_{domain}"
    )
    assert resolve_nuisance_name("PreFiring", run) == "CMS_l1_ecal_prefiring"
    for source in ("lepSF_elec_mva", "lepSF_muon_mva",
                   "lepSF_elec_non_mva", "lepSF_muon_non_mva"):
        assert resolve_nuisance_name(source, run) == f"{source}_{domain}"


@pytest.mark.parametrize("dm", (0, 1, 10, 11))
@pytest.mark.parametrize("period", ("2022EE", "2023BPix"))
def test_retired_efes_aliases_rejected(dm, period):
    source = f"CMS_scale_t_DeepTau2018v2p5_DM{dm}_genElectron_{period}"
    assert source not in SYST_NAMING_MAP["run3"]
    with pytest.raises(RuntimeError, match="not found"):
        resolve_nuisance_name(source, "run3")
    year = period[:4]
    valid = f"CMS_scale_t_DeepTau2018v2p5_DM{dm}_genElectron_{year}"
    assert resolve_nuisance_name(valid, "run3") == valid


def make_package(tmp_path, card_names=("Run3_second.txt", "Run2_first.txt")):
    source = tmp_path / "source"
    cards = source / "cards"
    cards.mkdir(parents=True)
    histogram = hist.Hist(hist.axis.Regular(1, 0, 1), storage=hist.storage.Weight())
    histogram.fill(0.5)
    for card_name in card_names:
        root_name = card_name.replace(".txt", "_shapes.root")
        (cards / card_name).write_text(
            f"shapes * * {root_name} $PROCESS $PROCESS_$SYSTEMATIC\n"
            "PU shape 1\nMET_UnclusteredEnergy shape 1\n"
        )
        with uproot.recreate(cards / root_name) as root_file:
            for source_name in ("PU", "MET_UnclusteredEnergy"):
                for direction in ("Up", "Down"):
                    root_file[f"ttH_sm_{source_name}{direction}"] = histogram
    ordered = "".join(f"cards/{card_name}\n" for card_name in card_names)
    (source / "ordered_card_inputs.txt").write_text(ordered)
    (source / "package-provenance.json").write_text("{}\n")
    return source, ordered


def test_ordered_pairing_provenance_and_existing_output(tmp_path):
    source, ordered = make_package(tmp_path)
    output = tmp_path / "derivative"
    provenance = standardize_package(source, output)
    assert (output / "ordered_card_inputs.txt").read_text() == ordered
    assert {path.name for path in (output / "cards").iterdir()} == {
        "Run3_second.txt", "Run2_first.txt",
        "Run3_second_shapes.root", "Run2_first_shapes.root",
    }
    assert provenance == json.loads((output / "derivative-provenance.json").read_text())
    assert provenance["source_release_path"] == str(source)
    assert provenance["source_ordered_card_inputs_sha256"] == hashlib.sha256(
        ordered.encode()
    ).hexdigest()
    assert provenance["source_package_provenance_sha256"] == hashlib.sha256(
        b"{}\n"
    ).hexdigest()
    assert provenance["input_card_count"] == provenance["output_card_count"] == 2
    assert provenance["generated_member_counts"]["root_files"] == 2
    readme = (output / "README.md").read_text()
    assert "reviewer/Combine derivative" in readme
    assert "not the certified lane_09 fit-input authority" in readme
    assert "inherited from the input datacards" in readme
    assert "naming/interface transformation only" in readme
    for card_name, domain in (("Run3_second.txt", "13p6TeV"),
                              ("Run2_first.txt", "13TeV")):
        card_text = (output / "cards" / card_name).read_text()
        root_name = card_name.replace(".txt", "_shapes.root")
        assert root_name in card_text
        assert f"CMS_pileup_{domain} shape" in card_text
        with uproot.open(output / "cards" / root_name) as root_file:
            keys = set(root_file.keys(cycle=False))
            assert f"ttH_sm_CMS_pileup_{domain}Up" in keys
            assert f"ttH_sm_CMS_pileup_{domain}Down" in keys
            assert f"ttH_sm_CMS_scale_met_Unclustred_energy_{domain}Up" in keys
    with pytest.raises(FileExistsError):
        standardize_package(source, output)


def test_distinct_final_nuisances_cannot_collapse(tmp_path, monkeypatch):
    source, _ = make_package(tmp_path, ("Run2_first.txt",))
    monkeypatch.setitem(SYST_NAMING_MAP["run2"], "MET_UnclusteredEnergy", "CMS_pileup_13TeV")
    with pytest.raises(ValueError, match="Nuisance collision"):
        standardize_package(source, tmp_path / "derivative")
    assert not (tmp_path / "derivative").exists()


def test_output_cannot_be_inside_source_package(tmp_path):
    source, _ = make_package(tmp_path, ("Run2_first.txt",))
    with pytest.raises(ValueError, match="outside the input package"):
        standardize_package(source, source / "derivative")
    assert not (source / "derivative").exists()


def test_root_key_collision_fails_before_output(tmp_path, monkeypatch):
    source, _ = make_package(tmp_path, ("Run2_first.txt",))
    root_path = source / "cards" / "Run2_first_shapes.root"
    histogram = hist.Hist(hist.axis.Regular(1, 0, 1), storage=hist.storage.Weight())
    with uproot.update(root_path) as root_file:
        for direction in ("Up", "Down"):
            root_file[f"ttH_sm_JES_Absolute{direction}"] = histogram
    monkeypatch.setitem(SYST_NAMING_MAP["run2"], "JES_Absolute", "CMS_pileup_13TeV")
    with pytest.raises(ValueError, match="Nuisance collision|ROOT key collision"):
        standardize_package(source, tmp_path / "derivative")
    assert not (tmp_path / "derivative").exists()
