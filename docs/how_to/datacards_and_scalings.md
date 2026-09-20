# Create cards and finalize EFT scalings

`analysis/topeft_run2/make_cards.py` is the maintained direct card-production
interface. It consumes one or more compatible histogram PKLs—normally the
nonprompt-transformed products—and writes individual text cards, ROOT template
files, canonical `selectedWCs.txt`, and `scalings-preselect.json`. For a
prequalified multi-row production, the one maintained resumable execution
entry point is
`analysis/topeft_run2/run_datacard_matrix_resumable.sh`. Campaign/operator
scripts remain records and are not additional maintained interfaces.

| Interface | Owns | Defaults/derived state | Delegates or does not own |
| --- | --- | --- | --- |
| `make_cards.py` | input merge validation, WC selection, channel/variable selection, `DatacardMaker` construction, local or generated Condor execution | fitting binning, year coverage `warn`, Asimov data, no nuisances or MC-stat opt-in | `DatacardMaker` owns card/template/scaling construction; registries, rate payloads, binning and histogram artifacts remain external authorities |
| `datacards_post_processing.py` | one topology selection, deterministic physical-channel ordering, file selection/copy, `chN` relabeling | exact one-of selector; `-a` chooses `ALL_CH_LST_SR`; destination is fixed to `ptz-lj0pt_withSys` | does not make individual cards, fit them, combine them, or recalculate producer scaling payloads |
| EFTFit/Combine | individual-card combination and statistical fit | external workflow | creates `combinedcard.txt` later; does not redefine topeft's channel/topology selection |

The region -> distribution -> binning mapping is shared source authority:
physical regions and jet populations come from `topeft/channels/ch_lst.json`;
the finalizer chooses each region's card distribution (`lj0pt`, `ptz`, `ptll`,
`ptz_wtau`, or `lt`); `topeft/modules/axes.py` supplies processing/fitting
edges. An operator matrix may record a campaign selection but must not become a
second copy of that map.

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

## Run a prequalified matrix resumably

The canonical runner accepts an ordered JSON manifest; it does not derive or
qualify the physics matrix. Each row records its logical and attempt IDs, era,
working directory, input PKL, output root, distribution, literal physical
channel argv, years, missing-parton path, SR registry, row-specific merge
report, immutable snapshot/log destinations, expected output paths, and exact
`make_cards.py` argv. The manifest also selects a control root and advisory-lock
path. Use attempt-specific log, snapshot, merge-report, and expected-output
paths.

The schema is `topeft_datacard_matrix_v2`. The manifest owns an opaque,
prequalified runtime contract: it names the absolute producer Python and
`make_cards.py` paths and hashes the qualification layer's chosen runtime
files. The runner only verifies that contract mechanically; it never decides
which source files are scientifically sufficient.

```json
{
  "schema": "topeft_datacard_matrix_v2",
  "control_root": "/path/to/runner-control",
  "lock_path": "/path/to/runner-control/runner.lock",
  "runtime_contract": {
    "contract_id": "qualified-run3-runtime-001",
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
    "merge_report_path": "/path/to/evidence/run3_01/merge_report.json",
    "snapshot_directory": "/path/to/runner-control/snapshots/run3_01_attempt_01",
    "log_path": "/path/to/evidence/run3_01/row.log",
    "expected_output_paths": ["/path/to/cards/run3/card.txt", "/path/to/cards/run3/card.root"],
    "producer_args": ["--out-dir", "/path/to/cards/run3", "--var-lst", "lj0pt", "--ch-lst", "physical_channel_a", "physical_channel_b", "--year", "2022", "2022EE", "2023", "2023BPix", "--miss-parton-file", "/absolute/path/to/missing_parton_run3.root", "--sr-registry", "ALL_CH_LST_SR", "--merge-report", "/path/to/evidence/run3_01/merge_report.json"]
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

Run long, manually authorized executions in a named `tmux` session so the
operator can detach without terminating the runner. Inspect `--plan-only` and
`--status` first, and keep the exact accepted manifest unchanged during an
attempt. The runner validates the schema and runtime fingerprints before plan
or execution, holds one OS advisory lock for a mutating run, and directly runs
the qualified Python argv with no shell intermediary and no `codex-run.sh`
runtime dependency. It stops on the first command or evidence failure.

After a successful row command, the runner checks the declared outputs, retains
the row-specific merge report, snapshots `selectedWCs.txt`,
`scalings-preselect.json`, and the merge report, hashes the primary TXT/ROOT
outputs and every row-local control artifact (merge report, snapshots, and log),
and atomically publishes an execution receipt. Receipt validation rechecks both
size and SHA256. This is execution-integrity evidence, not a physics
certificate.

On restart, a row is skipped only when its receipt matches the current manifest,
argv, paths, runtime contract, and byte-bound artifacts. Owner metadata is
updated atomically under the OS lock before each row. `--status` reports
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

Keep these lifecycle layers separate:

1. This runner owns sequential execution, logs, snapshots, and execution
   receipts.
2. A later review owns scientific certification of cards, templates, and
   producer metadata.
3. A separately authorized step owns selected-WC and scaling consolidation.
4. `datacards_post_processing.py` remains the finalizer and is never launched by
   the resumable runner.

The output set for either the generated or `--use-selected` selection path
contains one text-card/ROOT-template pair per selected physical channel and
distribution, canonical `selectedWCs.txt`, and `scalings-preselect.json`. The
preselect file records producer-owned EFT polynomial payloads under physical
channel/distribution labels. `make_cards.py` does not assign final `chN` labels
or create `combinedcard.txt`.

The tracked `run_make_cards_run3_yawen_matrix.sh` is classified as an archival
operator record: its site/user paths, campaign inputs/hashes, environment and
branch assumptions, and DATACARD023-qualified provenance make it useful for
that campaign but not a supported wrapper. It remains tracked in its runnable
location; moving, removing, or generalizing it requires a separate executable
source-control decision. Use `make_cards.py` directly for maintained work.

## Finalize the current full topology

The card directory must already contain the individual card/template pairs,
`selectedWCs.txt`, and `scalings-preselect.json`. Then run:

```bash
python datacards_post_processing.py /absolute/path/to/cards -a
```

Exactly one topology selector is required. `-a`/`--all-analysis` selects the
full current topology from `ch_lst.json`. The script deterministically orders
the physical channel names, maps them to `ch1`, `ch2`, and so on, copies the
selected card/template/WC inputs, and writes final `scalings.json`. A matching
scaling record retains its producer-owned payload while only its channel label
is replaced by the deterministic `chN` label.

Use a card directory whose `ptz-lj0pt_withSys` destination does not already
exist; the finalizer creates it and does not implement resume/overwrite. It
has incomplete selector-dependent count guards: `-s`, `-z`, and `-t` check both
text and ROOT totals; `-a` checks only the ROOT total; and `-f` checks neither.
The printed "root templates copied" line also reports the text counter. Do not
use that line or a successful exit as completeness evidence. Independently
list and count the copied `.txt` and `.root` files, pair them by the expected
physical `<channel>_<distribution>` stem, and compare the pairs with the
selected topology before handing the directory onward.

The mapping procedure is deterministic: load the chosen registry block,
expand its physical jet populations, choose the source-owned distribution for
each category, sort the resulting physical channel/distribution names, and map
their one-based positions to `ch1`, `ch2`, .... Only scaling records whose
physical label is selected are retained. A record's coefficients/WC order are
not recalculated during relabeling.

`combinedcard.txt` is neither an input nor an output of
`datacards_post_processing.py`. EFTFit later combines the individual cards and
creates `combinedcard.txt` before the Combine handoff. If the final scaling
file has no record for an exact channel/process pair, that pair has no external
EFT morph; do not fabricate one during finalization.

Validate this boundary with `tests/test_split_datacard_boundary.py`,
`tests/test_ptll_semantic_contract.py`,
`tests/test_datacard_late_rebin.py`, and the relevant card-option tests. A
binning change can alter template bin counts and `scalings-preselect.json`, so
reproduce cards and final scalings together even when existing PKLs remain
exactly aggregatable.

## Diagnose card/finalization failures

| Failure | Correct response |
| --- | --- |
| merge policy/schema/companion mismatch | fix or reproduce the upstream artifact; do not concatenate dictionaries manually |
| selected variable/channel absent | inspect the merged histogram axes and source registry; a regex cannot create missing content |
| fitting edges not exactly representable | correct the canonical fitting view or produce compatible processing-binned PKLs |
| selected-WC mismatch | review the new selection and reference; do not skip the check without an explicit validated reason |
| finalizer missing card/template | reproduce that physical channel/distribution pair; do not let relabeling hide an incomplete set |
| preselect scaling has no selected physical label | determine whether the process intentionally has no external EFT morph or the producer output is incomplete |
| destination already exists | choose a fresh card-finalization directory; there is no supported resume/merge behavior |

The selectors `-s`, `-z`, `-t`, and `-f` describe narrower or historical
topologies. In particular, `-s` is the historical TOP-22-006 selection, not the
current default. See the [historical TOP-22-006 page](historical/top_22_006.md).

Exact schemas and option contracts are in the
[datacards/scalings reference](../reference/datacards_and_scalings.md). The
[EFTFit boundary explanation](../explanation/datacards_and_eftfit.md) describes
why finalization and card combination remain separate responsibilities.

Use [categories and observables](categories_and_observables.md) before changing
the physical category or distribution that a card consumes, and use
[corrections, weights, and systematics](corrections_weights_and_systematics.md)
before changing the upstream variation. This guide owns the card-facing rate,
applicability, fitting-view, selected-WC, and scaling-export changes only.
