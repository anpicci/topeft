# AnalysisProcessor data flow

This document describes the data flow inside
`analysis/topeft_run2/analysis_processor.py` and how workflow-level planning
connects to processor runtime behavior.

## 1) Inputs from workflow planning

`RunWorkflow` builds `AnalysisProcessor` instances with:

- `sample`: single or multi-sample metadata mapping
- `channel_dict`: resolved channel/app metadata from metadata authority
- `hist_keys`: per-variation histogram-key payloads
- `available_systematics`: grouped systematic definitions
- `golden_json_path` / `golden_json_paths` for data samples
- `produce_sidecars` gate (default false)

For TaskVine DDR, workflow groups tasks into channel-keyed processors while
passing sample maps and histogram tuples that are already systematic-aligned.

## 2) DatasetContext resolution

At event processing time, `_build_dataset_context()` resolves a
`DatasetContext` object containing:

- sample identity (`sample_name`, `sample_metadata`)
- dataset/trigger dataset labels
- data/MC/EFT flags
- year, run-era, xsec/sum-of-weights
- lumi mask/lumi values
- EFT coefficient arrays when present

Dataset resolution rules:

- Primary lookup uses event metadata dataset name with alias support.
- If multiple samples are configured and lookup fails, processing fails fast.
- If exactly one sample exists, fallback is allowed with warning.

## 3) Sample metadata mapping semantics

`_normalise_sample_mapping()` allows both legacy single-sample and mapping
inputs, then stores:

- `_samples_by_name`: canonical per-sample metadata
- `_sample_aliases`: dataset/histAxis alias map

This supports DDR grouped processors that run multiple datasets through one
processor instance while preserving per-sample metadata correctness.

## 4) Golden JSON routing for data

Golden JSON routing is sample-aware:

- Constructor stores explicit `golden_json_paths` (preferred) or
  legacy `golden_json_path` fallback.
- Data samples without a configured path fail fast during initialization.
- `_resolve_golden_json_path_for_sample()` resolves by sample name and alias,
  then applies `LumiMask` in `_build_dataset_context()`.

## 5) Histogram-key normalization and systematics

`hist_keys` are normalized to ordered 5-tuples:

- `(var, channel, application, sample, systematic)`

Validation rules include:

- every entry must be a 5-tuple
- all keys for a processor instance must share variable/application
- sample keys must map to configured sample metadata
- flavored channel aliases must map back to base channel consistently

`available_systematics` is stored both as ordered tuples and set views for
fast membership checks in variation dispatch.

## 6) Sidecar gating

Sidecars are controlled by `produce_sidecars`:

- default (`false`): histogram accumulator contains only histogram payloads
- enabled (`true`): accumulator also includes
  - `__topeft_variation_summary__`
  - `region_yields`

This gate is required for predictable DDR flattening output defaults.

## 7) Accumulator contents by execution mode

### Futures/iterative path

Accumulator is emitted directly from processor execution and remains keyed by
internal tuple keys `(var, channel, application, sample, systematic)`.

### TaskVine DDR path

DDR returns nested payloads (`processor_key -> dataset -> leaf_output`).
Workflow then flattens (strictly) into canonical serialized output by default:

- `(sample, channel, var, application, systematic_label)`

The strict flatten layer enforces processor-key/tuple-key consistency and
fail-fast collision behavior.

## 8) Related references

- [schemas.md](schemas.md)
- [ddr_preprocess_proxy_policy.md](ddr_preprocess_proxy_policy.md)
- [analysis_processing.md](analysis_processing.md)
