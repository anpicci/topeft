# Workflow Module Chain

This page shows the concrete module chain for Run-2 analysis execution and
where each step is implemented.

## Entry and Configuration

- Entrypoint: `analysis/topeft_run2/run_analysis.py`
- Config normalization and YAML merge: `analysis/topeft_run2/run_analysis_helpers.py`
- Shared executor argument wiring: `topeft/modules/executor_cli.py`

## Workflow Orchestration

- Main orchestrator: `analysis/topeft_run2/workflow.py`
  - planning (`ChannelPlanner`, `HistogramPlanner`)
  - executor setup (`ExecutorFactory`)
  - TaskVine handoff and DDR execution (`RunWorkflow._execute_ddr`)

## DDR and TaskVine Integration Points

- DDR helper call site (reference module): `topcoffea/modules/dynamic_data_reduction.py`
- TaskVine probe wrapper: `topeft/modules/taskvine_probe.py`
- TaskVine probe implementation (reference): `topcoffea/modules/taskvine_probe.py`

## Call-flow Diagram

```text
run_analysis.py
  -> build_parser()
  -> enforce_options_single_source()
  -> RunConfigBuilder.build()
  -> metadata_authority.load_metadata_bundle()
  -> workflow.run_workflow(config, metadata_bundle)
       -> RunWorkflow.run()
          -> SampleLoader.collect/load()
          -> ChannelPlanner + HistogramPlanner
          -> ExecutorFactory.create_runner() / taskvine_context()
          -> RunWorkflow._execute_ddr()  [taskvine executor path]
             -> topcoffea.modules.dynamic_data_reduction.build_ddr_data_from_flist()
             -> topcoffea.modules.dynamic_data_reduction.run_ddr()
             -> flatten_ddr_output() (default schema: flat)
          -> write histos/<outname>.pkl.gz
```

## Operational Notes

- `full_run.sh` is a strict options-first wrapper around `run_analysis.py`.
- TaskVine/DDR driver knobs are configured in YAML/CLI, not via env fallback.
- Worker auth proxy staging (`proxy.pem`) is handled in `workflow.py` during DDR setup.
