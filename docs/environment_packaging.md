# Remote environment maintenance

Changes to `environment.yml` affect both local development setups and the
archived environment shipped to remote workers. After editing the specification
make sure the companion [`topcoffea`](https://github.com/TopEFT/topcoffea)
package remains importable::

       python -c "import topcoffea"

The CI workflow runs the same smoke test to confirm downstream scripts can
resolve `topcoffea.modules` without manual `PYTHONPATH` tweaks.  Once the import
works, walk through the standard refresh steps:

To avoid accidental NumPy ABI breakage from CVMFS/system site-packages, the
environment now clears `PYTHONPATH` and sets `PYTHONNOUSERSITE=1`. These
variables are applied by conda on **environment activation**, so you must
update/recreate the env and re-activate it for changes to take effect.

Copy/paste refresh steps:

       conda env update -f environment.yml --prune
       conda activate coffea2025

A quick diagnosis is:

       python -c "import numpy, sys; print(sys.executable); print(sys.prefix); print(numpy.__file__)"

This should point inside the active conda env, not `/usr/lib*` or `/cvmfs`.
The regression guardrail lives in `tests/test_numpy_abi_import.py` and enforces
this path-based check with extra diagnostics if it fails.

For reproducible verification, run from the repo root or use absolute paths:

       cd /users/apiccine/work/ChUpdate/topeft
       PYTHONPATH="" PYTHONNOUSERSITE=1 $PYTHON_ENV -m pytest -q \
         /users/apiccine/work/ChUpdate/topeft/tests/test_numpy_abi_import.py

1. Recreate the local Conda environment so the lock file matches the new pins::

       conda env update -f environment.yml --prune

   This command updates the existing `coffea2025` environment in-place and
   removes packages that are no longer required.

2. Regenerate the packaged tarball that workflows submit to remote resources::

       python -m topcoffea.modules.remote_environment

   The helper will compare the current `environment.yml` (including the
   `coffea==2025.7.3` / `awkward==2.8.7` pins plus the aligned
   `hist==2.9.*` / `boost-histogram>=1.4` pair) against the cached archive in
   `topeft-envs/` and build a fresh tarball when the spec or local editable
   packages (`topeft`, `topcoffea`) have changed.

Remember to commit both the specification and the newly generated archive when
updating the shipped environment.  Workflows such as ``analysis/topeft_run2/run_analysis.py``
now default to ``--environment-file=cached`` and will error out when the tarball
is absent, so keeping the package up to date is part of the standard review
checklist.  Whenever you touch dependency pins, rebuild the tarball and reactivate
the refreshed ``coffea2025`` environment before running either the futures or
TaskVine executors to avoid mismatched NumPy/Pandas ABIs between the manager and
workers.
