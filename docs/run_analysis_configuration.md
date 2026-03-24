# Run analysis configuration flow

This is the detailed configuration and troubleshooting guide for
``analysis/topeft_run2/run_analysis.py``. The entry point stitches together the
command line, metadata bundles, and Coffea execution helpers that drive the Run
2 analysis. This page documents how the configuration is normalized, how the
helpers cooperate, and which extension points are available when adapting the
workflow to new samples or channels. Readers looking for a catalog of the
dataclasses and metadata payloads that emerge from this process should start
with the [Run configuration dataclasses and metadata overview](dataclasses_and_metadata.md).

If you only need a quick lookup of supported CLI flags and YAML keys, jump to
the dedicated [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md).
If this is your first pass through the workflow, start instead with
[workflow_and_yaml_hub.md](workflow_and_yaml_hub.md) and
[quickstart_run2.md](quickstart_run2.md), then return here when you need to
tune behavior or debug configuration issues. If you specifically need the
wrapper/operator recipe, use
[how_to_run_analysis_workflow.md](how_to_run_analysis_workflow.md).

## Invocation quick reference

`run_analysis` is not installed as a standalone shell command in this workflow.
Use Python to launch `run_analysis.py`:

```bash
# from repo root
"$PYTHON_ENV" analysis/topeft_run2/run_analysis.py --help
```

```bash
# from analysis/topeft_run2
cd analysis/topeft_run2
"$PYTHON_ENV" run_analysis.py --help
```

For YAML-driven runs, keep execution options in `--options path.yml[:profile]`
only; CLI-only runs should omit `--options` and pass flags directly.

The guide follows the same YAML-first workflow presented in the quickstart
examples (``docs/quickstart_run2.md`` and ``docs/quickstart_top22_006.md``).  The
YAML options file is optional, but using it keeps custom runs reproducible and
makes it easy to share presets with collaborators.

## Metadata configuration {#metadata-configuration}

The workflow resolves all region, variable, and systematic choices from
``analysis/metadata/metadata.yml`` before it touches the Coffea executors.  The file
is packaged with the module so that quickstarts, CLI runs, and YAML-driven
profiles all agree on the same catalogue of tasks.  The table below summarises
the metadata sections that feed directly into the planners:

For standard runs, use ``analysis/metadata/metadata.yml`` exactly as written.
Relative ``--metadata`` values (and YAML ``metadata`` keys) are resolved from
the repository root, not from the current working directory. Paths that resolve
outside the ``topeft`` repo root via ``..`` are rejected; use the canonical
repo-root-relative path above or pass an absolute path when you really intend to
load a different file.

| Metadata key | Controls | Processor impact |
| --- | --- | --- |
| ``channels.groups[].regions`` | Channel labels, subchannels, jet bins, tags, and application assignments. | Guides `ChannelPlanner` when enumerating signal/control regions and annotating each Coffea task. |
| ``channels.groups[].histogram_variables`` | Per-region include/exclude rules for histogram names. | Filters the `HistogramPlanner` combinations so only approved variables are scheduled. |
| ``variables`` | Histogram axis definitions, binning, and callable expressions. | Becomes the histogram catalogue consumed by `AnalysisProcessor`. |
| ``scenarios`` | Friendly scenario names mapped to channel groups. | Powers the ``--scenario`` CLI flag and YAML ``scenarios`` lists. |
| ``systematics`` | Weight, object, and theory variations (with optional year or feature guards). | Supplies `weight_variations_from_metadata(...)` and the systematic helper with the variations to evaluate when ``do_systs`` is enabled. |
| ``golden_jsons`` | Year-indexed data-quality JSON files. | Enables automated golden JSON lookups when running over data samples. |

When customising an analysis, clone the file rather than editing the baseline in
place.  A common workflow is:

1. Copy ``analysis/metadata/metadata.yml`` to ``analysis/topeft_run2/configs/metadata_<tag>.yml`` (or another tracked location).
2. Update the cloned YAML with any new regions, variables, or systematics.
3. Point ``python -m topeft.quickstart`` at the clone with ``--metadata`` to test
   the changes quickly.  For ``run_analysis.py`` runs, set ``metadata:
   configs/metadata_<tag>.yml`` (or similar) inside the YAML profile you launch
   with ``--options`` so the override stays version-controlled while the CLI
   continues to rely on the scenario registry for standard runs.

The quickstart and scenario guides link back to this section so that anyone
tweaking the Run 2 configuration knows where each dial is sourced.

## Overview of the configuration pipeline

``run_analysis.py`` executes the steps below when launched from the repository
root:

    python analysis/topeft_run2/run_analysis.py \
        input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json \
        --options analysis/topeft_run2/configs/fullR2_run.yml:sr

1. **Argument parsing** – `analysis.topeft_run2.run_analysis.build_parser(...)`
   defines the CLI options that downstream helpers understand.  The parser keeps
   backwards compatibility with the historical ``jsonFiles`` positional argument
   while advertising the YAML-driven ``--options`` knob, which accepts either
   ``path.yml`` or ``path.yml:profile`` when you need a specific preset.
2. **YAML overrides** – `analysis.topeft_run2.run_analysis_helpers.RunConfigBuilder`
   reads the options file (if provided) before evaluating CLI values.  The YAML
   supports three blocks:

   * ``defaults`` – baseline values that are always applied.
   * ``profiles`` – named overlays that can be enabled via ``path.yml:profile``
     or automatically when only one profile exists.
   * Top-level keys – additional overrides that do not fit in the two sections
     above.  They are merged last so that ad-hoc experiments can live next to
     reusable defaults.

   When an options file is supplied, the YAML becomes the single source of truth.
   Drop ``--options`` if you need to experiment with ad-hoc CLI flags; otherwise
   bake the desired configuration into the file before launching the workflow.
   ``--metadata`` is mutually exclusive with ``--options`` and must be provided
   inside the YAML when needed.

   !!! note "CLI vs YAML precedence"
       ``--options`` tells ``RunConfigBuilder`` to merge ``defaults``, the selected
       profile, and any top-level keys before reading CLI values. When ``--options``
       is present, other CLI flags are rejected to keep the run reproducible, so
       *all* configuration (including executor choice and workload knobs) must be
       encoded in the YAML. ``full_run.sh`` applies the same guard when it selects
       the Run‑2 presets on your behalf.

3. **Configuration normalization** – the builder converts all inputs into a
   `analysis.topeft_run2.run_analysis_helpers.RunConfig` dataclass.  The
   dataclass mirrors the traditional CLI options but guarantees consistent types
   (lists instead of comma separated strings, ``None`` for unset values, etc.).
4. **Sample discovery** – `analysis.topeft_run2.run_analysis_helpers.SampleLoader`
   expands positional inputs into concrete JSON files, parsing ``.cfg`` bundles
   and directories when necessary.  The loader attaches redirectors, validates
   files, and normalizes numeric metadata.  See the
   [sample metadata reference](sample_metadata_reference.md) for a manifest
   checklist and troubleshooting advice tailored to this stage.
5. **Metadata planning** – `analysis.topeft_run2.workflow.ChannelPlanner`
   and `analysis.topeft_run2.workflow.HistogramPlanner` translate the
   selected metadata scenarios and variable definitions into the list of
   histogram tasks.  This is where ``--scenario``, ``--skip-sr`` and similar
   knobs take effect.
6. **Execution** – `analysis.topeft_run2.workflow.ExecutorFactory`
   instantiates the selected backend (``futures``, ``iterative`` or
   ``taskvine``).  Each histogram task yields an
   `analysis.topeft_run2.analysis_processor.AnalysisProcessor` instance
   configured for the corresponding sample and channel.  Progress is summarized
   according to ``summary_verbosity``—``"brief"`` prints bullet lists of the
   unique samples, channel/application pairs, variables, and systematics that
   will be processed, while ``"full"`` prepends the same lists to the
   combination table and structured dump (including a reminder when
   ``split_lep_flavor`` is active).  These details are optionally mirrored in
   the single-line ``log_tasks`` messages.

The helpers are designed so that the resulting `RunConfig` can be stored
or passed around.  For example, the quickstart workflow returns the configuration
it used so that you can plug the same object into `run_workflow(...)` later.

## CLI highlights

While the dedicated [`run_analysis.py` CLI reference](run_analysis_cli_reference.md)
lists every flag in detail (path and default values, grouped by category), the
most important Run‑2 knobs are summarised below:

When `--options` is supplied, these CLI flags must be encoded in the YAML file;
the parser rejects them to preserve reproducibility.

* **Scenario selection** – Use `--scenario NAME` to enable a metadata scenario
  (for example `TOP_22_006`). Repeat the flag to combine scenarios. When a YAML
  profile is supplied via `--options path.yml[:profile]`, the profile becomes
  authoritative and `--scenario` must be encoded inside the YAML. The CLI
  enforces the mutual exclusion rule so that misconfigured runs fail fast.
* **YAML profiles (`--options`)** – Apply reusable presets such as
  `analysis/topeft_run2/configs/fullR2_run.yml:sr`. `RunConfigBuilder` merges
  `defaults`, the selected profile, then any top‑level overrides. When
  `--options` is provided, other CLI flags are rejected, so set workload controls
  like `executor`, `chunksize`, and `nchunks` directly in the YAML. The
  `full_run.sh` wrapper is options-only, so wrapper launches always pass an
  explicit `--options` spec and do not inject additional config flags.
* **Executor choice** – `--executor taskvine|futures|iterative` selects the
  backend. TaskVine is recommended for distributed campaigns, `futures` for
  local multi‑core runs, and `iterative` for tiny smoke tests. For wrapper
  launches, set `executor` in YAML.
* **Workload controls** – `--chunksize` (number of events per chunk),
  `--nchunks` (maximum chunks processed), and `--nworkers` (threads/processes)
  are the primary levers when tuning runtimes. Futures runs also accept
  `--futures-prefetch`, `--futures-retries`, and `--futures-retry-wait` to
  control task pipelining and retry behaviour.
* **Region toggles** – `--skip-sr`, `--skip-cr`, and `--do-systs` mirror the
  settings embedded in the Run‑2 YAML profiles. Set them from the CLI for
  ad-hoc runs, or encode them in the profile when using `--options`.

For a comprehensive, flag-by-flag breakdown (including defaults and YAML keys),
refer to [`run_analysis_cli_reference.md`](run_analysis_cli_reference.md).

### Example commands

Direct CLI runs remain useful for tiny tests or bespoke scans:

```bash
# From the topeft repository root
# Five-event futures debug run with verbose diagnostics
python analysis/topeft_run2/run_analysis.py \
    input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json \
    --scenario TOP_22_006 \
    --executor futures \
    --nworkers 1 \
    --chunksize 5 --nchunks 1 \
    --log-level DEBUG \
    --summary-verbosity brief \
    --skip-cr
```

```bash
# From the topeft repository root
# Futures run driven by the canonical Run-2 SR profile
python analysis/topeft_run2/run_analysis.py \
    input_samples/cfgs/mc_signal_samples_NDSkim.cfg,\
    input_samples/cfgs/mc_background_samples_NDSkim.cfg,\
    input_samples/cfgs/data_samples_NDSkim.cfg \
    --options analysis/topeft_run2/configs/fullR2_run.yml:sr
```

```bash
# From the topeft repository root
# CLI-only futures run tuned for local retry/prefetch debugging
python analysis/topeft_run2/run_analysis.py \
    input_samples/sample_jsons/test_samples/UL17_private_ttH_for_CI.json \
    --scenario TOP_22_006 \
    --executor futures \
    --nworkers 2 \
    --chunksize 50000 \
    --nchunks 2 \
    --futures-prefetch 1 \
    --futures-retries 2 \
    --futures-retry-wait 10 \
    --futures-tail-timeout 300
```

The first and third examples rely purely on CLI flags for quick debugging; the
second mirrors a typical options-driven wrapper launch where the YAML preset
controls scenarios, metadata, and execution toggles.

### Common pitfalls

* `--scenario` and `--options` are mutually exclusive on the CLI. Wrapper runs
  are options-only and must encode scenario selection in YAML.
* If a YAML profile sets `executor: taskvine` but you want to run locally,
  edit the YAML (or run without `--options`) and set `executor: futures`.
* `--chunksize` and `--nchunks` must be specified in the YAML when `--options`
  is active; CLI overrides are rejected to keep configuration reproducible.

## Systematic handling

Systematic switches are managed collaboratively by the helpers:

* ``RunConfig.do_systs`` enables systematic planning.  The builder honours YAML
  booleans (``true``/``false``) and CLI flags.
* `analysis.topeft_run2.run_analysis_helpers.weight_variations_from_metadata(...)`
  inspects ``analysis/metadata/metadata.yml`` to identify all available sum-of-weight
  variations.  Supplying a YAML options file with a ``systematics`` block lets
  you add or restrict variations on a per-profile basis.
* `SampleLoader` makes the variations available on each sample entry so
  that `analysis.topeft_run2.workflow.RunWorkflow` can validate the
  metadata before any Coffea tasks are submitted.
* `analysis.topeft_run2.workflow.SystematicsHelper` (instantiated inside
  the workflow) cross-references the metadata with the scenario-provided feature
  flags and the requested year, building the final structure that
  `AnalysisProcessor` consumes.

When ``--do-renormfact-envelope`` is enabled, the workflow enforces the presence
of ``--do-systs`` and ``--do-np`` because the renormalization/factorization
envelope is only meaningful after the non-prompt application integrals are
available.  These checks happen in `RunWorkflow._validate_config(...)` so that
misconfigurations fail fast.

## Key helpers and extension points

The table below summarises the most common extension hooks:

| Helper | Responsibility | How to extend |
| ------ | -------------- | ------------- |
| `RunConfigBuilder` | Merge CLI, defaults, and YAML into a `RunConfig`. | Subclass the builder and override `build(...)` to recognise additional YAML keys (for example, executor-specific settings).  The CLI parser can expose the same flag so that existing scripts keep working. |
| `SampleLoader` | Resolve JSON/CFG inputs and normalize metadata. | Provide a custom ``SampleLoader`` to support other manifest formats (for example, CSV).  The replacement object must offer ``collect`` and ``load`` methods returning the same structures. |
| `analysis.topeft_run2.workflow.ChannelPlanner` | Activate channels according to metadata scenarios. | Extend `topeft.modules.channel_metadata.ChannelMetadataHelper` or wrap the planner to insert additional filters (for example, dropping jet categories). |
| `analysis.topeft_run2.workflow.HistogramPlanner` | Enumerate histogram combinations for execution. | Pass a custom planner that rewrites the histogram list (for example, sampling only a subset of variables) before the workflow starts the executor. |
| `analysis.topeft_run2.workflow.ExecutorFactory` | Configure the execution backend. | Supply a factory that sets up distributed resources (for example, a site-specific TaskVine profile).  The factory only needs to return an object with a ``create_runner`` method. |
| `analysis.topeft_run2.workflow.run_workflow(...)` | Convenience wrapper mirroring the CLI. | Import the function and feed it the `RunConfig` returned by the quickstart helpers when you want to programmatically drive the workflow from notebooks or scripts. |

### Adding new configuration values

1. Extend the CLI parser in ``run_analysis.py`` with the new flag.
2. Update the ``field_specs`` mapping in `RunConfigBuilder` so that the
   value is recorded inside `RunConfig`.  Reuse the existing coercion
   helpers when possible (``coerce_bool``, ``coerce_int`` or
   ``normalize_sequence``).
3. Add documentation for the new key to the YAML options file used in your team
   and mention the knob in the quickstart walkthrough if it helps new users.
4. Use the value in either `RunWorkflow` or
   `AnalysisProcessor`.  Because `RunConfig` is a dataclass, adding
   optional attributes is backwards compatible and automatically reflected in the
   quickstart return value.

### Using the YAML quickstart workflow

The quickstart helper (``python -m topeft.quickstart``) produces a YAML snippet
when called with ``--emit-options``.  Saving the output provides a reproducible
baseline that can be tweaked manually before feeding it to ``run_analysis.py``.
Common adjustments include enabling ``do_systs``, tweaking
``summary_verbosity`` to show only the bullet lists or the full table, and
switching executors once the run is ready to scale beyond the local machine.

## Troubleshooting checklist

* If the workflow aborts with ``Missing weight variation`` exceptions, confirm
  that the requested variations are listed under ``systematics`` in the metadata
  bundle and that the JSON files contain the corresponding ``nSumOfWeights``
  entries.
* When ``--test`` is requested with a distributed executor, the workflow raises
  an error because only the local ``futures`` backend is configured for fast
  validation runs.  Drop the flag or switch executors when performing smoke tests
  on remote resources.
* ``FileNotFoundError`` from `SampleLoader` usually means that relative
  paths were provided.  Always invoke ``run_analysis.py`` from the repository
  root or supply absolute paths.
* If histogram handling fails with an ``ImportError`` noting that
  ``topcoffea.modules.histEFT`` is missing, confirm
  that your installed ``topcoffea`` ref follows the coordinated compatibility
  guidance in ``topcoffea/docs/topeft_integration.md``, then reinstall from your
  local checkout (for example ``pip install -e /path/to/topcoffea``) before
  retrying the run.

With these pieces in place you can mix and match quickstart presets and YAML
profiles while keeping the run history compact and shareable.  When you need to
experiment with CLI overrides, drop ``--options`` so the command-line values are
honoured for that run.
