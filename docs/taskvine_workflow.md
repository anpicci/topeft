# TaskVine workflow quickstart

TaskVine is the default distributed executor for `topeft`.  This guide threads
together the full workflow so new analysts can bootstrap the Coffea 2025.7
environment, package the tarball consumed by remote workers, and submit a
matching worker pool.

This page is the distributed-execution branch of the primary newcomer path. If
you are starting from scratch, read [workflow_and_yaml_hub.md](workflow_and_yaml_hub.md)
and [quickstart_run2.md](quickstart_run2.md) first.

## 1. Prepare the Coffea 2025.7 environment

All examples assume a clean checkout of both `topeft` and `topcoffea`.  Install
[Miniconda](https://docs.conda.io/en/latest/miniconda.html) if it is not already
available, then create the shared Conda environment shipped with the repository:

```bash
conda env create -f environment.yml
conda activate coffea2025
pip install -e .
```

Clone the companion [`topcoffea`](https://github.com/TopEFT/topcoffea) repository
next to `topeft` and install it in editable mode:

```bash
cd ..
git clone https://github.com/TopEFT/topcoffea.git
cd topcoffea
git switch <coordinated-ref>
pip install -e .
cd ../topeft
```

Choose a release tag or feature ref coordinated with your `topeft` checkout.
Compatibility policy is documented in `topcoffea/docs/topeft_integration.md`.

Upgrading an existing checkout?  Run `conda env update -f environment.yml --prune`
instead of recreating the environment.  Conda may request a solver update when
aligning with the conda-forge builds—allow the prompt (or execute
`conda update -n base -c conda-forge conda`) so the editable installs match the
packaged worker tarball.

## 2. Package the TaskVine environment tarball

The workflow relies on the refreshed
`topcoffea.modules.remote_environment.get_environment()` helper to assemble a
TaskVine-ready archive under `topeft-envs/`.  Run the packaging step after
installing the editable modules or updating dependencies.  Always invoke the
helper from the same ref (or tag) you just installed so the tarball mirrors the
source checkout—every CLI entry point now validates `.git/HEAD` (or the
`TOPCOFFEA_BRANCH` override for detached tags) against the coordinated ref and
aborts early when the sibling repository drifts:

```bash
python -m topcoffea.modules.remote_environment
```

Each invocation prints the cache path and automatically rebuilds the tarball
when the Conda specification or either editable repository has changed.  To
force a rebuild manually, remove the cached file or execute:

```bash
python -c "from topcoffea.modules.remote_environment import get_environment; print(get_environment(force=True))"
```

The returned path is exactly what the TaskVine executor passes via the
`environment_file` argument.  Keep the archive under version control whenever you
update the dependencies so other analysts can reuse the same package.  For
`executor=taskvine`, `run_analysis.py` now auto-builds a tarball whenever
`environment_file` is unset/empty and logs both the build trigger and the final
path.  You can still set `environment_file` explicitly (`path`, `cached`, or
`auto`) for reproducibility and policy control.

For the detailed rebuild policy, cache naming rules, and maintainer-focused
packaging notes, see [Environment packaging](environment_packaging.md).

`environment_file=none` (including `--no-environment-file`) is not supported
for TaskVine in `run_analysis.py`; the run fails fast with exit code `2`
because workers require a Python environment tarball.

## 3. Enable TaskVine in the workflow configuration

TaskVine is selected automatically on the CLI, but YAML profiles may still list
older executors for local smoke tests.  Open the profile you plan to run (for
example `analysis/topeft_run2/configs/fullR2_run.yml`) and set the executor to
`taskvine`:

```yaml
profiles:
  cr:
    # ...existing options...
    executor: taskvine
```

Run invocations should call `run_analysis.py` through Python; `run_analysis`
itself is not an installed entrypoint:

```bash
"$PYTHON_ENV" analysis/topeft_run2/run_analysis.py --help
```

```bash
cd analysis/topeft_run2
"$PYTHON_ENV" run_analysis.py --help
```

When launching via YAML (`--options path.yml[:profile]`), set metadata inside
the YAML profile using the canonical repo-root-relative path:
`analysis/metadata/metadata.yml`.

The [`run_analysis.py` CLI and YAML reference](run_analysis_cli_reference.md)
documents every distributed-execution flag, including helper attributes such as
`taskvine_manager_name_template`, `environment_file`, and `resources_mode`. Worker
standard output is forwarded to the TaskVine manager logs by default—override
this behaviour with `--no-taskvine-print-stdout` (or the YAML key
`taskvine_print_stdout: false`) when you only want the structured processor logs
to reach the terminal.  For smoke profiles, prefer
`taskvine_print_stdout: false`; turn it back on only for worker-debug sessions.
The knob is defined at the CLI surface in `topeft/modules/executor_cli.py`,
normalized by `analysis/topeft_run2/run_analysis_helpers.py`, and consumed in
TaskVine runner creation in `analysis/topeft_run2/workflow.py`.

## 4. Submit a worker pool with the packaged environment

When the workflow starts it advertises a manager name of the form
`<user>-taskvine-coffea` (or a custom value passed through
`--taskvine-manager-name`). Launch a worker pool that matches this identifier and stages
the tarball produced in step 2:

```bash
vine_submit_workers --cores 4 --memory 16000 --disk 16000 \
    --python-env "$(python -m topcoffea.modules.remote_environment)" \
    -M ${USER}-taskvine-coffea 10
```

Supplying `--python-env` preloads the packaged archive so new workers do not
have to download it from the manager.  Omit the flag when the submission helper
does not support it—the TaskVine executor will still ship the same tarball via
`environment_file`.

Local tests can use `vine_worker` instead:

```bash
vine_worker --cores 1 --memory 8000 --disk 8000 -M ${USER}-taskvine-coffea
```

The workflow stages `analysis_processor.py` and any sibling helper modules that
match `analysis_processor*.py` before tasks are submitted. Add new helpers next
to the processor (or under an `analysis_processor_helpers/` package) and they
will be shipped automatically without having to update CLI glue code.

## 5. Explore the quickstart workflows

Once the workers are connected, follow one of the onboarding guides for complete
end-to-end examples:

- [TOP-22-006 Quickstart Guide](quickstart_top22_006.md) – Launches the SR/CR
  presets backed by TaskVine.
- [Run 2 quickstart pipeline](quickstart_run2.md) – Smokes a reduced histogram
  set and links to the YAML-based configuration.

Both guides call out where to adjust metadata, toggle scenarios, and select the
TaskVine executor so analysts can move seamlessly from setup to distributed
submissions.

If you need to tune YAML, CLI, metadata, or troubleshooting behavior after the
TaskVine setup is clear, continue with
[run_analysis_configuration.md](run_analysis_configuration.md).

## Legacy naming note

Older internal notes sometimes referred to this workflow as "Work Queue." The
supported distributed backend in current `topeft` workflows is TaskVine, and
this page is the canonical source for setup and execution guidance.
