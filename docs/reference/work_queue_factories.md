# Separate dynamic Work Queue factories for Run 2 and Run 3

These resource specifications prepare future homogeneous worker supply. Use
one native `work_queue_factory` per activated family, with separate campaign
binding and lifecycle. Preparing the files starts no factory, changes no
existing supply, and does not authorize activation or live reload.

| Family | Resource specification, relative to the repository root |
| --- | --- |
| Run 2 | [`analysis/topeft_run2/factory_run2.json`](../../analysis/topeft_run2/factory_run2.json) |
| Run 3 | [`analysis/topeft_run2/factory_run3.json`](../../analysis/topeft_run2/factory_run3.json) |

The files are independently maintained regular files. Their initial values
are equal; changing one later does not change the other.

| JSON field | Run 2 | Run 3 | Meaning with the inspected CCTools 7.15.10 consumer |
| --- | ---: | ---: | --- |
| `cores` | 60 | 60 | Requested CPU cores per worker |
| `memory` | 240000 | 240000 | Nominal MB parameter; Condor receives `request_memory = 240000`, in MiB (234.375 GiB) |
| `disk` | 300000 | 300000 | Nominal MB parameter; Condor multiplies by 1024, giving `request_disk = 307200000`, in KiB (300000 MiB) |
| `min-workers` | 10 | 10 | Factory target floor, including when calculated demand is below the floor |
| `max-workers` | 50 | 50 | Factory target ceiling |
| `workers-per-cycle` | 5 | 5 | Throttle on submitted workers still waiting to connect; see below |
| `timeout` | 900 | 900 | Seconds for both worker connection and idle timeouts |

Per factory, the floor corresponds to 600 cores and 2400000 MiB; the ceiling
corresponds to 3000 cores and 12000000 MiB. These are requested resource totals,
not allocation guarantees or task counts. Each family has its own floor of 10
and ceiling of 50. They are not a shared Run 2 + Run 3 cap, nor a global cap
against unrelated suppliers. External connected workers affect the native
factory's aggregate accounting; static, pending, held and remote supply must
be reconciled separately before activation.

## Consumer semantics and qualification limits

The local factory and worker report CCTools **7.15.10 FINAL**. Their installed
hashes match the package's `sha256_in_prefix` records. The relevant local
sources match the corresponding files at CCTools `release/7.15.10`
(`4bcd982c1f4ceaaca424af85331efb6cf32fd2c5`):

- `batch_job/src/work_queue_factory.c`: JSON parsing, CLI/config precedence,
  demand calculation, worker command, throttle, wrapper transfer and shutdown.
- `batch_job/src/batch_queue_condor.c`: resource conversion, input transfer
  and job removal.
- `work_queue/src/work_queue_worker.c`: worker timeout parsing and idle timer.

This is static source inspection plus installed help/version evidence. It is
not a generated Condor submit file, a backend probe, or a reproducible-build
proof linking those sources to every instruction in the installed binaries.
Recheck the consumer if the installation changes, and obtain actual Condor
resource readback during a separately authorized activation.

The factory parses CLI options first, then reads the JSON. Fields present in
the JSON replace the corresponding CLI values. Missing fields retain their
current values, so `-M` supplies the binding omitted from these resource files.
`-C` alone is not a launch-ready command: without a manager name or explicit
manager host/port, this consumer rejects the configuration. It rereads its
config each cycle when the modification time changes; a bad reread retains
the previous values. Editing an active config is an operational action.

The throttle computes waiting workers from submitted minus aggregate connected
workers. With a positive limit, additional submissions are bounded by
`max(0, 5 - workers_waiting_to_connect)` when the throttle applies. Five pending
connections can therefore prevent further submissions. The help mentions
30 seconds; the loop also performs queries and waits, so there is no fixed
five-per-30-seconds ramp or guarantee of five successful connections. The floor
can create demand even without useful manager work. Above the target, this
source waits for workers to exit rather than immediately removing excess jobs.

Factory `timeout=900` becomes worker `-t 900`, setting both connection and idle
timeouts. Worker task activity resets the idle timer. This is an initial
operational policy for releasing inactive workers, not a measured optimum,
task wall-time limit, stuck-task recovery mechanism or `--factory-timeout`.
The latter controls how long the factory tolerates seeing no managers and is
not set by these specs. A surviving factory may refill after workers exit;
900 seconds does not stop the factory or permanently drain supply. Extra worker
options are appended after `-t` and can override its timers: review resolved
argv before activation. Existing static-worker timeouts are not changed.

The disk value reuses the existing processing supply setting. Do not enable
`--autosize`, `--capacity`, extra resource overrides, GPU requirements, feature
routing or custom packing policy for these profiles. The consumer's native
tasks-per-worker default is a demand heuristic, not a measured task concurrency
or throughput guarantee. No task-size, task-resource or producer setting is
selected here.

## Bind a future campaign explicitly

Before activation, record all of the following for each family:

| Input | Required binding |
| --- | --- |
| Campaign and manager set | Exact campaign identity and complete manager names approved by its owner |
| Selector | Anchored regex matching exactly that family's manager set; positive matches and rejection of the other family and unrelated names |
| Execution identity | Explicit submission owner/UID, schedd and pool, with the site's native Condor configuration verified in that execution context |
| Consumer | Absolute factory and worker paths, versions and hashes |
| Resource file | Absolute path and hash of the selected family JSON |
| Runtime namespace | Fresh, distinct scratch directory, debug log, stdout/stderr log and PID-record path for each family |
| Worker environment | Existing qualified archive and credentials/CVMFS prerequisites for the campaign; no archive rebuild is implied |
| Supply inventory | Static cohorts, top-ups, local/remote factories and IDLE/RUNNING/HELD/REMOVING jobs, with provenance and overlap resolved |

For illustration only, `^example_campaign_run2_source$` selects
`example_campaign_run2_source` and rejects `example_campaign_run3_source`;
`^example_campaign_run3_source$` does the converse. Replace these examples with
the actual complete manager set. Escape regex metacharacters in real names;
use an anchored explicit alternation for multiple names. Historical BTV
prefixes are not universal selectors. Neither JSON contains `manager-name`,
a default wildcard, or an implicit connection to current production.

The native option shapes below are **unbound command models**, not commands
ready for execution. Every angle-bracket input requires an explicit future
binding and activation authorization, including the submission context above.

```text
<absolute_work_queue_factory> -T condor \
  -C <absolute_topeft>/analysis/topeft_run2/factory_run2.json \
  -M '^example_campaign_run2_source$' \
  -S <fresh_absolute_run2_scratch> \
  -d all -o <fresh_absolute_run2_debug_log> \
  --worker-binary <absolute_work_queue_worker> \
  --wrapper ./with_oasis_certs \
  --wrapper-input <absolute_site_with_oasis_certs>

<absolute_work_queue_factory> -T condor \
  -C <absolute_topeft>/analysis/topeft_run2/factory_run3.json \
  -M '^example_campaign_run3_source$' \
  -S <fresh_absolute_run3_scratch> \
  -d all -o <fresh_absolute_run3_debug_log> \
  --worker-binary <absolute_work_queue_worker> \
  --wrapper ./with_oasis_certs \
  --wrapper-input <absolute_site_with_oasis_certs>
```

The inspected site wrapper is the existing executable
`analysis/topeft_run2/with_oasis_certs`; it is a local prerequisite, not a new
tracked launcher supplied by these specs. Verify its identity and availability
at the future site. `--wrapper` prefixes the **worker** command in this source,
despite the help's wording about wrapping the factory. `--wrapper-input`
copies the wrapper basename into factory scratch and includes it in worker
input transfers. The worker binary is copied there too; Condor enables input
transfer. The wrapper must be executable as `./with_oasis_certs` on workers.
It sources the OASIS client when certificates are available through CVMFS;
otherwise it creates temporary certificate files in the worker directory and
cleans those on exit. Its embedded certificate/CRL validity and the worker-site
environment need qualification before use. This preparation did not execute
the wrapper or transfer anything.

Do not share scratch, logs or PID records between families or reuse an old
factory scratch directory for a new lifecycle. Capture the actual factory PID,
full argv, host, owner, start time, config hash, schedd and submitted job IDs
when a future launch is authorized. Preserve that evidence through shutdown;
a PID alone is insufficient identity. No persistent launcher or controller is
required by these specs.

## Stop with native lifecycle awareness

Shutdown requires its own bounded authorization. First bind the exact factory
process and all jobs it owns, inspect active tasks, and choose the approved
drain/removal policy. In the inspected source, SIGINT, SIGQUIT and SIGTERM set
the abort flag; leaving the main loop calls `remove_all_workers` on the
factory's job table. The Condor backend implements removal with `condor_rm`.
A signal to the factory can therefore remove busy workers; it is not a
drain-only operation. Parent-death or factory-timeout exits can reach the same
cleanup. Do not signal a wrapper or stale PID expecting a guaranteed safe drain.

For a planned drain, the operator must coordinate producer completion and
worker retirement under that future policy before terminating the supplier.
Keep Run 2 and Run 3 identities distinct, prevent unintended refill, and read
back actual process and scheduler results after any authorized action. Do not
infer shutdown from a missing PID in a restricted namespace, or infer a safe
retry from an interrupted command. No shutdown action was performed here.

## Supply and production ownership

The campaign owner supplies the manager binding and authorizes production;
the supply operator owns factory lifecycle, inventory and readback. Creating
or running a producer does not start a factory through these files. Existing
static supply and historical setup/logs remain separate. Future activation
must reconcile the whole current family population to avoid duplicate or
unaccounted supply; historical cluster IDs alone are insufficient. A previously
confirmed retirement need not be repeated to prepare these files.

See the [production guide](../how_to/production.md) for producer commands and
the [Work Queue how-to](../how_to/work_queue.md) for monitoring and historical
multi-profile context. These two homogeneous specs do not reinstate heavy
fallback or a profile-aware multi-factory actuator.
