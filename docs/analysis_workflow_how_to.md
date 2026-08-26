# Analysis workflow how-to

Run these commands from `analysis/topeft_run2` in an activated environment
containing the current sibling `topeft` and `topcoffea` checkouts. Replace
example absolute paths and tags; do not reuse historical campaign paths.

## Run a maintained campaign with `run_cr.sh`

Inspect, then execute, a fresh Run 3 campaign:

```bash
./run_cr.sh --production-profile run3_full \
  --output-dir /absolute/path/to/fresh_run3_campaign \
  --campaign-tag run3_campaign --dry-run

./run_cr.sh --production-profile run3_full \
  --output-dir /absolute/path/to/fresh_run3_campaign \
  --campaign-tag run3_campaign
```

The wrapper chooses the full profile blocks, `fullR3_run.sh` arguments,
deferred nonprompt lifecycle, environment archive, state file, and artifact
checks. Resume only the same frozen plan:

```bash
./run_cr.sh --production-profile run3_full \
  --output-dir /absolute/path/to/fresh_run3_campaign \
  --campaign-tag run3_campaign --resume
```

`rebin_fine` is a separate Run 2/Run 3 specialist profile and requires an
explicit current `--env-file`. To extend a maintained profile, edit its block
declarations and corresponding invariant/state checks together, preserve
unique output names, and update `tests/test_run3_full_production_profile.py` or
`tests/test_rebin_fine_resume_and_environment.py`. Do not duplicate sample
selection or sumw2 policy in the wrapper.

## Run one block with `fullR3_run.sh`

`fullR3_run.sh` chooses cfg bundles and builds the lower-level command:

```bash
./fullR3_run.sh -y 2022 2022EE 2023 2023BPix -t run3_block --sr \
  --hist-vars njets lj0pt ptz ptll ptz_wtau lt \
  --do-np --defer-np -p /absolute/path/to/output --dry-run
```

Remove `--dry-run` after inspecting the command. Use `--sample-json FILE` or
`--cfg-override FILE` for exactly one explicit input authority. Unrecognized
options are forwarded to `run_analysis.py`. The wrapper does not create
campaign state or coordinate multiple blocks; those are `run_cr.sh` duties.

When changing this wrapper, keep cfg selection centralized in the Run 2
aggregate and Run 3 per-year arrays, keep region selection explicit, and make
new options either owned here or transparently forwarded—not both.

## Run `run_analysis.py` directly

The low-level CLI needs no ancillary shell wrapper:

```bash
python run_analysis.py \
  ../../input_samples/cfgs/NDSkim_2022_background_samples.cfg \
  --executor futures --years 2022 --nworkers 8 \
  --hist-list njets lj0pt ptz ptll lt \
  --category-groups 2los_CRZ \
  --outpath /absolute/path/to/output --outname run3_direct
```

The positional input is a sample JSON/cfg expression understood by the sample
loader. Defaults include `--executor work_queue`, `--nworkers 8`,
`--chunksize 100000`, `--outpath histos`, and `--outname plotsTopEFT`.
`--options FILE[:KEY]` loads an existing YAML option set, with explicit CLI
arguments taking precedence. Use `--pretend` to resolve inputs without running
the analysis. For nonprompt output choose
`--do-np --np-postprocess=inline|defer`; `skip` produces no transformed file.

The direct route does not choose a supported campaign matrix, protect a fresh
namespace, or resume failed stages. Record the exact input, options, years,
categories, histogram list, and output identity yourself.

## Plot with the maintained wrapper

```bash
./run_plotter.sh -f /path/to/final_np.pkl.gz \
  -o /absolute/path/to/plots -y run3 --sr \
  --variables lj0pt ptz ptll lt --channel-output merged --dry-run
```

The wrapper validates required paths/year tokens, expands `run2` or `run3`,
detects CR/SR from the filename unless overridden, and forwards remaining
options. It calls `make_cr_and_sr_plots.py`; it does not define histogram or
channel metadata itself.

## Plot directly

```bash
python make_cr_and_sr_plots.py \
  -f /path/to/final_np.pkl.gz -o /absolute/path/to/plots -n run3_sr \
  -y 2022 2022EE 2023 2023BPix --sr \
  --variables lj0pt ptz ptll lt --binning fitting \
  --year-coverage-policy error
```

Repeat `-f` for coherent fragments, or use `--pkl-list-file`. Direct plotting
defaults to `--binning processing`, `--channel-output merged`, one worker,
warning-only year coverage, and enabled negative-weight reports. It rejects a
mixed Run 2/Run 3 selection.

## Make cards directly

```bash
python make_cards.py /path/to/final_np.pkl.gz \
  --out-dir /absolute/path/to/cards \
  --var-lst lj0pt ptz ptll ptz_wtau lt \
  --ch-lst '^2lss_.*' '^3l_.*' '^4l_.*' \
  --binning fitting --year-coverage-policy error
```

Use `--pkl-list-file` instead of positional inputs for a long coherent list.
The default is Asimov data, no nuisance insertion, `fitting` binning, and
`warn` year coverage. `--unblind`, `--do-nuisance`, `--do-mc-stat`, and
`--keep-negative-bins` are explicit opt-ins. Use `--merge-only` to stop after
load/merge validation and `--merge-report PATH` to retain the report.

There is no maintained general card wrapper. The tracked matrix scripts bind
site paths, campaign rows, and provenance snapshots and are noncanonical.

## Finalize scalings

```bash
python datacards_post_processing.py /absolute/path/to/cards -a
```

Exactly one topology selector must be set. `-a` selects `ALL_CH_LST_SR`; other
legacy selectors are `-s`, `-z`, `-t`, and `-f`. The command requires
`scalings-preselect.json` and `selectedWCs.txt`, creates a new
`ptz-lj0pt_withSys` directory, copies selected cards/templates, and writes
ordered `scalings.json`. It does not read or create `combinedcard.txt`.

## Select an existing sumw2 scheme

Put `sumw2_storage` in the YAML passed through `--options`:

```yaml
sumw2_storage:
  mode: full_diagnostics
```

Available modes are `production`, `production_central`, `taufitter`,
`full_diagnostics`, `disabled`, and `full_custom`. `production` is the default
when the block is absent. Rule-based modes accept `rules` with dataset/process
exact or prefix selectors and optional `variables`. Unknown keys, modes,
families, empty matches, overlaps, or a policy that misses required consumers
fail closed. Prefer `production` for maintained production; use diagnostic or
custom modes only when their storage cost and consumers are understood.

### Add a new sumw2 mode

This changes a software registry, not merely a YAML value:

1. Add the name to `SUMW2_MODES` in `topeft/modules/sumw2_policy.py` and, if it
   takes rules, to `RULE_MODES`.
2. Define its resolution, sample-profile, rule, and consumer-coverage behavior
   in `resolve_sumw2_storage_mode` and `resolve_sumw2_storage_policy`.
3. Decide whether schema-v2 provenance can express it. If not, introduce a new
   schema version and explicit legacy readback rather than silently changing
   version 2.
4. Update producer, sidecar, transformation, merge, card, and policy tests.

### Change the default sumw2 mode

The default is independently owned by the absent-block branches in
`resolve_sumw2_storage_mode` (including `sumw2_storage.get("mode",
"production")`). Change those branches consistently, then update default-mode,
artifact compatibility, nonprompt, and card-consumer tests. Adding a mode does
not change the default; changing the default does not require a new mode.

## Select and extend binning

Plotting accepts `--binning processing|fitting`; cards default to `fitting`.
Definitions live in `topeft/modules/axes.py`, while resolution and exact
aggregation live in `topeft/modules/axis_binning.py`.

To add a fitting definition, add a `fitting.default` edge list and optional
ordered channel overrides under the existing histogram family. Edges must be
strictly increasing and exactly aggregatable from processing edges. To add a
new family, add its processing definition first, wire it to histogram
production, and then add fitting metadata if needed. Update
`tests/test_axis_binning.py` and card/plot late-rebin coverage.

Changing `processing` changes newly produced histograms. Changing `fitting`
changes downstream aggregation without rewriting the PKL. Changing a default
or an existing definition can affect card shapes and scaling coefficients and
therefore requires explicit compatibility review and regenerated validation.
Do not replace `ptz` with `ptll`: only the documented off-Z high/low channels
select `ptll`.
