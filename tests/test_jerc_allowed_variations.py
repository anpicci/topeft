from analysis.topeft_run2.analysis_processor import _build_jerc_allowed_variations
from topeft.modules.systematics import SystematicVariation


def _variation(base, *, name=None, variation_type="object", component=None, applies_to=("mc",)):
    return SystematicVariation(
        name=name or f"{base}_{component or 'nominal'}",
        base=base,
        type=variation_type,
        applies_to=set(applies_to),
        component=component,
    )


def test_allowed_variations_nominal_mc_disables_jer_variations():
    allowed = _build_jerc_allowed_variations((), is_mc=True)
    assert allowed["jer"] is False
    assert allowed["jes"] is False
    assert allowed["ues"] is False


def test_allowed_variations_collects_jes_components():
    variations = (
        _variation("jes", component="FlavorQCD"),
        _variation("jes", component="Absolute"),
        _variation("jer", name="JER_2018Up"),
        _variation("pileup", variation_type="weight"),
    )
    allowed = _build_jerc_allowed_variations(variations, is_mc=True)
    assert allowed["jer"] is True
    assert allowed["ues"] is False
    assert allowed["jes"] == {"components": ["Absolute", "FlavorQCD"]}


def test_allowed_variations_handles_ues_aliases_and_data_sample():
    variations = (
        _variation("jes", component="FlavorQCD", applies_to=("data",)),
        _variation("met_unclustered_energy"),
    )
    allowed = _build_jerc_allowed_variations(variations, is_mc=False)
    assert allowed["jer"] is False
    assert allowed["jes"] == {"components": ["FlavorQCD"]}
    assert allowed["ues"] is True


def test_allowed_variations_jer_branch_only_when_requested_and_mc():
    variations = (
        _variation("jer", name="JER_2018Up"),
        _variation("jer", name="JER_2018Down"),
    )
    allowed_mc = _build_jerc_allowed_variations(variations, is_mc=True)
    allowed_data = _build_jerc_allowed_variations(variations, is_mc=False)
    assert allowed_mc["jer"] is True
    assert allowed_data["jer"] is False
