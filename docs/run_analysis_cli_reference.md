# `run_analysis.py` CLI and YAML reference

This page is the authoritative flag reference for
`analysis/topeft_run2/run_analysis.py`.

## Options exclusivity rule

When `--options <path[:profile]>` is provided, options YAML is the only
configuration source.

- Allowed alongside `--options`: `--help` (and `--version` only if present).
- Disallowed alongside `--options`: all other config flags, including
  `--metadata`, `--executor`, `--chunksize`, `--scenario`, `--pretend`, etc.

## Key defaults

- `--executor`: `taskvine`
- `--chunksize`: `500000`
- `--ddr-output-schema`: `flat`
- `--produce-sidecars`: disabled

## Core flags

| Flag | Default | Notes |
| --- | --- | --- |
| `jsonFiles` (positional) | empty | JSON/CFG input specs when not using YAML-only profiles. |
| `--options` | unset | YAML file path or `path.yml:profile`. |
| `--executor` | `taskvine` | `taskvine`, `futures`, `iterative`. |
| `--chunksize` | `500000` | Events per chunk. |
| `--nchunks` | unset | Cap processed chunks. |
| `--nworkers` | `8` | Worker count. |
| `--outname` | `plotsTopEFT` | Output file stem. |
| `--outpath` | `histos` | Output directory. |
| `--treename` | `Events` | Input tree. |
| `--scenario` | `TOP_22_006` when omitted | Scenario name; YAML profiles should encode this. |
| `--metadata` | unset | Metadata path when not using `--options`. |
| `--summary-verbosity` | `brief` | `none`, `brief`, `full`. |
| `--produce-sidecars` | `false` | Enables sidecar creation in processor outputs. |

## TaskVine/distributed flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--port` | `9123-9130` | Manager port/range. |
| `--no-port-negotiation` | false | Disable manager port scanning fallback. |
| `--manager-name` | unset | Explicit manager name. |
| `--manager-name-template` | unset | Template with `{pid}` support. |
| `--scratch-dir` | unset | Shared staging path. |
| `--resource-monitor` | `measure` | TaskVine monitor mode. |
| `--resources-mode` | `auto` | TaskVine resources mode. |
| `--environment-file` | `cached` | Remote env tarball selection. |
| `--taskvine-print-stdout` | true | Forward worker stdout. |

## Futures/iterative debug flags

| Flag | Default | Notes |
| --- | --- | --- |
| `--futures-workers` | executor default | Local process count override. |
| `--futures-status` | executor default | Progress bar toggle. |
| `--futures-tail-timeout` | unset | Timeout for stalled task cancellation. |
| `--futures-memory` | unset | Memory hint for dynamic chunking. |
| `--futures-prefetch` | `1` | Input prefetch count. |
| `--futures-retries` | `0` | Retry count. |
| `--futures-retry-wait` | `5.0` | Seconds between retries. |

## DDR flags

These apply to TaskVine DDR mode.

| Flag | Default | Notes |
| --- | --- | --- |
| `--ddr-processor-key-delim` | `-` | Delimiter for processor key schema `<channel><delim><var><delim><application><delim><systematic_label>`. |
| `--ddr-output-schema {flat,tuple}` | `flat` | `flat` is canonical default; `tuple` preserves tuple-style output schema. |
| `--ddr-preserve-sidecars` | false | Preserve non-hist sidecars under reserved key during flattening. |
| `--ddr-sidecars-key` | `__sidecars__` | Reserved key for preserved sidecars. |
| `--ddr-step-size` | unset | Defaults to `--chunksize` when unset. |
| `--ddr-max-task-retries` | unset | DDR task retries. |
| `--ddr-results-directory` | unset | Override DDR results directory. |
| `--ddr-verbose` | unset | DDR-layer verbose toggle. |
| `--ddr-x509-proxy` | unset | Proxy source path; staged as `proxy.pem`. |
| `--ddr-preprocessed-data` | unset | Reuse preprocess mapping from disk and skip preprocess. |
| `--ddr-save-preprocess` | unset | Save preprocess mapping after preprocess step. |
| `--ddr-auto-save-preprocess` | true | Auto-save preprocess mapping when reuse is not requested. |
| `--ddr-preprocess-artifact` | unset | Override deterministic auto-save path target. |

## Output schema note

- TaskVine DDR serialized output defaults to flat canonical tuples:
  `(sample, channel, var, application, systematic_label)`.
- Futures/iterative outputs remain tuple-keyed:
  `(var, channel, application, sample, systematic)`.

See [schemas.md](schemas.md) for full schema contract and fail-fast policies.
