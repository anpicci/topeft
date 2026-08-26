# Analysis workflow reference

This page records stable ownership, defaults, schemas, and failure boundaries.
CLI parsers and typed source functions remain authoritative for signatures;
run `--help` against the checked-out source for the exhaustive option list.

## Supported entrypoints

| Component | Kind and status | Inputs | Defaults/outputs | Failure boundary |
| --- | --- | --- | --- | --- |
| `analysis/topeft_run2/run_cr.sh` | Maintained campaign wrapper | `--production-profile`, fresh absolute `--output-dir`, `--campaign-tag`; optional current `--env-file`, `--resume`, `--dry-run` | `run3_full` or `rebin_fine`; campaign state plus source/transformed PKLs and sidecars | Rejects missing/mismatched state, reused fresh namespace, invalid archive, ambiguous interruption, or incomplete outputs |
| `analysis/topeft_run2/fullR3_run.sh` | Maintained command/config wrapper | years, exactly one of `--cr`/`--sr`, optional hist/input/output overrides, forwarded analysis options | year/config-dependent `run_analysis.py` command | Rejects conflicting input/output options, missing cfg/JSON, unsupported region/year combinations |
| `analysis/topeft_run2/run_analysis.py` | Direct developer CLI | optional sample JSON/cfg expression and CLI/YAML options | executor `work_queue`; 8 workers; chunksize 100000; `histos/plotsTopEFT.pkl.gz` | Validates executor, sample universe, categories, environment, policy, and artifacts before or at the owning boundary |
| `analysis/topeft_run2/run_plotter.sh` | Maintained plotting wrapper | readable PKL, output directory, years | forwards to direct plotter; filename region detection | Rejects missing input/year; underlying plotter owns artifact/metadata validation |
| `analysis/topeft_run2/make_cr_and_sr_plots.py` | Direct plotting CLI | repeatable `-f` or list file, output, years/options | processing binning; merged channels; one worker; year coverage `warn` | Rejects incoherent artifacts, ambiguous channel authority, invalid binning, and mixed Run 2/Run 3 |
| `analysis/topeft_run2/make_cards.py` | Direct card CLI | positional PKLs or list file, variables/channels/options | fitting binning; year coverage `warn`; Asimov data | Rejects incoherent artifacts, invalid exact rebin, incomplete shape pairs, and selected-WC/coverage failures according to options |
| `analysis/topeft_run2/datacards_post_processing.py` | Direct topology/scaling finalizer | datacard directory plus exactly one topology selector | selected copy directory and final `scalings.json` | Rejects selector count, missing inputs, output collision, or unexpected copied file counts |

The matrix and resume scripts with campaign/date/site names are operator
records, not maintained public wrappers. They may provide evidence about a
past campaign but are not the source of CLI defaults or a reusable recipe.

## Current sample/config authorities

`fullR3_run.sh` owns runtime reachability. Run 2 SR uses
`mc_signal_samples_NDSkim.cfg`, `mc_background_samples_NDSkim.cfg`, and
`data_samples_NDSkim.cfg`; the relevant CR path also includes
`mc_background_samples_cr_NDSkim.cfg`. Run 3 selects corresponding
`NDSkim_${year}_...` variants. A direct `--sample-json` or `--cfg-override`
supersedes these for that invocation.

## Region, distribution, and fitting-binning contract

The runtime bin registries are `topeft.modules.axes.info` and
`topeft.modules.axis_binning`. The table below preserves the reusable selection
contract that was otherwise embedded only in a noncanonical Run 3 matrix; it
does not make that wrapper supported and does not duplicate numeric bin edges.

| Physical region/category family | Final distribution | Binning owner |
| --- | --- | --- |
| ordinary 2lss and 4l categories, plus off-Z `none` 3l categories | `lj0pt` | `axes.info["lj0pt"]` |
| forward 2lss and forward 3l categories | `lt` | `axes.info["lt"]` |
| `2los_onZ_1tau` and selected 3l on-Z categories | `ptz` | `axes.info["ptz"]` |
| `2lss_*_1tau_onZ` categories | `ptz_wtau` | `axes.info["ptz_wtau"]` |
| explicitly split 3l off-Z `high`/`low` categories | `ptll` | `axes.info["ptll"]` channel overrides |

`datacards_post_processing.py` applies the same semantic selection while
building physical card-channel names. Actual `ptz` remains distinct from final
`ptll`; there is no fallback from missing `ptll` to `ptz`.

`axes.info[family]["processing"]` owns production edges. Optional
`["fitting"]["default"]` and ordered `["channels"]` regex overrides own the
card/fit view. `resolve_axis_edges(family, mode, channel)` returns processing
edges or the first matching fitting override/default. Exact aggregation keeps
underflow and overflow and rejects non-nested, non-increasing, or ambiguous
physical axes.

## Sumw2 policy and provenance

`topeft.modules.sumw2_policy` is the registry/default owner.

- Current provenance schema: `SUMW2_PROVENANCE_SCHEMA_VERSION == 2`.
- Readable legacy provenance schema: version 1, with explicit compatibility
  restrictions; legacy evidence is not silently upgraded.
- Available modes: `production`, `production_central`, `taufitter`,
  `full_diagnostics`, `disabled`, `full_custom`.
- Current default: `production` when `sumw2_storage` or its `mode` is absent.
- `production` binds private signal sample identity;
  `production_central` binds central signal identity; the other modes are
  unrestricted unless their own rules impose a boundary.
- Rule keys: `dataset_names`, `dataset_prefixes`, `process_names`,
  `process_prefixes`, and `variables`.

`resolved_sumw2_policy.to_provenance()` serializes source, requested/resolved
mode, signal profile, normalized rules, runtime families, resolved datasets,
processes and concrete targets, warnings, and schema version. The adjacent PKL
sidecar also carries `sumw2_content_manifest`, whose required process/family
content is recomputed and checked at readback, transformation, merge, plot, and
card boundaries.

The maintained contract is scalar SM/WC=0 `<family>_sumw2` companions for
policy-selected concrete dataset/process/family targets. Nonzero-WC quartic
sumw2 is not part of this contract. Unknown/empty/overlapping selectors,
unknown families, mode/analysis mismatches, signal-profile mismatches, missing
consumer requirements, invalid provenance fields, or missing required
companions fail closed. Deprecated `no_sumw2` values map explicitly to
`disabled` or `full_diagnostics` with warnings.

Public developer surfaces include `sumw2_target`, `sumw2_mode_resolution`,
`normalized_sumw2_rule`, `resolved_sumw2_policy`,
`resolve_sumw2_storage_mode`, `resolve_sumw2_storage_policy`, and
`resolved_policy_from_provenance`. Their typed source signatures and docstrings
are authoritative.

## Card and scaling artifact schemas

`make_cards.py` consumes one coherent final histogram family and writes
individual card/template pairs, `selectedWCs.txt`, and a JSON array in
`scalings-preselect.json`. Scaling records retain at least their physical
`channel` and the producer-owned process, parameter, and coefficient payload.
Multiple records for one physical channel/process are valid producer output;
the finalizer filters and relabels every matching record rather than replacing
the payload with a process-global number.

For `datacards_post_processing.py DATACARD_DIR -a`:

1. `ALL_CH_LST_SR` in `topeft/channels/ch_lst.json` selects lepton/channel and
   jet families.
2. The source maps each physical category to `lj0pt`, `ptz`, `ptll`,
   `ptz_wtau`, or `lt` according to explicit predicates.
3. The physical names are sorted into `CATSELECTED`.
4. `CATSELECTED[i]` maps to `ch{i+1}`.
5. Matching cards/templates and `selectedWCs.txt` are copied to
   `ptz-lj0pt_withSys`.
6. Every matching preselect record keeps all fields except `channel`, which is
   replaced with the deterministic `chN`; unmatched records are removed.
7. The result is written as `scalings.json`.

The historical output-directory name does not mean all channels use `ptz` or
`lj0pt`. `combinedcard.txt` is neither consumed nor produced here. EFTFit later
combines individual cards and constructs the workspace using compatible `chN`
ordering. Missing final records mean no external EFT morph for that exact
channel/process.

## Artifact and sidecar reference

Use [HistEFT API contract](histeft_api_contract.md) for the full PKL, sidecar,
split-family, merge, transformation, and compatibility schemas. Source and
split products use sidecar schema version 2; transformed data-driven products
use version 3. `topeft.modules.histogram_artifact` is the machine-near owner.

## Validation ownership

The primary focused tests are `tests/test_run3_full_production_profile.py`,
`tests/test_axis_binning.py`, `tests/test_datacard_late_rebin.py`,
`tests/test_datacard_tools_shape_pairs.py`,
`tests/test_run_analysis_hist_outputs.py`,
`tests/test_histogram_artifact_sidecars.py`,
`tests/test_make_cards_multi_pkl.py`, and
`tests/test_ptll_semantic_contract.py`. A changed registry, default, schema, or
mapping must update the tests at the boundary it owns; documentation validation
does not replace regenerated card/scaling or production validation.
