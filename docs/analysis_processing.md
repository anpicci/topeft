# Workflow and processor reference

This page summarizes workflow execution in `analysis/topeft_run2` at medium
depth. It focuses on how configuration, metadata authority, planners, and
executors connect. For processor internals and object-level runtime details,
use [analysis_processor_data_flow.md](analysis_processor_data_flow.md).

## Workflow execution overview

1. `run_analysis.py` parses CLI arguments and enforces options-only behavior.
When `--options <path[:profile]>` is provided, options YAML becomes the single
configuration source and conflicting CLI flags are rejected.

2. `RunConfigBuilder` builds a normalized `RunConfig`.
It merges YAML sections in this order: `defaults` -> selected `profiles`
entry -> top-level passthrough keys. Without `--options`, explicit CLI values
override parser defaults.

3. Metadata and scenario are resolved through the single authority:
`analysis/topeft_run2/metadata_authority.py`.
`metadata_authority.load_metadata_bundle(...)` validates the selected scenario
against canonical scenario definitions in
`analysis/metadata/run2_scenarios.yaml`, resolves metadata source/provenance,
and returns the bundle consumed by workflow planning.

4. `SampleLoader` expands input specs into concrete samples:
JSON files, CFG manifests, and directories are normalized into a `samplesdict`
plus filesets. Numeric metadata fields are coerced early so planning/execution
receive consistent types.

5. Planning creates the executable histogram task graph:
`ChannelPlanner` resolves scenario channel groups and feature tags from the
metadata bundle, `SystematicsHelper` derives the variation matrix, and
`HistogramPlanner` enumerates `(var, channel, application, sample, systematic)`
combinations. `summary_verbosity` controls how much of this plan is logged.

6. `ExecutorFactory` dispatches the plan:
`futures` and `iterative` execute local runner tasks; `taskvine` uses
Coffea Dynamic Data Reduction (DDR) manager/worker execution. TaskVine-specific
settings (ports, manager naming, staging, DDR preprocess artifacts, proxy
staging) are read from the same `RunConfig`.

7. Output serialization depends on executor path:
futures/iterative retain tuple-keyed processor outputs, while TaskVine DDR
defaults to the canonical flat schema. Sidecars are off by default and can be
preserved explicitly when flattening DDR output.

8. Pretend-mode behavior is intentionally lightweight:
with `pretend: true`, the workflow validates config + plan and exits before
task submission and output writing.

## Output schema at a glance

- Processor/planner internal keys: `(var, channel, application, sample, systematic)`
- TaskVine DDR default serialized keys:
  `(sample, channel, var, application, systematic_label)`
- Optional DDR tuple schema preserves tuple-style output for compatibility.

See [schemas.md](schemas.md) for the authoritative schema contract and failure
policies.

## Detailed references

- [Analysis processor data flow](analysis_processor_data_flow.md)
- [CLI and YAML reference](run_analysis_cli_reference.md)
- [DDR preprocess and proxy policy](ddr_preprocess_proxy_policy.md)
