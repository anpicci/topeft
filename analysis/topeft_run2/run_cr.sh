#!/usr/bin/env bash
set -euo pipefail

srplot009_print_command() {
  printf ' %q' "$@"
  printf '\n'
}

srplot009_campaign_log_path=""
srplot009_campaign_start_time=""

srplot009_finalize_campaign_log() {
  local exit_code="$1"
  local end_time

  if [[ -z "${srplot009_campaign_log_path}" ]]; then
    return
  fi
  end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf 'campaign_end_time_utc: %s\n' "${end_time}"
  printf 'campaign_exit_code: %s\n' "${exit_code}"
}

srplot009_identity_field() {
  local field="$1"
  local identity_text="$2"
  awk -F': ' -v field="${field}" '$1 == field {print $2; exit}' <<< "${identity_text}"
}

srplot009_require_fresh_paths() {
  local output_root="$1"

  if [[ -e "${output_root}" ]]; then
    echo "ERROR: SRPLOT-009 output root already exists; refusing overwrite, merge, or resume: ${output_root}" >&2
    return 1
  fi
}

srplot009_assert_committed_source() {
  local repository_root="$1"
  local production_paths=(
    analysis/topeft_run2/run_cr.sh
    analysis/topeft_run2/fullR3_run.sh
    analysis/topeft_run2/run_analysis.py
    analysis/topeft_run2/analysis_processor.py
    input_samples/cfgs/mc_signal_samples_NDSkim.cfg
    input_samples/cfgs/mc_background_samples_NDSkim.cfg
    input_samples/cfgs/data_samples_NDSkim.cfg
    topeft/channels/ch_lst.json
    topeft/modules
  )

  if ! git -C "${repository_root}" diff --quiet -- "${production_paths[@]}" \
    || ! git -C "${repository_root}" diff --cached --quiet -- "${production_paths[@]}" \
    || [[ -n "$(git -C "${repository_root}" diff --name-only --diff-filter=U -- "${production_paths[@]}")" ]]; then
    echo "ERROR: tracked production-semantic source/configuration is not frozen at the current commit." >&2
    echo "Commit or separately reconcile those changes before launching; no environment or block was started." >&2
    return 1
  fi
}

srplot009_validate_frozen_environment() {
  local validation_backend="$1"
  local validation_scenario="$2"
  local environment_file="$3"
  local expected_sha256="$4"
  local wrap="$5"
  local python_env="$6"
  local run_analysis_path="$7"
  local direct_sha256
  local validation_identity
  local validation_path
  local validation_sha256
  local validation_manifest
  local validation_fingerprint
  local validation_status
  local validation_topcoffea_commit
  local validation_topcoffea_source

  if [[ ! -f "${environment_file}" || ! -r "${environment_file}" || ! -s "${environment_file}" ]]; then
    echo "ERROR: frozen snapshot archive is not a readable nonempty regular file: ${environment_file}" >&2
    return 1
  fi
  direct_sha256=$(sha256sum "${environment_file}")
  direct_sha256="${direct_sha256%% *}"
  if [[ "${direct_sha256}" != "${expected_sha256}" ]]; then
    echo "ERROR: frozen snapshot archive SHA-256 mismatch." >&2
    return 1
  fi

  if [[ -n "${validation_backend}" ]]; then
    validation_identity=$("${validation_backend}" validate_environment "${validation_scenario}" "${environment_file}")
  else
    validation_identity=$("${wrap}" /bin/bash --noprofile --norc -c \
      'cd -- "$1" && exec "$2" "$3" --validate-env-file --env-integrity-only --env-file "$4"' \
      srplot009_environment_validation \
      "$(dirname -- "${run_analysis_path}")" \
      "${python_env}" \
      "${run_analysis_path}" \
      "${environment_file}")
  fi
  printf '%s\n' "${validation_identity}"

  validation_path=$(srplot009_identity_field env_file "${validation_identity}")
  validation_sha256=$(srplot009_identity_field env_file_sha256 "${validation_identity}")
  validation_manifest=$(srplot009_identity_field env_manifest "${validation_identity}")
  validation_fingerprint=$(srplot009_identity_field environment_fingerprint "${validation_identity}")
  validation_status=$(srplot009_identity_field environment_validation_status "${validation_identity}")
  validation_topcoffea_commit=$(srplot009_identity_field topcoffea_git_commit "${validation_identity}")
  validation_topcoffea_source=$(srplot009_identity_field topcoffea_relevant_source_fingerprint "${validation_identity}")

  if [[ "${validation_path}" != "${environment_file}" \
    || "${validation_sha256}" != "${expected_sha256}" \
    || "${validation_manifest}" != "${environment_file}.manifest.json" \
    || ! -f "${validation_manifest}" \
    || -z "${validation_fingerprint}" \
    || "${validation_status}" != "valid" \
    || -z "${validation_topcoffea_commit}" \
    || -z "${validation_topcoffea_source}" ]]; then
    echo "ERROR: maintained integrity validation did not read back the exact frozen archive identity." >&2
    return 1
  fi
}

srplot009_write_environment_identity() {
  local identity_path="$1"
  local repository_root="$2"
  local script_dir="$3"
  local environment_file="$4"
  local environment_sha256="$5"
  local block_count="$6"
  local temporary_path
  local topeft_commit
  local run_cr_sha256
  local fullr3_sha256
  local run_analysis_sha256
  local analysis_processor_sha256
  local channel_registry_sha256
  local signal_cfg_sha256
  local background_cfg_sha256
  local data_cfg_sha256

  topeft_commit=$(git -C "${repository_root}" rev-parse HEAD)
  run_cr_sha256=$(sha256sum "${script_dir}/run_cr.sh"); run_cr_sha256="${run_cr_sha256%% *}"
  fullr3_sha256=$(sha256sum "${script_dir}/fullR3_run.sh"); fullr3_sha256="${fullr3_sha256%% *}"
  run_analysis_sha256=$(sha256sum "${script_dir}/run_analysis.py"); run_analysis_sha256="${run_analysis_sha256%% *}"
  analysis_processor_sha256=$(sha256sum "${script_dir}/analysis_processor.py"); analysis_processor_sha256="${analysis_processor_sha256%% *}"
  channel_registry_sha256=$(sha256sum "${repository_root}/topeft/channels/ch_lst.json"); channel_registry_sha256="${channel_registry_sha256%% *}"
  signal_cfg_sha256=$(sha256sum "${repository_root}/input_samples/cfgs/mc_signal_samples_NDSkim.cfg"); signal_cfg_sha256="${signal_cfg_sha256%% *}"
  background_cfg_sha256=$(sha256sum "${repository_root}/input_samples/cfgs/mc_background_samples_NDSkim.cfg"); background_cfg_sha256="${background_cfg_sha256%% *}"
  data_cfg_sha256=$(sha256sum "${repository_root}/input_samples/cfgs/data_samples_NDSkim.cfg"); data_cfg_sha256="${data_cfg_sha256%% *}"

  temporary_path=$(mktemp "$(dirname -- "${identity_path}")/.environment_identity.XXXXXX")
  {
    printf 'field\tvalue\n'
    printf 'environment_use_mode\tmaintained_snapshot\n'
    printf 'archive_path\t%s\n' "${environment_file}"
    printf 'archive_sha256\t%s\n' "${environment_sha256}"
    printf 'manifest_path\t%s.manifest.json\n' "${environment_file}"
    printf 'environment_validation_status\tvalid_integrity_only\n'
    printf 'topeft_git_commit\t%s\n' "${topeft_commit}"
    printf 'run_cr_sha256\t%s\n' "${run_cr_sha256}"
    printf 'fullR3_run_sha256\t%s\n' "${fullr3_sha256}"
    printf 'run_analysis_sha256\t%s\n' "${run_analysis_sha256}"
    printf 'analysis_processor_sha256\t%s\n' "${analysis_processor_sha256}"
    printf 'channel_registry_sha256\t%s\n' "${channel_registry_sha256}"
    printf 'signal_cfg_sha256\t%s\n' "${signal_cfg_sha256}"
    printf 'background_cfg_sha256\t%s\n' "${background_cfg_sha256}"
    printf 'data_cfg_sha256\t%s\n' "${data_cfg_sha256}"
    printf 'block_count\t%s\n' "${block_count}"
    printf 'same_explicit_archive_required_for_all_blocks\ttrue\n'
    printf 'environment_build_or_resolution\tforbidden\n'
  } > "${temporary_path}"
  mv -- "${temporary_path}" "${identity_path}"
}

srplot009_run_block() {
  local validation_backend="$1"
  local validation_scenario="$2"
  local block_id="$3"
  local log_path="$4"
  local events_path="$5"
  local environment_file="$6"
  shift 6
  local command=("$@")
  local start_time
  local end_time
  local exit_code

  start_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '%s\t%s\tstarted\t\n' "${start_time}" "${block_id}" >> "${events_path}"
  {
    printf 'block_id: %s\n' "${block_id}"
    printf 'start_time_utc: %s\n' "${start_time}"
    printf 'environment_file: %s\n' "${environment_file}"
    printf 'command:'
    srplot009_print_command "${command[@]}"
  } | tee -a "${log_path}"

  set +e
  if [[ -n "${validation_backend}" ]]; then
    "${validation_backend}" run_block "${validation_scenario}" "${block_id}" "${environment_file}" "${command[@]}" 2>&1 | tee -a "${log_path}"
  else
    "${command[@]}" 2>&1 | tee -a "${log_path}"
  fi
  exit_code=${PIPESTATUS[0]}
  set -e

  end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  {
    printf 'end_time_utc: %s\n' "${end_time}"
    printf 'exit_code: %s\n' "${exit_code}"
  } | tee -a "${log_path}"
  printf '%s\t%s\tfinished\t%s\n' "${end_time}" "${block_id}" "${exit_code}" >> "${events_path}"

  if (( exit_code != 0 )); then
    echo "ERROR: ${block_id} failed with exit code ${exit_code}; later blocks were not started." >&2
    return "${exit_code}"
  fi
}

run_srplot009_campaign() {
  local dry_run="$1"
  local output_root="$2"
  local campaign_tag="$3"

  local script_dir
  local repository_root
  local wrap=/users/apiccine/work/correction-lib/codex-run.sh
  local python_env=/users/apiccine/work/miniconda3/envs/clib-env/bin/python
  local run_analysis_path
  local environment_file=/users/apiccine/work/correction-lib/topeft/analysis/topeft_run2/topeft-envs/env_spec_9d72aad444117c28.tar.gz
  local environment_sha256=8245afe4b3c28f4948039d383ad2176f1ee3ebb5e61bcdf1b49289452b025332
  local validation_backend="${SRPLOT009_VALIDATION_BACKEND:-}"
  local validation_root="${SRPLOT009_VALIDATION_ROOT:-}"
  local validation_scenario="${SRPLOT009_VALIDATION_SCENARIO:-success}"
  local sumw2_options_path
  local temporary_sumw2_options=""
  local identity_path
  local events_path
  local logs_dir
  local block_index
  local block_id
  local tag
  local categories=()
  local hist_vars=()
  local block_command=()
  local category_sets=(
    "2l 2lss_1tau 2los_1tau 4l"
    "3l_m_offZ"
    "3l_p_offZ"
    "3l_onZ_tau"
    "3l_fwd"
  )
  local histogram_sets=(
    "njets lj0pt ptz ptz_wtau lt"
    "njets lj0pt ptll lt"
    "njets lj0pt ptll lt"
    "njets lj0pt ptz lt"
    "njets lj0pt ptz lt"
  )

  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  repository_root=$(git -C "${script_dir}" rev-parse --show-toplevel)
  run_analysis_path="${script_dir}/run_analysis.py"
  cd -- "${script_dir}"

  if [[ -n "${validation_backend}" ]]; then
    case "${validation_root}" in
      /tmp/*) ;;
      *)
        echo "ERROR: SRPLOT009_VALIDATION_ROOT must be an absolute path below /tmp." >&2
        return 1
        ;;
    esac
    case "${validation_backend}" in
      /tmp/*) ;;
      *)
        echo "ERROR: SRPLOT009_VALIDATION_BACKEND must be an executable below /tmp." >&2
        return 1
        ;;
    esac
    if [[ ! -x "${validation_backend}" ]]; then
      echo "ERROR: SRPLOT009_VALIDATION_BACKEND is not executable." >&2
      return 1
    fi
    case "${output_root}" in
      /tmp/*) ;;
      *) output_root="${validation_root}/output" ;;
    esac
  fi

  srplot009_require_fresh_paths "${output_root}"
  if [[ "${output_root}" != /* ]]; then
    echo "ERROR: Run-2 output root must be absolute: ${output_root}" >&2
    return 1
  fi
  if [[ -z "${campaign_tag}" || "${campaign_tag}" == *$'\t'* || "${campaign_tag}" == *$'\n'* ]]; then
    echo "ERROR: Run-2 campaign tag must be nonempty and contain no tabs/newlines." >&2
    return 1
  fi

  echo "SRPLOT-009 Run-2 SR campaign"
  echo "output_root: ${output_root}"
  echo "campaign_tag: ${campaign_tag}"
  echo "block_count: 5"
  echo "overwrite_or_resume_policy: fail_closed_no_overwrite_no_resume"
  echo "interruption_retry_policy: no_automatic_retry_inspect_first"
  echo "environment_policy: exact_frozen_archive_integrity_plus_snapshot"
  echo "sumw2_storage_mode: full_diagnostics"

  if ! srplot009_validate_frozen_environment \
    "${validation_backend}" "${validation_scenario}" \
    "${environment_file}" "${environment_sha256}" \
    "${wrap}" "${python_env}" "${run_analysis_path}"; then
    echo "ERROR: frozen snapshot integrity validation failed; all five blocks remain not_started." >&2
    return 1
  fi

  if [[ "${dry_run}" == "true" ]]; then
    temporary_sumw2_options=$(mktemp /tmp/run2_full_sumw2.XXXXXX.yml)
    sumw2_options_path="${temporary_sumw2_options}"
    trap 'rm -f -- "${temporary_sumw2_options}"' RETURN
  else
    if [[ -z "${validation_backend}" ]]; then
      srplot009_assert_committed_source "${repository_root}"
    fi
    mkdir -- "${output_root}"
    sumw2_options_path="${output_root}/sumw2_full_diagnostics.yml"
    srplot009_campaign_log_path="${output_root}/campaign.log"
    srplot009_campaign_start_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    exec > >(tee -a "${srplot009_campaign_log_path}") 2>&1
    trap 'srplot009_finalize_campaign_log "$?"' EXIT
    printf 'campaign_command: ./run_cr.sh --production-profile run2_full\n'
    printf 'campaign_start_time_utc: %s\n' "${srplot009_campaign_start_time}"
    identity_path="${output_root}/environment_identity.tsv"
    srplot009_write_environment_identity \
      "${identity_path}" "${repository_root}" "${script_dir}" \
      "${environment_file}" "${environment_sha256}" 5
    logs_dir="${output_root}/logs"
    mkdir -- "${logs_dir}"
    events_path="${output_root}/srplot009_campaign_events.tsv"
    printf 'timestamp_utc\tblock_id\tevent\texit_code\n' > "${events_path}"
  fi

  printf 'sumw2_storage:\n  mode: full_diagnostics\n' > "${sumw2_options_path}"
  echo "sumw2_options_path: ${sumw2_options_path}"
  echo "environment_file: ${environment_file}"
  echo "environment_sha256: ${environment_sha256}"

  for block_index in 0 1 2 3 4; do
    block_id="block$((block_index + 1))"
    tag="${campaign_tag}-${block_id}"
    read -r -a categories <<< "${category_sets[block_index]}"
    read -r -a hist_vars <<< "${histogram_sets[block_index]}"
    block_command=(
      "${wrap}" /bin/bash --noprofile --norc -c
      'cd -- "$1" && shift && exec "$@"'
      "srplot009_${block_id}"
      "${script_dir}"
      ./fullR3_run.sh
      -y run2
      -t "${tag}"
      --sr
      --hist-vars "${hist_vars[@]}"
      -p "${output_root}"
      --all-analysis
      --category-groups "${categories[@]}"
      --do-systs
      --do-np
      --np-postprocess=inline
      -x work_queue
      -s 100000
      --env-file "${environment_file}"
      --snapshot
      --options "${sumw2_options_path}"
    )

    if [[ "${dry_run}" == "true" ]]; then
      block_command+=(--dry-run)
      printf 'SRPLOT009_BLOCK_COMMAND\t%s\t' "${block_id}"
      srplot009_print_command "${block_command[@]}"
      "${block_command[@]}"
    else
      srplot009_run_block \
        "${validation_backend}" "${validation_scenario}" "${block_id}" \
        "${logs_dir}/${block_id}.log" "${events_path}" "${environment_file}" \
        "${block_command[@]}"
    fi
  done

  if [[ "${dry_run}" == "true" ]]; then
    echo "dry_run_complete: five commands resolved; no environment, output root, scheduler, or production action was created"
  else
    echo "Run-2 full campaign completed all five blocks with one frozen snapshot archive."
  fi
}

run_cr_matrix_campaign() {
  local profile="$1"
  local dry_run="$2"
  local output_root="$3"
  local campaign_tag="$4"
  local script_dir
  local repository_root
  local wrap=/users/apiccine/work/correction-lib/codex-run.sh
  local python_env=/users/apiccine/work/miniconda3/envs/clib-env/bin/python
  local environment_file=/users/apiccine/work/correction-lib/topeft/analysis/topeft_run2/topeft-envs/env_spec_9d72aad444117c28.tar.gz
  local environment_sha256=8245afe4b3c28f4948039d383ad2176f1ee3ebb5e61bcdf1b49289452b025332
  local validation_backend="${SRPLOT009_VALIDATION_BACKEND:-}"
  local validation_root="${SRPLOT009_VALIDATION_ROOT:-}"
  local validation_scenario="${SRPLOT009_VALIDATION_SCENARIO:-success}"
  local sumw2_options_path
  local temporary_sumw2_options=""
  local logs_dir=""
  local events_path=""
  local identity_path
  local year_expr
  local family_index
  local var_set
  local block_index=0
  local block_id
  local tag
  local years=()
  local categories=()
  local hist_vars=()
  local block_command=()
  local year_sets=()
  local category_sets=(
    "2l_CR 2l_CRflip 2los_CRZ 2los_CRtt 3l_CR"
    "1l_1tau_CRtt 1l_1tau_CRDY 2los_1tau"
  )
  local non_tau_var_sets=(
    "fwd0pt fwd0eta j0pt j0eta lj0pt njets nbtagsm"
    "lt met ptz l0conept l0eta l1conept l1eta"
    "nbtagsl invmass ljptsum npvsGood"
  )
  local tau_var_sets=(
    "fwd0pt fwd0eta j0pt j0eta lj0pt njets nbtagsm"
    "lt met ptz l0conept l0eta l1conept l1eta"
    "nbtagsl invmass ljptsum npvsGood ptz_wtau tau0Fpt tau0Tpt"
  )

  case "${profile}" in
    run2_full_CR) year_sets=("2016APV 2016 2017 2018") ;;
    run3_full_CR) year_sets=("2022 2022EE" "2023 2023BPix") ;;
    *) echo "ERROR: internal unsupported CR profile ${profile}." >&2; return 1 ;;
  esac

  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  repository_root=$(git -C "${script_dir}" rev-parse --show-toplevel)
  cd -- "${script_dir}"

  if [[ -n "${validation_backend}" ]]; then
    case "${validation_root}" in /tmp/*) ;; *) echo "ERROR: SRPLOT009_VALIDATION_ROOT must be below /tmp." >&2; return 1 ;; esac
    case "${validation_backend}" in /tmp/*) ;; *) echo "ERROR: SRPLOT009_VALIDATION_BACKEND must be below /tmp." >&2; return 1 ;; esac
    [[ -x "${validation_backend}" ]] || { echo "ERROR: validation backend is not executable." >&2; return 1; }
    case "${output_root}" in
      /tmp/*) ;;
      *) output_root="${validation_root}/output" ;;
    esac
  fi

  srplot009_require_fresh_paths "${output_root}"
  [[ "${output_root}" == /* ]] || { echo "ERROR: CR output root must be absolute." >&2; return 1; }
  [[ -n "${campaign_tag}" ]] || { echo "ERROR: CR campaign tag must be nonempty." >&2; return 1; }
  srplot009_validate_frozen_environment \
    "${validation_backend}" "${validation_scenario}" \
    "${environment_file}" "${environment_sha256}" \
    "${wrap}" "${python_env}" "${script_dir}/run_analysis.py"

  if [[ "${dry_run}" == "true" ]]; then
    temporary_sumw2_options=$(mktemp "/tmp/${profile}_sumw2.XXXXXX.yml")
    sumw2_options_path="${temporary_sumw2_options}"
    trap 'rm -f -- "${temporary_sumw2_options}"' RETURN
  else
    if [[ -z "${validation_backend}" ]]; then
      srplot009_assert_committed_source "${repository_root}"
    fi
    mkdir -- "${output_root}"
    sumw2_options_path="${output_root}/sumw2_full_diagnostics.yml"
    logs_dir="${output_root}/logs"
    mkdir -- "${logs_dir}"
    events_path="${output_root}/${profile}_campaign_events.tsv"
    printf 'timestamp_utc\tblock_id\tevent\texit_code\n' > "${events_path}"
    identity_path="${output_root}/environment_identity.tsv"
    srplot009_write_environment_identity \
      "${identity_path}" "${repository_root}" "${script_dir}" \
      "${environment_file}" "${environment_sha256}" "$(( ${#year_sets[@]} * 6 ))"
  fi
  printf 'sumw2_storage:\n  mode: full_diagnostics\n' > "${sumw2_options_path}"

  echo "profile: ${profile}"
  echo "output_root: ${output_root}"
  echo "environment_file: ${environment_file}"
  echo "environment_sha256: ${environment_sha256}"
  echo "environment_policy: exact_frozen_archive_integrity_plus_snapshot"
  echo "sumw2_storage_mode: full_diagnostics"
  echo "overwrite_or_resume_policy: fail_closed_no_overwrite_no_resume"

  for year_expr in "${year_sets[@]}"; do
    read -r -a years <<< "${year_expr}"
    for family_index in 0 1; do
      read -r -a categories <<< "${category_sets[family_index]}"
      if (( family_index == 0 )); then
        local -n active_var_sets=non_tau_var_sets
      else
        local -n active_var_sets=tau_var_sets
      fi
      for var_set in "${active_var_sets[@]}"; do
        block_index=$((block_index + 1))
        block_id="block${block_index}"
        tag="${campaign_tag}-${block_id}"
        read -r -a hist_vars <<< "${var_set}"
        block_command=(
          "${wrap}" /bin/bash --noprofile --norc -c
          'cd -- "$1" && shift && exec "$@"'
          "${profile}_${block_id}"
          "${script_dir}"
          ./fullR3_run.sh
          -y "${years[@]}"
          -t "${tag}"
          --cr
          --hist-vars "${hist_vars[@]}"
          -p "${output_root}"
          --all-analysis
          --category-groups "${categories[@]}"
          --do-systs
          --do-np
          --np-postprocess=inline
          -x work_queue
          -s 100000
          --env-file "${environment_file}"
          --snapshot
          --options "${sumw2_options_path}"
        )
        if [[ "${dry_run}" == "true" ]]; then
          block_command+=(--dry-run)
          printf 'PROFILE_BLOCK_COMMAND\t%s\t%s\t' "${profile}" "${block_id}"
          srplot009_print_command "${block_command[@]}"
          "${block_command[@]}"
        else
          srplot009_run_block \
            "${validation_backend}" "${validation_scenario}" "${block_id}" \
            "${logs_dir}/${block_id}.log" "${events_path}" "${environment_file}" \
            "${block_command[@]}"
        fi
      done
      unset -n active_var_sets
    done
  done

  echo "${profile} completed ${block_index} resolved blocks."
}

matrix_profile=""
matrix_dry_run=false
matrix_output_dir=""
matrix_campaign_tag=""
matrix_env_file=""
matrix_resume=false

matrix_parse_args() {
  local args=("$@")
  local index=0
  while (( index < ${#args[@]} )); do
    case "${args[index]}" in
      --production-profile) matrix_profile="${args[index + 1]:-}"; index=$((index + 2)) ;;
      --dry-run) matrix_dry_run=true; index=$((index + 1)) ;;
      --output-dir) matrix_output_dir="${args[index + 1]:-}"; index=$((index + 2)) ;;
      --campaign-tag) matrix_campaign_tag="${args[index + 1]:-}"; index=$((index + 2)) ;;
      --env-file) matrix_env_file="${args[index + 1]:-}"; index=$((index + 2)) ;;
      --resume) matrix_resume=true; index=$((index + 1)) ;;
      -h|--help) index=$((index + 1)) ;;
      *) index=$((index + 1)) ;;
    esac
  done
}

if (( $# == 0 )) || { (( $# == 1 )) && [[ "$1" == "--dry-run" ]]; }; then
  [[ "${1:-}" == "--dry-run" ]] && matrix_dry_run=true
  run_srplot009_campaign \
    "${matrix_dry_run}" \
    /groups/klannon/apiccine/run2_srplot009_current_branch \
    current-branch-srplot009
  exit $?
fi

matrix_parse_args "$@"
case "${matrix_profile}" in
  run2_full|run2_full_CR|run3_full_CR|run2_run3_full|run2_run3_full_CR)
    if [[ -z "${matrix_output_dir}" || -z "${matrix_campaign_tag}" ]]; then
      echo "ERROR: ${matrix_profile} requires --output-dir and --campaign-tag." >&2
      exit 1
    fi
    if [[ -n "${matrix_env_file}" && "${matrix_env_file}" != "/users/apiccine/work/correction-lib/topeft/analysis/topeft_run2/topeft-envs/env_spec_9d72aad444117c28.tar.gz" ]]; then
      echo "ERROR: requested profiles are pinned to the maintained frozen snapshot archive." >&2
      exit 1
    fi
    if [[ "${matrix_resume}" == "true" ]]; then
      echo "ERROR: ${matrix_profile} has no automatic resume; inspect interrupted state first." >&2
      exit 1
    fi
    ;;
esac

case "${matrix_profile}" in
  run2_full)
    run_srplot009_campaign "${matrix_dry_run}" "${matrix_output_dir}" "${matrix_campaign_tag}"
    exit $?
    ;;
  run2_full_CR|run3_full_CR)
    run_cr_matrix_campaign "${matrix_profile}" "${matrix_dry_run}" "${matrix_output_dir}" "${matrix_campaign_tag}"
    exit $?
    ;;
  run2_run3_full|run2_run3_full_CR)
    if [[ -e "${matrix_output_dir}" ]]; then
      echo "ERROR: combined output namespace already exists: ${matrix_output_dir}" >&2
      exit 1
    fi
    combined_suffix=""
    first_profile=run2_full
    second_profile=run3_full
    if [[ "${matrix_profile}" == "run2_run3_full_CR" ]]; then
      combined_suffix=_CR
      first_profile=run2_full_CR
      second_profile=run3_full_CR
    fi
    if [[ "${matrix_dry_run}" == "false" ]]; then
      mkdir -- "${matrix_output_dir}"
      printf 'state\tprofile\nstarted\t%s\n' "${matrix_profile}" > "${matrix_output_dir}/combined_campaign_state.tsv"
      trap 'printf "interrupted\t%s\n" "${matrix_profile}" >> "${matrix_output_dir}/combined_campaign_state.tsv"; exit 130' INT TERM HUP
    fi
    component_common=(--env-file /users/apiccine/work/correction-lib/topeft/analysis/topeft_run2/topeft-envs/env_spec_9d72aad444117c28.tar.gz)
    [[ "${matrix_dry_run}" == "true" ]] && component_common+=(--dry-run)
    "$0" --production-profile "${first_profile}" \
      --output-dir "${matrix_output_dir}/run2${combined_suffix}" \
      --campaign-tag "${matrix_campaign_tag}_run2" "${component_common[@]}"
    if [[ "${matrix_dry_run}" == "false" ]]; then
      printf 'run2_success\t%s\n' "${first_profile}" >> "${matrix_output_dir}/combined_campaign_state.tsv"
    fi
    "$0" --production-profile "${second_profile}" \
      --output-dir "${matrix_output_dir}/run3${combined_suffix}" \
      --campaign-tag "${matrix_campaign_tag}_run3" "${component_common[@]}"
    if [[ "${matrix_dry_run}" == "false" ]]; then
      printf 'complete\t%s\n' "${matrix_profile}" >> "${matrix_output_dir}/combined_campaign_state.tsv"
    fi
    exit 0
    ;;
esac

print_usage() {
  cat <<'EOF'
Usage: ./run_cr.sh [--dry-run]
       ./run_cr.sh --production-profile PROFILE [--dry-run] \
  [--output-dir PATH] [--campaign-tag TAG] [--env-file PATH] [--resume]

Public PROFILE values:
  run2_full, run3_full, run2_run3_full
  run2_full_CR, run3_full_CR, run2_run3_full_CR

With no arguments, run_cr.sh remains a backward-compatible alias for the fixed
five-block run2_full campaign. Combined profiles run Run 2 then Run 3 in
separate child namespaces and start Run 3 only after Run-2 success.

All six public profiles use the exact maintained frozen archive in snapshot
mode, Work Queue without a profile-level worker count, and explicit
full_diagnostics sumw2 storage. Explicit component and combined profiles
require a fresh absolute output directory and campaign tag.

run3_full is the canonical complete Run-3 SR source-production profile.
rebin_fine is the specialized six-block Run-2/Run-3 source-production profile
for fitting families whose bins changed and remains available as a legacy
profile. Resume remains available only where already maintained by the legacy
generic profile machinery.
EOF
}

production_profile=""
profile_dry_run=false
profile_output_dir=""
profile_campaign_tag=""
profile_env_file=""
profile_resume=false

while (( $# > 0 )); do
  case "$1" in
    --production-profile)
      if (( $# < 2 )); then
        echo "ERROR: --production-profile requires a value." >&2
        exit 1
      fi
      production_profile="$2"
      shift 2
      ;;
    --dry-run)
      profile_dry_run=true
      shift
      ;;
    --output-dir)
      if (( $# < 2 )) || [[ -z "$2" ]]; then
        echo "ERROR: --output-dir requires a non-empty path." >&2
        exit 1
      fi
      profile_output_dir="$2"
      shift 2
      ;;
    --campaign-tag)
      if (( $# < 2 )) || [[ -z "$2" ]]; then
        echo "ERROR: --campaign-tag requires a non-empty value." >&2
        exit 1
      fi
      profile_campaign_tag="$2"
      shift 2
      ;;
    --env-file)
      if (( $# < 2 )) || [[ -z "$2" ]]; then
        echo "ERROR: --env-file requires a non-empty path." >&2
        exit 1
      fi
      profile_env_file="$2"
      shift 2
      ;;
    --resume)
      profile_resume=true
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "ERROR: unsupported run_cr.sh option '$1'." >&2
      print_usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${production_profile}" ]]; then
  echo "ERROR: --production-profile is required; no production was scheduled." >&2
  print_usage >&2
  exit 1
fi

case "${production_profile}" in
  run3_full|rebin_fine) ;;
  *)
    echo "ERROR: unsupported production profile '${production_profile}'." >&2
    exit 1
    ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(git -C "${script_dir}" rev-parse --show-toplevel)
cd -- "${script_dir}"

###############################################################################
# Global configuration
###############################################################################

output_dir=""
chunk_size="100000"

# Nominal TOP-23-002-like ttgamma sample-role strategy.
#
# Run 2:
#   TTGJets NLO                          -> production-like ttgamma
#   TTGamma_Dilept / TTGamma_SingleLept -> decay-like ttgamma
#   inclusive ttbar                     -> veto selected
#                                          external-conversion-like leptons
#
# Run 3:
#   TTG-1Jets_PTG-* -> inclusive ttgamma treatment
#   inclusive ttbar -> veto selected external-conversion-like leptons
#
# The diagnostic Run 2 NLO-only policy is intentionally not used here.
ttgamma_sample_role_policy="split"

campaign_tag=""
production_env_file=""
production_env_file_sha256=""
production_environment_fingerprint=""
production_topcoffea_git_commit=""
production_topcoffea_source_fingerprint=""
production_sumw2_options_path=""
production_sumw2_temporary_options=""
production_state_path=""
production_git_commit=""

run_cr=false
run_sr=true
dry_run="${profile_dry_run}"

if [[ -z "${profile_output_dir}" || -z "${profile_campaign_tag}" ]]; then
  cat >&2 <<EOF
ERROR: ${production_profile} requires explicit --output-dir and --campaign-tag.

No production or campaign-state mutation was performed.
EOF
  exit 1
fi
output_dir="${profile_output_dir}"
campaign_tag="${profile_campaign_tag}"

for production_state_value in "${output_dir}" "${campaign_tag}"; do
  if [[ "${production_state_value}" == *$'\t'* || "${production_state_value}" == *$'\n'* ]]; then
    echo "ERROR: ${production_profile} state fields must not contain tab or newline characters." >&2
    exit 1
  fi
done

if [[ "${output_dir}" != /* ]]; then
  echo "ERROR: ${production_profile} --output-dir must be an absolute path: ${output_dir}" >&2
  exit 1
fi

if [[ "${production_profile}" == "run3_full" ]] \
  && { [[ "${output_dir}" == "/groups/klannon/apiccine/preappr_v9_260729" ]] \
    || [[ "${output_dir}" == "/groups/klannon/apiccine/rebin_fine_260818_v3" ]] \
    || [[ "${campaign_tag}" == "ANv9" ]] \
    || [[ "${campaign_tag}" == "rebin-fine-260818-v3" ]]; }; then
  echo "ERROR: run3_full must use a fresh namespace, not a historical baseline or v3 campaign." >&2
  exit 1
fi

if [[ "${profile_resume}" == "false" && -e "${output_dir}" ]]; then
  echo "ERROR: ${production_profile} output directory already exists: ${output_dir}" >&2
  exit 1
fi

if [[ "${profile_resume}" == "true" && ! -d "${output_dir}" ]]; then
  echo "ERROR: ${production_profile} --resume requires an existing campaign output directory: ${output_dir}" >&2
  exit 1
fi

cr_pkl_base_tag="${campaign_tag}"
sr_pkl_base_tag="${campaign_tag}"

# Select which production regions to run.
#
# Completed regions should normally remain disabled to prevent accidental
# reruns.
run_cr=false
run_sr=true

# Resolve and print commands without launching production.
dry_run="${profile_dry_run}"

# Shared CR/SR production switches.
do_systs=true
do_np=true

# Enable only when lepton-flavour-split outputs are explicitly required.
split_lep_flavor=false

###############################################################################
# CR configuration
###############################################################################

# Each entry is one independent histogram chunk.
cr_non_tau_var_sets=(
  "fwd0pt fwd0eta j0pt j0eta lj0pt njets nbtagsm"
  "lt met ptz l0conept l0eta l1conept l1eta"
  "nbtagsl invmass ljptsum npvsGood"
)

cr_tau_var_sets=(
  "fwd0pt fwd0eta j0pt j0eta lj0pt njets nbtagsm"
  "lt met ptz l0conept l0eta l1conept l1eta"
  "nbtagsl invmass ljptsum npvsGood ptz_wtau tau0Fpt tau0Tpt"
)

# CR outputs intentionally combine periods into Run 2, 2022, and 2023 groups.
#
# Run 2 is commented because its CR production is already complete.
cr_year_sets=(
  # "2016APV 2016 2017 2018"
  "2022 2022EE"
  "2023 2023BPix"
)

# Current category names used by the analysis helpers.
#
# The aggregate 2los_1tau group is included for the 2los tau request. If the
# branch gains explicit 2los_1tau_Ftau / 2los_1tau_Ttau category groups, add
# them only after confirming the exact names and intended histogram coverage.
cr_category_sets=(
  "2l_CR 2l_CRflip 2los_CRZ 2los_CRtt 3l_CR"
  "1l_1tau_CRtt 1l_1tau_CRDY 2los_1tau"
)

# Parallel to cr_category_sets. Each category family selects its intentional
# histogram chunks instead of forming an invalid shared Cartesian product.
cr_category_var_set_names=(
  "cr_non_tau_var_sets"
  "cr_tau_var_sets"
)

###############################################################################
# SR configuration
###############################################################################

# ptz is the Z-candidate family and ptll is the closest-SFOS dilepton-pT family
# for 3l off-Z low/high. Request each public family only from category blocks
# that can fill it.
sr_with_ptz_wtau_var_sets=(
  "njets lj0pt ptz ptz_wtau lt"
)

sr_offz_var_sets=(
  "njets lj0pt ptll lt"
)

sr_onz_tau_var_sets=(
  "njets lj0pt ptz lt"
)

sr_fwd_var_sets=(
  "njets lj0pt ptz lt"
)

# The complete Run-3 plan keeps the two off-Z charge families in separate
# source blocks so failures and output identities remain unambiguous.
run3_full_category_sets=(
  "2l 2lss_1tau 2los_1tau 4l"
  "3l_m_offZ"
  "3l_p_offZ"
  "3l_onZ_tau"
  "3l_fwd"
)

run3_full_category_var_set_names=(
  "sr_with_ptz_wtau_var_sets"
  "sr_offz_var_sets"
  "sr_offz_var_sets"
  "sr_onz_tau_var_sets"
  "sr_fwd_var_sets"
)

# Static memory-bounded source-production plan for the families whose fitting
# bins changed. The plan is intentionally limited to canonical live keys and
# excludes njets, whose missing-parton workflow is produced separately.
rebin_fine_category_sets=(
  "2lss_1tau 3l_m_offZ"
  "3l_p_offZ 3l_onZ_tau"
  "3l_fwd"
)

rebin_fine_2lss_1tau_3l_m_offz_var_sets=(
  "lj0pt ptll ptz_wtau"
)

rebin_fine_3l_p_offz_3l_onZ_tau_var_sets=(
  "lj0pt ptz ptll"
)

rebin_fine_3l_fwd_var_sets=(
  "lt"
)

rebin_fine_category_var_set_names=(
  "rebin_fine_2lss_1tau_3l_m_offz_var_sets"
  "rebin_fine_3l_p_offz_3l_onZ_tau_var_sets"
  "rebin_fine_3l_fwd_var_sets"
)

if [[ "${production_profile}" == "rebin_fine" ]]; then
  sr_year_sets=(
    "2016APV 2016 2017 2018"
    "2022 2022EE 2023 2023BPix"
  )
  sr_year_category_set_names=(
    "rebin_fine_category_sets"
    "rebin_fine_category_sets"
  )
  sr_year_category_var_set_names=(
    "rebin_fine_category_var_set_names"
    "rebin_fine_category_var_set_names"
  )
else
  sr_year_sets=(
    "2022 2022EE 2023 2023BPix"
  )
  sr_year_category_set_names=(
    "run3_full_category_sets"
  )
  sr_year_category_var_set_names=(
    "run3_full_category_var_set_names"
  )
fi

production_state_filename=".${production_profile}_campaign_state.json"
production_block_ids=()
production_plan_year_exprs=()
production_plan_category_sets=()
production_plan_var_sets=()

if [[ "${production_profile}" == "rebin_fine" ]]; then
  production_block_ids=(
    "run2_a"
    "run2_b"
    "run2_c"
    "run3_a"
    "run3_b"
    "run3_c"
  )
  production_plan_year_exprs=(
    "2016APV 2016 2017 2018"
    "2016APV 2016 2017 2018"
    "2016APV 2016 2017 2018"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
  )
  production_plan_category_sets=(
    "2lss_1tau 3l_m_offZ"
    "3l_p_offZ 3l_onZ_tau"
    "3l_fwd"
    "2lss_1tau 3l_m_offZ"
    "3l_p_offZ 3l_onZ_tau"
    "3l_fwd"
  )
  production_plan_var_sets=(
    "lj0pt ptll ptz_wtau"
    "lj0pt ptz ptll"
    "lt"
    "lj0pt ptll ptz_wtau"
    "lj0pt ptz ptll"
    "lt"
  )
else
  production_block_ids=(
    "run3_full_a"
    "run3_full_b"
    "run3_full_c"
    "run3_full_d"
    "run3_full_e"
  )
  production_plan_year_exprs=(
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
  )
  production_plan_category_sets=(
    "2l 2lss_1tau 2los_1tau 4l"
    "3l_m_offZ"
    "3l_p_offZ"
    "3l_onZ_tau"
    "3l_fwd"
  )
  production_plan_var_sets=(
    "njets lj0pt ptz ptz_wtau lt"
    "njets lj0pt ptll lt"
    "njets lj0pt ptll lt"
    "njets lj0pt ptz lt"
    "njets lj0pt ptz lt"
  )
fi

###############################################################################
# Execution accounting
###############################################################################

declare -a block_summary_statuses=()
declare -a block_summary_modes=()
declare -a block_summary_years=()
declare -a block_summary_categories=()
declare -a block_summary_variables=()
declare -a block_summary_output_tags=()
declare -a block_summary_exit_codes=()
declare -a block_summary_durations=()

run_success_count=0
run_failure_count=0
run_skipped_count=0

###############################################################################
# Helpers
###############################################################################

join_by() {
  local delimiter="$1"
  shift

  local IFS="${delimiter}"
  echo "$*"
}

assert_boolean() {
  local value="$1"
  local option_name="$2"

  case "${value}" in
    true|false) ;;
    *)
      echo "ERROR: ${option_name} must be true or false, got '${value}'." >&2
      exit 1
      ;;
  esac
}

assert_parallel_array_lengths() {
  local label="$1"
  local left_count="$2"
  local right_count="$3"

  if (( left_count != right_count )); then
    cat >&2 <<EOF
ERROR: inconsistent ${label} configuration.

Number of category entries:
  ${left_count}

Number of variable-set mapping entries:
  ${right_count}
EOF
    exit 1
  fi
}

assert_array_defined() {
  local array_name="$1"

  if ! declare -p "${array_name}" >/dev/null 2>&1; then
    echo "ERROR: mapped array '${array_name}' is not defined." >&2
    exit 1
  fi
}

production_output_name() {
  local year_expr="$1"
  local pkl_tag="$2"
  local years=()
  local year_label

  read -r -a years <<< "${year_expr}"
  year_label=$(join_by - "${years[@]}")
  printf '%sSRs_%s' "${year_label}" "${pkl_tag}"
}

write_production_plan() {
  local plan_path="$1"
  local index
  local year_expr
  local category_set
  local var_set
  local cats=()
  local vars=()
  local cat_tag
  local var_tag
  local pkl_tag
  local output_name

  : > "${plan_path}"
  for index in "${!production_block_ids[@]}"; do
    year_expr="${production_plan_year_exprs[index]}"
    category_set="${production_plan_category_sets[index]}"
    var_set="${production_plan_var_sets[index]}"
    read -r -a cats <<< "${category_set}"
    read -r -a vars <<< "${var_set}"
    cat_tag=$(join_by - "${cats[@]}")
    var_tag=$(join_by - "${vars[@]}")
    pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"
    output_name=$(production_output_name "${year_expr}" "${pkl_tag}")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${production_block_ids[index]}" \
      "${year_expr}" \
      "${category_set}" \
      "${var_set}" \
      "${pkl_tag}" \
      "${output_name}" \
      "${output_dir}/${output_name}.pkl.gz" \
      "${output_dir}/${output_name}_np.pkl.gz" \
      >> "${plan_path}"
  done
}

production_state_tool() {
  python - "$@" <<'PY'
import datetime
import json
import os
import sys
from pathlib import Path


VALID_STATUSES = {
    "planned",
    "source_running",
    "source_ready",
    "source_failed",
    "nonprompt_running",
    "nonprompt_failed",
    "success",
}
VALID_SOURCE_STATUSES = {"planned", "running", "ready", "failed"}
VALID_NONPROMPT_STATUSES = {"blocked", "planned", "running", "failed", "success"}


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def atomic_write(path, payload):
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def load(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read campaign state {path}: {exc}")


def read_plan(path, production_profile):
    blocks = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read generated {production_profile} plan {path}: {exc}")
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 8:
            fail(f"invalid generated {production_profile} plan row: {line!r}")
        block_id, years, categories, histograms, output_tag, output_name, nominal, nonprompt = fields
        block = {
            "id": block_id,
            "years": years.split(),
            "category_groups": categories.split(),
            "histograms": histograms.split(),
            "output_tag": output_tag,
            "output_name": output_name,
            "expected_outputs": [nominal, nonprompt],
        }
        block["expected_nominal_path"] = nominal
        block["expected_np_path"] = nonprompt
        blocks.append(block)
    if not blocks or len({block["id"] for block in blocks}) != len(blocks):
        fail(f"generated {production_profile} plan does not contain unique blocks")
    return blocks


def desired_state(arguments):
    plan_path = Path(arguments[0])
    production_profile, schema_version, tag, output_dir, commit, env_file, env_sha256, env_fingerprint, topcoffea_commit, topcoffea_source, ttgamma, do_systs, do_np = arguments[1:]
    return {
        "schema_version": int(schema_version),
        "production_profile": production_profile,
        "campaign_tag": tag,
        "output_dir": output_dir,
        "topeft_git_commit": commit,
        "env_file": env_file,
        "env_file_sha256": env_sha256,
        "environment_fingerprint": env_fingerprint,
        "topcoffea_git_commit": topcoffea_commit,
        "topcoffea_relevant_source_fingerprint": topcoffea_source,
        "ttgamma_sample_role_policy": ttgamma,
        "do_systs": do_systs == "true",
        "do_np": do_np == "true",
        "blocks": read_plan(plan_path, production_profile),
    }


def validate_state(state, desired):
    for key in (
        "schema_version",
        "production_profile",
        "campaign_tag",
        "output_dir",
        "topeft_git_commit",
        "env_file",
        "env_file_sha256",
        "environment_fingerprint",
        "topcoffea_git_commit",
        "topcoffea_relevant_source_fingerprint",
        "ttgamma_sample_role_policy",
        "do_systs",
        "do_np",
    ):
        if state.get(key) != desired[key]:
            fail(f"campaign state mismatch for {key}: recorded={state.get(key)!r} requested={desired[key]!r}")
    recorded_blocks = state.get("blocks")
    if not isinstance(recorded_blocks, list) or len(recorded_blocks) != len(desired["blocks"]):
        fail("campaign state block count does not match the live profile plan")
    for recorded, expected in zip(recorded_blocks, desired["blocks"]):
        for key in expected:
            if recorded.get(key) != expected[key]:
                fail(f"campaign state mismatch for block {expected['id']} field {key}")
        if recorded.get("status") not in VALID_STATUSES:
            fail(f"campaign state has invalid status for block {expected['id']}: {recorded.get('status')!r}")
        if recorded.get("source_status") not in VALID_SOURCE_STATUSES:
            fail(f"campaign state has invalid source status for block {expected['id']}")
        if recorded.get("nonprompt_status") not in VALID_NONPROMPT_STATUSES:
            fail(f"campaign state has invalid nonprompt status for block {expected['id']}")
        if not isinstance(recorded.get("transitions"), list):
            fail(f"campaign state lacks transition history for block {expected['id']}")
        expected_stage_statuses = {
            "planned": ("planned", "blocked"),
            "source_running": ("running", "blocked"),
            "source_ready": ("ready", "planned"),
            "source_failed": ("failed", "blocked"),
            "nonprompt_running": ("ready", "running"),
            "nonprompt_failed": ("ready", "failed"),
            "success": ("ready", "success"),
        }[recorded["status"]]
        if (recorded["source_status"], recorded["nonprompt_status"]) != expected_stage_statuses:
            fail(f"campaign state has contradictory stage statuses for block {expected['id']}")


mode = sys.argv[1]
state_path = Path(sys.argv[2])

if mode in {"initialize", "validate"}:
    desired = desired_state(sys.argv[3:17])
    readonly = len(sys.argv) > 17 and sys.argv[17] == "true"
    if mode == "initialize":
        if state_path.exists():
            fail(f"refusing to overwrite existing {desired['production_profile']} campaign state: {state_path}")
        planned_blocks = desired["blocks"]
        state = {**desired, "blocks": []}
        timestamp = now_utc()
        state["created_at_utc"] = timestamp
        state["updated_at_utc"] = timestamp
        for block in planned_blocks:
            initialized = {
                **block,
                "status": "planned",
                "exit_code": None,
                "source_status": "planned",
                "source_exit_code": None,
                "nonprompt_status": "blocked",
                "nonprompt_exit_code": None,
                "last_transition_utc": timestamp,
                "last_transition_detail": "campaign_initialized",
                "transitions": [
                    {
                        "timestamp_utc": timestamp,
                        "stage": "campaign",
                        "status": "planned",
                        "exit_code": None,
                        "detail": "campaign_initialized",
                    }
                ],
            }
            state["blocks"].append(initialized)
        atomic_write(state_path, state)
    else:
        state = load(state_path)
        validate_state(state, desired)
        changed = False
        for block in state["blocks"]:
            if readonly:
                continue
            if block["source_status"] == "running":
                timestamp = now_utc()
                block["status"] = "source_failed"
                block["source_status"] = "failed"
                block["last_transition_utc"] = timestamp
                block["last_transition_detail"] = "resume_observed_interrupted_source_stage"
                block["transitions"].append(
                    {
                        "timestamp_utc": timestamp,
                        "stage": "source",
                        "status": "failed",
                        "exit_code": block.get("source_exit_code"),
                        "detail": block["last_transition_detail"],
                    }
                )
                changed = True
            elif block["nonprompt_status"] == "running":
                timestamp = now_utc()
                block["status"] = "nonprompt_failed"
                block["nonprompt_status"] = "failed"
                block["last_transition_utc"] = timestamp
                block["last_transition_detail"] = "resume_observed_interrupted_nonprompt_stage"
                block["transitions"].append(
                    {
                        "timestamp_utc": timestamp,
                        "stage": "nonprompt",
                        "status": "failed",
                        "exit_code": block.get("nonprompt_exit_code"),
                        "detail": block["last_transition_detail"],
                    }
                )
                changed = True
        if changed:
            state["updated_at_utc"] = now_utc()
            atomic_write(state_path, state)
    raise SystemExit(0)

state = load(state_path)
if mode == "env_file":
    expected_profile, expected_tag, expected_output_dir = sys.argv[3:6]
    for key, expected in (
        ("production_profile", expected_profile),
        ("campaign_tag", expected_tag),
        ("output_dir", expected_output_dir),
    ):
        if state.get(key) != expected:
            fail(
                f"campaign state mismatch for {key}: "
                f"recorded={state.get(key)!r} requested={expected!r}"
            )
    env_file = state.get("env_file")
    if not isinstance(env_file, str) or not env_file.startswith("/"):
        fail("campaign state does not contain an absolute frozen env_file")
    print(env_file)
    raise SystemExit(0)

if mode == "status":
    block_id = sys.argv[3]
    for block in state.get("blocks", []):
        if block.get("id") == block_id:
            print(
                "\t".join(
                    (
                        str(block.get("status", "")),
                        str(block.get("source_status", "")),
                        str(block.get("nonprompt_status", "")),
                    )
                )
            )
            raise SystemExit(0)
    fail(f"campaign state does not contain block {block_id}")

if mode == "mark":
    block_id, stage, stage_status, exit_code, detail = sys.argv[3:8]
    if stage == "source" and stage_status not in VALID_SOURCE_STATUSES:
        fail(f"invalid requested source status {stage_status!r}")
    if stage == "nonprompt" and stage_status not in VALID_NONPROMPT_STATUSES:
        fail(f"invalid requested nonprompt status {stage_status!r}")
    if stage not in {"source", "nonprompt"}:
        fail(f"invalid requested stage {stage!r}")
    for block in state.get("blocks", []):
        if block.get("id") == block_id:
            parsed_exit_code = None if exit_code == "none" else int(exit_code)
            if stage == "source":
                block["source_status"] = stage_status
                block["source_exit_code"] = parsed_exit_code
                block["status"] = {
                    "planned": "planned",
                    "running": "source_running",
                    "ready": "source_ready",
                    "failed": "source_failed",
                }[stage_status]
                if stage_status == "ready":
                    block["nonprompt_status"] = "planned"
                    block["nonprompt_exit_code"] = None
                else:
                    block["nonprompt_status"] = "blocked"
                    block["nonprompt_exit_code"] = None
            else:
                block["nonprompt_status"] = stage_status
                block["nonprompt_exit_code"] = parsed_exit_code
                block["status"] = {
                    "blocked": "source_failed",
                    "planned": "source_ready",
                    "running": "nonprompt_running",
                    "failed": "nonprompt_failed",
                    "success": "success",
                }[stage_status]
            block["exit_code"] = parsed_exit_code
            block["last_transition_utc"] = now_utc()
            block["last_transition_detail"] = detail
            block.setdefault("transitions", []).append(
                {
                    "timestamp_utc": block["last_transition_utc"],
                    "stage": stage,
                    "status": stage_status,
                    "exit_code": parsed_exit_code,
                    "detail": detail,
                }
            )
            state["updated_at_utc"] = now_utc()
            atomic_write(state_path, state)
            raise SystemExit(0)
    fail(f"campaign state does not contain block {block_id}")

fail(f"unsupported production state operation {mode!r}")
PY
}

resolve_production_environment() {
  local requested_env_file="${profile_env_file}"
  local matrix_env_file=/users/apiccine/work/correction-lib/topeft/analysis/topeft_run2/topeft-envs/env_spec_9d72aad444117c28.tar.gz
  local matrix_env_sha256=8245afe4b3c28f4948039d383ad2176f1ee3ebb5e61bcdf1b49289452b025332
  local frozen_env_file=""
  local canonical_requested_env_file=""
  local direct_sha256=""
  local validation_status=""
  local validation_args=()

  production_state_path="${output_dir}/${production_state_filename}"

  if [[ "${profile_resume}" == "true" ]]; then
    if [[ ! -f "${production_state_path}" ]]; then
      echo "ERROR: ${production_profile} --resume requires campaign state: ${production_state_path}" >&2
      exit 1
    fi
    frozen_env_file=$(production_state_tool env_file \
      "${production_state_path}" "${production_profile}" "${campaign_tag}" "${output_dir}")
    if [[ -n "${requested_env_file}" ]]; then
      if [[ "${requested_env_file}" != /* ]]; then
        echo "ERROR: ${production_profile} --env-file must be an absolute path: ${requested_env_file}" >&2
        exit 1
      fi
      canonical_requested_env_file=$(readlink -f -- "${requested_env_file}" || true)
      if [[ -z "${canonical_requested_env_file}" || "${canonical_requested_env_file}" != "${frozen_env_file}" ]]; then
        echo "ERROR: resume --env-file does not match the exact archive frozen in campaign state." >&2
        exit 1
      fi
    fi
    requested_env_file="${frozen_env_file}"
    if [[ "${production_profile}" == "run3_full" && "${requested_env_file}" != "${matrix_env_file}" ]]; then
      echo "ERROR: run3_full resume state does not use the required frozen snapshot archive." >&2
      exit 1
    fi
    if [[ "${production_profile}" == "run3_full" ]]; then
      validation_args=(--validate-env-file --env-integrity-only --env-file "${requested_env_file}")
    else
      validation_args=(--validate-env-file --env-file "${requested_env_file}")
    fi
  elif [[ -n "${requested_env_file}" ]]; then
    if [[ "${requested_env_file}" != /* ]]; then
      echo "ERROR: ${production_profile} --env-file must be an absolute path: ${requested_env_file}" >&2
      exit 1
    fi
    canonical_requested_env_file=$(readlink -f -- "${requested_env_file}" || true)
    if [[ "${production_profile}" == "run3_full" && "${canonical_requested_env_file}" != "${matrix_env_file}" ]]; then
      echo "ERROR: run3_full is pinned to the required frozen snapshot archive." >&2
      exit 1
    fi
    if [[ "${production_profile}" == "run3_full" ]]; then
      validation_args=(--validate-env-file --env-integrity-only --env-file "${requested_env_file}")
    else
      validation_args=(--validate-env-file --env-file "${requested_env_file}")
    fi
  elif [[ "${production_profile}" == "run3_full" ]]; then
    requested_env_file="${matrix_env_file}"
    canonical_requested_env_file="${matrix_env_file}"
    validation_args=(--validate-env-file --env-integrity-only --env-file "${requested_env_file}")
  else
    echo "ERROR: rebin_fine requires an explicit --env-file; no environment was built." >&2
    exit 1
  fi

  if [[ "${production_profile}" == "run3_full" ]]; then
    direct_sha256=$(sha256sum "${matrix_env_file}")
    direct_sha256="${direct_sha256%% *}"
    if [[ "${direct_sha256}" != "${matrix_env_sha256}" ]]; then
      echo "ERROR: run3_full frozen snapshot archive SHA-256 mismatch." >&2
      exit 1
    fi
  fi

  if ! production_environment_validation=$(python ./run_analysis.py "${validation_args[@]}"); then
    echo "ERROR: ${production_profile} could not validate its environment archive; no campaign state was changed." >&2
    exit 1
  fi
  printf '%s\n' "${production_environment_validation}"

  production_env_file=$(awk -F': ' '/^env_file: / {print $2; exit}' <<< "${production_environment_validation}")
  production_env_file_sha256=$(awk -F': ' '/^env_file_sha256: / {print $2; exit}' <<< "${production_environment_validation}")
  production_environment_fingerprint=$(awk -F': ' '/^environment_fingerprint: / {print $2; exit}' <<< "${production_environment_validation}")
  production_topcoffea_git_commit=$(awk -F': ' '/^topcoffea_git_commit: / {print $2; exit}' <<< "${production_environment_validation}")
  production_topcoffea_source_fingerprint=$(awk -F': ' '/^topcoffea_relevant_source_fingerprint: / {print $2; exit}' <<< "${production_environment_validation}")
  validation_status=$(awk -F': ' '/^environment_validation_status: / {print $2; exit}' <<< "${production_environment_validation}")

  if [[ "${production_env_file}" != /* ]] \
    || [[ ! -f "${production_env_file}" || ! -r "${production_env_file}" || ! -s "${production_env_file}" ]] \
    || [[ -z "${production_env_file_sha256}" ]] \
    || [[ -z "${production_environment_fingerprint}" ]] \
    || [[ -z "${production_topcoffea_git_commit}" ]] \
    || [[ -z "${production_topcoffea_source_fingerprint}" ]] \
    || [[ "${validation_status}" != "valid" ]]; then
    echo "ERROR: run_analysis.py did not return a complete valid environment identity." >&2
    exit 1
  fi

  if [[ "${profile_resume}" == "true" && "${production_env_file}" != "${frozen_env_file}" ]]; then
    echo "ERROR: validated resume environment path differs from campaign state." >&2
    exit 1
  fi
  if [[ -n "${canonical_requested_env_file}" && "${production_env_file}" != "${canonical_requested_env_file}" ]]; then
    echo "ERROR: --env-file validation returned a different archive path." >&2
    exit 1
  fi
  if [[ "${production_profile}" == "run3_full" && "${production_env_file_sha256}" != "${matrix_env_sha256}" ]]; then
    echo "ERROR: maintained validator SHA-256 differs from the required frozen archive identity." >&2
    exit 1
  fi
}

production_block_id() {
  local year_expr="$1"
  local category_set="$2"
  local index

  for index in "${!production_block_ids[@]}"; do
    if [[ "${year_expr}" == "${production_plan_year_exprs[index]}" ]] \
      && [[ "${category_set}" == "${production_plan_category_sets[index]}" ]]; then
      printf '%s' "${production_block_ids[index]}"
      return 0
    fi
  done

  echo "ERROR: unable to resolve ${production_profile} block identity for '${year_expr}' / '${category_set}'." >&2
  return 1
}

production_outputs_present() {
  local block_id="$1"
  local plan_path="$2"
  local nominal_path
  local nonprompt_path

  IFS=$'\t' read -r _ _ _ _ _ _ nominal_path nonprompt_path < <(
    awk -F '\t' -v block_id="${block_id}" '$1 == block_id {print; exit}' "${plan_path}"
  )
  [[ -n "${nominal_path}" && -n "${nonprompt_path}" && -s "${nominal_path}" && -s "${nonprompt_path}" ]]
}

production_any_output_exists() {
  local block_id="$1"
  local plan_path="$2"
  local nominal_path
  local nonprompt_path

  IFS=$'\t' read -r _ _ _ _ _ _ nominal_path nonprompt_path < <(
    awk -F '\t' -v block_id="${block_id}" '$1 == block_id {print; exit}' "${plan_path}"
  )
  [[ -e "${nominal_path}" || -e "${nonprompt_path}" ]]
}

production_assert_live_plan() {
  local index
  local var_set_name

  if [[ "${production_profile}" == "rebin_fine" ]]; then
    if (( ${#production_block_ids[@]} != 6 )) \
      || (( ${#sr_year_sets[@]} != 2 )) \
      || [[ "${sr_year_sets[0]}" != "2016APV 2016 2017 2018" ]] \
      || [[ "${sr_year_sets[1]}" != "2022 2022EE 2023 2023BPix" ]]; then
      echo "ERROR: live rebin_fine packing no longer matches the frozen six-block contract." >&2
      exit 1
    fi

    for index in 0 1 2; do
      if [[ "${rebin_fine_category_sets[index]}" != "${production_plan_category_sets[index]}" ]] \
        || [[ "${production_plan_category_sets[index]}" != "${production_plan_category_sets[index + 3]}" ]]; then
        echo "ERROR: live rebin_fine category packing no longer matches the frozen plan." >&2
        exit 1
      fi
      var_set_name="${rebin_fine_category_var_set_names[index]}"
      declare -n profile_var_set_ref="${var_set_name}"
      if (( ${#profile_var_set_ref[@]} != 1 )) \
        || [[ "${profile_var_set_ref[0]}" != "${production_plan_var_sets[index]}" ]] \
        || [[ "${production_plan_var_sets[index]}" != "${production_plan_var_sets[index + 3]}" ]]; then
        echo "ERROR: live rebin_fine histogram packing no longer matches the frozen plan." >&2
        unset -n profile_var_set_ref
        exit 1
      fi
      unset -n profile_var_set_ref
    done

    for index in "${!production_plan_var_sets[@]}"; do
      if [[ " ${production_plan_var_sets[index]} " == *" njets "* ]]; then
        echo "ERROR: rebin_fine must not request njets." >&2
        exit 1
      fi
    done
  else
    if (( ${#production_block_ids[@]} != 5 )) \
      || (( ${#sr_year_sets[@]} != 1 )) \
      || [[ "${sr_year_sets[0]}" != "2022 2022EE 2023 2023BPix" ]]; then
      echo "ERROR: live run3_full packing no longer matches the five-block Run-3 contract." >&2
      exit 1
    fi
    for index in "${!production_block_ids[@]}"; do
      if [[ "${run3_full_category_sets[index]}" != "${production_plan_category_sets[index]}" ]]; then
        echo "ERROR: live run3_full category packing no longer matches the frozen plan." >&2
        exit 1
      fi
      var_set_name="${run3_full_category_var_set_names[index]}"
      declare -n profile_var_set_ref="${var_set_name}"
      if (( ${#profile_var_set_ref[@]} != 1 )) \
        || [[ "${profile_var_set_ref[0]}" != "${production_plan_var_sets[index]}" ]]; then
        echo "ERROR: live run3_full histogram packing no longer matches the frozen plan." >&2
        unset -n profile_var_set_ref
        exit 1
      fi
      unset -n profile_var_set_ref
    done
  fi
}

prepare_production_campaign() {
  local plan_directory
  local schema_version=3

  production_assert_live_plan
  production_git_commit=$(git -C "${repository_root}" rev-parse HEAD)
  production_state_path="${output_dir}/${production_state_filename}"
  if [[ "${dry_run}" == "true" ]]; then
    production_plan_file=$(mktemp "/tmp/${production_profile}_plan.XXXXXX")
  else
    if [[ "${profile_resume}" == "false" ]]; then
      mkdir -- "${output_dir}"
    fi
    plan_directory="${output_dir}"
    production_plan_file=$(mktemp "${plan_directory}/.${production_profile}_plan.XXXXXX")
  fi
  write_production_plan "${production_plan_file}"

  if [[ "${profile_resume}" == "true" ]]; then
    if [[ ! -f "${production_state_path}" ]]; then
      echo "ERROR: ${production_profile} --resume requires campaign state: ${production_state_path}" >&2
      exit 1
    fi
    production_state_tool validate \
      "${production_state_path}" \
      "${production_plan_file}" \
      "${production_profile}" \
      "${schema_version}" \
      "${campaign_tag}" \
      "${output_dir}" \
      "${production_git_commit}" \
      "${production_env_file}" \
      "${production_env_file_sha256}" \
      "${production_environment_fingerprint}" \
      "${production_topcoffea_git_commit}" \
      "${production_topcoffea_source_fingerprint}" \
      "${ttgamma_sample_role_policy}" \
      "${do_systs}" \
      "${do_np}" \
      "${dry_run}"
  elif [[ "${dry_run}" == "false" ]]; then
    production_state_tool initialize \
      "${production_state_path}" \
      "${production_plan_file}" \
      "${production_profile}" \
      "${schema_version}" \
      "${campaign_tag}" \
      "${output_dir}" \
      "${production_git_commit}" \
      "${production_env_file}" \
      "${production_env_file_sha256}" \
      "${production_environment_fingerprint}" \
      "${production_topcoffea_git_commit}" \
      "${production_topcoffea_source_fingerprint}" \
      "${ttgamma_sample_role_policy}" \
      "${do_systs}" \
      "${do_np}"
  fi
}

prepare_production_sumw2_options() {
  if [[ "${production_profile}" != "run3_full" ]]; then
    return
  fi
  if [[ "${dry_run}" == "true" ]]; then
    production_sumw2_temporary_options=$(mktemp /tmp/run3_full_sumw2.XXXXXX.yml)
    production_sumw2_options_path="${production_sumw2_temporary_options}"
    printf 'sumw2_storage:\n  mode: full_diagnostics\n' > "${production_sumw2_options_path}"
  else
    production_sumw2_options_path="${output_dir}/sumw2_full_diagnostics.yml"
    if [[ "${profile_resume}" == "false" ]]; then
      printf 'sumw2_storage:\n  mode: full_diagnostics\n' > "${production_sumw2_options_path}"
    fi
  fi
  if [[ ! -f "${production_sumw2_options_path}" ]] \
    || [[ "$(<"${production_sumw2_options_path}")" != $'sumw2_storage:\n  mode: full_diagnostics' ]]; then
    echo "ERROR: run3_full sumw2 options do not match full_diagnostics." >&2
    exit 1
  fi
}

cleanup_production_plan() {
  if [[ -n "${production_plan_file:-}" && -f "${production_plan_file}" ]]; then
    rm -f -- "${production_plan_file}"
  fi
  if [[ -n "${production_sumw2_temporary_options:-}" && -f "${production_sumw2_temporary_options}" ]]; then
    rm -f -- "${production_sumw2_temporary_options}"
  fi
}

assert_supported_year_expr() {
  local year_expr="$1"
  local year
  local years_in_expr=()

  read -r -a years_in_expr <<< "${year_expr}"

  if (( ${#years_in_expr[@]} == 0 )); then
    echo "ERROR: empty year expression." >&2
    exit 1
  fi

  for year in "${years_in_expr[@]}"; do
    case "${year}" in
      2016APV|2016|2017|2018|2022|2022EE|2023|2023BPix) ;;
      *)
        cat >&2 <<EOF
ERROR: unsupported year token '${year}' in year expression '${year_expr}'.

Allowed year tokens:
  2016APV 2016 2017 2018 2022 2022EE 2023 2023BPix
EOF
        exit 1
        ;;
    esac
  done
}

print_command() {
  local -a cmd=("$@")

  echo "Executing:"
  printf ' %q' "${cmd[@]}"
  echo
}

print_var_sets() {
  local label="$1"
  shift

  local var_set
  local index=0

  echo "${label} variable chunks:"
  for var_set in "$@"; do
    index=$((index + 1))
    echo "  ${index}: ${var_set}"
  done
}

format_duration() {
  local duration_seconds="$1"
  local hours
  local minutes
  local seconds

  hours=$((duration_seconds / 3600))
  minutes=$(((duration_seconds % 3600) / 60))
  seconds=$((duration_seconds % 60))

  printf '%02d:%02d:%02d' "${hours}" "${minutes}" "${seconds}"
}

record_block_result() {
  local status="$1"
  local mode="$2"
  local year_expr="$3"
  local category_set="$4"
  local var_set="$5"
  local output_tag="$6"
  local exit_code="$7"
  local duration_seconds="$8"

  block_summary_statuses+=("${status}")
  block_summary_modes+=("${mode}")
  block_summary_years+=("${year_expr}")
  block_summary_categories+=("${category_set}")
  block_summary_variables+=("${var_set}")
  block_summary_output_tags+=("${output_tag}")
  block_summary_exit_codes+=("${exit_code}")
  block_summary_durations+=("${duration_seconds}")

  case "${status}" in
    SUCCESS)
      run_success_count=$((run_success_count + 1))
      ;;
    FAILED)
      run_failure_count=$((run_failure_count + 1))
      ;;
    SKIPPED)
      run_skipped_count=$((run_skipped_count + 1))
      ;;
    DRY_RUN)
      ;;
    *)
      echo "ERROR: unknown block status '${status}'." >&2
      exit 1
      ;;
  esac
}

print_run_summary() {
  local total_count
  local attempted_count
  local index
  local exit_code
  local signal_number
  local signal_suffix
  local duration_text

  total_count=${#block_summary_statuses[@]}
  attempted_count=$((run_success_count + run_failure_count))

  echo
  echo "========================================"
  echo "run_cr.sh execution summary"
  echo "campaign_tag: ${campaign_tag}"
  echo "output_dir: ${output_dir}"
  echo "configured block invocations: ${total_count}"
  echo "attempted: ${attempted_count}"
  echo "successful: ${run_success_count}"
  echo "failed: ${run_failure_count}"
  echo "skipped as completed: ${run_skipped_count}"
  echo "----------------------------------------"

  if (( total_count == 0 )); then
    echo "No CR/SR block invocations were scheduled."
  else
    for index in "${!block_summary_statuses[@]}"; do
      exit_code="${block_summary_exit_codes[index]}"
      signal_suffix=""
      if [[ "${block_summary_statuses[index]}" == "FAILED" ]] && (( exit_code > 128 )); then
        signal_number=$((exit_code - 128))
        signal_suffix=" signal=${signal_number}"
      fi
      duration_text=$(format_duration "${block_summary_durations[index]}")

      printf '[%02d] %s mode=%s exit=%s%s duration=%s\n' \
        "$((index + 1))" \
        "${block_summary_statuses[index]}" \
        "${block_summary_modes[index]}" \
        "${exit_code}" \
        "${signal_suffix}" \
        "${duration_text}"
      echo "     years: ${block_summary_years[index]}"
      echo "     categories: ${block_summary_categories[index]}"
      echo "     variables: ${block_summary_variables[index]}"
      echo "     output_tag: ${block_summary_output_tags[index]}"
    done
  fi

  echo "========================================"
}

build_common_command_options() {
  local -n cmd_ref="$1"

  cmd_ref+=(
    --ttgamma-sample-role-policy "${ttgamma_sample_role_policy}"
    --sample-universe-wrapper "run_cr.sh -> fullR3_run.sh"
  )

  # cmd_ref+=(--analysis-mode taufitter)

  if [[ "${do_systs}" == "true" ]]; then
    cmd_ref+=(--do-systs)
  fi

  if [[ "${do_np}" == "true" ]]; then
    # --do-np configures and certifies the current nonprompt/sumw2 contract;
    # --defer-np prevents run_analysis.py from materializing the _np artifact
    # in the processor process. run_sr_block launches run_data_driven.py only
    # after that child exits and the source artifact is verified.
    cmd_ref+=(--do-np --defer-np)
  fi

  cmd_ref+=(
    -p "${output_dir}"
    --all-analysis
  )

  cmd_ref+=(--env-file "${production_env_file}")

  if [[ "${production_profile}" == "run3_full" ]]; then
    cmd_ref+=(
      --snapshot
      --options "${production_sumw2_options_path}"
      -x work_queue
    )
  fi

  if [[ "${split_lep_flavor}" == "true" ]]; then
    cmd_ref+=(--split-lep-flavor)
  fi

  if [[ "${dry_run}" == "true" ]]; then
    cmd_ref+=(--dry-run)
  fi
}

run_cr_block() {
  local year_expr="$1"
  local var_set="$2"
  shift 2

  assert_supported_year_expr "${year_expr}"

  local years=()
  local vars=()
  local cats=("$@")
  local cat_tag
  local var_tag
  local pkl_tag
  local start_epoch
  local end_epoch
  local duration_seconds
  local exit_code

  read -r -a years <<< "${year_expr}"
  read -r -a vars <<< "${var_set}"

  cat_tag=$(join_by - "${cats[@]}")
  var_tag=$(join_by - "${vars[@]}")
  pkl_tag="${cr_pkl_base_tag}_${cat_tag}_${var_tag}"

  echo "----------------------------------------"
  echo "Mode: CR"
  echo "Years: ${year_expr}"
  echo "Categories: ${cats[*]}"
  echo "Variables: ${vars[*]}"
  echo "ttgamma sample-role policy: ${ttgamma_sample_role_policy}"
  echo "Campaign tag: ${campaign_tag}"
  echo "Output tag: ${pkl_tag}"
  echo "Output dir: ${output_dir}"
  echo "Dry run: ${dry_run}"
  echo "----------------------------------------"

  local cmd=(
    ./fullR3_run.sh
    -y "${years[@]}"
    -t "${pkl_tag}"
    -s "${chunk_size}"
    --cr
    --hist-vars "${vars[@]}"
    --category-groups "${cats[@]}"
  )

  build_common_command_options cmd

  print_command "${cmd[@]}"
  start_epoch=$(date +%s)

  # Keep child stdout/stderr attached directly to the caller. The conditional
  # invocation only captures the exit status so set -e does not terminate the
  # campaign when one production block fails or its Python child is killed.
  if "${cmd[@]}"; then
    exit_code=0
  else
    exit_code=$?
  fi

  end_epoch=$(date +%s)
  duration_seconds=$((end_epoch - start_epoch))

  if (( exit_code == 0 )); then
    record_block_result \
      "SUCCESS" "CR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo "${year_expr} CR done for ${cat_tag} / ${var_tag}"
  else
    record_block_result \
      "FAILED" "CR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo \
      "ERROR: ${year_expr} CR failed for ${cat_tag} / ${var_tag} with exit code ${exit_code}; continuing with the next block." \
      >&2
  fi

  echo "----------------------------------------"
  echo
}

run_sr_block() {
  local year_expr="$1"
  local var_set="$2"
  shift 2

  assert_supported_year_expr "${year_expr}"

  local years=()
  local vars=()
  local cats=("$@")
  local cat_tag
  local var_tag
  local pkl_tag
  local source_path
  local nonprompt_path
  local start_epoch
  local end_epoch
  local duration_seconds
  local source_exit_code=0
  local nonprompt_exit_code=0
  local production_block=""
  local production_status=""
  local source_status=""
  local nonprompt_status=""
  local source_reusable=false

  read -r -a years <<< "${year_expr}"
  read -r -a vars <<< "${var_set}"

  cat_tag=$(join_by - "${cats[@]}")
  var_tag=$(join_by - "${vars[@]}")
  pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"

  production_block=$(production_block_id "${year_expr}" "${cats[*]}")
  IFS=$'\t' read -r _ _ _ _ _ _ source_path nonprompt_path < <(
    awk -F '\t' -v block_id="${production_block}" '$1 == block_id {print; exit}' "${production_plan_file}"
  )
  if [[ -z "${source_path}" || -z "${nonprompt_path}" ]]; then
    echo "ERROR: unable to resolve expected output paths for ${production_block}." >&2
    exit 1
  fi

  if [[ "${dry_run}" == "true" && "${profile_resume}" == "false" ]]; then
    production_status="planned"
    source_status="planned"
    nonprompt_status="blocked"
  else
    IFS=$'\t' read -r production_status source_status nonprompt_status < <(
      production_state_tool status "${production_state_path}" "${production_block}"
    )
  fi

  if [[ "${production_status}" == "success" ]]; then
    if [[ -s "${source_path}" && -s "${nonprompt_path}" ]]; then
      echo "----------------------------------------"
      echo "Skipping validated ${production_profile} block: ${production_block}"
      echo "Campaign state, source artifact, and separate nonprompt artifact are complete."
      echo "----------------------------------------"
      record_block_result \
        "SKIPPED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
        "${pkl_tag}" "0" "0"
      return 0
    fi
    if [[ ! -s "${source_path}" ]]; then
      production_state_tool mark \
        "${production_state_path}" "${production_block}" \
        "source" "failed" "none" "success_state_missing_expected_source"
    else
      production_state_tool mark \
        "${production_state_path}" "${production_block}" \
        "nonprompt" "failed" "none" "success_state_missing_expected_nonprompt"
    fi
    echo "ERROR: ${production_profile} state marks ${production_block} successful, but an expected artifact is missing or empty." >&2
    exit 1
  fi

  case "${source_status}" in
    ready)
      if [[ ! -s "${source_path}" ]]; then
        production_state_tool mark \
          "${production_state_path}" "${production_block}" \
          "source" "failed" "none" "source_ready_state_missing_expected_source"
        echo "ERROR: ${production_block} records a reusable source, but it is missing or empty." >&2
        exit 1
      fi
      source_reusable=true
      ;;
    planned|failed)
      if [[ -e "${source_path}" || -e "${nonprompt_path}" ]]; then
        echo "ERROR: ${production_profile} block ${production_block} is ${production_status}, but an expected output path already exists. Refusing ambiguous overwrite." >&2
        exit 1
      fi
      ;;
    running)
      echo "ERROR: ${production_block} has an ambiguous interrupted source stage; run a non-dry --resume preflight before retrying." >&2
      exit 1
      ;;
    *)
      echo "ERROR: ${production_block} has invalid source status '${source_status}'." >&2
      exit 1
      ;;
  esac

  if [[ -e "${nonprompt_path}" ]]; then
    echo "ERROR: ${production_block} is not successful, but its expected _np path already exists. Refusing ambiguous overwrite." >&2
    exit 1
  fi

  echo "----------------------------------------"
  echo "Mode: SR"
  echo "Years: ${year_expr}"
  echo "Categories: ${cats[*]}"
  echo "Variables: ${vars[*]}"
  echo "ttgamma sample-role policy: ${ttgamma_sample_role_policy}"
  echo "Campaign tag: ${campaign_tag}"
  echo "Output tag: ${pkl_tag}"
  echo "Output dir: ${output_dir}"
  echo "Source stage status: ${source_status}"
  echo "Nonprompt stage status: ${nonprompt_status}"
  echo "Dry run: ${dry_run}"
  echo "----------------------------------------"

  local source_cmd=(
    ./fullR3_run.sh
    -y "${years[@]}"
    -t "${pkl_tag}"
    -s "${chunk_size}"
    --sr
    --hist-vars "${vars[@]}"
    --category-groups "${cats[@]}"
  )

  build_common_command_options source_cmd
  local nonprompt_cmd=(
    python ./run_data_driven.py
    --input-pkl "${source_path}"
    --output-pkl "${nonprompt_path}"
  )

  start_epoch=$(date +%s)

  if [[ "${source_reusable}" == "false" ]]; then
    if [[ "${dry_run}" == "false" ]]; then
      production_state_tool mark \
        "${production_state_path}" "${production_block}" \
        "source" "running" "none" "source_child_started"
    fi
    print_command "${source_cmd[@]}"
    # This conditional waits for the heavy processor child to exit completely.
    # The separate data-driven process is not created until after this returns.
    if "${source_cmd[@]}"; then
      source_exit_code=0
    else
      source_exit_code=$?
    fi
  else
    echo "Reusing validated completed source for ${production_block}: ${source_path}"
  fi

  if [[ "${dry_run}" == "true" ]]; then
    if (( source_exit_code != 0 )); then
      end_epoch=$(date +%s)
      duration_seconds=$((end_epoch - start_epoch))
      record_block_result \
        "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
        "${pkl_tag}" "${source_exit_code}" "${duration_seconds}"
      echo "ERROR: ${production_block} source dry-run resolution failed with exit code ${source_exit_code}." >&2
      return 0
    fi
    echo "Separate nonprompt command (not executed by dry-run):"
    printf ' %q' "${nonprompt_cmd[@]}"
    echo
    end_epoch=$(date +%s)
    duration_seconds=$((end_epoch - start_epoch))
    record_block_result \
      "DRY_RUN" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "0" "${duration_seconds}"
    echo "${year_expr} ${production_profile} two-stage dry-run resolved for ${cat_tag} / ${var_tag}"
    echo "----------------------------------------"
    echo
    return 0
  fi

  if [[ "${source_reusable}" == "false" ]]; then
    if (( source_exit_code != 0 )); then
      production_state_tool mark \
        "${production_state_path}" "${production_block}" \
        "source" "failed" "${source_exit_code}" "source_child_exit_nonzero"
      end_epoch=$(date +%s)
      duration_seconds=$((end_epoch - start_epoch))
      record_block_result \
        "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
        "${pkl_tag}" "${source_exit_code}" "${duration_seconds}"
      echo "ERROR: ${production_block} source production failed with exit code ${source_exit_code}; continuing." >&2
      return 0
    fi
    if [[ ! -s "${source_path}" || -e "${nonprompt_path}" ]]; then
      production_state_tool mark \
        "${production_state_path}" "${production_block}" \
        "source" "failed" "${source_exit_code}" "source_exit_zero_invalid_stage_outputs"
      end_epoch=$(date +%s)
      duration_seconds=$((end_epoch - start_epoch))
      record_block_result \
        "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
        "${pkl_tag}" "${source_exit_code}" "${duration_seconds}"
      echo "ERROR: ${production_block} source stage did not produce exactly one nonempty source and no _np output." >&2
      return 0
    fi
    production_state_tool mark \
      "${production_state_path}" "${production_block}" \
      "source" "ready" "${source_exit_code}" "source_child_exit_zero_expected_source_present"
  fi

  production_state_tool mark \
    "${production_state_path}" "${production_block}" \
    "nonprompt" "running" "none" "separate_nonprompt_child_started_after_source_exit"
  print_command "${nonprompt_cmd[@]}"
  if "${nonprompt_cmd[@]}"; then
    nonprompt_exit_code=0
  else
    nonprompt_exit_code=$?
  fi

  end_epoch=$(date +%s)
  duration_seconds=$((end_epoch - start_epoch))

  if (( nonprompt_exit_code == 0 )) && [[ -s "${nonprompt_path}" ]]; then
    production_state_tool mark \
      "${production_state_path}" "${production_block}" \
      "nonprompt" "success" "${nonprompt_exit_code}" "separate_nonprompt_exit_zero_expected_output_present"
    record_block_result \
      "SUCCESS" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${nonprompt_exit_code}" "${duration_seconds}"
    echo "${year_expr} SR source and separate nonprompt stages done for ${cat_tag} / ${var_tag}"
  else
    production_state_tool mark \
      "${production_state_path}" "${production_block}" \
      "nonprompt" "failed" "${nonprompt_exit_code}" "separate_nonprompt_failed_or_missing_output"
    record_block_result \
      "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${nonprompt_exit_code}" "${duration_seconds}"
    echo \
      "ERROR: ${production_block} separate nonprompt stage failed or its _np output is missing/empty; continuing with the next block." \
      >&2
  fi

  echo "----------------------------------------"
  echo
}

###############################################################################
# Preflight summary
###############################################################################

assert_boolean "${run_cr}" "run_cr"
assert_boolean "${run_sr}" "run_sr"
assert_boolean "${dry_run}" "dry_run"
assert_boolean "${do_systs}" "do_systs"
assert_boolean "${do_np}" "do_np"
assert_boolean "${split_lep_flavor}" "split_lep_flavor"
assert_boolean "${profile_resume}" "profile_resume"

assert_parallel_array_lengths \
  "CR category-to-variable mapping" \
  "${#cr_category_sets[@]}" \
  "${#cr_category_var_set_names[@]}"

assert_parallel_array_lengths \
  "run3_full SR category-to-variable mapping" \
  "${#run3_full_category_sets[@]}" \
  "${#run3_full_category_var_set_names[@]}"

assert_parallel_array_lengths \
  "rebin_fine SR category-to-variable mapping" \
  "${#rebin_fine_category_sets[@]}" \
  "${#rebin_fine_category_var_set_names[@]}"

assert_parallel_array_lengths \
  "SR year-to-category mapping" \
  "${#sr_year_sets[@]}" \
  "${#sr_year_category_set_names[@]}"

assert_parallel_array_lengths \
  "SR year-to-variable-map mapping" \
  "${#sr_year_sets[@]}" \
  "${#sr_year_category_var_set_names[@]}"

for var_set_name in \
  "${cr_category_var_set_names[@]}" \
  "${run3_full_category_var_set_names[@]}" \
  "${rebin_fine_category_var_set_names[@]}"; do
  assert_array_defined "${var_set_name}"
done

for category_array_name in "${sr_year_category_set_names[@]}"; do
  assert_array_defined "${category_array_name}"
done

for mapping_array_name in "${sr_year_category_var_set_names[@]}"; do
  assert_array_defined "${mapping_array_name}"
done

resolve_production_environment

echo "========================================"
echo "run_cr.sh configuration"
echo "production_profile: ${production_profile}"
echo "campaign_tag: ${campaign_tag}"
echo "ttgamma sample-role policy: ${ttgamma_sample_role_policy}"
echo "output_dir: ${output_dir}"
echo "chunk_size: ${chunk_size}"
echo "run_cr: ${run_cr}"
echo "run_sr: ${run_sr}"
echo "dry_run: ${dry_run}"
echo "do_systs: ${do_systs}"
echo "do_np: ${do_np}"
echo "split_lep_flavor: ${split_lep_flavor}"
echo "resume: ${profile_resume}"
echo "env_file: ${production_env_file}"
echo "env_file_sha256: ${production_env_file_sha256}"
if [[ "${profile_resume}" == "true" ]]; then
  if [[ "${production_profile}" == "run3_full" ]]; then
    echo "environment_policy: state_frozen_exact_archive_integrity_plus_snapshot"
  else
    echo "environment_policy: state_frozen_strict_single_archive"
  fi
elif [[ "${production_profile}" == "run3_full" ]]; then
  echo "environment_policy: exact_frozen_archive_integrity_plus_snapshot"
elif [[ -n "${profile_env_file}" ]]; then
  echo "environment_policy: explicit_single_archive"
else
  echo "environment_policy: legacy_profile_policy"
fi
if [[ "${production_profile}" == "run3_full" ]]; then
  echo "sumw2_storage_mode: full_diagnostics"
fi
echo "campaign_state: ${output_dir}/${production_state_filename}"
print_var_sets "CR non-tau" "${cr_non_tau_var_sets[@]}"
print_var_sets "CR tau" "${cr_tau_var_sets[@]}"
print_var_sets "SR with ptz_wtau" "${sr_with_ptz_wtau_var_sets[@]}"
print_var_sets "SR off-Z" "${sr_offz_var_sets[@]}"
print_var_sets "SR on-Z/tau" "${sr_onz_tau_var_sets[@]}"
print_var_sets "SR forward" "${sr_fwd_var_sets[@]}"

if [[ "${production_profile}" == "rebin_fine" ]]; then
  echo "rebin_fine SR category blocks (used for both Run 2 and Run 3):"
  printf '  %s\n' "${rebin_fine_category_sets[@]}"
else
  echo "run3_full Run-3 SR category blocks:"
  printf '  %s\n' "${run3_full_category_sets[@]}"
fi

echo "========================================"
echo

case "${ttgamma_sample_role_policy}" in
  split) ;;
  *)
    cat >&2 <<EOF
ERROR: this production helper is intended to run the nominal split policy.

Current ttgamma_sample_role_policy:
  ${ttgamma_sample_role_policy}

Expected:
  split
EOF
    exit 1
    ;;
esac

trap cleanup_production_plan EXIT
prepare_production_campaign
prepare_production_sumw2_options

###############################################################################
# Main CR production
###############################################################################

if [[ "${run_cr}" == "true" ]]; then
  for year_expr in "${cr_year_sets[@]}"; do
    for category_index in "${!cr_category_sets[@]}"; do
      category_set="${cr_category_sets[category_index]}"
      category_var_set_name="${cr_category_var_set_names[category_index]}"

      declare -n category_var_sets="${category_var_set_name}"
      read -r -a cats <<< "${category_set}"

      for var_set in "${category_var_sets[@]}"; do
        run_cr_block "${year_expr}" "${var_set}" "${cats[@]}"
      done

      unset -n category_var_sets
    done
  done
else
  echo "Skipping CR production because run_cr=${run_cr}"
  echo
fi

###############################################################################
# Main SR production
###############################################################################

if [[ "${run_sr}" == "true" ]]; then
  for year_index in "${!sr_year_sets[@]}"; do
    year_expr="${sr_year_sets[year_index]}"
    category_set_array_name="${sr_year_category_set_names[year_index]}"
    category_var_map_array_name="${sr_year_category_var_set_names[year_index]}"

    declare -n active_category_sets="${category_set_array_name}"
    declare -n active_category_var_set_names="${category_var_map_array_name}"

    assert_parallel_array_lengths \
      "SR category-to-variable mapping for '${year_expr}'" \
      "${#active_category_sets[@]}" \
      "${#active_category_var_set_names[@]}"

    for category_index in "${!active_category_sets[@]}"; do
      category_set="${active_category_sets[category_index]}"
      category_var_set_name="${active_category_var_set_names[category_index]}"

      assert_array_defined "${category_var_set_name}"
      declare -n category_var_sets="${category_var_set_name}"
      read -r -a cats <<< "${category_set}"

      for var_set in "${category_var_sets[@]}"; do
        run_sr_block "${year_expr}" "${var_set}" "${cats[@]}"
      done

      unset -n category_var_sets
    done

    unset -n active_category_sets
    unset -n active_category_var_set_names
  done
else
  echo "Skipping SR production because run_sr=${run_sr}"
  echo
fi

###############################################################################
# Final status
###############################################################################

print_run_summary

echo "campaign_tag: ${campaign_tag}"
echo "ttgamma sample-role policy: ${ttgamma_sample_role_policy}"
echo "output_dir: ${output_dir}"

if (( run_failure_count > 0 )); then
  echo "run_cr.sh finished with ${run_failure_count} failed production block(s)." >&2
  exit 1
fi

echo "run_cr.sh completed successfully"
exit 0
