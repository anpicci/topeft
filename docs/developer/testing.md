# Testing Guide

This page is the canonical testing reference for `topeft`.

## Run tests from the repository root

Use the ChUpdate wrapper and the shared Python environment:

```bash
WRAP=/users/apiccine/work/ChUpdate/codex-run.sh
PYTHON_ENV="/users/apiccine/work/miniconda3/envs/coffea2025/bin/python"

$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/ChUpdate/topeft && $PYTHON_ENV -m pytest -q'
```

Run a single test file when iterating:

```bash
WRAP=/users/apiccine/work/ChUpdate/codex-run.sh
PYTHON_ENV="/users/apiccine/work/miniconda3/envs/coffea2025/bin/python"

$WRAP /bin/bash --noprofile --norc -c 'cd /users/apiccine/work/ChUpdate/topeft && $PYTHON_ENV -m pytest -q tests/test_taskvine_executor.py -k taskvine'
```

## TaskVine test notes

`tests/test_taskvine_executor.py` launches
`analysis/topeft_run2/run_analysis.py` with the TaskVine executor and verifies
that a histogram archive is produced.

Local prerequisites:

- `ndcctools` with Python TaskVine bindings.
- Coffea build exposing `coffea.processor.TaskVineExecutor`.
- `vine_worker` and `vine_factory` binaries on `PATH`.

When these requirements are unavailable, the test is expected to skip.

## Optional coverage output

If `pytest-cov` is available in your environment:

- `pytest --cov`
- `pytest --cov --cov-report html`

For environment and packaging guidance, see
[docs/environment_packaging.md](../environment_packaging.md). For the full
documentation map, see [docs/index.md](../index.md).
