[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.5258003.svg)](https://doi.org/10.5281/zenodo.5258002)
[![CI](https://github.com/TopEFT/topcoffea/actions/workflows/main.yml/badge.svg)](https://github.com/TopEFT/topeft/actions/workflows/main.yml)
[![Coffea-casa](https://img.shields.io/badge/launch-Coffea--casa-green)](https://cmsaf-jh.unl.edu/hub/spawn)
[![codecov](https://codecov.io/gh/TopEFT/topcoffea/branch/master/graph/badge.svg?token=U2DMI1C22F)](https://codecov.io/gh/TopEFT/topcoffea)

# topeft

`topeft` is the analysis and workflow repository for TopEFT Coffea-based runs.
If you are a newcomer, analyst, or day-to-day operator, this is the repository
to start with.

`topeft` builds on the shared `topcoffea` library for corrections, executors,
and common utilities. If you need shared-library internals, corrections logic,
or cross-repository compatibility guidance, use the
[`topcoffea` docs hub](https://github.com/TopEFT/topcoffea/blob/main/docs/index.md)
and
[`topcoffea/docs/topeft_integration.md`](https://github.com/TopEFT/topcoffea/blob/main/docs/topeft_integration.md).

## Start here

`docs/index.md` is the canonical documentation hub for this repository. For a
newcomer, follow this path:

1. [Workflow and YAML hub](docs/workflow_and_yaml_hub.md)
2. [Run 2 quickstart pipeline](docs/quickstart_run2.md)
3. [TaskVine workflow quickstart](docs/taskvine_workflow.md) for distributed
   execution, or [How to run an analysis workflow](docs/how_to_run_analysis_workflow.md)
   for the wrapper entrypoint
4. [Run analysis configuration flow](docs/run_analysis_configuration.md) when
   you need to tune YAML or CLI behavior
5. [`run_analysis.py` CLI and YAML reference](docs/run_analysis_cli_reference.md)

## Choose your next guide

- First run / newcomer: [Workflow and YAML hub](docs/workflow_and_yaml_hub.md)
  and [Run 2 quickstart pipeline](docs/quickstart_run2.md)
- Distributed execution / TaskVine: [TaskVine workflow quickstart](docs/taskvine_workflow.md)
  and [Environment packaging](docs/environment_packaging.md)
- Wrapper-driven execution: [How to run an analysis workflow](docs/how_to_run_analysis_workflow.md)
- Configuration and workflow knobs: [Run analysis configuration flow](docs/run_analysis_configuration.md)
  and [`run_analysis.py` CLI and YAML reference](docs/run_analysis_cli_reference.md)
- Troubleshooting outputs, metadata, or schemas:
  [Run analysis configuration flow](docs/run_analysis_configuration.md#troubleshooting-checklist),
  [Sample metadata reference](docs/sample_metadata_reference.md), and
  [DDR outputs and pickle structure](docs/ddr_outputs_and_pkl.md)
- Architecture / maintainer context: [Workflow and processor reference](docs/analysis_processing.md)
  and [Workflow module chain](docs/workflow_module_chain.md)
- Developer verification: [Testing guide](docs/developer/testing.md)
- Legacy / archival context: [Run 2 legacy notes](docs/run2_legacy_notes.md),
  [TOP-22-006 script walkthrough](docs/quickstart_top22_006.md), and
  [Run and plot quickstart](docs/run_and_plot_quickstart.md). These are not
  part of the primary newcomer path.

## Documentation map

Use [docs/index.md](docs/index.md) as the authoritative docs map. The README is
intentionally a landing page; detailed workflow, metadata, configuration,
Troubleshooting, and archival material lives in the docs pages linked above.

## Testing and contributing

Testing instructions are centralized in
[docs/developer/testing.md](docs/developer/testing.md). For code changes, keep
the `topeft` and `topcoffea` refs aligned, run the documented verification
steps, and open a PR against the coordinated branch you are working on.
