from __future__ import annotations

import copy

import pytest

from topeft.modules.axes import info as axes_info
from topeft.modules.axes import info_2d as axes_info_2d
from topeft.modules.data_driven_products import (
    certify_data_driven_preflight,
    data_driven_product_error,
    resolve_data_driven_products,
    validate_serialized_data_driven_contract,
)
from topeft.modules.sumw2_policy import resolve_sumw2_storage_policy


@pytest.fixture
def samples():
    return {
        "data_a": {
            "histAxisName": "dataUL18",
            "isData": True,
            "WCnames": [],
        },
        "prompt_a": {
            "histAxisName": "TTTo2L2Nu_centralUL18",
            "isData": False,
            "WCnames": [],
        },
        "unselected_a": {
            "histAxisName": "other_centralUL18",
            "isData": False,
            "WCnames": [],
        },
        "eft_a": {
            "histAxisName": "ttHJet_privateUL18",
            "isData": False,
            "WCnames": ["ctG"],
        },
    }


def _explicit_block(*, nonprompt=True, flips=True):
    return {
        "nonprompt": {
            "enabled": nonprompt,
            **(
                {
                    "source_contributors": {
                        "data": {"process_names": ["dataUL18"]},
                        "prompt_mc": {
                            "process_prefixes": ["TTTo2L2Nu_central"]
                        },
                    }
                }
                if nonprompt
                else {}
            ),
        },
        "flips": {
            "enabled": flips,
            **(
                {
                    "source_contributors": {
                        "data": {"process_prefixes": ["data"]},
                    }
                }
                if flips
                else {}
            ),
        },
    }


def _resolve_products(block, samples, *, present=True, legacy_do_np=False):
    return resolve_data_driven_products(
        block,
        data_driven_products_present=present,
        legacy_do_np=legacy_do_np,
        samples=samples,
        runtime_families=("njets", "met"),
        metadata_path="run_options.yml",
    )


def _resolve_policy(block, samples, *, implicit_requirements=()):
    return resolve_sumw2_storage_policy(
        block,
        samples=samples,
        runtime_families=("njets", "met"),
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        sumw2_storage_present=block is not None,
        implicit_production_requirements=implicit_requirements,
    )


def test_explicit_products_resolve_editable_exact_and_prefix_contributors(samples):
    resolved = _resolve_products(_explicit_block(), samples)
    assert resolved.source == "explicit"
    assert resolved.enabled_products() == ("nonprompt", "flips")
    assert resolved.product("nonprompt").contributors_for("data") == ("dataUL18",)
    assert resolved.product("nonprompt").contributors_for("prompt_mc") == (
        "TTTo2L2Nu_centralUL18",
    )
    assert resolved.product("flips").output_processes == ("flipsUL18",)
    assert resolved.product("nonprompt").output_processes == ("nonpromptUL18",)


def test_absent_block_derives_exact_legacy_products_and_warns(samples):
    with pytest.warns(UserWarning, match="implicit sibling data_driven_products|data_driven_products is absent"):
        resolved = _resolve_products(
            None,
            samples,
            present=False,
            legacy_do_np=True,
        )
    assert resolved.source == "implicit_legacy_data_driven_default"
    assert resolved.enabled_products() == ("nonprompt", "flips")
    assert resolved.product("nonprompt").contributors_for("prompt_mc") == (
        "TTTo2L2Nu_centralUL18",
    )
    assert "ttHJet_privateUL18" not in resolved.product(
        "nonprompt"
    ).contributors_for("prompt_mc")


def test_absent_block_without_legacy_do_np_disables_both_products(samples):
    with pytest.warns(UserWarning, match=r"enabled_products=\[\]"):
        resolved = _resolve_products(
            None,
            samples,
            present=False,
            legacy_do_np=False,
        )
    assert resolved.enabled_products() == ()


@pytest.mark.parametrize(
    "mutator,error_match",
    [
        (
            lambda block: block["nonprompt"].__setitem__("variables", ["njets"]),
            "unknown.*variables",
        ),
        (
            lambda block: block.__setitem__("unknown", {"enabled": False}),
            "unknown data_driven_products",
        ),
        (
            lambda block: block["nonprompt"]["source_contributors"].__setitem__(
                "signal", {"process_names": ["other_centralUL18"]}
            ),
            r"unknown=\['signal'\]",
        ),
        (
            lambda block: block["flips"]["source_contributors"]["data"].__setitem__(
                "process_names", ["missingUL18"]
            ),
            "matched nothing",
        ),
    ],
)
def test_unknown_variable_product_role_and_unmatched_selectors_fail(
    samples, mutator, error_match
):
    block = _explicit_block()
    mutator(block)
    with pytest.raises(data_driven_product_error, match=error_match):
        _resolve_products(block, samples)


def test_overlapping_roles_and_ambiguous_duplicate_selector_resolution_fail(samples):
    overlapping = _explicit_block()
    overlapping["nonprompt"]["source_contributors"]["prompt_mc"] = {
        "process_names": ["dataUL18"]
    }
    with pytest.raises(data_driven_product_error, match="scalar non-EFT MC"):
        _resolve_products(overlapping, samples)

    ambiguous = _explicit_block()
    ambiguous["flips"]["source_contributors"]["data"] = {
        "process_names": ["dataUL18"],
        "process_prefixes": ["data"],
    }
    with pytest.raises(data_driven_product_error, match="ambiguous duplicate"):
        _resolve_products(ambiguous, samples)


def test_both_disabled_is_valid_and_requires_no_targets(samples):
    resolved = _resolve_products(_explicit_block(nonprompt=False, flips=False), samples)
    assert resolved.enabled_products() == ()
    assert resolved.required_targets() == ()
    disabled = _resolve_policy({"mode": "disabled"}, samples)
    certify_data_driven_preflight(resolved, disabled)


def test_implicit_production_selects_only_requested_source_targets(samples):
    products = _resolve_products(_explicit_block(), samples)
    policy = resolve_sumw2_storage_policy(
        None,
        samples=samples,
        runtime_families=("njets", "met"),
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        sumw2_storage_present=False,
        implicit_production_requirements=products.required_targets(),
    )
    requested, contract = certify_data_driven_preflight(products, policy)
    assert policy.requested_mode == "production"
    assert policy.source == "implicit_production_default"
    assert set(policy.selected_processes("njets")) == {
        "dataUL18",
        "TTTo2L2Nu_centralUL18",
    }
    assert "other_centralUL18" not in policy.selected_processes("njets")
    assert requested["products"]["nonprompt"]["enabled"] is True
    assert contract["families"]["met"]["flips"][
        "required_source_sumw2_processes"
    ] == ["dataUL18"]


def test_full_diagnostics_and_complete_full_custom_pass_all_families(samples):
    products = _resolve_products(_explicit_block(), samples)
    full_diagnostics = _resolve_policy({"mode": "full_diagnostics"}, samples)
    certify_data_driven_preflight(products, full_diagnostics)

    complete_custom = _resolve_policy(
        {
            "mode": "full_custom",
            "rules": [
                {
                    "process_names": [
                        "dataUL18",
                        "TTTo2L2Nu_centralUL18",
                    ]
                }
            ],
        },
        samples,
    )
    certify_data_driven_preflight(products, complete_custom)


def test_explicit_production_and_taufitter_require_complete_product_sources(samples):
    products = _resolve_products(_explicit_block(), samples)
    source_rule = {
        "process_names": ["dataUL18", "TTTo2L2Nu_centralUL18"],
    }
    explicit_production = _resolve_policy(
        {"mode": "production", "rules": [source_rule]},
        samples,
    )
    certify_data_driven_preflight(products, explicit_production)

    taufitter = resolve_sumw2_storage_policy(
        {"mode": "taufitter", "rules": [source_rule]},
        samples=samples,
        runtime_families=("njets", "met"),
        axes_info=axes_info,
        axes_info_2d=axes_info_2d,
        analysis_mode="taufitter",
        sumw2_storage_present=True,
    )
    certify_data_driven_preflight(products, taufitter)


def test_incomplete_full_custom_and_disabled_requested_products_fail_actionably(samples):
    products = _resolve_products(_explicit_block(), samples)
    incomplete = _resolve_policy(
        {
            "mode": "full_custom",
            "rules": [
                {
                    "process_names": ["dataUL18"],
                    "variables": ["njets"],
                }
            ],
        },
        samples,
    )
    with pytest.raises(
        data_driven_product_error,
        match="metadata_path=.*resolved_sumw2_mode=.*missing_contributors=.*Correct one of",
    ):
        certify_data_driven_preflight(products, incomplete)

    disabled = _resolve_policy({"mode": "disabled"}, samples)
    with pytest.raises(data_driven_product_error, match="resolved_sumw2_mode='disabled'"):
        certify_data_driven_preflight(products, disabled)


def test_full_custom_missing_one_applicable_family_fails(samples):
    products = _resolve_products(_explicit_block(), samples)
    subset = _resolve_policy(
        {
            "mode": "full_custom",
            "rules": [
                {
                    "process_names": [
                        "dataUL18",
                        "TTTo2L2Nu_centralUL18",
                    ],
                    "variables": ["njets"],
                }
            ],
        },
        samples,
    )
    with pytest.raises(
        data_driven_product_error,
        match="family 'met'.*missing_contributors",
    ):
        certify_data_driven_preflight(products, subset)


def test_serialized_contract_validation_rejects_tampering(samples):
    products = _resolve_products(_explicit_block(), samples)
    policy = _resolve_policy({"mode": "full_diagnostics"}, samples)
    requested, contract = certify_data_driven_preflight(products, policy)
    assert validate_serialized_data_driven_contract(
        requested,
        contract,
        policy=policy,
    ) == (requested, contract)

    tampered = copy.deepcopy(contract)
    tampered["families"]["njets"]["nonprompt"][
        "required_source_sumw2_processes"
    ].remove("TTTo2L2Nu_centralUL18")
    with pytest.raises(data_driven_product_error, match="disagree with contributor roles"):
        validate_serialized_data_driven_contract(requested, tampered, policy=policy)

    target_tampered = copy.deepcopy(contract)
    target_tampered["families"]["njets"]["nonprompt"][
        "required_source_sumw2_targets"
    ] = [
        target
        for target in target_tampered["families"]["njets"]["nonprompt"][
            "required_source_sumw2_targets"
        ]
        if target["dataset"] != "prompt_a"
    ]
    with pytest.raises(
        data_driven_product_error,
        match="disagree with the immutable sumw2 policy",
    ):
        validate_serialized_data_driven_contract(
            requested,
            target_tampered,
            policy=policy,
        )
