#!/usr/bin/env bash
#
# Produce the immutable Run 3 missing-parton input-pkl campaign.  This driver
# deliberately stops after pkl validation: payload and DatacardMaker work are
# separate consumers of the resulting canonical inputs.

set -Eeuo pipefail

public_baseline="7f7d77f5d4ff45238b9622b4c29f6390a7cbabc0"
topcoffea_baseline="8b660e749f53fdc7fa9a16dab0082ffe6e370d90"
run3_years=(2022 2022EE 2023 2023BPix)

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
topeft_repo="$(cd -- "${script_dir}/../.." && pwd)"
workspace_root="$(cd -- "${topeft_repo}/.." && pwd)"
topcoffea_repo="${workspace_root}/topcoffea"
driver_relpath="analysis/topeft_run2/$(basename -- "${BASH_SOURCE[0]}")"
environment_wrapper="${workspace_root}/codex-run.sh"
python_env="${PYTHON_ENV:-/users/apiccine/work/miniconda3/envs/clib-env/bin/python}"
default_output_parent="/groups/klannon/apiccine/misspar_debug"
executor="${MISSING_PARTON_EXECUTOR:-work_queue}"
all_analysis_chunks="${ALL_ANALYSIS_CHUNKS:-2}"

central_cfg="input_samples/cfgs/missing_parton_run3_central_tzq_NDSkim.cfg"
private_cfg="input_samples/cfgs/missing_parton_run3_private_tllq_NDSkim.cfg"

mode=""
output_root=""
resume_mode=false
validate_only_mode=false
current_phase="preflight"
manifest_file=""
status_file=""
state_history_file=""
retry_history_file=""
command_plan_file=""
output_contract_file=""
call_chain_file=""
validation_file=""
log_file=""
campaign_lock_dir=""
campaign_lock_fd=""

declare -a all_analysis_groups=()
declare -a top22006_groups=()
declare -a chunk_specs=()
declare -a central_process_labels=()
declare -a private_process_labels=()

usage() {
  cat <<'USAGE_EOF'
Usage:
  run_run3_missing_parton_pkls_overnight.sh --dry-run-only [output_root]
  run_run3_missing_parton_pkls_overnight.sh --execute [output_root]
  run_run3_missing_parton_pkls_overnight.sh --resume <existing_output_root>
  run_run3_missing_parton_pkls_overnight.sh --validate-only <existing_output_root>

Prepare one immutable Run 3 campaign containing, in order:
  1. all-analysis central NLO tZq category chunks;
  2. all-analysis private LO tllq category chunks;
  3. canonical merged all-analysis central/private pkls;
  4. TOP-22-006 central NLO tZq and private LO tllq diagnostic pkls.

No mode is implicit.  --execute is the only mode that can run event processing.
--dry-run-only creates a fresh campaign plan and executes no production command.
--resume revalidates completed outputs and runs only incomplete/invalid phases.
--validate-only is read-only with respect to an existing campaign root.

Environment overrides:
  ALL_ANALYSIS_CHUNKS      positive integer >= 2 (default: 2)
  MISSING_PARTON_EXECUTOR  futures, work_queue, or taskvine (default: work_queue)
  PYTHON_ENV               pinned interpreter (default: correction-lib clib-env)
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
    printf -v argument '%q' "$argument"
    quoted+="${quoted:+ }${argument}"
  done
  printf '%s\n' "${quoted}"
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

assert_clean_tracked_repo() {
  local repo_path="$1"
  local repo_name="$2"

  if [[ -n "$(git -C "${repo_path}" diff --name-only)" ]]; then
    die "${repo_name} has unstaged tracked changes"
  fi
  if [[ -n "$(git -C "${repo_path}" diff --cached --name-only)" ]]; then
    die "${repo_name} has staged tracked changes"
  fi
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
  [[ -n "${retry_history_file}" ]] || return 0
  printf '%s\t%s\t%s\n' "$(timestamp_iso)" "${action}" "${detail}" >> "${retry_history_file}"
}

on_error() {
  local exit_code="$1"
  local line_number="$2"
  local failed_command="$3"
  trap - ERR
  printf '\nFAILED: phase=%s exit_code=%s line=%s command=%s\n' \
    "${current_phase}" "${exit_code}" "${line_number}" "${failed_command}" >&2
  if [[ "${validate_only_mode}" != true && -n "${status_file}" ]]; then
    write_status "failed" "phase=${current_phase}; exit_code=${exit_code}; line=${line_number}; command=${failed_command}" || true
  fi
  if [[ "${validate_only_mode}" != true && -n "${manifest_file}" && -e "${manifest_file}" ]]; then
    write_manifest "failed" || true
  fi
  exit "${exit_code}"
}

on_signal() {
  local signal_name="$1"
  trap - INT TERM
  printf '\nINTERRUPTED: phase=%s signal=%s\n' "${current_phase}" "${signal_name}" >&2
  if [[ "${validate_only_mode}" != true && -n "${status_file}" ]]; then
    write_status "interrupted" "phase=${current_phase}; signal=${signal_name}" || true
  fi
  if [[ "${validate_only_mode}" != true && -n "${manifest_file}" && -e "${manifest_file}" ]]; then
    write_manifest "interrupted" || true
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
      --dry-run-only|--execute|--validate-only)
        [[ -z "${mode}" ]] || die "select exactly one mode"
        mode="$1"
        shift
        ;;
      --resume)
        [[ -z "${mode}" ]] || die "select exactly one mode"
        [[ $# -ge 2 ]] || die "--resume requires an existing output root"
        mode="--resume"
        output_root="$2"
        shift 2
        ;;
      --all-analysis-chunks)
        [[ $# -ge 2 ]] || die "--all-analysis-chunks requires an integer"
        all_analysis_chunks="$2"
        shift 2
        ;;
      --executor)
        [[ $# -ge 2 ]] || die "--executor requires a value"
        executor="$2"
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
        [[ -z "${positional_root}" ]] || die "only one output root may be supplied"
        positional_root="$1"
        shift
        ;;
    esac
  done

  [[ -n "${mode}" ]] || die "choose --dry-run-only, --execute, --resume, or --validate-only"
  if [[ "${mode}" == "--resume" ]]; then
    [[ -z "${positional_root}" ]] || die "--resume accepts its output root directly after the flag"
  else
    output_root="${positional_root}"
  fi

  case "${executor}" in
    futures|work_queue|taskvine) ;;
    *) die "--executor must be futures, work_queue, or taskvine" ;;
  esac
  is_positive_integer "${all_analysis_chunks}" || die "ALL_ANALYSIS_CHUNKS must be a positive integer"
  (( all_analysis_chunks >= 2 )) || die "ALL_ANALYSIS_CHUNKS must be at least 2"

  if [[ -z "${output_root}" && "${mode}" != "--resume" ]]; then
    output_root="${default_output_parent}/run3_missing_parton_$(timestamp_utc)_${public_baseline:0:12}"
  fi
}

assert_static_prerequisites() {
  local changed_path

  [[ -d "${topeft_repo}/.git" ]] || die "topeft repository is unavailable: ${topeft_repo}"
  [[ -d "${topcoffea_repo}/.git" ]] || die "topcoffea repository is unavailable: ${topcoffea_repo}"
  [[ -x "${environment_wrapper}" ]] || die "environment wrapper is unavailable: ${environment_wrapper}"
  [[ -x "${python_env}" ]] || die "Python interpreter is unavailable: ${python_env}"
  git -C "${topeft_repo}" cat-file -e "${public_baseline}^{commit}"
  assert_clean_tracked_repo "${topeft_repo}" "topeft"
  assert_clean_tracked_repo "${topcoffea_repo}" "topcoffea"
  [[ "$(git -C "${topcoffea_repo}" rev-parse HEAD)" == "${topcoffea_baseline}" ]] \
    || die "topcoffea HEAD must equal ${topcoffea_baseline}"
  while IFS= read -r changed_path; do
    [[ -z "${changed_path}" || "${changed_path}" == "${driver_relpath}" ]] && continue
    die "feature branch differs from the public production baseline outside the driver: ${changed_path}"
  done < <(git -C "${topeft_repo}" diff --name-only "${public_baseline}...HEAD")
}

assert_committed_driver_for_execution() {
  if [[ "${mode}" != "--execute" && "${mode}" != "--resume" ]]; then
    return 0
  fi
  git -C "${topeft_repo}" ls-files --error-unmatch "${driver_relpath}" >/dev/null \
    || die "--execute/--resume require the driver to be committed"
  git -C "${topeft_repo}" diff --quiet -- "${driver_relpath}" \
    || die "the tracked driver has unstaged changes"
  git -C "${topeft_repo}" diff --cached --quiet -- "${driver_relpath}" \
    || die "the tracked driver has staged changes"
}

acquire_campaign_lock() {
  command -v flock >/dev/null 2>&1 || die "flock is required for exclusive campaign ownership"
  exec 9>"${campaign_lock_dir}/active.lock"
  flock -n 9 || die "another driver process owns this campaign root: ${output_root}"
  campaign_lock_fd=9
  printf 'pid=%s\nstarted=%s\nmode=%s\n' "$$" "$(timestamp_iso)" "${mode}" > "${campaign_lock_dir}/owner.txt"
}

read_json_keys() {
  local key="$1"
  run_python - "${topeft_repo}/topeft/channels/ch_lst.json" "${key}" <<'PY'
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
  local cfg_path="${topeft_repo}/${cfg_relpath}"
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
      [[ "${absolute_path}" == "${topeft_repo}/"* ]] \
        || die "cfg input lies outside topeft: ${token}"
      [[ -f "${absolute_path}" ]] || die "cfg references a missing JSON: ${absolute_path}"
      printf '%s\n' "${absolute_path#"${topeft_repo}/"}"
    done
  done < "${cfg_path}"
}

load_process_labels() {
  local cfg_relpath="$1"
  local -n labels_ref="$2"
  local -a json_relpaths=()

  mapfile -t json_relpaths < <(cfg_json_relpaths "${cfg_relpath}")
  mapfile -t labels_ref < <(
    run_python - "${topeft_repo}" "${json_relpaths[@]}" <<'PY'
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

record_call_chain() {
  local destination="$1"
  local path
  local baseline_blob
  local current_blob
  local -a paths=(
    analysis/topeft_run2/run_analysis.py
    analysis/topeft_run2/analysis_processor.py
    analysis/topeft_run2/make_cards.py
    topeft/modules/datacard_tools.py
    topeft/modules/axes.py
    topeft/modules/corrections.py
    topeft/modules/event_selection.py
    topeft/modules/object_selection.py
    topeft/modules/paths.py
    topeft/modules/ttgamma_photon_history.py
    topeft/modules/dataDrivenEstimation.py
    topeft/modules/deferred_np_metadata.py
    topeft/modules/get_renormfact_envelope.py
    topeft/channels/ch_lst.json
    topeft/params/params.json
    "${central_cfg}"
    "${private_cfg}"
  )
  local -a input_jsons=()

  mapfile -t input_jsons < <(cfg_json_relpaths "${central_cfg}")
  paths+=("${input_jsons[@]}")
  mapfile -t input_jsons < <(cfg_json_relpaths "${private_cfg}")
  paths+=("${input_jsons[@]}")

  printf 'path\tpublic_baseline_blob\tcurrent_blob\tmust_match_public\tresult\n' > "${destination}"
  for path in "${paths[@]}"; do
    baseline_blob="$(git -C "${topeft_repo}" rev-parse "${public_baseline}:${path}")" \
      || die "public baseline is missing production input: ${path}"
    current_blob="$(git -C "${topeft_repo}" rev-parse "HEAD:${path}")" \
      || die "current branch is missing production input: ${path}"
    if [[ "${baseline_blob}" != "${current_blob}" ]]; then
      printf '%s\t%s\t%s\tyes\tfail\n' "${path}" "${baseline_blob}" "${current_blob}" >> "${destination}"
      die "production-affecting blob differs from public baseline: ${path}"
    fi
    printf '%s\t%s\t%s\tyes\tpass\n' "${path}" "${baseline_blob}" "${current_blob}" >> "${destination}"
  done
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
    central_tzq) cfg="${central_cfg}" ;;
    private_tllq) cfg="${private_cfg}" ;;
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

append_plan_command() {
  local phase="$1"
  local role="$2"
  local scope="$3"
  local chunk="$4"
  local output_path="$5"
  local category_spec="$6"
  local systematics="nominal_only"
  local command_text
  local cfg

  build_run_analysis_command "${role}" "${scope}" "${output_path}" "${category_spec}"
  command_text="$(quote_command "${resolved_command[@]}")"
  cfg="${central_cfg}"
  if [[ "${role}" == "private_tllq" ]]; then
    cfg="${private_cfg}"
    systematics="with_systematics"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${phase}" "${role}" "${scope}" "${chunk}" "${cfg}" \
    "${run3_years[*]}" "${systematics}" "${output_path}" "${command_text}" \
    >> "${command_plan_file}"
}

build_command_plan() {
  local chunk_index
  local chunk_label
  local chunk_spec
  local role
  local output_path

  load_category_groups
  build_chunk_specs
  load_process_labels "${central_cfg}" central_process_labels
  load_process_labels "${private_cfg}" private_process_labels

  printf 'phase\trole\tscope\tchunk\tcfg\tperiods\tsystematics\toutput\texact_command\n' > "${command_plan_file}"
  printf 'classification\tphase\trole\tchunk\tpath\n' > "${output_contract_file}"

  for role in central_tzq private_tllq; do
    chunk_index=0
    for chunk_spec in "${chunk_specs[@]}"; do
      chunk_index=$((chunk_index + 1))
      printf -v chunk_label '%02d' "${chunk_index}"
      output_path="${output_root}/all_analysis/raw/${role}/missing_parton_run3_all_analysis_${role}_chunk${chunk_label}_njets.pkl.gz"
      append_plan_command "all_analysis" "${role}" "all_analysis" "${chunk_label}" "${output_path}" "${chunk_spec}"
      printf 'raw_chunk\tall_analysis\t%s\t%s\t%s\n' "${role}" "${chunk_label}" "${output_path}" >> "${output_contract_file}"
    done
  done

  for role in central_tzq private_tllq; do
    output_path="${output_root}/all_analysis/canonical/missing_parton_run3_all_analysis_${role}_njets.pkl.gz"
    printf 'canonical\tall_analysis\t%s\tmerged\t%s\n' "${role}" "${output_path}" >> "${output_contract_file}"
  done

  for role in central_tzq private_tllq; do
    output_path="${output_root}/top22006/missing_parton_top22006_run3_${role}_njets.pkl.gz"
    append_plan_command "top22006" "${role}" "top22006" "single" "${output_path}" "${top22006_groups[*]}"
    printf 'diagnostic\ttop22006\t%s\tsingle\t%s\n' "${role}" "${output_path}" >> "${output_contract_file}"
  done
}

validate_command_plan() {
  local expected_count=$((2 * all_analysis_chunks + 2))
  local actual_count

  actual_count="$(tail -n +2 "${command_plan_file}" | wc -l)"
  [[ "${actual_count}" -eq "${expected_count}" ]] \
    || die "command plan has ${actual_count} commands, expected ${expected_count}"
  rg -q $'^all_analysis\tcentral_tzq\tall_analysis' "${command_plan_file}" \
    || die "missing all-analysis central commands"
  rg -q $'^all_analysis\tprivate_tllq\tall_analysis' "${command_plan_file}" \
    || die "missing all-analysis private commands"
  rg -q $'^top22006\tcentral_tzq\ttop22006' "${command_plan_file}" \
    || die "missing TOP-22-006 central command"
  rg -q $'^top22006\tprivate_tllq\ttop22006' "${command_plan_file}" \
    || die "missing TOP-22-006 private command"
  rg -q -- '--skip-cr' "${command_plan_file}" || die "command plan must be SR-only"
  rg -q -- '--hist-list njets' "${command_plan_file}" || die "command plan must request njets"
  ! rg -q -- '--no-sumw2' "${command_plan_file}" || die "command plan must retain njets_sumw2"
  ! rg -q -- 'missing_parton\.py|DatacardMaker|combine' "${command_plan_file}" \
    || die "command plan must not generate payloads or cards"
  while IFS=$'\t' read -r phase role scope chunk cfg periods systematics output_path command_text; do
    [[ "${phase}" == "phase" ]] && continue
    [[ "${periods}" == "${run3_years[*]}" ]] || die "command periods differ from Run 3 contract"
    [[ "${command_text}" == *"--executor ${executor}"* ]] || die "command executor differs from selected executor"
    if [[ "${role}" == "central_tzq" ]]; then
      [[ "${systematics}" == "nominal_only" && "${command_text}" != *"--do-systs"* ]] \
        || die "central command must be nominal-only"
    else
      [[ "${systematics}" == "with_systematics" && "${command_text}" == *"--do-systs"* ]] \
        || die "private command must enable systematics"
    fi
    if [[ "${scope}" == "all_analysis" ]]; then
      [[ "${command_text}" == *"--all-analysis"* ]] || die "all-analysis command lacks --all-analysis"
    else
      [[ "${command_text}" != *"--all-analysis"* ]] || die "TOP-22-006 command must not use --all-analysis"
    fi
  done < "${command_plan_file}"
}

write_manifest() {
  local state="$1"
  local driver_checksum
  local wrapper_checksum
  local driver_commit
  local branch

  driver_checksum="$(sha256sum "${script_dir}/$(basename -- "${BASH_SOURCE[0]}")" | awk '{print $1}')"
  wrapper_checksum="$(sha256sum "${environment_wrapper}" | awk '{print $1}')"
  driver_commit="$(git -C "${topeft_repo}" rev-parse HEAD)"
  branch="$(git -C "${topeft_repo}" branch --show-current)"

  run_python - \
    "${manifest_file}" "${output_root}" "${state}" "${mode}" \
    "${public_baseline}" "${topcoffea_baseline}" "${driver_relpath}" \
    "${driver_checksum}" "${driver_commit}" "${branch}" "${python_env}" \
    "${environment_wrapper}" "${wrapper_checksum}" "${executor}" "${all_analysis_chunks}" <<'PY'
import csv
import datetime as dt
import gzip
import hashlib
import importlib.metadata
import json
import os
import pathlib
import sys

(manifest_path, root, state, mode, public_baseline, topcoffea_baseline,
 driver_path, driver_checksum, driver_commit, branch, python_env,
 wrapper_path, wrapper_checksum, executor, chunk_count) = sys.argv[1:]
root_path = pathlib.Path(root)

def read_tsv(name):
    path = root_path / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))

def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

def file_record(row):
    path = pathlib.Path(row["path"])
    record = dict(row)
    record["exists"] = path.is_file()
    if path.is_file():
        record["size_bytes"] = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        record["sha256"] = digest.hexdigest()
        try:
            with gzip.open(path, "rb") as stream:
                while stream.read(1024 * 1024):
                    pass
            record["gzip_validation"] = "pass"
        except Exception as exc:
            record["gzip_validation"] = f"fail: {exc}"
    return record

contract = read_tsv("output_contract.tsv")
payload = {
    "campaign_id": root_path.name,
    "manifest_version": 1,
    "start_or_update_timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "completion_state": state,
    "mode": mode,
    "output_root": str(root_path),
    "public_baseline_commit": public_baseline,
    "active_branch": branch,
    "driver": {"path": driver_path, "sha256": driver_checksum, "commit": driver_commit},
    "topcoffea_commit": topcoffea_baseline,
    "environment": {
        "python_interpreter": python_env,
        "python_version": sys.version,
        "environment_prefix": os.environ.get("CONDA_PREFIX"),
        "wrapper_path": wrapper_path,
        "wrapper_sha256": wrapper_checksum,
        "executor": executor,
        "package_versions": {name: package_version(name) for name in ("coffea", "awkward", "hist", "numpy", "cloudpickle")},
    },
    "periods": ["2022", "2022EE", "2023", "2023BPix"],
    "all_analysis_chunk_count": int(chunk_count),
    "production_call_chain": read_tsv("production_call_chain.tsv"),
    "commands": read_tsv("command_plan.tsv"),
    "dry_run_commands": read_tsv("command_plan.tsv"),
    "execution_commands": read_tsv("command_plan.tsv"),
    "output_contract": contract,
    "outputs": [file_record(row) for row in contract],
    "state_history": read_tsv("state_history.tsv"),
    "retry_history": read_tsv("retry_history.tsv"),
    "validation_records": read_tsv("output_validation.tsv"),
    "logs": {"run_log": str(root_path / "run.log"), "status": str(root_path / "status.txt")},
}
with open(manifest_path, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY
}

initialize_new_campaign() {
  if [[ -e "${output_root}" ]]; then
    [[ -d "${output_root}" ]] || die "output root exists and is not a directory: ${output_root}"
    [[ -z "$(find "${output_root}" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
      || die "output root is not empty and cannot be reused: ${output_root}"
  else
    mkdir -p "${output_root}"
  fi

  campaign_lock_dir="${output_root}/.campaign_lock"
  mkdir "${campaign_lock_dir}" || die "campaign root is already locked: ${output_root}"
  acquire_campaign_lock
  log_file="${output_root}/run.log"
  status_file="${output_root}/status.txt"
  state_history_file="${output_root}/state_history.tsv"
  retry_history_file="${output_root}/retry_history.tsv"
  command_plan_file="${output_root}/command_plan.tsv"
  output_contract_file="${output_root}/output_contract.tsv"
  call_chain_file="${output_root}/production_call_chain.tsv"
  validation_file="${output_root}/output_validation.tsv"
  manifest_file="${output_root}/campaign_manifest.json"

  printf 'timestamp\tstate\tdetail\n' > "${state_history_file}"
  printf 'timestamp\taction\tdetail\n' > "${retry_history_file}"
  printf 'path\trole\tscope\tclassification\tresult\tdetail\n' > "${validation_file}"
  exec > >(tee -a "${log_file}") 2>&1
}

initialize_existing_campaign() {
  [[ -d "${output_root}" ]] || die "campaign root does not exist: ${output_root}"
  campaign_lock_dir="${output_root}/.campaign_lock"
  [[ -d "${campaign_lock_dir}" ]] || die "campaign lock marker is missing: ${output_root}"
  log_file="${output_root}/run.log"
  status_file="${output_root}/status.txt"
  state_history_file="${output_root}/state_history.tsv"
  retry_history_file="${output_root}/retry_history.tsv"
  command_plan_file="${output_root}/command_plan.tsv"
  output_contract_file="${output_root}/output_contract.tsv"
  call_chain_file="${output_root}/production_call_chain.tsv"
  validation_file="${output_root}/output_validation.tsv"
  manifest_file="${output_root}/campaign_manifest.json"
  [[ -f "${manifest_file}" && -f "${command_plan_file}" && -f "${call_chain_file}" ]] \
    || die "campaign root lacks the required driver metadata"
  if [[ "${validate_only_mode}" != true ]]; then
    acquire_campaign_lock
  fi
}

assert_resume_identity() {
  local temporary_dir
  local temporary_plan
  local temporary_contract
  local temporary_call_chain
  local stored_status
  local stored_identity
  local current_driver_checksum

  stored_status="$(awk -F= '$1 == "state" {print $2}' "${status_file}" 2>/dev/null || true)"
  [[ "${stored_status}" != "success" ]] || die "a successful campaign is immutable; use --validate-only"
  current_driver_checksum="$(sha256sum "${script_dir}/$(basename -- "${BASH_SOURCE[0]}")" | awk '{print $1}')"
  stored_identity="$(run_python - "${manifest_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
print("\t".join((
    payload.get("public_baseline_commit", ""),
    payload.get("topcoffea_commit", ""),
    payload.get("driver", {}).get("sha256", ""),
    str(payload.get("all_analysis_chunk_count", "")),
)))
PY
)"
  IFS=$'\t' read -r stored_public stored_topcoffea stored_driver_checksum stored_chunk_count <<< "${stored_identity}"
  [[ "${stored_public}" == "${public_baseline}" ]] || die "resume public baseline differs from campaign metadata"
  [[ "${stored_topcoffea}" == "${topcoffea_baseline}" ]] || die "resume topcoffea pin differs from campaign metadata"
  [[ "${stored_driver_checksum}" == "${current_driver_checksum}" ]] || die "resume driver checksum differs from campaign metadata"
  [[ "${stored_chunk_count}" == "${all_analysis_chunks}" ]] || die "resume chunk count differs from campaign metadata"
  temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/run3_missing_parton_resume.XXXXXX")"
  temporary_plan="${temporary_dir}/command_plan.tsv"
  temporary_contract="${temporary_dir}/output_contract.tsv"
  temporary_call_chain="${temporary_dir}/production_call_chain.tsv"

  command_plan_file="${temporary_plan}"
  output_contract_file="${temporary_contract}"
  build_command_plan
  validate_command_plan
  record_call_chain "${temporary_call_chain}"
  cmp --silent "${temporary_plan}" "${output_root}/command_plan.tsv" \
    || die "resume command plan differs from the original campaign"
  cmp --silent "${temporary_contract}" "${output_root}/output_contract.tsv" \
    || die "resume output contract differs from the original campaign"
  cmp --silent "${temporary_call_chain}" "${output_root}/production_call_chain.tsv" \
    || die "resume call-chain hashes differ from the original campaign"
  command_plan_file="${output_root}/command_plan.tsv"
  output_contract_file="${output_root}/output_contract.tsv"
  call_chain_file="${output_root}/production_call_chain.tsv"
  record_retry "resume_verified" "command plan, baseline blobs, cfgs, JSONs, and dependency pin match"
}

record_validation() {
  local path="$1"
  local role="$2"
  local scope="$3"
  local classification="$4"
  local result="$5"
  local detail="$6"
  [[ -n "${validation_file}" && -e "${validation_file}" ]] || return 0
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

validate_pkl() {
  local path="$1"
  local role="$2"
  local scope="$3"
  local classification="$4"
  local labels_csv
  local details

  [[ -s "${path}" ]] || die "missing or empty pkl: ${path}"
  gzip -t "${path}"
  labels_csv="$(role_labels_csv "${role}")"
  details="$(run_python - "${path}" "${role}" "${scope}" "${labels_csv}" <<'PY'
import json
import math
import sys

import numpy as np
from topeft.modules.datacard_tools import load_and_merge_histogram_pkls

path, role, scope, labels_csv = sys.argv[1:]
expected_labels = [item for item in labels_csv.split(",") if item]
histograms, merge_report = load_and_merge_histogram_pkls([path], require_sumw2=True)
for key in ("njets", "njets_sumw2"):
    if key not in histograms:
        raise RuntimeError(f"missing required histogram: {key}")
    histogram = histograms[key]
    axis_names = [axis.name for axis in histogram.axes]
    missing_axes = [name for name in ("process", "channel", "systematic", "appl") if name not in axis_names]
    if missing_axes:
        raise RuntimeError(f"{key} lacks required axes: {missing_axes}")
    values = np.asarray(histogram.values(flow=True))
    if not np.isfinite(values).all():
        raise RuntimeError(f"{key} contains NaN or infinite bin content")

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
    "loader": "pass",
    "histograms": sorted(histograms),
    "axes": [axis.name for axis in njets.axes],
    "processes": processes,
    "channels": channels,
    "applications": applications,
    "expected_year_process_labels": expected_labels,
    "role": role,
    "scope": scope,
    "merge_inputs": merge_report["num_inputs"],
}, sort_keys=True))
PY
)"
  printf 'validated_pkl: %s\n' "${details}"
  record_validation "${path}" "${role}" "${scope}" "${classification}" "pass" "${details}"
}

validate_chunk_partition() {
  local role="$1"
  shift
  local details

  details="$(run_python - "${role}" "$@" <<'PY'
import json
import sys

import numpy as np
from topeft.modules.datacard_tools import load_and_merge_histogram_pkls

role = sys.argv[1]
paths = sys.argv[2:]
seen_channels = {}
for path in paths:
    histograms, _ = load_and_merge_histogram_pkls([path], require_sumw2=True)
    histogram = histograms["njets"]
    for channel in map(str, histogram.axes["channel"]):
        values = np.asarray(histogram[{"channel": channel}].values(flow=True))
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
PY
)"
  printf 'chunk_partition: %s\n' "${details}"
}

validate_merged_totals() {
  local canonical_path="$1"
  shift
  local details

  details="$(run_python - "${canonical_path}" "$@" <<'PY'
import json
import sys

import numpy as np
from topeft.modules.datacard_tools import load_and_merge_histogram_pkls

canonical_path = sys.argv[1]
raw_paths = sys.argv[2:]
raw, _ = load_and_merge_histogram_pkls(raw_paths, on_process_collision="allow", require_sumw2=True)
canonical, _ = load_and_merge_histogram_pkls([canonical_path], require_sumw2=True)
for key in ("njets", "njets_sumw2"):
    if key not in raw or key not in canonical:
        raise RuntimeError(f"missing {key} during merged-total validation")
    raw_values = np.asarray(raw[key].values(flow=True))
    canonical_values = np.asarray(canonical[key].values(flow=True))
    if raw_values.shape != canonical_values.shape:
        raise RuntimeError(f"{key} shape mismatch: {raw_values.shape} != {canonical_values.shape}")
    if not np.allclose(raw_values, canonical_values, rtol=1.0e-12, atol=1.0e-12):
        raise RuntimeError(f"{key} totals differ from the accumulated raw chunks")
print(json.dumps({"raw_chunk_count": len(raw_paths), "result": "pass"}, sort_keys=True))
PY
)"
  printf 'merged_totals: %s\n' "${details}"
}

quarantine_invalid_output() {
  local path="$1"
  local target_dir="${output_root}/invalid_outputs"
  local target_path

  [[ -e "${path}" ]] || return 0
  mkdir -p "${target_dir}"
  target_path="${target_dir}/$(basename -- "${path}").invalid.$(timestamp_utc).${RANDOM}"
  mv -- "${path}" "${target_path}"
  record_retry "quarantined_invalid_output" "${path} -> ${target_path}"
}

run_step() {
  local step_name="$1"
  shift
  printf '\n===== START %s =====\n' "${step_name}"
  printf 'timestamp=%s\ncommand=%s\n' "$(timestamp_iso)" "$(quote_command "$@")"
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

canonicalize_role() {
  local role="$1"
  local canonical_path
  local merge_report_path
  local chunk_index
  local chunk_label
  local -a raw_paths=()
  local raw_path

  canonical_path="$(canonical_path_for_role "${role}")"
  for ((chunk_index = 1; chunk_index <= all_analysis_chunks; chunk_index++)); do
    printf -v chunk_label '%02d' "${chunk_index}"
    raw_path="$(raw_path_for_chunk "${role}" "${chunk_label}")"
    raw_paths+=("${raw_path}")
  done
  validate_chunk_partition "${role}" "${raw_paths[@]}"

  if [[ "${resume_mode}" == true && -e "${canonical_path}" ]]; then
    if validate_pkl "${canonical_path}" "${role}" "all_analysis" "canonical"; then
      validate_merged_totals "${canonical_path}" "${raw_paths[@]}"
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
  write_manifest "all_analysis_validated"
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
  write_status "top22006_validated" "both TOP-22-006 diagnostic pkls passed validation"
  write_manifest "top22006_validated"
}

write_checksum_inventory() {
  local inventory_path="${output_root}/pkl_manifest.sha256"
  while IFS=$'\t' read -r classification phase role chunk path; do
    [[ "${classification}" == "classification" ]] && continue
    [[ -f "${path}" ]] || die "checksum inventory is missing output: ${path}"
    sha256sum "${path}"
  done < "${output_contract_file}" > "${inventory_path}"
}

print_dry_run() {
  write_status "dry_run" "complete command plan resolved; no production command was launched"
  printf '\n===== DRY-RUN COMMAND PLAN =====\n'
  cat "${command_plan_file}"
  printf '===== DRY-RUN OUTPUT CONTRACT =====\n'
  cat "${output_contract_file}"
  printf '===== DRY-RUN CALL-CHAIN HASHES =====\n'
  cat "${call_chain_file}"
  write_manifest "dry_run_complete"
  printf 'dry-run-only complete: no run_analysis.py or make_cards.py command was executed.\n'
}

validate_existing_campaign() {
  local temporary_dir
  local temporary_plan
  local temporary_contract
  local temporary_call_chain
  local classification
  local phase
  local role
  local chunk
  local path

  initialize_existing_campaign
  assert_static_prerequisites
  temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/run3_missing_parton_validate.XXXXXX")"
  temporary_plan="${temporary_dir}/command_plan.tsv"
  temporary_contract="${temporary_dir}/output_contract.tsv"
  temporary_call_chain="${temporary_dir}/production_call_chain.tsv"
  command_plan_file="${temporary_plan}"
  output_contract_file="${temporary_contract}"
  build_command_plan
  validate_command_plan
  record_call_chain "${temporary_call_chain}"
  cmp --silent "${temporary_plan}" "${output_root}/command_plan.tsv" \
    || die "validate-only command plan differs from the original campaign"
  cmp --silent "${temporary_contract}" "${output_root}/output_contract.tsv" \
    || die "validate-only output contract differs from the original campaign"
  cmp --silent "${temporary_call_chain}" "${output_root}/production_call_chain.tsv" \
    || die "validate-only call-chain hashes differ from the original campaign"
  command_plan_file="${output_root}/command_plan.tsv"
  output_contract_file="${output_root}/output_contract.tsv"
  call_chain_file="${output_root}/production_call_chain.tsv"
  validation_file=""

  while IFS=$'\t' read -r classification phase role chunk path; do
    [[ "${classification}" == "classification" ]] && continue
    validate_pkl "${path}" "${role}" "${phase}" "${classification}"
  done < "${output_contract_file}"
  for role in central_tzq private_tllq; do
    local -a raw_paths=()
    local chunk_index
    local chunk_label
    for ((chunk_index = 1; chunk_index <= all_analysis_chunks; chunk_index++)); do
      printf -v chunk_label '%02d' "${chunk_index}"
      raw_paths+=("$(raw_path_for_chunk "${role}" "${chunk_label}")")
    done
    validate_chunk_partition "${role}" "${raw_paths[@]}"
    validate_merged_totals "$(canonical_path_for_role "${role}")" "${raw_paths[@]}"
  done
  printf 'validate-only complete: campaign metadata and every output passed read-only validation.\n'
}

main() {
  parse_args "$@"

  if [[ "${mode}" == "--validate-only" ]]; then
    validate_only_mode=true
    validate_existing_campaign
    return 0
  fi

  if [[ "${mode}" == "--resume" ]]; then
    resume_mode=true
    initialize_existing_campaign
    exec > >(tee -a "${log_file}") 2>&1
    assert_static_prerequisites
    assert_committed_driver_for_execution
    assert_resume_identity
    write_status "preflight" "resume identity verification passed"
  else
    initialize_new_campaign
    assert_static_prerequisites
    assert_committed_driver_for_execution
    write_status "preflight" "new campaign root accepted"
    record_call_chain "${call_chain_file}"
    build_command_plan
    validate_command_plan
    write_manifest "preflight"
  fi

  if [[ "${mode}" == "--dry-run-only" ]]; then
    print_dry_run
    return 0
  fi

  write_status "dry_run" "execution command plan validated before event processing"
  printf '\n===== VALIDATED EXECUTION COMMAND PLAN =====\n'
  cat "${command_plan_file}"
  execute_all_analysis
  execute_top22006
  write_checksum_inventory
  write_status "success" "all required raw, canonical, and TOP-22-006 pkls passed validation"
  write_manifest "success"
  chmod a-w "${manifest_file}"
  printf 'SUCCESS: immutable campaign manifest=%s\n' "${manifest_file}"
}

main "$@"
