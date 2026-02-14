# TopEFT documentation map

Use this map to navigate the documentation tracks introduced during the docs
reorganisation. Each section highlights the current source of truth for that
topic so newcomers can follow a single path instead of bouncing between
overlapping quickstarts.

## Landing & quickstart

- [Workflow and YAML hub](workflow_and_yaml_hub.md) – **Start here** for
  prerequisites, YAML merging, and executor choices.
- [Run 2 quickstart pipeline](quickstart_run2.md) – Primary end-to-end Run‑2
  walkthrough (environment → run → plot).
- [Run and plot quickstart](run_and_plot_quickstart.md) – Legacy plotting
  appendix with extra tips beyond the main quickstart.
- [TOP-22-006 script walkthrough](quickstart_top22_006.md) – Scenario-specific
  quickstart extending the Run‑2 presets.

## Running analyses

- [Run analysis configuration flow](run_analysis_configuration.md) – Narrative
  walkthrough of CLI/YAML merging and workflow helpers.
- [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md) –
  Flag-by-flag lookup table.
- [TaskVine workflow quickstart](taskvine_workflow.md) – Distributed executor
  focus, including environment packaging pointers.
- [Datacard fitting workflow](fitting.md) – Canonical handoff from histogram
  production to datacard generation and Combine setup.
- [Environment packaging](environment_packaging.md) – Maintaining the shared
  TaskVine tarball.

## Metadata & scenarios

- [Run configuration dataclasses and metadata overview](dataclasses_and_metadata.md)
  – How metadata is stored in dataclasses.
- [Metadata channels and application structure](metadata_channels.md) – Channel
  group/application conventions and feature-flag mapping.
- [Channel group summary reference](channel_group_summary.md) – Expanded
  channel-group listings extracted from `analysis/metadata/metadata.yml`.
- [Run 2 metadata scenarios guide](run2_scenarios.md) – Scenario/feature
  definitions and validator pointers.
- [Sample metadata reference](sample_metadata_reference.md) – JSON manifest
  schema and troubleshooting tips.

## Developer references

- [Parameters and calibration assets](developer/parameters.md) – Maintainer
  notes for `topeft/params/`.
- [Module notes](developer/modules.md) – Consolidated notes for
  `topeft/modules/`.
- [Testing guide](developer/testing.md) – Canonical pytest usage and TaskVine
  test notes.

## Architecture & internals

- [Workflow and processor reference](analysis_processing.md) – Processor ↔
  workflow architecture and execution flow.
- [Tuple key audit](tuple_key_audit.md) – 5‑tuple conventions for histogram
  keys across the repository.
- [Run 2 legacy notes](run2_legacy_notes.md) – Maintainer-focused legacy
  context for `analysis/topeft_run2/`.

## Legacy / archival

- [Run 2 legacy notes](run2_legacy_notes.md) – Curated legacy/internal notes
  consolidated from historical `analysis/topeft_run2` docs.
- [Extreme events study notes](extreme_events_study.md) – Consolidated legacy
  notes for `analysis/extreme_events_study/`.
