#!/usr/bin/env bash
# Options-only wrapper for analysis/topeft_run2/run_analysis.py.
#
# This entrypoint intentionally accepts only --options (plus --help) so a
# single YAML profile remains the sole run configuration source.
#
# Notes:
#   - TaskVine + DDR is the recommended production path and is configured in YAML.
#   - TaskVine DDR output defaults to the canonical flat schema
#     (sample, channel, var, application, systematic_label).
#   - Futures/iterative debug profiles may still produce tuple-keyed outputs.
#   - Preprocess artifacts default to taskvine-results/ddr_preprocessed_data.json
#     unless overridden in YAML.
#   - If ddr_x509_proxy is configured, the workflow stages proxy.pem and sets
#     X509_USER_PROXY=proxy.pem for worker tasks.

set -euo pipefail

write_exit_marker() {
  local status="$1"
  local marker_path="${TOPEFT_EXIT_MARKER:-}"
  if [[ -z "$marker_path" ]]; then
    return
  fi
  mkdir -p "$(dirname "$marker_path")"
  printf '%s\n' "$status" > "$marker_path"
}

emit_exit_debug() {
  local status="$1"
  local pipestatus_text="$2"
  if [[ "${TOPEFT_EXIT_DEBUG:-0}" != "1" ]]; then
    return
  fi
  printf 'full_run.sh: driver_status=%s pipestatus=[%s]\n' "$status" "$pipestatus_text" >&2
}

run_with_status_capture() {
  local status=0
  local pipestatus_text=""
  local log_path="${TOPEFT_DRIVER_LOG:-}"

  if [[ -n "$log_path" ]]; then
    mkdir -p "$(dirname "$log_path")"
    set +e
    "$@" 2>&1 | tee "$log_path"
    local -a pipe_status=("${PIPESTATUS[@]}")
    status="${pipe_status[0]}"
    pipestatus_text="${pipe_status[*]}"
    set -e
  else
    set +e
    "$@"
    status=$?
    set -e
    pipestatus_text="$status"
  fi

  write_exit_marker "$status"
  emit_exit_debug "$status" "$pipestatus_text"
  return "$status"
}

run_self_test_exit_propagation() {
  local status="${1:-}"
  if ! [[ "$status" =~ ^[0-9]+$ ]] || (( status < 0 || status > 255 )); then
    echo "Error: --self-test-exit-propagation expects an integer exit code in [0,255]." >&2
    return 1
  fi

  local script
  printf -v script '%s\n%s\n%s\n' \
    'echo "full_run self-test stdout"' \
    'echo "full_run self-test stderr" >&2' \
    "exit $status"

  local test_status=0
  run_with_status_capture /bin/bash --noprofile --norc -c "$script" || test_status=$?
  return "$test_status"
}

print_usage() {
  cat <<'USAGE'
Usage:
  full_run.sh --options <path[:profile]>
  full_run.sh --self-test-exit-propagation <status>
  full_run.sh --help

Description:
  Wrapper around run_analysis.py in strict options-only mode.

Rules:
  - --options is required for normal execution.
  - --self-test-exit-propagation runs a local dummy command and exits with the requested status.
  - No other CLI flags are accepted by this wrapper.
  - Profile auto-selection is handled by RunConfigBuilder:
    pass path.yml and use default_profile in YAML when desired.

Examples:
  ./full_run.sh --options analysis/topeft_run2/configs/fullR2_run.yml:sr
  ./full_run.sh --options analysis/topeft_run2/configs/fullR2_run.yml

Tips:
  - Pin chunksize in YAML defaults (recommended: 500000).
  - Set executor: taskvine and DDR knobs in YAML for production runs.
  - Use dedicated futures/iterative debug profiles in YAML for local smoke tests.
  - Optional env vars:
      TOPEFT_EXIT_MARKER=<path>   # write final driver exit status to file
      TOPEFT_EXIT_DEBUG=1         # print driver_status + pipestatus to stderr
      TOPEFT_DRIVER_LOG=<path>    # tee driver stdout/stderr to this file
USAGE
}

main() {
  local options_spec=""
  local self_test_status=""

  if [[ $# -eq 0 ]]; then
    echo "Error: --options is required." >&2
    print_usage >&2
    return 1
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        print_usage
        return 0
        ;;
      --options)
        if [[ -n "$options_spec" ]]; then
          echo "Error: --options was provided more than once." >&2
          return 1
        fi
        if [[ $# -lt 2 ]]; then
          echo "Error: --options expects a non-empty value." >&2
          return 1
        fi
        options_spec="$2"
        shift 2
        ;;
      --options=*)
        if [[ -n "$options_spec" ]]; then
          echo "Error: --options was provided more than once." >&2
          return 1
        fi
        options_spec="${1#*=}"
        shift
        ;;
      --self-test-exit-propagation)
        if [[ -n "$self_test_status" ]]; then
          echo "Error: --self-test-exit-propagation was provided more than once." >&2
          return 1
        fi
        if [[ $# -lt 2 ]]; then
          echo "Error: --self-test-exit-propagation expects an integer value." >&2
          return 1
        fi
        self_test_status="$2"
        shift 2
        ;;
      --self-test-exit-propagation=*)
        if [[ -n "$self_test_status" ]]; then
          echo "Error: --self-test-exit-propagation was provided more than once." >&2
          return 1
        fi
        self_test_status="${1#*=}"
        shift
        ;;
      *)
        echo "Error: unsupported argument '$1'. This wrapper only accepts --options, --self-test-exit-propagation, and --help." >&2
        print_usage >&2
        return 1
        ;;
    esac
  done

  if [[ -n "$self_test_status" && -n "$options_spec" ]]; then
    echo "Error: --options and --self-test-exit-propagation are mutually exclusive." >&2
    return 1
  fi

  if [[ -n "$self_test_status" ]]; then
    local self_test_rc=0
    run_self_test_exit_propagation "$self_test_status" || self_test_rc=$?
    return "$self_test_rc"
  fi

  if [[ -z "${options_spec// }" ]]; then
    echo "Error: --options value cannot be empty." >&2
    return 1
  fi

  local script_dir
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

  local driver_status=0
  run_with_status_capture python "$script_dir/run_analysis.py" --options "$options_spec" || driver_status=$?
  return "$driver_status"
}

main "$@"
