# TopEFT documentation map

Use this page as the canonical hub for `topeft` documentation. The repository
`README.md` is the landing page; this index is the organized map for newcomers,
operators, and maintainers.

## Start here

Follow this sequence if you are new to `topeft` or need the shortest path from
setup to a first successful run:

1. [Workflow and YAML hub](workflow_and_yaml_hub.md) – **Start here** for
   prerequisites, YAML merging, and executor choices.
2. [Run 2 quickstart pipeline](quickstart_run2.md) – Primary end-to-end Run-2
   walkthrough from environment setup to first plots.
3. [TaskVine workflow quickstart](taskvine_workflow.md) – Distributed execution
   path for analyst and operator workflows.
4. [Run analysis configuration flow](run_analysis_configuration.md) – Narrative
   workflow guide for CLI and YAML configuration.
5. [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md) –
   Flag-by-flag configuration reference.

If you are using the wrapper entrypoint directly, continue with
[How to run an analysis workflow](how_to_run_analysis_workflow.md).

## Workflow guides and reference

- [How to run an analysis workflow](how_to_run_analysis_workflow.md) –
  Options-first operator guide for `full_run.sh`.
- [Run analysis configuration flow](run_analysis_configuration.md) – Workflow
  guide to CLI/YAML merging and helper resolution.
- [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md) –
  Configuration reference for all main workflow flags.
- [TaskVine workflow quickstart](taskvine_workflow.md) – Distributed execution
  guide, including environment-packaging handoff.
- [Environment packaging](environment_packaging.md) – Maintainer and operator
  guide for the shared TaskVine tarball.
- [TaskVine/DDR knob reference](taskvine_ddr_knobs.md) – Canonical CLI and YAML
  knob list for manager, debug, proxy, probe, and exit-marker behavior.
- [DDR preprocess + proxy policy](ddr_preprocess_proxy_policy.md) – Current
  TaskVine defaults for proxy staging and preprocess artifacts.
- [Schema reference](schemas.md) – Canonical internal and output schema
  contracts.
- [DDR outputs and pickle structure](ddr_outputs_and_pkl.md) – Raw DDR payload,
  flattened schema, and final `.pkl.gz` layout.
- [Datacard fitting workflow](fitting.md) – Canonical handoff from histogram
  production to datacard generation and Combine setup.

## Metadata and scenario reference

- [Run configuration dataclasses and metadata overview](dataclasses_and_metadata.md)
  – How metadata and workflow options are stored in dataclasses.
- [Metadata channels and application structure](metadata_channels.md) – Channel
  group, application, and feature-flag conventions.
- [Channel group summary reference](channel_group_summary.md) – Expanded
  channel-group listings extracted from `analysis/metadata/metadata.yml`.
- [Run 2 metadata scenarios guide](run2_scenarios.md) – Scenario definitions,
  feature bundles, and validator pointers.
- [Sample metadata reference](sample_metadata_reference.md) – JSON manifest
  schema plus common troubleshooting pointers.

## Troubleshooting and validation

- [Sample metadata reference](sample_metadata_reference.md) – First stop for
  malformed manifests, missing metadata keys, and sample-bookkeeping issues.
- [Schema reference](schemas.md) – Check tuple ordering and schema expectations
  when serialized outputs do not match downstream consumers.
- [DDR outputs and pickle structure](ddr_outputs_and_pkl.md) – Inspect raw DDR
  sidecars and final pickle layout when output reconstruction looks wrong.
- [Environment packaging](environment_packaging.md) – Rebuild policy and tarball
  expectations for worker-environment drift.
- [Testing guide](developer/testing.md) – Canonical smoke-test and pytest entry
  points.

## Architecture

- [Workflow and processor reference](analysis_processing.md) – Medium-depth
  processor and workflow architecture overview.
- [Workflow module chain](workflow_module_chain.md) – Concrete call chain from
  `run_analysis.py` to TaskVine DDR helpers.
- [Analysis processor data flow](analysis_processor_data_flow.md) – Detailed
  `AnalysisProcessor` runtime flow from dataset context to accumulator output.
- [Tuple key audit](tuple_key_audit.md) – Five-tuple histogram-key conventions
  across the repository.

## Developer references

- [Parameters and calibration assets](developer/parameters.md) – Maintainer
  notes for `topeft/params/`.
- [Module notes](developer/modules.md) – Consolidated notes for
  `topeft/modules/`.
- [Testing guide](developer/testing.md) – Canonical pytest usage and TaskVine
  test notes.

## Legacy / archival

- [Run 2 legacy notes](run2_legacy_notes.md) – Curated historical and maintainer
  context for `analysis/topeft_run2/`.
- [TOP-22-006 script walkthrough](quickstart_top22_006.md) – Scenario-specific
  quickstart retained for historical reproduction context.
- [Run and plot quickstart](run_and_plot_quickstart.md) – Legacy plotting
  appendix with extra tips beyond the primary quickstart path.
- [Extreme events study notes](extreme_events_study.md) – Consolidated legacy
  notes for `analysis/extreme_events_study/`.
