# Produce SR-reco extension PKLs

`run2_sr_ext` and `run3_sr_ext` are the maintained SR-reco profiles in
`analysis/topeft_run2/run_cr.sh`. Each uses the eight histograms `fwd0pt`,
`j0pt`, `b0pt`, `met`, `l0conept`, `l1conept`, `invmass`, and `tau0Tpt` where
they apply. `fwd0pt` is restricted to forward-labelled SR channels and
`tau0Tpt` to tight-tau channels. `b0pt` is the leading tagged b-jet pT
histogram; its numerical bins match `j0pt` while its key and label remain
distinct. Fit observables around b-tag classification are a separate analysis.

The supplied [default plan](../../analysis/topeft_run2/sr_reco_default_plan.json)
contains 12 units per era. `--sr-plan /absolute/plan.json` selects another
complete, valid initial partition. The plan has one `units` array; each unit
has a unique snake-case `id`, `category_groups` list and `histograms` list.
Each unit describes a category-group × histogram product. The launcher checks
that its applicable physical category × variable coverage is exact and unique
against the live channel registry. It derives the target size from that
registry. It does not accept unknown groups, keys, duplicates or gaps.
The default splits `l0conept` from the `j0pt b0pt` mixed-category chunk:
the largest category × axis-bin proxy is 2,112, versus 2,684 for the
otherwise equivalent 11-unit packing. This proxy is not a measured memory
or output-size limit.

## One root, selected units and continuation

Use a fresh output directory for the **initial** campaign. Run 2 and Run 3
remain distinct profile components and retain their existing shared-root
arrangement when a combined campaign owns them. An internal plan revision
stays inside its component's campaign root. No existing output is copied or
adopted from another root.

A selected-unit invocation uses the complete persisted plan. For example,
`--selected-fragment run2_sr_ext_a_1` runs one ordinary unit in the default
Run 2 plan. A later `--resume` uses the same root and skips verified completed
units. Run 2 writes source and inline `_np` artifacts in one source invocation.
Run 3 writes the source artifact first and performs `_np` in a separate local
stage. A verified Run 3 source can remain `source_ready` until that stage
finishes. The campaign is complete only after both stages have verified
receipts for all applicable coverage.

The state file is `.<profile>_campaign_state.json` in the campaign root. It
stores immutable plan snapshots, the active revision, per-unit source and
nonprompt status, artifact/sidecar receipts, environment and source contract,
and a coverage target. `campaign_summary.tsv` and `campaign_summary.md` read
that same state. A source or `_np` PKL's existence alone is not completion
proof. Keep the state, both sidecars, native Work Queue logs, output paths and
command transcript together for review.

## Repartition only untouched coverage

Prepare a JSON plan containing **only** still-uncovered units. Any valid
category-group × histogram repartition is accepted if its union is exactly
remaining physical coverage and every new unit ID and output path is unused.
All completed units remain in the original plan revision with unchanged
artifacts and receipts. The new plan is appended to the same state file and
activated by one atomic state replacement:

```text
./run_cr.sh --production-profile run2_sr_ext \
  --output-dir /absolute/existing/campaign --campaign-tag chosen_tag \
  --resume --activate-pending-plan /absolute/pending.json \
  --expected-plan-revision r1_exact_observed_id
```

Activation is a separate quiescent operation; it submits no work. Read the
current `active_sr_reco_revision` from state immediately before it. The
campaign lock must be available. Failed, interrupted, in-flight or otherwise
ambiguous units, stale revision IDs, changed source/input/binning contracts,
missing or changed artifact receipts, and output collisions reject the
replacement before changing state. A finished Run 3 source with a verified
receipt and pending local `_np` is retained; it is not called fully complete.
An interrupted atomic write leaves either the old state or the entire new
state authoritative. Do not edit state or receipts by hand.

After activation, ordinary `--resume` runs the retained deferred stages and
active pending units in the same root. `--selected-fragment` can filter a
single active unit without altering the full plan. The launcher checks
coverage across historical completed units and the active pending revision;
it does not decide completion from only the latest revision's rows.

## Work Queue staging and stop conditions

Every real Work Queue route, including CR and direct `run_analysis.py`, needs
an explicit guarded staging base. Through `run_cr.sh`, provide
`--wq-staging-base`, `--wq-quota-root`, `--wq-free-warning-bytes`,
`--wq-min-free-bytes 10000000000`, and `--wq-poll-seconds`. A direct
`run_analysis.py -x work_queue` invocation requires `--wq-filepath`,
`--wq-guard`, a unique invocation ID and the same free-space values. The
base must be an existing owned writable directory on a non-root filesystem;
implicit `/tmp` and root-backed staging are rejected by mount identity.
`--wq-treereduction` is optional and requires separate resource review.
`--wq-processing-cores 1` is a separate opt-in processing-category reservation
maximum. It does not change accumulation resources, set CPU affinity, or
establish worker packing or throughput.

Before launch, the guard requires at least the selected minimum usable bytes
from both filesystem free space and group quota, plus 1,000 free inodes.
The minimum is at least 10 GB (decimal). During execution it reports usable
free bytes and inodes without scanning the staging tree. Low readings and
temporary measurement failures produce warnings, never guard-generated signals.
The final manager readback rejects a dead watcher or changed ownership marker
before recording source success; ambiguous staging remains for inspection. The older
`--wq-warning-bytes`, `--wq-stop-bytes` and `--wq-reserve-bytes` options are
retired. Native logs are copied and checked before only the completed owned
staging is removed. Cleanup refusal retains staging and prints a warning; a
valid source receipt remains valid. A failed source stops later guarded units. Preserve
an ambiguous state and inspect the exact process, scheduler, artifact and log
ownership before any separate recovery decision.

An explicit worker archive is a frozen snapshot, not proof of source
compatibility. Any archive made before the `b0pt` bin change needs a fresh
module/axis qualification and path selection before this campaign can run.
The first manual canary also needs an isolated non-root staging mount with
measured quota/inode/free-space budget, scheduler readiness, a conservative
worker memory/concurrency and tree-reduction bound, and a fresh initial
campaign namespace. No historical aborted root should be reused.

`--dry-run` resolves commands without creating a campaign root or submitting
workers. It does not qualify an archive, site capacity, physics content or
production outputs.
