# Workflow and YAML hub

> Start here for Run-2 execution. This page documents the options-first wrapper
> flow, TaskVine DDR defaults, and where to find detailed schema/reference docs.

## Recommended execution model

`analysis/topeft_run2/full_run.sh` is now a strict options-only wrapper:

- Accepted flags: `--options <path[:profile]>` and `--help`.
- All run configuration (executor, samples, scenario, chunksize, DDR knobs,
  sidecars, proxy/preprocess settings) must live in YAML.
- TaskVine + DDR is the recommended production profile.

Example launches:

```bash
cd analysis/topeft_run2
./full_run.sh --options configs/fullR2_run.yml:sr
./full_run.sh --options configs/fullR2_run.yml
```

When no profile suffix is provided, `RunConfigBuilder` resolves the profile from
YAML (`default_profile` or single-profile fallback).

## Single authority for scenarios and metadata

Run-2 scenario resolution is centralized in
`analysis/topeft_run2/metadata_authority.py`.

- Canonical scenario map:
  `analysis/metadata/run2_scenarios.yaml`
- Canonical metadata bundle entrypoint:
  `metadata_authority.load_metadata_bundle(...)`

Use YAML `scenarios:` entries for wrapper runs. Do not depend on wrapper-side
scenario logic.

## YAML guidance

`--options` is the single configuration source when supplied.

- `defaults`: baseline values.
- `profiles`: named overlays selected with `path.yml:profile`.
- top-level keys: final overrides.

Recommended production defaults in YAML:

- `executor: taskvine`
- `chunksize: 500000`
- `ddr_output_schema: flat`
- `produce_sidecars: false`

For debug profiles, set `executor: futures` or `executor: iterative` in YAML.

## DDR defaults and policies

TaskVine DDR defaults in the current workflow:

- Flat canonical output schema for serialized DDR results.
- Strict flatten validation: processor-key fields must match histogram tuple
  fields; mismatches fail fast.
- Duplicate flattened keys fail fast with origin diagnostics.
- Delimiter-safe DDR processor keys with collision checks.
- Deterministic preprocess artifact default:
  `taskvine-results/ddr_preprocessed_data.json`.
- Proxy staging policy: copy configured proxy to `proxy.pem` and set
  `X509_USER_PROXY=proxy.pem` for worker jobs.

See:

- [Schema reference](schemas.md)
- [DDR preprocess/proxy policy](ddr_preprocess_proxy_policy.md)
- [CLI reference](run_analysis_cli_reference.md)

## Where to go next

- [How to run an analysis workflow](how_to_run_analysis_workflow.md)
- [Run 2 quickstart pipeline](quickstart_run2.md)
- [TaskVine workflow quickstart](taskvine_workflow.md)
- [Analysis processor data flow](analysis_processor_data_flow.md)
