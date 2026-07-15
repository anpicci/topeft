#!/usr/bin/env bash
#
# Execute one Run 3 missing-parton input-pkl campaign.  Repository and
# environment preparation are the operator's responsibility before invocation.
# This driver only runs and validates PKL production; it never builds payloads.

set -Eeuo pipefail

run3_years=(2022 2022EE 2023 2023BPix)

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
topeft_root="$(cd -- "${script_dir}/../.." && pwd)"
workspace_root="$(cd -- "${topeft_root}/.." && pwd)"
environment_wrapper="${workspace_root}/codex-run.sh"
python_env="${PYTHON_ENV:-/users/apiccine/work/miniconda3/envs/clib-env/bin/python}"
default_output_parent="/groups/klannon/apiccine/misspar_debug"
executor="${MISSING_PARTON_EXECUTOR:-work_queue}"
all_analysis_chunks="${ALL_ANALYSIS_CHUNKS:-2}"

central_cfg="input_samples/cfgs/missing_parton_run3_central_tzq_NDSkim.cfg"
private_cfg="input_samples/cfgs/missing_parton_run3_private_tllq_NDSkim.cfg"

output_root=""
resume_mode=false
current_phase="running"
status_file=""
state_history_file=""
retry_history_file=""
output_contract_file=""
validation_file=""
execution_commands_file=""
log_file=""
campaign_lock_dir=""

declare -a all_analysis_groups=()
declare -a top22006_groups=()
declare -a chunk_specs=()
declare -a central_process_labels=()
declare -a private_process_labels=()
declare -a resolved_command=()

usage() {
  cat <<'USAGE_EOF'
Usage:
  run_run3_missing_parton_pkls_overnight.sh [output_root]
  run_run3_missing_parton_pkls_overnight.sh --resume <existing_output_root>

Run one complete campaign in this order:
  1. all-analysis central NLO tZq category chunks;
  2. all-analysis private LO tllq category chunks;
  3. canonical merged all-analysis central/private PKLs;
  4. TOP-22-006 central NLO tZq and private LO tllq diagnostic PKLs.

The operator must prepare the repository, environment, and execution service
before starting this command.  The campaign root must be an absolute path; a
fresh root must be absent or empty.  Use --resume only for an interrupted
campaign created by this driver.

Canonical launch directory:
  cd /users/apiccine/work/correction-lib/topeft/analysis/topeft_run2
  ./run_run3_missing_parton_pkls_overnight.sh /absolute/campaign_root

Environment overrides:
  ALL_ANALYSIS_CHUNKS      integer >= 2 (default: 2)
  MISSING_PARTON_EXECUTOR  futures, work_queue, or taskvine (default: work_queue)
  PYTHON_ENV               interpreter used through correction-lib/codex-run.sh
USAGE_EOF
}

timestamp_utc() {
  date -u +%Y%m%dT%H%M%SZ
}

timestamp_iso() {
  date -u --iso-8601=seconds
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

quote_command() {
  local quoted=""
  local argument
  for argument in "$@"; do
    printf -v argument '%q' "${argument}"
    quoted+="${quoted:+ }${argument}"
  done
  printf '%s\n' "${quoted}"
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

run_python() {
  "${environment_wrapper}" /bin/bash --noprofile --norc -c \
    'cd "$1"; shift; exec "$@"' \
    run3_missing_parton_driver "${script_dir}" "${python_env}" "$@"
}

write_status() {
  local state="$1"
  local detail="${2:-}"
  current_phase="${state}"
  printf 'state=%s\ntimestamp=%s\ndetail=%s\n' \
    "${state}" "$(timestamp_iso)" "${detail}" > "${status_file}"
  printf '%s\t%s\t%s\n' "$(timestamp_iso)" "${state}" "${detail}" >> "${state_history_file}"
}

record_retry() {
  local action="$1"
  local detail="$2"
  printf '%s\t%s\t%s\n' "$(timestamp_iso)" "${action}" "${detail}" >> "${retry_history_file}"
}

on_error() {
  local exit_code="$1"
  local line_number="$2"
  local failed_command="$3"

  trap - ERR
  printf '\nFAILED: phase=%s exit_code=%s line=%s command=%s\n' \
    "${current_phase}" "${exit_code}" "${line_number}" "${failed_command}" >&2
  if [[ -n "${status_file}" ]]; then
    write_status "failed" "phase=${current_phase}; exit_code=${exit_code}; line=${line_number}; command=${failed_command}" || true
  fi
  exit "${exit_code}"
}

on_signal() {
  local signal_name="$1"

  trap - INT TERM
  printf '\nINTERRUPTED: phase=%s signal=%s\n' "${current_phase}" "${signal_name}" >&2
  if [[ -n "${status_file}" ]]; then
    write_status "interrupted" "phase=${current_phase}; signal=${signal_name}" || true
  fi
  exit 130
}

trap 'on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

parse_args() {
  local positional_root=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --resume)
        [[ $# -ge 2 ]] || die "--resume requires an existing output root"
        [[ -z "${positional_root}" && "${resume_mode}" == false ]] || die "select one campaign mode"
        resume_mode=true
        output_root="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --*)
        die "unknown option: $1"
        ;;
      *)
        [[ "${resume_mode}" == false ]] || die "--resume accepts its output root directly after the flag"
        [[ -z "${positional_root}" ]] || die "only one output root may be supplied"
        positional_root="$1"
        shift
        ;;
    esac
  done

  if [[ "${resume_mode}" == false ]]; then
    output_root="${positional_root}"
  fi
  case "${executor}" in
    futures|work_queue|taskvine) ;;
    *) die "MISSING_PARTON_EXECUTOR must be futures, work_queue, or taskvine" ;;
  esac
  is_positive_integer "${all_analysis_chunks}" || die "ALL_ANALYSIS_CHUNKS must be a positive integer"
  (( all_analysis_chunks >= 2 )) || die "ALL_ANALYSIS_CHUNKS must be at least 2"
  if [[ -z "${output_root}" && "${resume_mode}" == false ]]; then
    output_root="${default_output_parent}/run3_missing_parton_$(timestamp_utc)"
  fi
  [[ "${output_root}" == /* ]] || die "output root must be an absolute path"
}

assert_operational_prerequisites() {
  [[ -x "${environment_wrapper}" ]] || die "environment wrapper is unavailable: ${environment_wrapper}"
  [[ -x "${python_env}" ]] || die "Python interpreter is unavailable: ${python_env}"
  [[ -f "${script_dir}/run_analysis.py" ]] || die "run_analysis.py is unavailable"
  [[ -f "${script_dir}/make_cards.py" ]] || die "make_cards.py is unavailable"
  [[ -f "${topeft_root}/${central_cfg}" ]] || die "central cfg is unavailable: ${central_cfg}"
  [[ -f "${topeft_root}/${private_cfg}" ]] || die "private cfg is unavailable: ${private_cfg}"
  [[ -f "${topeft_root}/topeft/channels/ch_lst.json" ]] || die "channel list is unavailable"
  command -v flock >/dev/null 2>&1 || die "flock is required for exclusive campaign ownership"
  command -v gzip >/dev/null 2>&1 || die "gzip is required for PKL validation"
  command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required for PKL manifests"
}

campaign_paths() {
  status_file="${output_root}/status.txt"
  state_history_file="${output_root}/state_history.tsv"
  retry_history_file="${output_root}/resume_history.tsv"
  output_contract_file="${output_root}/output_contract.tsv"
  validation_file="${output_root}/validation.tsv"
  execution_commands_file="${output_root}/execution_commands.tsv"
  log_file="${output_root}/run.log"
  campaign_lock_dir="${output_root}/.campaign_lock"
}

acquire_campaign_lock() {
  mkdir -p "${campaign_lock_dir}"
  exec 9>"${campaign_lock_dir}/active.lock"
  flock -n 9 || die "another driver process owns this campaign root: ${output_root}"
  printf 'pid=%s\nstarted=%s\nmode=%s\n' "$$" "$(timestamp_iso)" \
    "$([[ "${resume_mode}" == true ]] && printf resume || printf fresh)" > "${campaign_lock_dir}/owner.txt"
}

write_campaign_metadata() {
  local driver_checksum

  driver_checksum="$(sha256sum "${BASH_SOURCE[0]}" | awk '{print $1}')"
  {
    printf 'campaign_id=run3_missing_parton_%s\n' "$(basename -- "${output_root}")"
    printf 'started=%s\n' "$(timestamp_iso)"
    printf 'output_root=%s\n' "${output_root}"
    printf 'working_directory=%s\n' "${topeft_root}"
    printf 'hostname=%s\n' "$(hostname)"
    printf 'driver_path=%s\n' "${BASH_SOURCE[0]}"
    printf 'driver_sha256=%s\n' "${driver_checksum}"
    printf 'environment_wrapper=%s\n' "${environment_wrapper}"
    printf 'python_interpreter=%s\n' "${python_env}"
    printf 'executor=%s\n' "${executor}"
    printf 'all_analysis_chunks=%s\n' "${all_analysis_chunks}"
    printf 'periods=%s\n' "${run3_years[*]}"
    printf 'central_cfg=%s\n' "${central_cfg}"
    printf 'private_cfg=%s\n' "${private_cfg}"
  } > "${output_root}/campaign_metadata.txt"
}

initialize_new_campaign() {
  if [[ -e "${output_root}" ]]; then
    [[ -d "${output_root}" ]] || die "output root exists and is not a directory: ${output_root}"
    [[ -z "$(find "${output_root}" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
      || die "refusing to reuse a populated campaign root: ${output_root}"
  else
    mkdir -p "$(dirname -- "${output_root}")"
    mkdir "${output_root}"
  fi
  campaign_paths
  acquire_campaign_lock
  mkdir -p "${output_root}/all_analysis/raw/central_tzq" \
    "${output_root}/all_analysis/raw/private_tllq" \
    "${output_root}/all_analysis/canonical" \
    "${output_root}/top22006" \
    "${output_root}/invalid_outputs"
  : > "${log_file}"
  printf 'timestamp\tstate\tdetail\n' > "${state_history_file}"
  printf 'timestamp\taction\tdetail\n' > "${retry_history_file}"
  printf 'path\trole\tscope\tclassification\tresult\tdetail\n' > "${validation_file}"
  printf 'timestamp\tstep\tcommand\n' > "${execution_commands_file}"
  write_campaign_metadata
}

initialize_existing_campaign() {
  [[ -d "${output_root}" ]] || die "resume root is not a directory: ${output_root}"
  campaign_paths
  [[ -f "${output_root}/campaign_metadata.txt" ]] || die "resume root was not created by this driver"
  [[ -f "${status_file}" ]] || die "resume root is missing status.txt"
  [[ -f "${output_contract_file}" ]] || die "resume root is missing output_contract.tsv"
  [[ -f "${validation_file}" ]] || die "resume root is missing validation.tsv"
  [[ -f "${execution_commands_file}" ]] || die "resume root is missing execution_commands.tsv"
  [[ "$(awk -F= '$1 == "state" {print $2}' "${status_file}")" != "success" ]] \
    || die "a successful campaign is immutable and cannot be resumed"
  acquire_campaign_lock
  record_retry "resume_started" "campaign root accepted; completed outputs will be revalidated"
}

read_json_keys() {
  local key="$1"
  run_python - "${topeft_root}/topeft/channels/ch_lst.json" "${key}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
for item in payload[sys.argv[2]]:
    print(item)
PY
}

load_category_groups() {
  mapfile -t all_analysis_groups < <(read_json_keys ALL_CH_LST_SR)
  mapfile -t top22006_groups < <(read_json_keys TOP22_006_CH_LST_SR)
  (( ${#all_analysis_groups[@]} >= all_analysis_chunks )) \
    || die "ALL_ANALYSIS_CHUNKS exceeds available all-analysis groups"
  (( ${#top22006_groups[@]} > 0 )) || die "TOP-22-006 group list is empty"
}

build_chunk_specs() {
  local total_groups="${#all_analysis_groups[@]}"
  local start_index=0
  local chunk_index
  local remaining
  local chunks_left
  local chunk_size
  local -a groups=()

  chunk_specs=()
  for ((chunk_index = 0; chunk_index < all_analysis_chunks; chunk_index++)); do
    remaining=$((total_groups - start_index))
    chunks_left=$((all_analysis_chunks - chunk_index))
    chunk_size=$(((remaining + chunks_left - 1) / chunks_left))
    groups=("${all_analysis_groups[@]:start_index:chunk_size}")
    chunk_specs+=("${groups[*]}")
    start_index=$((start_index + chunk_size))
  done
}

cfg_json_relpaths() {
  local cfg_relpath="$1"
  local cfg_path="${topeft_root}/${cfg_relpath}"
  local line
  local token
  local absolute_path

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -n "${line}" ]] || continue
    [[ "${line}" == root://* ]] && continue
    for token in ${line//,/ }; do
      absolute_path="$(realpath -m "${script_dir}/${token}")"
      [[ "${absolute_path}" == "${topeft_root}/"* ]] \
        || die "cfg input lies outside topeft: ${token}"
      [[ -f "${absolute_path}" ]] || die "cfg references a missing JSON: ${absolute_path}"
      printf '%s\n' "${absolute_path#"${topeft_root}/"}"
    done
  done < "${cfg_path}"
}

load_process_labels() {
  local cfg_relpath="$1"
  local -n labels_ref="$2"
  local -a json_relpaths=()

  mapfile -t json_relpaths < <(cfg_json_relpaths "${cfg_relpath}")
  mapfile -t labels_ref < <(
    run_python - "${topeft_root}" "${json_relpaths[@]}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for relpath in sys.argv[2:]:
    with (root / relpath).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    print(payload["histAxisName"])
PY
  )
  (( ${#labels_ref[@]} == 4 )) || die "${cfg_relpath} must resolve exactly four Run 3 process labels"
}

write_output_contract() {
  local destination="$1"
  local role
  local chunk_index
  local chunk_label

  printf 'classification\tscope\trole\tchunk\tpath\n' > "${destination}"
  for role in central_tzq private_tllq; do
    for ((chunk_index = 1; chunk_index <= all_analysis_chunks; chunk_index++)); do
      printf -v chunk_label '%02d' "${chunk_index}"
      printf 'raw_chunk\tall_analysis\t%s\t%s\t%s\n' "${role}" "${chunk_label}" \
        "$(raw_path_for_chunk "${role}" "${chunk_label}")" >> "${destination}"
    done
    printf 'canonical\tall_analysis\t%s\tmerged\t%s\n' "${role}" \
      "$(canonical_path_for_role "${role}")" >> "${destination}"
  done
  for role in central_tzq private_tllq; do
    printf 'diagnostic\ttop22006\t%s\tsingle\t%s\n' "${role}" \
      "$(top22006_path_for_role "${role}")" >> "${destination}"
  done
}

verify_resume_contract() {
  local temporary_contract

  temporary_contract="$(mktemp "${TMPDIR:-/tmp}/run3_missing_parton_contract.XXXXXX")"
  write_output_contract "${temporary_contract}"
  cmp -s "${temporary_contract}" "${output_contract_file}" \
    || die "resume output contract differs from the existing campaign"
  rm -f "${temporary_contract}"
}

build_run_analysis_command() {
  local role="$1"
  local scope="$2"
  local output_path="$3"
  local category_spec="$4"
  local cfg
  local outdir
  local outname
  local -a category_groups=()

  case "${role}" in
    central_tzq) cfg="${topeft_root}/${central_cfg}" ;;
    private_tllq) cfg="${topeft_root}/${private_cfg}" ;;
    *) die "unknown role: ${role}" ;;
  esac

  outdir="$(dirname -- "${output_path}")"
  outname="$(basename -- "${output_path}" .pkl.gz)"
  read -r -a category_groups <<< "${category_spec}"

  resolved_command=(
    "${environment_wrapper}" /bin/bash --noprofile --norc -c
    'cd "$1"; shift; exec "$@"'
    run3_missing_parton_driver "${script_dir}" "${python_env}" run_analysis.py
    "${cfg}" --years "${run3_years[@]}" --skip-cr --hist-list njets
    --executor "${executor}" --outpath "${outdir}" --outname "${outname}"
  )
  if [[ "${role}" == "private_tllq" ]]; then
    resolved_command+=(--do-systs)
  fi
  if [[ "${scope}" == "all_analysis" ]]; then
    resolved_command+=(--all-analysis --category-groups "${category_groups[@]}")
  else
    resolved_command+=(--category-groups "${category_groups[@]}")
  fi
}

record_validation() {
  local path="$1"
  local role="$2"
  local scope="$3"
  local classification="$4"
  local result="$5"
  local detail="$6"

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${path}" "${role}" "${scope}" "${classification}" "${result}" "${detail}" >> "${validation_file}"
}

role_labels_csv() {
  local role="$1"
  local -a labels=()
  case "${role}" in
    central_tzq) labels=("${central_process_labels[@]}") ;;
    private_tllq) labels=("${private_process_labels[@]}") ;;
    *) die "unknown role: ${role}" ;;
  esac
  local IFS=,
  printf '%s\n' "${labels[*]}"
}

run_histogram_validator() {
  run_python - "$@" <<'PY'
import json
import sys

import awkward as ak
import numpy as np
from topeft.modules.datacard_tools import load_and_merge_histogram_pkls


def normalize_histogram_values(values):
    """Return a dense numerical view without mutating the histogram values.

    Hist categorical combinations that were never populated can be represented
    as Awkward ``None`` or as masked cells.  Those are structural empties, so
    they become zero for validation.  All present numerical values are kept
    unchanged and are checked for NaN or infinity by ``require_finite``.
    """
    if isinstance(values, ak.highlevel.Array):
        filled = ak.fill_none(values, 0, axis=None)
        return np.asarray(ak.to_numpy(filled, allow_missing=False))

    if np.ma.isMaskedArray(values):
        return np.asarray(np.ma.asarray(values).filled(0))

    array = np.asarray(values)
    if array.dtype == object:
        filled = ak.fill_none(ak.Array(array.tolist()), 0, axis=None)
        return np.asarray(ak.to_numpy(filled, allow_missing=False))
    return array


def require_finite(values, context):
    normalized = normalize_histogram_values(values)
    if not np.isfinite(normalized).all():
        raise RuntimeError(f"{context} contains NaN or infinite bin content")
    return normalized


def load(path_or_paths, **kwargs):
    if isinstance(path_or_paths, str):
        path_or_paths = [path_or_paths]
    return load_and_merge_histogram_pkls(path_or_paths, require_sumw2=True, **kwargs)


mode, *args = sys.argv[1:]
if mode == "pkl":
    path, role, scope, labels_csv = args
    expected_labels = [item for item in labels_csv.split(",") if item]
    histograms, merge_report = load(path)
    for key in ("njets", "njets_sumw2"):
        if key not in histograms:
            raise RuntimeError(f"missing required histogram: {key}")
        histogram = histograms[key]
        axis_names = [axis.name for axis in histogram.axes]
        missing_axes = [name for name in ("process", "channel", "systematic", "appl") if name not in axis_names]
        if missing_axes:
            raise RuntimeError(f"{key} lacks required axes: {missing_axes}")
        require_finite(histogram.values(flow=True), key)

    njets = histograms["njets"]
    processes = sorted(map(str, njets.axes["process"]))
    missing_labels = sorted(set(expected_labels) - set(processes))
    if missing_labels:
        raise RuntimeError(f"expected process labels are absent: {missing_labels}; got {processes}")
    channels = sorted(map(str, njets.axes["channel"]))
    applications = sorted(map(str, njets.axes["appl"]))
    if not channels:
        raise RuntimeError("njets has no populated channel labels")
    if not applications or not all(item.startswith("isSR") for item in applications):
        raise RuntimeError(f"expected SR-only application labels, got {applications}")
    print(json.dumps({
        "axes": [axis.name for axis in njets.axes],
        "channels": channels,
        "histograms": sorted(histograms),
        "loader": "pass",
        "merge_inputs": merge_report["num_inputs"],
        "processes": processes,
        "role": role,
        "scope": scope,
    }, sort_keys=True))
elif mode == "chunk_partition":
    role, *paths = args
    seen_channels = {}
    for path in paths:
        histograms, _ = load(path)
        histogram = histograms["njets"]
        for channel in map(str, histogram.axes["channel"]):
            values = require_finite(
                histogram[{"channel": channel}].values(flow=True),
                f"njets channel {channel} in {path}",
            )
            if np.any(np.abs(values) > 0.0):
                if channel in seen_channels:
                    raise RuntimeError(
                        f"duplicate populated channel '{channel}' in chunk outputs "
                        f"{seen_channels[channel]} and {path}"
                    )
                seen_channels[channel] = path
    if not seen_channels:
        raise RuntimeError("no populated channels were found in chunk outputs")
    print(json.dumps({"role": role, "populated_channel_count": len(seen_channels), "result": "pass"}, sort_keys=True))
elif mode == "merged_totals":
    canonical_path, *raw_paths = args
    raw, _ = load(raw_paths, on_process_collision="allow")
    canonical, _ = load(canonical_path)
    for key in ("njets", "njets_sumw2"):
        if key not in raw or key not in canonical:
            raise RuntimeError(f"missing {key} during merged-total validation")
        raw_values = require_finite(raw[key].values(flow=True), f"raw {key}")
        canonical_values = require_finite(canonical[key].values(flow=True), f"canonical {key}")
        if raw_values.shape != canonical_values.shape:
            raise RuntimeError(f"{key} shape mismatch: {raw_values.shape} != {canonical_values.shape}")
        if not np.allclose(raw_values, canonical_values, rtol=1.0e-12, atol=1.0e-12):
            raise RuntimeError(f"{key} totals differ from the accumulated raw chunks")
    print(json.dumps({"raw_chunk_count": len(raw_paths), "result": "pass"}, sort_keys=True))
else:
    raise RuntimeError(f"unknown histogram validation mode: {mode}")
PY
}

validate_pkl() {
  local path="$1"
  local role="$2"
  local scope="$3"
  local classification="$4"
  local labels_csv
  local details
  local file_size
  local checksum

  if [[ ! -s "${path}" ]]; then
    printf 'PKL validation failed: missing or empty pkl: %s\n' "${path}" >&2
    return 1
  fi
  if ! gzip -t "${path}"; then
    printf 'PKL validation failed: gzip integrity check failed: %s\n' "${path}" >&2
    return 1
  fi
  labels_csv="$(role_labels_csv "${role}")" || return 1
  if ! details="$(run_histogram_validator pkl "${path}" "${role}" "${scope}" "${labels_csv}")"; then
    printf 'PKL validation failed: loader or histogram contract failed: %s\n' "${path}" >&2
    return 1
  fi
  file_size="$(stat -c '%s' "${path}")"
  checksum="$(sha256sum "${path}" | awk '{print $1}')"
  printf 'validated_pkl: %s\n' "${details}"
  record_validation "${path}" "${role}" "${scope}" "${classification}" "pass" \
    "bytes=${file_size}; sha256=${checksum}; ${details}"
}

validate_chunk_partition() {
  local role="$1"
  shift
  local details

  if ! details="$(run_histogram_validator chunk_partition "${role}" "$@")"; then
    printf 'chunk-partition validation failed for role: %s\n' "${role}" >&2
    return 1
  fi
  printf 'chunk_partition: %s\n' "${details}"
}

validate_merged_totals() {
  local canonical_path="$1"
  shift
  local details

  if ! details="$(run_histogram_validator merged_totals "${canonical_path}" "$@")"; then
    printf 'merged-total validation failed: %s\n' "${canonical_path}" >&2
    return 1
  fi
  printf 'merged_totals: %s\n' "${details}"
}

quarantine_invalid_output() {
  local path="$1"
  local target_path

  [[ -e "${path}" ]] || return 0
  target_path="${output_root}/invalid_outputs/$(basename -- "${path}").invalid.$(timestamp_utc).${RANDOM}"
  mv -- "${path}" "${target_path}"
  record_retry "quarantined_invalid_output" "${path} -> ${target_path}"
}

run_step() {
  local step_name="$1"
  local command_text
  shift

  command_text="$(quote_command "$@")"
  printf '\n===== START %s =====\n' "${step_name}"
  printf 'timestamp=%s\ncommand=%s\n' "$(timestamp_iso)" "${command_text}"
  printf '%s\t%s\t%s\n' "$(timestamp_iso)" "${step_name}" "${command_text}" >> "${execution_commands_file}"
  "$@"
  printf '===== DONE %s timestamp=%s =====\n' "${step_name}" "$(timestamp_iso)"
}

execute_analysis_output() {
  local phase="$1"
  local role="$2"
  local scope="$3"
  local chunk="$4"
  local output_path="$5"
  local category_spec="$6"
  local classification="$7"

  if [[ "${resume_mode}" == true && -e "${output_path}" ]]; then
    if validate_pkl "${output_path}" "${role}" "${scope}" "${classification}"; then
      record_retry "resume_skip_valid" "${output_path}"
      return 0
    fi
    quarantine_invalid_output "${output_path}"
  fi
  [[ ! -e "${output_path}" ]] || die "refusing to overwrite existing output: ${output_path}"
  mkdir -p "$(dirname -- "${output_path}")"
  build_run_analysis_command "${role}" "${scope}" "${output_path}" "${category_spec}"
  run_step "${phase}_${role}_${chunk}" "${resolved_command[@]}"
  validate_pkl "${output_path}" "${role}" "${scope}" "${classification}"
}

canonical_path_for_role() {
  local role="$1"
  printf '%s/all_analysis/canonical/missing_parton_run3_all_analysis_%s_njets.pkl.gz\n' "${output_root}" "${role}"
}

raw_path_for_chunk() {
  local role="$1"
  local chunk_label="$2"
  printf '%s/all_analysis/raw/%s/missing_parton_run3_all_analysis_%s_chunk%s_njets.pkl.gz\n' \
    "${output_root}" "${role}" "${role}" "${chunk_label}"
}

top22006_path_for_role() {
  local role="$1"
  printf '%s/top22006/missing_parton_top22006_run3_%s_njets.pkl.gz\n' "${output_root}" "${role}"
}

validate_raw_output_count() {
  local role="$1"
  local -a raw_paths=()

  mapfile -t raw_paths < <(find "${output_root}/all_analysis/raw/${role}" -maxdepth 1 -type f \
    -name "missing_parton_run3_all_analysis_${role}_chunk*_njets.pkl.gz" -print | sort)
  (( ${#raw_paths[@]} == all_analysis_chunks )) \
    || die "expected ${all_analysis_chunks} raw ${role} chunk outputs, found ${#raw_paths[@]}"
}

canonicalize_role() {
  local role="$1"
  local canonical_path
  local merge_report_path
  local chunk_index
  local chunk_label
  local raw_path
  local -a raw_paths=()

  canonical_path="$(canonical_path_for_role "${role}")"
  for ((chunk_index = 1; chunk_index <= all_analysis_chunks; chunk_index++)); do
    printf -v chunk_label '%02d' "${chunk_index}"
    raw_path="$(raw_path_for_chunk "${role}" "${chunk_label}")"
    raw_paths+=("${raw_path}")
  done
  validate_raw_output_count "${role}"
  validate_chunk_partition "${role}" "${raw_paths[@]}"

  if [[ "${resume_mode}" == true && -e "${canonical_path}" ]]; then
    if validate_pkl "${canonical_path}" "${role}" "all_analysis" "canonical" \
      && validate_merged_totals "${canonical_path}" "${raw_paths[@]}"; then
      record_retry "resume_skip_valid" "${canonical_path}"
      return 0
    fi
    quarantine_invalid_output "${canonical_path}"
  fi
  [[ ! -e "${canonical_path}" ]] || die "refusing to overwrite canonical output: ${canonical_path}"
  mkdir -p "$(dirname -- "${canonical_path}")"
  merge_report_path="${output_root}/all_analysis/canonical/${role}_merge_report.json"
  run_step "canonicalize_${role}" \
    "${environment_wrapper}" /bin/bash --noprofile --norc -c \
    'cd "$1"; shift; exec "$@"' \
    run3_missing_parton_driver "${script_dir}" "${python_env}" make_cards.py \
    "${raw_paths[@]}" --merge-only --on-process-collision allow \
    --merge-report "${merge_report_path}" --cache-merged-pkl "${canonical_path}" \
    --out-dir "$(dirname -- "${canonical_path}")"
  validate_pkl "${canonical_path}" "${role}" "all_analysis" "canonical"
  validate_merged_totals "${canonical_path}" "${raw_paths[@]}"
}

execute_all_analysis() {
  local role
  local chunk_index
  local chunk_label
  local chunk_spec
  local output_path

  write_status "all_analysis_running" "central then private category chunks execute sequentially"
  for role in central_tzq private_tllq; do
    chunk_index=0
    for chunk_spec in "${chunk_specs[@]}"; do
      chunk_index=$((chunk_index + 1))
      printf -v chunk_label '%02d' "${chunk_index}"
      output_path="$(raw_path_for_chunk "${role}" "${chunk_label}")"
      execute_analysis_output "all_analysis" "${role}" "all_analysis" "${chunk_label}" \
        "${output_path}" "${chunk_spec}" "raw_chunk"
    done
  done
  for role in central_tzq private_tllq; do
    canonicalize_role "${role}"
  done
  write_status "all_analysis_validated" "all raw chunks and canonical role inputs passed validation"
}

execute_top22006() {
  local role
  local output_path

  write_status "top22006_running" "central then private TOP-22-006 commands execute sequentially"
  for role in central_tzq private_tllq; do
    output_path="$(top22006_path_for_role "${role}")"
    execute_analysis_output "top22006" "${role}" "top22006" "single" \
      "${output_path}" "${top22006_groups[*]}" "diagnostic"
  done
  write_status "top22006_validated" "both TOP-22-006 diagnostic PKLs passed validation"
}

validate_final_outputs() {
  local classification
  local scope
  local role
  local chunk
  local path
  local -a raw_paths=()
  local chunk_index
  local chunk_label

  while IFS=$'\t' read -r classification scope role chunk path; do
    [[ "${classification}" == "classification" ]] && continue
    validate_pkl "${path}" "${role}" "${scope}" "${classification}"
  done < "${output_contract_file}"
  for role in central_tzq private_tllq; do
    raw_paths=()
    for ((chunk_index = 1; chunk_index <= all_analysis_chunks; chunk_index++)); do
      printf -v chunk_label '%02d' "${chunk_index}"
      raw_paths+=("$(raw_path_for_chunk "${role}" "${chunk_label}")")
    done
    validate_raw_output_count "${role}"
    validate_chunk_partition "${role}" "${raw_paths[@]}"
    validate_merged_totals "$(canonical_path_for_role "${role}")" "${raw_paths[@]}"
  done
}

write_checksum_inventory() {
  local inventory_path="${output_root}/pkl_manifest.sha256"
  local classification
  local scope
  local role
  local chunk
  local path

  while IFS=$'\t' read -r classification scope role chunk path; do
    [[ "${classification}" == "classification" ]] && continue
    [[ -f "${path}" ]] || die "checksum inventory is missing output: ${path}"
    sha256sum "${path}"
  done < "${output_contract_file}" > "${inventory_path}"
}

main() {
  parse_args "$@"
  assert_operational_prerequisites

  if [[ "${resume_mode}" == true ]]; then
    initialize_existing_campaign
  else
    initialize_new_campaign
  fi
  exec > >(tee -a "${log_file}") 2>&1

  load_category_groups
  build_chunk_specs
  load_process_labels "${central_cfg}" central_process_labels
  load_process_labels "${private_cfg}" private_process_labels

  if [[ "${resume_mode}" == true ]]; then
    verify_resume_contract
    write_status "running" "resume accepted; completed outputs will be revalidated"
  else
    write_output_contract "${output_contract_file}"
    write_status "running" "fresh campaign started"
  fi

  execute_all_analysis
  execute_top22006
  validate_final_outputs
  write_checksum_inventory
  write_status "success" "all required raw, canonical, and TOP-22-006 PKLs passed validation"
  printf 'SUCCESS: campaign outputs and checksum manifest are complete under %s\n' "${output_root}"
}

main "$@"
