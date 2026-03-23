# TaskVine and DDR Driver Knobs

This page documents the TaskVine/DDR driver knobs that were promoted from
ad-hoc environment variables to first-class `run_analysis.py` configuration.

## Rules

- No environment-variable fallback exists for the knobs in this document.
- Use either YAML (`--options`) or CLI flags for these knobs.
- Do not mix `--options` with conflicting CLI flags.
- `analysis/topeft_run2/full_run.sh` remains options-only for normal runs.
- In `fullR2_run.yml`, use `cr` for normal CR runs and `cr_smoke` for
  smoke/probe launches.

## Knob Reference

| CLI flag | YAML key | Default | Effect |
| --- | --- | --- | --- |
| `--taskvine-manager-name` | `taskvine_manager_name` | unset | Overrides TaskVine manager/project name. |
| `--taskvine-manager-name-template` | `taskvine_manager_name_template` | auto (`<manager>-{pid}`) when manager is set | Controls manager-name materialization per run (supports `{pid}`). |
| `--taskvine-proxy-path` | `taskvine_proxy_path` | unset | Stages proxy as `proxy.pem` and sets worker `X509_USER_PROXY=proxy.pem`. |
| `--ddr-debug` / `--no-ddr-debug` | `ddr_debug` | `false` | Enables deterministic DDR debug markers in workflow logs. |
| `--ddr-worker-probe-enabled` / `--no-ddr-worker-probe-enabled` | `ddr_worker_probe_enabled` | `false` | Runs worker-side cert/xrootd probe before DDR preprocess. |
| `--ddr-worker-probe-url` | `ddr_worker_probe_url` | built-in test URL | ROOT URL used by the worker probe task. |
| `--ddr-worker-probe-timeout` | `ddr_worker_probe_timeout` | `20` | Worker probe timeout (seconds). |
| `--driver-log-path` | `driver_log_path` | unset | Mirrors driver stdout/stderr into a logfile. |
| `--exit-marker-path` | `exit_marker_path` | unset | Writes final driver exit code to a marker file. |
| `--exit-debug` / `--no-exit-debug` | `exit_debug` | `false` | Emits final `driver_status=<code>` line to stderr. |

## Manager Name vs Template

- `taskvine_manager_name` / `--taskvine-manager-name`:
  sets the base TaskVine project/manager name (for example
  `apiccine-taskvine-proxydebug9-std-fullrun`).
- `taskvine_manager_name_template` / `--taskvine-manager-name-template`:
  controls how that base is materialized per run. The template can include
  placeholders like `{pid}` to avoid collisions across concurrent runs.

Typical behavior:

- Name only: manager template defaults to `<name>-{pid}`.
- Name + template: template wins and controls final manager identity.

## YAML-only Example (recommended with `full_run.sh`)

```yaml
# analysis/topeft_run2/configs/fullR2_run.yml
profiles:
  cr_smoke:
    executor: taskvine
    taskvine_manager_name: apiccine-taskvine-proxydebug
    taskvine_proxy_path: /tmp/x509up_u241575
    ddr_debug: true
    ddr_worker_probe_enabled: true
    ddr_worker_probe_url: root://cmsxrootd.crc.nd.edu//store/user/.../output_157.root
    ddr_worker_probe_timeout: 30
    driver_log_path: /users/apiccine/work/ChUpdate/reports/proxydebug.log
    exit_marker_path: /users/apiccine/work/ChUpdate/reports/proxydebug.exit
    exit_debug: true
```

Run:

```bash
./analysis/topeft_run2/full_run.sh --options analysis/topeft_run2/configs/fullR2_run.yml:cr_smoke
```

## CLI-only Example (`run_analysis.py` without `--options`)

```bash
python analysis/topeft_run2/run_analysis.py \
  ../../input_samples/cfgs/mc_background_samples_NDSkim_loc.cfg \
  --executor taskvine \
  --taskvine-manager-name apiccine-taskvine-proxydebug \
  --taskvine-proxy-path /tmp/x509up_u241575 \
  --ddr-debug \
  --ddr-worker-probe-enabled \
  --ddr-worker-probe-timeout 30 \
  --driver-log-path /users/apiccine/work/ChUpdate/reports/proxydebug_cli.log \
  --exit-marker-path /users/apiccine/work/ChUpdate/reports/proxydebug_cli.exit \
  --exit-debug \
  --metadata analysis/metadata/metadata.yml \
  --scenario TOP_22_006
```

## Explicit Non-mixing Rule

Invalid (hard error):

```bash
python analysis/topeft_run2/run_analysis.py \
  --options analysis/topeft_run2/configs/fullR2_run.yml:cr_smoke \
  --ddr-debug
```

Use either:
- YAML-only (`--options ...`), or
- CLI-only (no `--options`).

## Exit-Code Policy

`run_analysis.py` uses this explicit policy:

- `0`: workflow completed and output write succeeded.
- `2`: argument/config/options errors (argparse errors, YAML parse/validation
  errors, and options/CLI conflict errors).
- `130`: `KeyboardInterrupt`.
- `1`: all other runtime failures.

`exit_marker_path` writes the selected code when configured, and `exit_debug`
emits `driver_status=<code>` on stderr. Runtime failures are not swallowed, so
their full Python stacktraces remain visible.
