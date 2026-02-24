from __future__ import annotations

from analysis.topeft_run2 import analysis_processor
from analysis.topeft_run2 import workflow


class _DummyAccumulator:
    def __init__(self, value: int):
        self.value = value

    def __iadd__(self, other: "_DummyAccumulator"):
        self.value += other.value
        return self


def _minimal_processor_inputs():
    sample_info = {
        "sampleA": {
            "histAxisName": "sampleA",
            "isData": False,
            "year": "2018",
            "xsec": 1.0,
            "nSumOfWeights": 1.0,
            "WCnames": [],
            "path": "/store/mc/sampleA",
        }
    }
    hist_keys = {
        "nominal": (("njets", "2lss", "isSR_2lSS", "sampleA", "nominal"),),
    }
    var_info = {
        "definition": "njets",
        "label": "N_{jets}",
        "regular": (4, 0, 4),
    }
    channel_dict = {
        "jet_selection": "atleast_2j",
        "chan_def_lst": ["2lss"],
        "lep_flav_lst": (),
        "appl_region": "isSR_2lSS",
        "features": (),
    }
    return sample_info, hist_keys, var_info, channel_dict


def test_build_ddr_processor_key_rejects_delimiter_in_fields():
    try:
        workflow.build_ddr_processor_key(
            "2lss-contains-delim",
            "njets",
            "isSR_2lSS",
            "nominal",
            delim="-",
        )
        assert False, "Expected ValueError for delimiter collision"
    except ValueError as exc:
        assert "contains delimiter" in str(exc)


def test_ddr_processor_key_roundtrip():
    key = workflow.build_ddr_processor_key(
        "2lss",
        "njets",
        "isSR_2lSS",
        "nominal",
        delim="-",
    )
    channel, variable, application, systematic = workflow._parse_ddr_processor_key(
        key,
        delim="-",
    )
    assert (channel, variable, application, systematic) == (
        "2lss",
        "njets",
        "isSR_2lSS",
        "nominal",
    )


def test_flatten_ddr_output_uses_canonical_schema_and_drops_sidecars_by_default():
    processor_key = workflow.build_ddr_processor_key(
        "2lss",
        "njets",
        "isSR_2lSS",
        "nominal",
        delim="-",
    )
    payload = {
        processor_key: {
            "dataset_A": {
                ("njets", "2lss", "isSR_2lSS", "sampleA", "nominal"): _DummyAccumulator(
                    2
                ),
                "region_yields": {"ignored": True},
            },
            "dataset_B": {
                ("njets", "2lss", "isSR_2lSS", "sampleA", "nominal"): _DummyAccumulator(
                    5
                )
            },
        }
    }

    flattened = workflow.flatten_ddr_output(payload, delim="-", output_schema="flat")
    expected_key = ("sampleA", "2lss", "njets", "isSR_2lSS", "nominal")
    assert list(flattened.keys()) == [expected_key]
    assert flattened[expected_key].value == 7
    assert "__sidecars__" not in flattened

    flattened_with_sidecars = workflow.flatten_ddr_output(
        payload,
        delim="-",
        output_schema="flat",
        preserve_sidecars=True,
        sidecars_key="__sidecars__",
    )
    assert "__sidecars__" in flattened_with_sidecars


def test_analysis_processor_sidecars_disabled_by_default():
    sample_info, hist_keys, var_info, channel_dict = _minimal_processor_inputs()

    processor_default = analysis_processor.AnalysisProcessor(
        sample=sample_info,
        wc_names_lst=[],
        hist_keys=hist_keys,
        var_info=var_info,
        channel_dict=channel_dict,
        available_systematics={},
        systematic_variations=(),
    )
    assert analysis_processor.AnalysisProcessor.VARIATION_SUMMARY_KEY not in processor_default.accumulator
    assert analysis_processor.AnalysisProcessor.REGION_YIELDS_KEY not in processor_default.accumulator

    processor_with_sidecars = analysis_processor.AnalysisProcessor(
        sample=sample_info,
        wc_names_lst=[],
        hist_keys=hist_keys,
        var_info=var_info,
        channel_dict=channel_dict,
        available_systematics={},
        systematic_variations=(),
        produce_sidecars=True,
    )
    assert analysis_processor.AnalysisProcessor.VARIATION_SUMMARY_KEY in processor_with_sidecars.accumulator
    assert analysis_processor.AnalysisProcessor.REGION_YIELDS_KEY in processor_with_sidecars.accumulator
