#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage: ./run_cr.sh [--production-profile baseline|rebin_fine] [--dry-run] \
  [--output-dir PATH] [--campaign-tag TAG]

The default no-argument invocation preserves the existing baseline/resume
configuration. The rebin_fine profile prepares only the source histogram
families whose fitting bins changed. Its non-dry invocation requires an
explicit fresh output directory and campaign tag.
EOF
}

production_profile="baseline"
profile_dry_run=false
profile_output_dir=""
profile_campaign_tag=""

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

case "${production_profile}" in
  baseline|rebin_fine) ;;
  *)
    echo "ERROR: unsupported production profile '${production_profile}'." >&2
    exit 1
    ;;
esac

cd /users/apiccine/work/correction-lib/topeft/analysis/topeft_run2

###############################################################################
# Global configuration
###############################################################################

output_dir="/groups/klannon/apiccine/preappr_v9_260729"
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

# Use a strategy-specific tag to avoid mixing baseline, feature, and diagnostic
# outputs.
campaign_tag="ANv9"

if [[ "${production_profile}" == "rebin_fine" ]]; then
  run_cr=false
  run_sr=true
  dry_run="${profile_dry_run}"

  if [[ "${dry_run}" == "true" ]]; then
    output_dir="${profile_output_dir:-/tmp/rebin_fine_dry_run}"
    campaign_tag="${profile_campaign_tag:-rebin_fine_dry_run}"
  else
    if [[ -z "${profile_output_dir}" || -z "${profile_campaign_tag}" ]]; then
      cat >&2 <<EOF
ERROR: rebin_fine production requires explicit --output-dir and --campaign-tag.

Use --dry-run to inspect the static plan without production side effects.
EOF
      exit 1
    fi
    output_dir="${profile_output_dir}"
    campaign_tag="${profile_campaign_tag}"
  fi

  if [[ "${output_dir}" == "/groups/klannon/apiccine/preappr_v9_260729" ]] \
    || [[ "${campaign_tag}" == "ANv9" ]]; then
    echo "ERROR: rebin_fine must not reuse the baseline/resume output namespace." >&2
    exit 1
  fi

  if [[ "${dry_run}" == "false" && -e "${output_dir}" ]]; then
    echo "ERROR: rebin_fine output directory already exists: ${output_dir}" >&2
    exit 1
  fi
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

# Run 2 retains the successful combined off-Z grouping. Run 3 splits the
# negative- and positive-charge off-Z families so each large artifact remains
# smaller and failures are isolated more narrowly.
sr_run2_category_sets=(
  "2l 2lss_1tau 2los_1tau 4l"
  "3l_m_offZ 3l_p_offZ"
  "3l_onZ_tau"
  "3l_fwd"
)

sr_run2_category_var_set_names=(
  "sr_with_ptz_wtau_var_sets"
  "sr_offz_var_sets"
  "sr_onz_tau_var_sets"
  "sr_fwd_var_sets"
)

sr_run3_category_sets=(
  "2l 2lss_1tau 2los_1tau 4l"
  "3l_m_offZ"
  "3l_p_offZ"
  "3l_onZ_tau"
  "3l_fwd"
)

sr_run3_category_var_set_names=(
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

# Each year expression selects its own category layout and variable mapping.
sr_year_sets=(
  "2016APV 2016 2017 2018"
  "2022 2022EE 2023 2023BPix"
)

sr_year_category_set_names=(
  "sr_run2_category_sets"
  "sr_run3_category_sets"
)

sr_year_category_var_set_names=(
  "sr_run2_category_var_set_names"
  "sr_run3_category_var_set_names"
)

# Exact SR blocks that must not be rerun while resuming the current campaign.
#
# Key format:
#   "<year expression>|<category expression>"
#
# The two split Run 3 off-Z entries are intentionally marked covered by the
# already-produced combined Run 3 off-Z processor artifact. Keep them here only
# after its manual streaming data-driven recovery has completed successfully.
# Empty this array before a clean production from scratch.
sr_completed_block_keys=(
  "2016APV 2016 2017 2018|2l 2lss_1tau 2los_1tau 4l"
  "2016APV 2016 2017 2018|3l_m_offZ 3l_p_offZ"
  "2016APV 2016 2017 2018|3l_onZ_tau"
  "2016APV 2016 2017 2018|3l_fwd"
  "2022 2022EE 2023 2023BPix|2l 2lss_1tau 2los_1tau 4l"
  "2022 2022EE 2023 2023BPix|3l_m_offZ"
  "2022 2022EE 2023 2023BPix|3l_p_offZ"
)

# Guard the current campaign resume against accidentally treating the split
# Run 3 off-Z blocks as complete before the manually recovered combined _np
# artifact exists. Set to false only for a deliberately fresh campaign after
# also resetting sr_completed_block_keys.
require_recovered_run3_offz_np=true
recovered_run3_offz_np="${output_dir}/2022-2022EE-2023-2023BPixSRs_ANv9_3l_m_offZ-3l_p_offZ_njets-lj0pt-ptz-lt_np.pkl.gz"

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
  sr_completed_block_keys=()
  require_recovered_run3_offz_np=false
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

# Intentional workaround: clear cached remote-environment artifacts before each
# production block to avoid the previously observed environment failure mode.
# Do not remove this from the per-block execution path without revalidating that
# failure mode.
clean_env_cache() {
  if [[ -d topeft-envs ]]; then
    find topeft-envs \
      -mindepth 1 \
      -maxdepth 1 \
      \( -type f -o -type l \) \
      -delete
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

is_completed_sr_block() {
  local year_expr="$1"
  local category_set="$2"
  local block_key="${year_expr}|${category_set}"
  local completed_block_key

  for completed_block_key in "${sr_completed_block_keys[@]}"; do
    if [[ "${block_key}" == "${completed_block_key}" ]]; then
      return 0
    fi
  done

  return 1
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
    cmd_ref+=(--do-np)
  fi

  cmd_ref+=(
    -p "${output_dir}"
    --all-analysis
  )

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

  if [[ "${dry_run}" == "false" ]]; then
    clean_env_cache
  fi

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
  local start_epoch
  local end_epoch
  local duration_seconds
  local exit_code

  read -r -a years <<< "${year_expr}"
  read -r -a vars <<< "${var_set}"

  cat_tag=$(join_by - "${cats[@]}")
  var_tag=$(join_by - "${vars[@]}")
  pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"

  echo "----------------------------------------"
  echo "Mode: SR"
  echo "Years: ${year_expr}"
  echo "Categories: ${cats[*]}"
  echo "Variables: ${vars[*]}"
  echo "ttgamma sample-role policy: ${ttgamma_sample_role_policy}"
  echo "Campaign tag: ${campaign_tag}"
  echo "Output tag: ${pkl_tag}"
  echo "Output dir: ${output_dir}"
  echo "Dry run: ${dry_run}"
  echo "----------------------------------------"

  if [[ "${dry_run}" == "false" ]]; then
    clean_env_cache
  fi

  local cmd=(
    ./fullR3_run.sh
    -y "${years[@]}"
    -t "${pkl_tag}"
    -s "${chunk_size}"
    --sr
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
      "SUCCESS" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo "${year_expr} SR done for ${cat_tag} / ${var_tag}"
  else
    record_block_result \
      "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo \
      "ERROR: ${year_expr} SR failed for ${cat_tag} / ${var_tag} with exit code ${exit_code}; continuing with the next block." \
      >&2
  fi

  echo "----------------------------------------"
  echo
}

record_completed_sr_block() {
  local year_expr="$1"
  local category_set="$2"
  local var_set="$3"
  local cats=()
  local vars=()
  local cat_tag
  local var_tag
  local pkl_tag

  read -r -a cats <<< "${category_set}"
  read -r -a vars <<< "${var_set}"

  cat_tag=$(join_by - "${cats[@]}")
  var_tag=$(join_by - "${vars[@]}")

  # The split Run 3 off-Z blocks are currently skipped because the completed
  # combined artifact covers both logical category families. Report that actual
  # artifact tag rather than implying that separate split files already exist.
  if [[ "${year_expr}" == "2022 2022EE 2023 2023BPix" ]] \
    && [[ "${category_set}" == "3l_m_offZ" || "${category_set}" == "3l_p_offZ" ]]; then
    pkl_tag="${sr_pkl_base_tag}_3l_m_offZ-3l_p_offZ_${var_tag}"
  else
    pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"
  fi

  record_block_result \
    "SKIPPED" "SR" "${year_expr}" "${category_set}" "${var_set}" \
    "${pkl_tag}" "0" "0"
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
assert_boolean "${require_recovered_run3_offz_np}" "require_recovered_run3_offz_np"

assert_parallel_array_lengths \
  "CR category-to-variable mapping" \
  "${#cr_category_sets[@]}" \
  "${#cr_category_var_set_names[@]}"

assert_parallel_array_lengths \
  "Run 2 SR category-to-variable mapping" \
  "${#sr_run2_category_sets[@]}" \
  "${#sr_run2_category_var_set_names[@]}"

assert_parallel_array_lengths \
  "Run 3 SR category-to-variable mapping" \
  "${#sr_run3_category_sets[@]}" \
  "${#sr_run3_category_var_set_names[@]}"

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
  "${sr_run2_category_var_set_names[@]}" \
  "${sr_run3_category_var_set_names[@]}"; do
  assert_array_defined "${var_set_name}"
done

for category_array_name in "${sr_year_category_set_names[@]}"; do
  assert_array_defined "${category_array_name}"
done

for mapping_array_name in "${sr_year_category_var_set_names[@]}"; do
  assert_array_defined "${mapping_array_name}"
done

if [[ "${run_sr}" == "true" ]] \
  && [[ "${require_recovered_run3_offz_np}" == "true" ]] \
  && [[ "${dry_run}" == "false" ]] \
  && [[ ! -s "${recovered_run3_offz_np}" ]]; then
  cat >&2 <<EOF
ERROR: the current resume configuration marks the split Run 3 off-Z blocks as
covered by the previously produced combined artifact, but the manually recovered
combined _np output is not present or is empty:

  ${recovered_run3_offz_np}

Complete and validate that recovery before restarting this campaign, or set
require_recovered_run3_offz_np=false and adjust sr_completed_block_keys for a
deliberately fresh/reprocessed campaign.
EOF
  exit 1
fi

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
echo "require_recovered_run3_offz_np: ${require_recovered_run3_offz_np}"
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
  echo "Run 2 SR category blocks:"
  printf '  %s\n' "${sr_run2_category_sets[@]}"
  echo "Run 3 SR category blocks:"
  printf '  %s\n' "${sr_run3_category_sets[@]}"
fi

echo "SR completed-block skip list:"
if (( ${#sr_completed_block_keys[@]} == 0 )); then
  echo "  none"
else
  for completed_block_key in "${sr_completed_block_keys[@]}"; do
    echo "  ${completed_block_key}"
  done
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

      if is_completed_sr_block "${year_expr}" "${category_set}"; then
        for var_set in "${category_var_sets[@]}"; do
          echo "----------------------------------------"
          echo "Skipping completed SR block"
          echo "Years: ${year_expr}"
          echo "Categories: ${category_set}"
          echo "Variables: ${var_set}"
          echo "----------------------------------------"
          echo
          record_completed_sr_block "${year_expr}" "${category_set}" "${var_set}"
        done
        unset -n category_var_sets
        continue
      fi

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
