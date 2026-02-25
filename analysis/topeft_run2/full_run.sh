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

print_usage() {
  cat <<'USAGE'
Usage:
  full_run.sh --options <path[:profile]>
  full_run.sh --help

Description:
  Wrapper around run_analysis.py in strict options-only mode.

Rules:
  - --options is required for execution.
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
USAGE
}

main() {
  local options_spec=""

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
      *)
        echo "Error: unsupported argument '$1'. This wrapper only accepts --options and --help." >&2
        print_usage >&2
        return 1
        ;;
    esac
  done

  if [[ -z "${options_spec// }" ]]; then
    echo "Error: --options value cannot be empty." >&2
    return 1
  fi

  local script_dir
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

  exec python "$script_dir/run_analysis.py" --options "$options_spec"
}

main "$@"
