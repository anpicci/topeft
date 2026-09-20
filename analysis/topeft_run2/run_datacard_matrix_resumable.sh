#!/usr/bin/env bash
set -euo pipefail

readonly workspace_root='/users/apiccine/work/correction-lib'
readonly repository_root="${workspace_root}/topeft"
readonly wrap="${workspace_root}/codex-run.sh"
readonly python_env='/users/apiccine/work/miniconda3/envs/clib-env/bin/python'
readonly engine='analysis/topeft_run2/datacard_matrix_runner.py'

exec "$wrap" /bin/bash --noprofile --norc -c \
  'working_directory=$1; shift; cd "$working_directory"; exec "$@"' \
  datacard-matrix-runner "$repository_root" "$python_env" "$engine" "$@"
