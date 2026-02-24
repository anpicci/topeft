# Workflow and processor reference

This page summarizes execution flow for `analysis/topeft_run2` and points to
stable references for schema and data-flow details.

## End-to-end flow

1. `run_analysis.py` builds `RunConfig` from CLI/YAML.
2. `metadata_authority.load_metadata_bundle(...)` resolves metadata/scenario.
3. `SampleLoader` expands JSON/CFG inputs into `samplesdict` and filesets.
4. `ChannelPlanner` and `HistogramPlanner` build histogram tasks.
5. `ExecutorFactory` dispatches tasks through `futures`, `iterative`, or
   TaskVine DDR.
6. `AnalysisProcessor` applies selections/systematics and fills histograms.

## Internal keying vs serialized output

Inside planning/processor code, histogram keys remain 5-tuples:

- `(var, channel, application, sample, systematic)`

Serialized output depends on executor path:

- TaskVine DDR default serialization: flat canonical tuples
  `(sample, channel, var, application, systematic_label)`
- Futures/iterative serialization: tuple keys as filled by processor

See [schemas.md](schemas.md) for the canonical contract.

## Sidecars

Sidecar payloads are default-off (`produce_sidecars: false`).

- Enable creation with `produce_sidecars: true`.
- Preserve sidecars in flattened DDR output with
  `ddr_preserve_sidecars: true` and optional `ddr_sidecars_key`.

## Where detailed internals live

- [Analysis processor data flow](analysis_processor_data_flow.md)
- [DDR preprocess + proxy policy](ddr_preprocess_proxy_policy.md)
- [CLI reference](run_analysis_cli_reference.md)
