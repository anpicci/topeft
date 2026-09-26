# Create cards and build datacard packages

`analysis/topeft_run2/make_cards.py` produces cards directly from one or more
compatible histogram PKLs—normally the nonprompt-transformed products—and
writes individual text cards, ROOT template files, `selectedWCs.txt`, and
`scalings-preselect.json`. For multiple production
rows, use `analysis/topeft_run2/run_datacard_matrix_resumable.sh` to run and
resume the matrix.

| Interface | Purpose | Inputs and defaults | Outputs and checks |
| --- | --- | --- | --- |
| `make_cards.py` | Merge histogram inputs and select WCs, channels, and variables | Fitting binning, year coverage `warn`, Asimov data, no nuisances or MC-stat opt-in | `DatacardMaker` writes TXT cards, ROOT templates, and scaling records; local or Condor execution |
| `build_per_era_datacard_package.py build` | Build one Run 2 or Run 3 package | Era, one or more completed matrix-v2 manifests, fresh absolute output; default `ALL_CH_LST_SR` channel set | Checks recorded source files, copies card/template pairs, consolidates WCs and scalings, and assigns per-era `chN` |
| `build_combined_datacard_package.py build` | Build a cards-only Run 2 + Run 3 package | Two per-era package directories, fresh absolute output, analysis, package date, and version | Writes the combined mapping, ordered card list, and scalings; checks the package against its inputs; does not run Combine |
| EFTFit/Combine | Combine cards and construct the statistical model | Packaged cards and scalings plus fit configuration | Creates `combinedcard.txt` and the workspace after package construction |

The region → distribution → binning choices come from repository configuration:
physical regions and jet populations are defined in `topeft/channels/ch_lst.json`;
the per-era builder chooses each region's card distribution (`lj0pt`, `ptz`, `ptll`,
`ptz_wtau`, or `lt`); `topeft/modules/axes.py` supplies processing/fitting
edges. A matrix manifest records the selected production rows; it does not
redefine the region or binning configuration.

## Create individual cards and templates

From `analysis/topeft_run2`:

```bash
python make_cards.py /path/to/final_np.pkl.gz \
  --out-dir /absolute/path/to/cards \
  --var-lst lj0pt ptz ptll ptz_wtau lt \
  --ch-lst '^2lss_.*' '^3l_.*' '^4l_.*' \
  --binning fitting --year-coverage-policy error
```

Repeat positional PKLs for coherent fragments, or use `--pkl-list-file` for a
long list; do not provide both. The default uses Asimov data, fitting binning,
no nuisance insertion, and warning-only year coverage. `--unblind`,
`--do-nuisance`, `--do-mc-stat`, and `--keep-negative-bins` are explicit
choices. `--merge-only` stops after load/merge validation, and
`--merge-report PATH` retains the diagnostic report.

Before card production, confirm that every input belongs to one compatible
production family and has the nominal/sumw2 companions required by the selected
card channels and variables. A filename or campaign directory is not
compatibility evidence.

`make_cards.py` validates and merges all PKLs before constructing
`DatacardMaker`. It rejects positional inputs combined with `--pkl-list-file`,
mixed incompatible schemas/policies, and missing required companions.
`--merge-only` is the lowest-cost way to exercise that boundary. A cached
merged PKL written with `--cache-merged-pkl` is a new artifact and sidecar when
the input schema supports it; preserve its lineage and merge report.

Channel arguments are selection patterns interpreted by the existing
`regex_match` helper against actual histogram channel labels. They do not add a
channel to the registry or repair an absent artifact category. Variables must
exist as histogram families in the merged input.

## Modify card selection or configuration

- Select variables and channels through `--var-lst` and `--ch-lst`; keep
  physical channel definitions in `topeft/channels/ch_lst.json`.
- Choose processing or fitting edges through `--binning`; change definitions at
  `topeft/modules/axes.py`, following the [binning guide](flexible_binning.md).
- Use `--miss-parton-file` and `--sr-registry` to select existing supported
  configuration. Do not duplicate payload or registry data in an operator
  wrapper.
- `--rate-syst-json` overrides the run-era rate-systematics JSON path. An
  explicit value is forwarded to `DatacardMaker` as `rate_systs_path`; when it
  is omitted, `DatacardMaker` selects its maintained Run 2 or Run 3 default.
- `--use-selected FILE` reads the reviewed JSON for card construction,
  canonicalizes its signal-only representation, and materializes that
  representation as `<out_dir>/selectedWCs.txt` without modifying `FILE`.
- When extending the CLI, update parsing, Condor forwarding if applicable,
  `DatacardMaker` construction, output/provenance behavior, and focused tests.

The `--condor` implementation is not transparent forwarding. It generates a
worker script and submit files with a curated option list, one CPU, 20000 MB
memory, 4096 MB disk, transferred `make_cards.py`/`selectedWCs.txt`/PKL list,
and a shared output-directory assumption. When a supported card option must
work under Condor, add it to `_build_condor_base_other_opts` and test both local
and generated-worker commands. Do not assume a new parser option reaches jobs.

To add a supported selection/configuration control:

1. Identify its existing owner: physical channels in `ch_lst.json`, axes in
   `axes.py`, currently default-selected rate-systematic JSON in
   `DatacardMaker`, missing-parton payload/registry through their dedicated
   options, or WC selection through selected-WC inputs. Use
   `--rate-syst-json` only to select an existing supported rate-systematics
   JSON.
2. Add a CLI selector only when choosing among existing supported authorities;
   do not copy the configuration into `make_cards.py`.
3. Validate choices before output creation and thread the resolved value to
   `DatacardMaker` once.
4. Preserve local/Condor equivalence or explicitly fail a mode that cannot
   represent the option.
5. Update `tests/test_make_cards_multi_pkl.py`, the focused option/physics
   contract test, `tests/test_split_datacard_boundary.py`, and late-rebin or
   selective-sumw2 tests when those surfaces are affected.

Card changes can affect template shapes, nuisance content, WC selection, the
preselected scaling records, and every later EFT fit. Validate the card/template
pair together rather than checking the text card alone.

## Run a datacard matrix resumably

The runner accepts an ordered JSON manifest. Define the physics matrix before
running it. Each row records its logical and attempt IDs, era,
working directory, input PKL, output root, distribution, literal physical
channel argv, years, missing-parton path, SR registry, row-specific merge
report, immutable snapshot/log destinations, expected output paths, and exact
`make_cards.py` argv. The manifest also selects a control root and advisory-lock
path. Use attempt-specific log, snapshot, merge-report, and expected-output
paths.

The schema is `topeft_datacard_matrix_v2`. Its `runtime_contract` names the
absolute Python executable and `make_cards.py` path and records hashes for
the selected runtime files. The runner checks those paths and hashes before
execution; the manifest author chooses the file set.

```json
{
  "schema": "topeft_datacard_matrix_v2",
  "control_root": "/path/to/runner-control",
  "lock_path": "/path/to/runner-control/runner.lock",
  "runtime_contract": {
    "contract_id": "run3-runtime-001",
    "python_executable": "/absolute/path/to/python",
    "make_cards_path": "/absolute/path/to/topeft/analysis/topeft_run2/make_cards.py",
    "fingerprints": [{"path": "/absolute/path/to/runtime-file", "sha256": "<lowercase-sha256>"}]
  },
  "rows": [{
    "row_id": "run3_01",
    "attempt_id": "attempt_01",
    "era": "run3",
    "working_directory": "/path/to/topeft",
    "input_pkl": "/path/to/input.pkl.gz",
    "output_root": "/path/to/cards/run3",
    "distribution": "lj0pt",
    "physical_channels": ["physical_channel_a", "physical_channel_b"],
    "years": ["2022", "2022EE", "2023", "2023BPix"],
    "missing_parton_path": "/absolute/path/to/missing_parton_run3.root",
    "sr_registry": "ALL_CH_LST_SR",
    "merge_report_path": "/path/to/row-logs/run3_01/merge_report.json",
    "snapshot_directory": "/path/to/runner-control/snapshots/run3_01_attempt_01",
    "log_path": "/path/to/row-logs/run3_01/row.log",
    "expected_output_paths": ["/path/to/cards/run3/card.txt", "/path/to/cards/run3/card.root"],
    "producer_args": ["--out-dir", "/path/to/cards/run3", "--var-lst", "lj0pt", "--ch-lst", "physical_channel_a", "physical_channel_b", "--year", "2022", "2022EE", "2023", "2023BPix", "--miss-parton-file", "/absolute/path/to/missing_parton_run3.root", "--sr-registry", "ALL_CH_LST_SR", "--merge-report", "/path/to/row-logs/run3_01/merge_report.json"]
  }]
}
```

All paths are absolute. `input_pkl` is structural, not searched for in an
argument list. For a row, the literal producer argv is exactly
`[python_executable, make_cards_path, input_pkl, *producer_args]`; each physical
channel remains one argv element.

A minimal invocation is:

```bash
analysis/topeft_run2/run_datacard_matrix_resumable.sh --plan-only /path/to/manifest.json
analysis/topeft_run2/run_datacard_matrix_resumable.sh --status /path/to/manifest.json
analysis/topeft_run2/run_datacard_matrix_resumable.sh /path/to/manifest.json
```

The public wrapper locates its companion Python engine relative to its own
absolute directory, so it does not depend on the checkout location or the
caller's current working directory. It prefers `python` and falls back to
`python3` for the runner engine bootstrap.

Run long, manually authorized executions in a named `tmux` session so the
operator can detach without terminating the runner. Inspect `--plan-only` and
`--status` first, and keep the manifest unchanged during an
attempt. The runner validates the schema and runtime fingerprints before plan
or execution, holds one OS advisory lock for a mutating run, and directly runs
the declared Python argv with no shell intermediary. It stops on the first
command or output-check failure.

After a successful row command, the runner checks the declared outputs, retains
the row-specific merge report, snapshots `selectedWCs.txt`,
`scalings-preselect.json`, and the merge report, hashes the primary TXT/ROOT
outputs and every row-local control artifact (merge report, snapshots, and log),
and atomically publishes an execution receipt. Receipt validation rechecks both
size and SHA256; these checks do not assess the physics content.

On restart, a row is skipped only when its receipt matches the current manifest,
argv, paths, runtime contract, and byte-bound artifacts. A valid immutable
receipt permits that skip even if the row's historical input PKL or
missing-parton file is no longer available. Rows that are about to execute
still require the current runtime contract, a readable regular input PKL, and
a readable regular missing-parton file. The manifest binds
`missing_parton_path` to exactly one matching `--miss-parton-file` producer
argument, so the checked file is the file passed to `make_cards.py`.

`--plan-only` does not mutate or execute. For each `not_started` row it reports
runtime and execution-input availability and marks the overall plan not
launch-ready when a required input is unavailable; completed rows are not
penalized for unavailable historical execution inputs.

Owner metadata is updated atomically under the OS lock before each row.
`started_at` records when this runner acquired execution ownership and remains
stable for that runner's lifetime; `current_row_started_at` records the start
of the current row and changes with each row. `--status` reports
`active` only when evidence has no receipt *and* the lock plus owner metadata
identify that exact row/attempt; evidence with a free lock is
`interrupted_requires_external_reconciliation`, even if stale owner JSON
remains. `invalid_receipt` means recorded bytes no longer match.

Before each row launch, the held runner rechecks the runtime contract and
freshly classifies the row. Only `not_started` launches; valid receipts skip,
and `active`, interrupted, unreceipted, or invalid state blocks. External
reconciliation must decide whether a new attempt is safe and, if so, supply a
new attempt ID and non-overwriting paths. There is no automatic retry or
output-existence shortcut. A runtime fingerprint change blocks before the next
row.

The steps are:

1. Run the producer rows and retain their logs, snapshots, and receipts.
2. Review the completed matrix-v2 manifests and source artifacts.
3. Build each per-era package with `build_per_era_datacard_package.py build`.
   The runner does not launch either package builder.

## Build per-era packages

`make_cards.py` or the resumable runner produces individual TXT/ROOT pairs
and row-local `selectedWCs.txt` and `scalings-preselect.json`. The last row's
shared metadata files are not a complete era package. Supply the completed
matrix-v2 manifests to the per-era builder; repeat
`--matrix-manifest` for each contributing manifest. Run the following
builder command from the repository root:

```bash
python analysis/topeft_run2/build_per_era_datacard_package.py build \
  --era run2 \
  --matrix-manifest /path/to/run2-matrix-v2.json \
  --output /absolute/path/to/new-run2-package \
  --analysis TOP-26-006
```

Repeat with `--era run3`, its completed manifest(s), and a distinct fresh
output. The builder defaults to the `ALL_CH_LST_SR` channel set in
`topeft/channels/ch_lst.json`; `--channel-registry` and
`--channel-set-key` select an alternative channel set. It rechecks
receipt-bound source files and exact card/template pairs, assigns deterministic
per-era `chN` labels, consolidates selected WCs and scaling records, and
publishes `cards/`, `selectedWCs.txt`, `scalings.json`,
`physical_to_chN.json`, and `package-provenance.json`. Duplicate scaling
identities are rejected. `combinedcard.txt` is not built here.

## Build and consume a combined Run 2 + Run 3 package

Use the Run 2 and Run 3 per-era package directories as inputs. Run the
combined builder from the repository root. It derives the mapping and card
order from their mappings, copies ROOT templates, updates only the card
template reference, and relabels scaling channels. It checks the staged and
published cards-only package against the input packages. It requires a fresh
absolute output path:

```bash
python analysis/topeft_run2/build_combined_datacard_package.py build \
  --run2-package /absolute/path/to/run2-package \
  --run3-package /absolute/path/to/run3-package \
  --output /absolute/path/to/new-combined-package \
  --analysis TOP-26-006 \
  --package-date YYMMDD \
  --package-version v1
```

The package contains `cards/`, `scalings.json`,
`combined_mapping_manifest.json`, `ordered_card_inputs.txt`,
`package-provenance.json`, and a README. It does not contain a
combined `selectedWCs.txt` or `combinedcard.txt`. The `certify` subcommand can
check an existing package against the same Run 2 and Run 3 inputs. Fit
configuration determines the Wilson coefficients used when building the
workspace.

`ordered_card_inputs.txt` lists cards in combination order. From the combined
package directory, follow its generated README:

```bash
cd <combined-package-root>
mapfile -t cards < ordered_card_inputs.txt
combineCards.py "${cards[@]}" > combinedcard.txt
```

The list follows the packaged channel mapping; do not use shell-glob order.
This command combines the individual cards. Workspace construction and fitting
follow in EFTFit/Combine.

## Diagnose card/finalization failures

| Failure | Correct response |
| --- | --- |
| merge policy/schema/companion mismatch | fix or reproduce the upstream artifact; do not concatenate dictionaries manually |
| selected variable/channel absent | inspect the merged histogram axes and source registry; a regex cannot create missing content |
| fitting edges not exactly representable | correct the fitting-bin definition or produce compatible processing-binned PKLs |
| selected-WC mismatch | review the new selection and reference before rerunning |
| per-era builder missing card/template | reproduce that physical channel/distribution pair; do not let packaging hide an incomplete set |
| preselect scaling has no selected physical label | determine whether the process intentionally has no external EFT morph or the producer output is incomplete |
| destination already exists | choose a fresh package directory; there is no supported resume/merge behavior |

Exact schemas and option contracts are in the
[datacards/scalings reference](../reference/datacards_and_scalings.md). The
[EFTFit boundary explanation](../explanation/datacards_and_eftfit.md) describes
why package construction and card combination remain separate responsibilities.

Use [categories and observables](categories_and_observables.md) before changing
the physical category or distribution that a card consumes, and use
[corrections, weights, and systematics](corrections_weights_and_systematics.md)
before changing the upstream variation. This guide owns the card-facing rate,
applicability, fitting-view, selected-WC, and scaling-export changes only.
