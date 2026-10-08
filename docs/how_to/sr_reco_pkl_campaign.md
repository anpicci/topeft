# Produce and qualify SR-reco extension PKLs

Use `run2_sr_ext` and `run3_sr_ext` in `analysis/topeft_run2/run_cr.sh`
for the maintained SR-reco extension source campaigns. The current
`run2_sr_ext` and `run3_sr_ext` profiles each materialize 15 fragments from
five SR category groups and three variable chunks per group. This is the
current profile grouping, not a fixed fragment count for every future SR
campaign. The exact block and artifact names come from the maintained profile
configuration; see
[production configuration](../reference/production_configuration.md) for the
category/variable matrix.

This guide specifies launch and evidence requirements. It does not certify a
particular campaign or replace the artifact schemas in
[histogram artifacts](../reference/histogram_artifacts.md).

## Opt-in 20-fragment guarded candidate

`run2_sr_ext20` and `run3_sr_ext20` use the same five category groups and
variables as the 15-fragment extension profiles, with four nonempty variable
chunks per group. Their block identities end in `_a_1` through `_e_4` and
belong to a new 20+20 membership contract. They do not reuse historical
15+15 receipts. The four accepted **nominal** `--chunksize` choices are
`100000`, `75000`, `50000`, and `25000`; this argument is required for these
profiles. Coffea's `dynamic_chunksize` is disabled in this launch path, but
`split_on_exhaustion` can reduce an effective task size after resource
failure. The chosen number is therefore not a guaranteed size for every
executed task.

A real 20-fragment launch requires `--wq-staging-base` and all of
`--wq-quota-root`, `--wq-warning-bytes`, `--wq-stop-bytes`,
`--wq-reserve-bytes`, and `--wq-poll-seconds`. The base must be an existing,
owned, writable directory on a non-root filesystem. The quota root must be
the exact applicable `/groups/<owner>` or `/users/<owner>` root supported by
the site's `quota` command. A unique campaign/block/attempt directory is
created beneath the base, and that exact directory is passed to
`WorkQueueExecutor.filepath`. The thresholds are operator-selected from the
chosen mount's measured capacity, quota and observed output sizes; the
workflow has no universal byte budget. `--wq-treereduction` may explicitly
select `20`, `10` or `5`; omitting it retains Coffea's existing setting.
Smaller fan-in can reduce a single reduction's input load while increasing
tree depth and intermediate I/O. Worker resource co-location and safe peak
memory remain unproven.

The separate watchdog polls charged staging bytes, entry count, filesystem
free blocks/inodes, quota headroom and the exact manager PID. It sends
SIGTERM on a stop or measurement failure because installed Coffea handles
SIGINT by attempting final accumulation. This is a polling heuristic: large
in-flight transfers can overshoot a threshold. A guard trip returns nonzero,
blocks later guarded fragments and leaves the owned directory marked
`cleanup_needed`. After a normal manager exit, campaign state and native logs
are recorded before the exact owned directory is removed. Any ambiguous
intermediate, reader or ownership state leaves it for explicit review.

The existing 15-fragment profiles remain selectable. They can use the same
opt-in guard arguments, while their nominal chunk-size behavior remains
unchanged. Their unguarded legacy path must not be used for the proposed
resource-safe canary. The 20-fragment candidate is not released for execution
by this documentation. A later operator review must establish the staging
mount's writability and conservative headroom, the worker archive at
`analysis/topeft_run2/topeft-envs/`, an isolated output namespace, scheduler
state and a monitored single-fragment plan before Andrea authorizes a manual
canary.

## Resolve source and worker authorities

The manager and local postprocessing execute from the live checkout.
`analysis_processor.py` is separately transferred to Work Queue as
live-checkout-controlled source. Run 2 performs inline local
`DataDrivenProducer` processing during `run_analysis.py`; Run 3 runs the local
`run_data_driven.py` stage after its source stage completes. Worker-only
imports, runtime libraries, and correction payloads come from the explicitly
selected frozen worker environment. Thus the worker archive's TOPEFT and
TOPCOFFEA source provenance and the manager/local TOPCOFFEA checkout are
distinct authorities.

Prepare an environment archive through the canonical
`run_analysis.py --prepare-env-only` path, backed by
`topcoffea.modules.remote_environment.get_environment` (documented in
TOPCOFFEA's `docs/environment_archive_contract.md`), and select its absolute
path with `run_cr.sh --env-file`. Record the resolved
environment request/fingerprint, archive path and SHA-256, frozen TOPEFT source
identity, worker TOPCOFFEA identity, and live manager/local source identities.
An explicit archive is a frozen snapshot: validate its integrity and
provenance; do not interpret its selection as proof that it matches the current
checkout. No particular historical tarball is the permanent worker
environment.

Before each launch, assess compatibility against the maintained contracted
live-manager dependencies, the live local data-driven and transferred
processor source, the manager/local TOPCOFFEA authority, and the explicit
frozen archive. Equality of the whole live TOPEFT HEAD to the frozen TOPEFT
commit is not the launch gate. A change in a contracted dependency requires
review before execution. If the campaign namespace encodes a worker-frozen
source identity, keep that identity consistent with the selected archive;
the workflow does not prescribe a universal date or short-SHA spelling.

## Run 2, then Run 3

Use the maintained `run_cr.sh` workflow and one campaign output root. Keep the
terminal transcript and exact process exit status for each profile. Workers
are provisioned separately with the manager name printed for each Work Queue
source invocation.

1. Before `run2_sr_ext`, rerun the applicable launch-compatibility preflight;
   require the fresh output root to be absent; inspect the scheduler situation;
   then run the Run 2 command with the explicit `--env-file`, absolute
   `--output-dir`, and `--campaign-tag`.
2. Start `run3_sr_ext` only after the Run 2 process returns zero. Rerun the
   compatibility preflight and inspect the scheduler situation immediately
   before Run 3. Use the same campaign namespace and archive. There is no
   second fresh-root absence gate: Run 2 has already established the
   shared output root.

A zero process status is necessary, but campaign state, receipts, artifacts,
sidecars, and logs still need post-run review. In Run 2, each fragment's source
and `_np` artifacts are produced by the inline path. In Run 3, the local
`run_data_driven.py` child follows successful source publication. Do not start
the deferred stage from an incomplete source artifact.

## Native Work Queue logs and recovery

The campaign assigns each source invocation a native log directory:

```text
<output_root>/work_queue_logs/<production_component>/<block_id>/source_native/
```

The four native files are `debug.log` (manager diagnostics), `tr.log`
(transactions), `stats.log` (statistics), and `tasks.log` (task history).
After verified archival, the campaign records the corresponding `source/`
directory in state. An existing owned native log prevents a new invocation;
checkout-global log files are not campaign-owned state. See
[Work Queue operations](work_queue.md) for direct-run defaults and archive
behavior.

A nonzero return, interruption, lost terminal, unclear completion, ambiguous
owned or stale native logs, or ambiguous campaign state is a stop for
classification. Preserve the transcript, state, receipts, artifacts, and
native logs. Inspect process and scheduler ownership and the exact output
paths before choosing any recovery action. Do not automatically retry,
resume, delete, overwrite, restart, or resubmit a fragment or stage. The
presence of a source PKL alone does not establish that its sidecar or deferred
`_np` stage completed.

## Return evidence and qualify artifacts

For each profile, retain its command transcript and exact exit status, final
`run_cr.sh` campaign state and block receipts, any campaign summary or failure
snapshot, and the exact source/`_np` PKL and sidecar inventory with paths and
sizes. Return the worker-archive identity and live-source provenance bound to
the campaign, plus native Work Queue logs when needed to explain completion or
recovery. Use the runner's serialized state as the primary completion record;
do not reconstruct it from filenames alone.

After successful Run 2 and Run 3 production, qualify the extension campaign
with the checks below against the maintained profile configuration:

- Match expected fragment membership for each current 15-fragment profile,
  including source and `_np` realization. Confirm Run 2 inline and Run 3
  deferred local data-driven stage order from state, receipts, and sidecars.
- Reconcile each PKL with its adjacent sidecar, source-to-`_np` lineage,
  campaign state, and receipt. Check path ownership, nonempty size, artifact
  digest, and the sidecar's recorded size and digest.
- Compare the recorded family/category inventory and applicability with the
  profile plan. `fwd0pt` and `fwd0eta` have support only in forward-labelled SR
  categories; `tau0Tpt` has support only in categories with at least one tight
  tau. `tau0Fpt` is absent from the SR-reco extension variable set. Distinguish
  an intentionally inapplicable channel from a missing expected fill.
- Check the applicable systematic variations, including expected Up/Down
  templates; the resolved production `sumw2` companions and data-driven
  contract; and the raw event-count setting recorded by the profile. These
  extension profiles use systematics, implicit production `sumw2`, and no
  raw-count recording.

Qualification is a separate post-production step. This checklist does not imply
that any current production run or artifact set has passed it.
