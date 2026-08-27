# Specialist interfaces

These interfaces support focused inspection or maintenance. They are not
alternative production routes.

## Histogram inspection

`analysis/topeft_run2/inspect_histeft_pkl.py` is the read-only artifact
inspection CLI. It reports axes, WC metadata, populated categories, nominal
evaluations, and value/variance availability without replacing artifact
validation. The detailed in-memory API is documented in
[HistEFT and SparseHist](histeft.md); artifact/sidecar validation belongs to
[histogram artifacts](histogram_artifacts.md).

This is a public supported inspection CLI. The required positional `pkl_path`
accepts `.pkl` or `.pkl.gz`. `--hist` selects one exact top-level key;
otherwise at most `--max-hists` histogram-like objects are summarized (default
5). `--max-labels` limits displayed labels/edges (default 20). Both limits must
be positive integers. `--yield-summary` additionally attempts an available
nominal total and variance summary. Success returns 0 and writes only stdout;
the tool does not modify the input. Missing/unreadable input, unknown requested
key, invalid limits, or incompatible pickle content fails. Loading a pickle is
code-deserialization and should be limited to trusted repository artifacts.

## Nominal schema utilities

`topeft.modules.nominal_schema` owns the split scalar/EFT/sumw2 sibling layout,
canonical keys, compatibility validation, merge behavior, WC evaluation, and
materialized consumer views. Its public developer functions include
`get_nominal_components()`, `validate_nominal_family()`,
`validate_nominal_mapping()`, `canonicalize_nominal_keys()`,
`merge_nominal_mappings()`, `evaluate_nominal_at_wc()`, and the explicit
materialization helpers.

The complete symbol, parameter, return, and failure table is in
[histogram artifacts](histogram_artifacts.md#topeftmodulesnominal_schema).

## Data-driven product utilities

`topeft.modules.data_driven_products` owns generated-process naming, requested
and resolved product contracts, preflight certification, sumw2 requirement
validation, and bounded compatibility readback. These functions support
`run_data_driven.py`; they do not authorize a consumer to synthesize a missing
second moment.

The complete record and function table is in
[histogram artifacts](histogram_artifacts.md#topeftmodulesdata_driven_products).

## Missing-parton contract utilities

`topeft.modules.missing_parton_contract` owns the current category and terminal
jet-bin layout used by the payload producer, consumer, and schema tests. See
[missing-parton payloads](missing_parton_payloads.md) for the installed files
and consumer selection.

Developer-facing constants are `SUPPORTED_SR_REGISTRIES`,
`DEFAULT_SR_REGISTRY`, current base/final channel counts, and the bounded legacy
branch/layout constants. Typed record classes model channel application labels,
parsed jet tokens, per-category payload layout, and the full registry layout.
Stable functions are:

| Symbol | Parameters and return | Contract |
| --- | --- | --- |
| `normalize_sr_registry` | Optional registry name → canonical string | Defaults to `ALL_CH_LST_SR`; unknown registries fail. |
| `load_or_validate_selected_registry` | Optional name/config path → selected registry and config | Loads the category JSON and validates exact supported structure. Reads one file. |
| `parse_analysis_njet_token`, `parse_sr_njet_token` | Registry token string → parsed semantic tuple | Enforce direct versus terminal jet-bin syntax; malformed tokens fail. |
| `build_registry_payload_layout` | Selected registry mapping/context → immutable layout | Derives category order, physical bins, and terminal-bin coverage. |
| `load_registry_payload_layout` | Registry/config options → immutable layout | File-reading convenience around the builder. |
| `build_channel_appl_contract`, `load_missing_parton_channel_contract` | Registry/layout/config inputs → channel/application contract | Own exact final SR application labels used by cards; no label guessing. |
| `legacy_missing_parton_payload_lengths` | No required inputs → immutable expected-length mapping | Exposes only the accepted legacy schema. |
| `validate_legacy_missing_parton_values`, `validate_legacy_missing_parton_payload` | Legacy arrays/payload → `None` | Bounded compatibility validation; never converts legacy content into current production authority. |

Tests in `tests/test_missing_parton_contract.py`,
`tests/test_missing_parton_registry_layout.py`, and
`tests/test_missing_parton_sr_registry.py` own these invariants.

Specialist analysis guides are indexed from the main
[documentation landing page](../README.md), not duplicated here.
