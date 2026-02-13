# Metadata channels and application structure

This page is the canonical reference for how Run 2 channel metadata is
organized in `topeft`. It focuses on channel-group structure, application tags,
and feature flags. For full scenario definitions and CLI behavior, see the
linked docs below.

## Source of truth

Run 2 channel definitions live in:

- `analysis/metadata/metadata.yml` under `channels.groups`
- `analysis/metadata/run2_scenarios.yaml` for scenario-to-group mapping

Workflow entry points resolve scenarios through metadata authority helpers, then
expand groups into concrete channel/application selections.

## Channel-group model

Each `channels.groups` entry packages:

- region/channel names to evaluate,
- application tags (for example SR/CR usage on data vs MC),
- optional histogram include/exclude lists via `histogram_variables`,
- optional feature flags consumed by processor logic.

This allows one metadata object to define both "what channels run" and "how
those channels should be interpreted during scheduling and histogram filling."

## Application structure

Application tags are metadata-level labels that determine where a channel is
used in workflow planning (for example, signal/control usage and data-vs-MC
partitioning). The planner layer keeps these tags alongside each channel so
histogram scheduling and downstream summaries stay aligned with the selected
scenario.

## Feature flags used by Run 2 channels

Run 2 channel groups may declare feature tags used by processor-side logic:

- `offz_split`: enables split trilepton off-Z categories.
- `requires_tau`: enables tau-enriched object, weight, and category behavior.
- `requires_forward`: enables forward-jet category handling.
- `requires_central`: marks central-jet requirements for specific split groups.

Detailed processor effects are documented in [Run 2 legacy notes](run2_legacy_notes.md).

## Related canonical docs

- [Run configuration dataclasses and metadata overview](dataclasses_and_metadata.md)
- [Run 2 scenarios, groups, and workflows](run2_scenarios.md)
- [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md)
- [Workflow and YAML overview](workflow_and_yaml_hub.md)
