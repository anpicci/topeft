# Entrypoints and wrappers

This page identifies supported entrypoints and the responsibility that each
layer retains. It is a lookup page, not a production recipe. See the
[production how-to](../how_to/production.md) for commands in context.

## Supported entrypoints

| Component | Kind and status | Inputs | Defaults and outputs | Failure boundary |
| --- | --- | --- | --- | --- |
| `analysis/topeft_run2/run_cr.sh` | Maintained production-profile wrapper | `--production-profile`, a fresh absolute `--output-dir`, and `--campaign-tag`; optional `--env-file`, `--resume`, and `--dry-run` | `run3_full` or `rebin_fine`; campaign state plus source/transformed PKLs and sidecars | Rejects missing or mismatched state, a reused fresh namespace, invalid archives, ambiguous interruption, and incomplete outputs |
| `analysis/topeft_run2/fullR3_run.sh` | Maintained command/configuration wrapper | Years, exactly one of `--cr` or `--sr`, optional histogram/input/output overrides, and forwarded analysis options | Year/config-dependent `run_analysis.py` command | Rejects conflicting input overrides, missing cfg/JSON inputs, and unsupported region/year combinations |
| `analysis/topeft_run2/run_analysis.py` | Direct developer CLI | Sample JSON/cfg expression and CLI or YAML options | Executor `work_queue`; 8 workers; chunksize 100000; `histos/plotsTopEFT.pkl.gz` | Validates executor, active sample universe, categories, environment, policies, and artifact contracts at their owning boundaries |
| `analysis/topeft_run2/run_data_driven.py` | Direct transformed-artifact CLI | A validated source PKL/sidecar and requested data-driven product | Streaming input; output name derived from the input when omitted | Rejects missing/incompatible sidecars, uncertified input policy, invalid product requests, and incomplete transformed companions |
| `analysis/topeft_run2/run_plotter.sh` | Maintained plotting wrapper | Readable PKL, output directory, and years | Forwards to the direct plotter; can infer CR/SR from the filename; creates the output directory even in dry-run mode | Rejects missing inputs/years; the direct plotter owns artifact and metadata validation |
| `analysis/topeft_run2/make_cr_and_sr_plots.py` | Direct plotting CLI | Repeatable `-f` inputs or a list file, output, years, and plot controls | Processing binning; merged channels; one worker; year coverage `warn` | Rejects incoherent artifacts, ambiguous channel authority, invalid binning, and mixed Run 2/Run 3 inputs |
| `analysis/topeft_run2/make_cards.py` | Direct card CLI | Positional PKLs or a list file, variables/channels, and card controls | Fitting binning; year coverage `warn`; Asimov data | Rejects incoherent artifacts, invalid exact aggregation, incomplete shape pairs, and selected-WC/coverage failures according to options |
| `analysis/topeft_run2/datacards_post_processing.py` | Direct topology/scaling finalizer | Datacard directory plus exactly one topology selector | Selected copy directory and final `scalings.json` | Rejects selector count, missing inputs, output collisions, and the copied-file counts checked for the selected topology; `-a` checks ROOT count only and `-f` has no count check |

All rows above are `public_supported`. The executable file and its usage/parser
block are signature authority. Normal success is exit status 0; parser,
preflight, child-process, validation, or publication failures return nonzero or
raise before completion.

## Production CLI contracts

### `analysis/topeft_run2/run_cr.sh`

Purpose: execute a named maintained block plan and retain enough local campaign
state to resume without confusing partial, stale, or mismatched output.

| Input | Type/requirement/default | Semantics |
| --- | --- | --- |
| `--production-profile` | Required enum: `run3_full` or `rebin_fine` | Selects the hard-coded maintained block plan. It is not a free-form config path. |
| `--output-dir` | Required fresh absolute path for a new campaign | Owns state, logs, and produced artifacts. Existing state is accepted only through compatible resume behavior. |
| `--campaign-tag` | Required non-empty string | Portable campaign identity recorded with state. |
| `--env-file` | Optional path | Forwarded environment archive; validated according to the child environment contract. |
| `--resume` | Boolean, default false | Reopens compatible campaign state and mechanically selects incomplete blocks/stages. |
| `--dry-run` | Boolean, default false | Skips campaign-block execution, but is not side-effect-free: the wrapper first resolves and validates the environment, and `run3_full` without `--env-file` may prepare an environment archive. It then prints the resolved plan without running the campaign blocks. |

The wrapper derives full `fullR3_run.sh` invocations, records profile/block
state, and, for the maintained deferred path, invokes `run_data_driven.py` only
after the heavy processor child exits. It does not own selections, processor
physics, bin edges, or artifact schemas. Extend a profile by changing its one
block-plan owner and the production-profile tests; do not copy its defaults into
another wrapper.

### `analysis/topeft_run2/fullR3_run.sh`

Purpose: translate a year bundle plus CR/SR intent into one direct analysis
command. Required inputs are the requested year/bundle and exactly one of
`--cr`/`--sr`. Optional `--sample-json` and `--cfg-override` are mutually
exclusive input authorities. Histogram-family, output, executor, environment,
nonprompt, and other unknown analysis options are forwarded to
`run_analysis.py` after wrapper-owned validation.

The wrapper derives current NDSkim cfgs, a CR `cr` or SR `ana` hist list when no
override is supplied, and output/region naming. It writes no histogram itself.
Its side effect is executing the constructed direct command. Missing inputs,
invalid region/year combinations, conflicting cfg/JSON overrides, or child
failure stop the wrapper. Current cfg resolution is detailed in
[production configuration](production_configuration.md).

### `analysis/topeft_run2/run_analysis.py`

Purpose: validate one active sample/configuration universe, construct
`AnalysisProcessor`, execute the selected coffea executor, and publish a
processor artifact pair; optionally publish an inline nonprompt transformed
pair.

| Stable input group | Type/default/accepted values | Semantics |
| --- | --- | --- |
| Positional `jsonFiles` | Optional path/expression, default empty string | Sample JSON or cfg authority. Higher wrappers normally supply it. |
| Executor/resources | `--executor work_queue` by default; workers 8; chunksize 100000; optional chunks/prefix/tree | Executor names are validated later by the execution branch; parser acceptance alone is not support. |
| Output | `--outname plotsTopEFT`, `--outpath histos` | Publishes `<outpath>/<outname>.pkl.gz` and adjacent metadata. Existing/output safety is owned by the writer path. |
| Scope | Optional years, histogram list, category groups, WC list | Filters the resolved input/processor family universe. Names are validated before or during processor construction. |
| Analysis flags | Off-Z, tau, forward, or all-analysis; default none | Mutually exclusive mode selectors. `--analysis-mode` accepts `standard` or `taufitter`, default `standard`. |
| Sumw2/systematics | Modern YAML `sumw2_storage`; deprecated `--no-sumw2`; `--do-systs` | Modern policy is resolved before processing. Legacy statistical inputs have explicit compatibility/conflict handling. |
| Nonprompt | `--do-np`; `--np-postprocess` in `inline`, `defer`, `skip`, default `inline` | Inline publishes a transformed artifact; defer prints a direct follow-up command; skip omits transformation. |
| Environment | Optional archive/rebuild/prepare/snapshot/no-remote controls | Owns worker-environment preparation/validation, not package installation. |
| YAML overlay | `--options FILE` | One mapping loaded after CLI-derived values; recognized YAML values replace corresponding CLI values. See the exact caveat in production configuration. |

`--pretend` reads/resolves inputs without executing analysis; `--test` bounds
the event/chunk run but is still execution. The unsupported renormalization-
envelope flag exits before analysis work. The direct command fails closed on
sample/profile, category, sumw2, data-driven, environment, processor, and
artifact-publication errors. It returns no library value; its durable return is
the published artifact pair and exit status.

## Transformation CLI contract

### `analysis/topeft_run2/run_data_driven.py`

Purpose: consume one already-complete validated processor artifact and publish
one separately transformed artifact with lineage.

`--input-pkl` is required. `--output-pkl` is optional and otherwise derives an
`_np` or `_np_nominal_reference` name. `--only-flips` drops nonprompt processes
from the transformed result; it does not invoke an independent flips producer.
Streaming input is the default; `--legacy-dict-mode` is the explicit
materialized-dictionary compatibility choice. Data-driven/memory reports,
heartbeat/quiet controls, and `--nominal-only-reference` affect diagnostics or
the explicit output kind but do not weaken sidecar requirements. The deprecated
envelope option fails before reading the input.

`main(argv=None)` returns a process status and writes only through
`write_histogram_artifact`, binding the new sidecar to the validated input
lineage and transformation contract. Missing source certification, unsupported
product/applicability, output collision, transformation failure, or incomplete
nominal/sumw2 content prevents publication. See
[histogram artifacts](histogram_artifacts.md) for exact schemas.

## Layering contract

`run_cr.sh` expands a maintained production profile into calls to
`fullR3_run.sh`. `fullR3_run.sh` resolves the years, region, maintained sample
cfg files, and histogram family, then constructs `run_analysis.py`. Calling a
lower layer transfers its omitted responsibilities to the user; it does not
silently reconstruct the higher-level campaign record.

`run_plotter.sh` is a convenience layer over `make_cr_and_sr_plots.py`. It
creates the requested output directory before testing `--dry-run`; dry-run
skips the Python plotter but does not suppress that directory-creation side
effect.
`make_cards.py` is already the direct supported card interface and delegates
card/template construction to `topeft.modules.datacard_tools.DatacardMaker`.
`datacards_post_processing.py` finalizes selected scaling records after the
individual cards and templates exist; it is not a card producer.

See [production configuration](production_configuration.md),
[plotting](plotting.md), and
[datacards and scalings](datacards_and_scalings.md) for exact owned contracts.

## Operator records

Scripts with campaign, date, site, user, or immutable evidence identifiers in
their names are not supported merely because they are executable. In
particular, `run_make_cards_run3_yawen_matrix.sh` is a DATACARD023-qualified
operator record with fixed local paths, branch and input hashes, and a recorded
off-Z input that predates the required `ptll` schema. It is useful archival
evidence, but it is not a reusable current card entrypoint. The durable
region-to-distribution contract belongs to [flexible binning](flexible_binning.md)
and its source/test authorities.

## Signature and validation authority

Shell usage blocks and Python `build_arg_parser()` definitions are the exact
option authority. Focused ownership tests include
`tests/test_run3_full_production_profile.py`,
`tests/test_run_analysis_preflight.py`, `tests/test_run_data_driven.py`,
`tests/test_make_cr_and_sr_plots.py`, and
`tests/test_make_cards_multi_pkl.py`.
