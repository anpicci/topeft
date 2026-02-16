# Run 2 legacy notes

This page collects maintainers' legacy notes for `analysis/topeft_run2/` that
are still useful for debugging and repository archaeology. Canonical run
instructions and CLI/YAML behavior are documented elsewhere and are linked
below.

## Scope and status

- Use this page for historical context and maintainer-oriented caveats.
- Use [Workflow and YAML overview](workflow_and_yaml_hub.md) and
  [Run 2 quickstart pipeline](quickstart_run2.md) for current execution
  guidance.
- Use [Run analysis configuration flow](run_analysis_configuration.md) for
  canonical `run_analysis.py` recipe commands and CLI/YAML behavior.

## Legacy script families in `analysis/topeft_run2/` (index only)

The directory still contains historically important utility scripts:

- reference-regeneration helpers used around CI baselines,
- metadata/JSON preparation helpers (`make_jsons.py`, `make_skim_jsons.py`,
  `run_sow.py`, `update_json_sow.py`),
- plotting and yield-comparison scripts (`make_cr_and_sr_plots.py`,
  `get_yield_json.py`, `comp_yields.py`),
- datacard support scripts (`make_cards.py`, `datacards_post_processing.py`,
  `get_datacard_yields.py`).

Many of these utilities predate the current docs structure; treat script-level
README snippets as implementation history and keep usage recipes in canonical
docs pages.

## Metadata feature dependencies (maintainer summary)

The processor includes metadata-driven feature branches that are easy to miss
when reading only high-level run guides:

- `offz_split`: changes trilepton off-Z category masking and `ptz` handling.
- `requires_tau`: enables tau-specific object preparation, masks, and weights.
- `requires_forward`: enables forward-jet category masks and related fill rules.

These flags are declared by metadata channel groups and resolved during scenario
selection.

## Where to read the canonical behavior

- [Metadata channels and application structure](metadata_channels.md)
- [Run 2 scenarios, groups, and workflows](run2_scenarios.md)
- [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md)
- [Workflow and processor reference](analysis_processing.md)
