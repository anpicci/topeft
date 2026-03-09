# `run_analysis.py` CLI and YAML reference

This page is the authoritative CLI and options-YAML mapping for
`analysis/topeft_run2/run_analysis.py`.

The single metadata/scenario authority is
`analysis/topeft_run2/metadata_authority.py`, with canonical scenario
definitions in `analysis/metadata/run2_scenarios.yaml`.

## Options exclusivity rule

When `--options <path[:profile]>` is present, options YAML is the single source
of truth.

- Allowed with `--options`: `--help` and `--version` (only if the parser
  exposes `--version`).
- Disallowed with `--options`: all other config flags, including `--metadata`,
  `--executor`, `--chunksize`, `--scenario`, `--pretend`, etc.
- Wrapper note: `analysis/topeft_run2/full_run.sh` is stricter and accepts only
  `--options` and `--help`.

## CLI to YAML mapping

| CLI flag(s) | YAML key(s) | Type after coercion | Default | Notes |
| --- | --- | --- | --- | --- |
| `jsonFiles` (positional) | `jsonFiles` | list of strings | `[]` | Accepts one path, comma-separated string, or YAML list. |
| `--options` | n/a (selector) | `path[:profile]` string | unset | Selects options file/profile. Not a `RunConfig` value by itself. |
| `--prefix`, `-r` | `prefix` | string | `""` | Prefix/redirector applied during sample loading. |
| `--executor`, `-x` | `executor` | string | `taskvine` | Supported: `taskvine`, `futures`, `iterative`. |
| `--test`, `-t` | `test` | bool | `false` | Fast smoke mode; only local executors support this path. |
| `--pretend` | `pretend` | bool | `false` | Validates configuration and histogram plan, then exits before execution/output write. |
| `--nworkers`, `-n` | `nworkers` | int | `8` | Worker count used by workflow execution paths (registered by shared `ExecutorCLIHelper`). |
| `--chunksize`, `-s` | `chunksize` | int | `500000` | Events per chunk. |
| `--nchunks`, `-c` | `nchunks` | optional int | `None` | Maximum number of chunks to process. |
| `--outname`, `-o` | `outname` | string | `plotsTopEFT` | Output filename stem. |
| `--outpath`, `-p` | `outpath` | string | `histos` | Output directory. |
| `--treename` | `treename` | string | `Events` | Input tree name. |
| `--metadata` | `metadata` | optional string | `None` | CLI metadata path. Use `analysis/metadata/metadata.yml` for the standard bundle. Relative paths are repo-root-relative and may not resolve outside the repo root; absolute paths remain allowed. Forbidden when `--options` is supplied. |
| `--scenario` (repeatable) | `scenarios` | list of strings | `TOP_22_006` when unset | Scenario names resolved through `metadata_authority`. |
| `--allow-partial-channel-groups` | `allow_partial_channel_groups` | bool | `false` | When true, missing scenario channel groups do not fail run construction. |
| `--skip-sr` | `skip_sr` | bool | `false` | Skip signal-region channels. |
| `--skip-cr` | `skip_cr` | bool | `false` | Skip control-region channels. |
| `--do-errors` | `do_errors` | bool | `false` | Save squared-weight coefficients. |
| `--do-systs` | `do_systs` | bool | `false` | Enable systematic variations. |
| `--split-lep-flavor` | `split_lep_flavor` | bool | `false` | Split channels by lepton flavor where configured. |
| `--summary-verbosity` | `summary_verbosity` | enum (`none`, `brief`, `full`) | `brief` | Controls pre-execution histogram summary detail. |
| `--log-level` | `log_level` | optional enum (`none`, `info`, `warning`, `error`, `debug`) | `None` (effective `INFO`) | Driver-process logging level. |
| `--log-tasks` | `log_tasks` | bool | `false` | Emit one-line task submission logs (futures path). |
| `--wc-list` | `wc_list` | list of strings | `[]` | Wilson coefficients to evaluate; duplicates removed preserving order. |
| `--ecut` | `ecut` | optional float | `None` | Event-level energy cut (GeV). |
| `--do-np` | `do_np` | bool | `false` | Run nonprompt estimation post-processing. |
| `--do-renormfact-envelope` | `do_renormfact_envelope` | bool | `false` | Requires `do_np` and `do_systs`. |
| `--port` | `port` | string | `9123-9130` | TaskVine manager port/range. |
| `--no-port-negotiation` | `negotiate_manager_port` | bool | negotiation enabled (`true`) | Flag disables fallback port negotiation. |
| `--taskvine-manager-name` | `taskvine_manager_name` | optional string | `None` | Explicit TaskVine manager/project name. |
| `--taskvine-manager-name-template` | `taskvine_manager_name_template` | optional string | `None` | Template with `{pid}` support for per-run materialization. |
| `--scratch-dir` | `scratch_dir` | optional string | `None` | Shared staging directory for distributed execution. |
| `--resource-monitor` | `resource_monitor` | optional string | `measure` | TaskVine resource monitor mode. |
| `--resources-mode` | `resources_mode` | optional string | `auto` | TaskVine resource mode. |
| `--environment-file` | `environment_file` | optional string | unset | Remote environment tarball selection (`cached`, `auto`, `none`, or path). For `executor=taskvine`, when this value is unset/empty the driver auto-builds a tarball and logs the resulting path before workflow launch. |
| `--no-environment-file` | `environment_file` | optional string | n/a | Alias for `--environment-file none`. Invalid with `executor=taskvine` in `run_analysis.py`. |
| `--taskvine-print-stdout`, `--no-taskvine-print-stdout` | `taskvine_print_stdout` | bool | `true` | Forward worker stdout to manager logs. |
| `--futures-status`, `--no-futures-status` | `futures_status` | optional bool | `None` | Toggle futures progress status output. |
| `--futures-tail-timeout` | `futures_tail_timeout` | optional int | `None` | Timeout for stalled futures tasks. |
| `--futures-memory` | `futures_memory` | optional int | `None` | Memory hint used by futures path. |
| `--futures-prefetch` | `futures_prefetch` | optional int | `1` | Number of files prefetched by futures path (`0` disables). |
| `--futures-retries` | `futures_retries` | int | `0` | Retries per futures task before abort. |
| `--futures-retry-wait` | `futures_retry_wait` | float | `5.0` | Seconds between futures retries. |
| `--produce-sidecars`, `--no-produce-sidecars` | `produce_sidecars` | bool | `false` | Include sidecar payloads in processor outputs. |
| `--ddr-processor-key-delim` | `ddr_processor_key_delim` | string | `-` | Delimiter for DDR-generated key labels. |
| `--ddr-output-schema` | `ddr_output_schema` | enum (`flat`, `tuple`) | `flat` | `flat` is canonical default for TaskVine DDR serialized output. |
| `--ddr-preserve-sidecars`, `--no-ddr-preserve-sidecars` | `ddr_preserve_sidecars` | bool | `false` | Preserve sidecars when flattening DDR output. |
| `--ddr-sidecars-key` | `ddr_sidecars_key` | string | `__sidecars__` | Reserved top-level key for preserved sidecars. |
| `--ddr-step-size` | `ddr_step_size` | optional int | `None` | Defaults to `chunksize` when unset. |
| `--ddr-max-task-retries` | `ddr_max_task_retries` | optional int | `None` | Maximum DDR task retries. |
| `--ddr-results-directory` | `ddr_results_directory` | optional string | `None` | Override DDR results directory path. |
| `--ddr-verbose`, `--no-ddr-verbose` | `ddr_verbose` | optional bool | `None` | DDR-layer verbose logging toggle. |
| `--taskvine-proxy-path` | `taskvine_proxy_path` | optional string | `None` | Proxy source path; staged as `proxy.pem` for workers. |
| `--ddr-preprocessed-data` | `ddr_preprocessed_data` | optional string | `None` | Reuse preprocess artifact and skip preprocess step. |
| `--ddr-save-preprocess` | `ddr_save_preprocess` | optional string | `None` | Save preprocess artifact after preprocess step. |
| `--ddr-auto-save-preprocess`, `--no-ddr-auto-save-preprocess` | `ddr_auto_save_preprocess` | bool | `true` | Auto-save preprocess artifact when reuse is not requested. |
| `--ddr-preprocess-artifact` | `ddr_preprocess_artifact` | optional string | `None` | Override deterministic auto-save preprocess path. |

## YAML-only helper keys

These keys control options-file composition and do not correspond to CLI flags.

| YAML key | Type | Default | Notes |
| --- | --- | --- | --- |
| `defaults` | mapping | `{}` | Applied first. |
| `profiles` | mapping of mappings | `{}` | Named overlays selected by `path.yml:profile`. |
| `default_profile` | optional string | `None` | Used when profile suffix is omitted. |

Additional YAML-only advanced runtime keys are accepted by `RunConfigBuilder`
for DDR internals (for example `ddr_resources_processing`,
`ddr_environment_variables`, `ddr_preprocess_kwargs`, `ddr_kwargs`) when a
profile needs settings that are intentionally not exposed as top-level CLI
switches.

## TaskVine `environment_file` auto-build policy

When `executor=taskvine` and `environment_file` resolves to an unset/empty
value, `run_analysis.py` now follows one deterministic path:

1. Log: `TaskVine environment_file not set; building environment tarball...`
2. Build via the canonical `topeft.modules.remote_environment` helper.
3. Log: `Built environment tarball at: <path>`
4. Continue the run with `config.environment_file` set to that path.

When `executor=taskvine`, explicit `environment_file=none` (including
`--no-environment-file`) is rejected with exit code `2`. TaskVine workers
require a Python environment tarball.

For reproducibility across repeated runs, explicitly setting
`environment_file` in CLI or YAML remains recommended.
