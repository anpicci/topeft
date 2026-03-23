# How to run an analysis workflow

This is the operator-facing guide for current Run-2 execution.

## Wrapper contract

`analysis/topeft_run2/full_run.sh` is strict options-only.

- Accepted: `--options <path[:profile]>`, `--help`
- Rejected: all other flags

Run all configuration from YAML options files.

## Standard TaskVine DDR run (recommended)

```bash
cd analysis/topeft_run2
./full_run.sh --options configs/fullR2_run.yml:sr
```

Recommended YAML defaults for production profiles:

- `executor: taskvine`
- `chunksize: 500000`
- `ddr_output_schema: flat`
- `produce_sidecars: false`

## Preprocess reuse pattern

Use YAML keys in the selected profile:

- `ddr_preprocessed_data: <path>` to reuse/skip preprocess
- `ddr_save_preprocess: <path>` to force save
- `ddr_auto_save_preprocess: true` for deterministic auto-save
- `ddr_preprocess_artifact: <path>` to override auto-save target

Default deterministic artifact target (when auto-save is active and no override
is set): `taskvine-results/ddr_preprocessed_data.json`.

## Proxy policy

Set `taskvine_proxy_path` in YAML.

- Workflow copies proxy to `proxy.pem` in TaskVine staging
- Worker env gets `X509_USER_PROXY=proxy.pem`

## Debug profiles

Keep separate YAML profiles for debug flows:

- Futures debug profile: `executor: futures`, limited `nchunks`
- Iterative smoke profile: `executor: iterative`, tiny chunks
- Plan-only profile: `pretend: true`

Invoke the same wrapper command with the chosen profile suffix.

## Equivalent CLI logging

`run_analysis.py` now logs an equivalent command without `--options` after
config resolution. This is informational only and helps auditing resolved values.

## Related references

- [Schema reference](schemas.md)
- [DDR preprocess/proxy policy](ddr_preprocess_proxy_policy.md)
- [Analysis processor data flow](analysis_processor_data_flow.md)
- [CLI reference](run_analysis_cli_reference.md)
