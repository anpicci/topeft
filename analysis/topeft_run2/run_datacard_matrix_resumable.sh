#!/usr/bin/env bash
set -euo pipefail

readonly workspace_root='/users/apiccine/work/correction-lib'
readonly repository_root="${workspace_root}/topeft"
readonly engine='analysis/topeft_run2/datacard_matrix_runner.py'

if command -v python >/dev/null 2>&1; then
  engine_python="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  engine_python="$(command -v python3)"
else
  printf '%s\n' 'python or python3 is required for the runner engine' >&2
  exit 127
fi

exec "$engine_python" "${repository_root}/${engine}" "$@"
