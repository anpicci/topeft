#!/usr/bin/env bash
set -euo pipefail

print_usage() {
  cat <<'EOF'
Usage: ./run_cr.sh [--production-profile baseline|rebin_fine] [--dry-run] \
  [--output-dir PATH] [--campaign-tag TAG] [--env-file PATH] [--resume]

The default no-argument invocation preserves the existing baseline/resume
configuration. The rebin_fine profile prepares only the source histogram
families whose fitting bins changed. Its non-dry invocation requires an
explicit fresh output directory, campaign tag, and verified absolute Poncho
environment archive. Use --resume only for a matching rebin_fine campaign.
EOF
}

production_profile="baseline"
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
rebin_fine_env_file=""
rebin_fine_env_file_sha256=""
rebin_fine_state_path=""
rebin_fine_git_commit=""

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

  if [[ -z "${profile_env_file}" ]]; then
    echo "ERROR: rebin_fine requires --env-file for both dry-run and production." >&2
    exit 1
  fi

  if [[ "${profile_env_file}" != /* ]]; then
    echo "ERROR: rebin_fine --env-file must be an absolute path: ${profile_env_file}" >&2
    exit 1
  fi

  if [[ ! -f "${profile_env_file}" || ! -r "${profile_env_file}" || ! -s "${profile_env_file}" ]]; then
    echo "ERROR: rebin_fine --env-file must be a readable, non-empty regular file: ${profile_env_file}" >&2
    exit 1
  fi

  rebin_fine_env_file=$(readlink -f -- "${profile_env_file}")
  if [[ -z "${rebin_fine_env_file}" || ! -f "${rebin_fine_env_file}" || ! -r "${rebin_fine_env_file}" || ! -s "${rebin_fine_env_file}" ]]; then
    echo "ERROR: unable to resolve a readable, non-empty rebin_fine environment archive: ${profile_env_file}" >&2
    exit 1
  fi
  rebin_fine_env_file_sha256=$(sha256sum -- "${rebin_fine_env_file}" | awk '{print $1}')

  for rebin_fine_state_value in "${output_dir}" "${campaign_tag}" "${rebin_fine_env_file}"; do
    if [[ "${rebin_fine_state_value}" == *$'\t'* || "${rebin_fine_state_value}" == *$'\n'* ]]; then
      echo "ERROR: rebin_fine state fields must not contain tab or newline characters." >&2
      exit 1
    fi
  done

  if [[ "${output_dir}" == "/groups/klannon/apiccine/preappr_v9_260729" ]] \
    || [[ "${campaign_tag}" == "ANv9" ]]; then
    echo "ERROR: rebin_fine must not reuse the baseline/resume output namespace." >&2
    exit 1
  fi

  if [[ "${dry_run}" == "false" && "${output_dir}" != /* ]]; then
    echo "ERROR: rebin_fine --output-dir must be an absolute path: ${output_dir}" >&2
    exit 1
  fi

  if [[ "${profile_resume}" == "false" && -e "${output_dir}" ]]; then
    echo "ERROR: rebin_fine output directory already exists: ${output_dir}" >&2
    exit 1
  fi

  if [[ "${profile_resume}" == "true" && "${dry_run}" == "false" && ! -d "${output_dir}" ]]; then
    echo "ERROR: rebin_fine --resume requires an existing campaign output directory: ${output_dir}" >&2
    exit 1
  fi
elif [[ "${profile_resume}" == "true" || -n "${profile_env_file}" ]]; then
  echo "ERROR: --resume and --env-file are only supported with --production-profile rebin_fine." >&2
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

rebin_fine_state_filename=".rebin_fine_campaign_state.json"
rebin_fine_block_ids=()
rebin_fine_plan_year_exprs=()
rebin_fine_plan_category_sets=()
rebin_fine_plan_var_sets=()

if [[ "${production_profile}" == "rebin_fine" ]]; then
  rebin_fine_block_ids=(
    "run2_a"
    "run2_b"
    "run2_c"
    "run3_a"
    "run3_b"
    "run3_c"
  )
  rebin_fine_plan_year_exprs=(
    "2016APV 2016 2017 2018"
    "2016APV 2016 2017 2018"
    "2016APV 2016 2017 2018"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
    "2022 2022EE 2023 2023BPix"
  )
  rebin_fine_plan_category_sets=(
    "2lss_1tau 3l_m_offZ"
    "3l_p_offZ 3l_onZ_tau"
    "3l_fwd"
    "2lss_1tau 3l_m_offZ"
    "3l_p_offZ 3l_onZ_tau"
    "3l_fwd"
  )
  rebin_fine_plan_var_sets=(
    "lj0pt ptll ptz_wtau"
    "lj0pt ptz ptll"
    "lt"
    "lj0pt ptll ptz_wtau"
    "lj0pt ptz ptll"
    "lt"
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

rebin_fine_output_name() {
  local year_expr="$1"
  local pkl_tag="$2"
  local years=()
  local year_label

  read -r -a years <<< "${year_expr}"
  year_label=$(join_by - "${years[@]}")
  printf '%sSRs_%s' "${year_label}" "${pkl_tag}"
}

write_rebin_fine_plan() {
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
  for index in "${!rebin_fine_block_ids[@]}"; do
    year_expr="${rebin_fine_plan_year_exprs[index]}"
    category_set="${rebin_fine_plan_category_sets[index]}"
    var_set="${rebin_fine_plan_var_sets[index]}"
    read -r -a cats <<< "${category_set}"
    read -r -a vars <<< "${var_set}"
    cat_tag=$(join_by - "${cats[@]}")
    var_tag=$(join_by - "${vars[@]}")
    pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"
    output_name=$(rebin_fine_output_name "${year_expr}" "${pkl_tag}")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${rebin_fine_block_ids[index]}" \
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

rebin_fine_state_tool() {
  python - "$@" <<'PY'
import datetime
import json
import os
import sys
from pathlib import Path


VALID_STATUSES = {"planned", "running", "success", "failed_or_incomplete"}


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


def read_plan(path):
    blocks = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read generated rebin_fine plan {path}: {exc}")
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 8:
            fail(f"invalid generated rebin_fine plan row: {line!r}")
        block_id, years, categories, histograms, output_tag, output_name, nominal, nonprompt = fields
        blocks.append(
            {
                "id": block_id,
                "years": years.split(),
                "category_groups": categories.split(),
                "histograms": histograms.split(),
                "output_tag": output_tag,
                "output_name": output_name,
                "expected_outputs": [nominal, nonprompt],
            }
        )
    if len(blocks) != 6 or len({block["id"] for block in blocks}) != len(blocks):
        fail("generated rebin_fine plan does not contain six unique blocks")
    return blocks


def desired_state(arguments):
    plan_path = Path(arguments[0])
    tag, output_dir, commit, env_file, env_sha256, ttgamma, do_systs, do_np = arguments[1:]
    return {
        "schema_version": 1,
        "production_profile": "rebin_fine",
        "campaign_tag": tag,
        "output_dir": output_dir,
        "topeft_git_commit": commit,
        "env_file": env_file,
        "env_file_sha256": env_sha256,
        "ttgamma_sample_role_policy": ttgamma,
        "do_systs": do_systs == "true",
        "do_np": do_np == "true",
        "blocks": read_plan(plan_path),
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
        "ttgamma_sample_role_policy",
        "do_systs",
        "do_np",
    ):
        if state.get(key) != desired[key]:
            fail(f"campaign state mismatch for {key}: recorded={state.get(key)!r} requested={desired[key]!r}")
    recorded_blocks = state.get("blocks")
    if not isinstance(recorded_blocks, list) or len(recorded_blocks) != len(desired["blocks"]):
        fail("campaign state block count does not match the live six-block plan")
    block_keys = ("id", "years", "category_groups", "histograms", "output_tag", "output_name", "expected_outputs")
    for recorded, expected in zip(recorded_blocks, desired["blocks"]):
        for key in block_keys:
            if recorded.get(key) != expected[key]:
                fail(f"campaign state mismatch for block {expected['id']} field {key}")
        if recorded.get("status") not in VALID_STATUSES:
            fail(f"campaign state has invalid status for block {expected['id']}: {recorded.get('status')!r}")


mode = sys.argv[1]
state_path = Path(sys.argv[2])

if mode in {"initialize", "validate"}:
    desired = desired_state(sys.argv[3:12])
    readonly = len(sys.argv) > 12 and sys.argv[12] == "true"
    if mode == "initialize":
        if state_path.exists():
            fail(f"refusing to overwrite existing rebin_fine campaign state: {state_path}")
        state = desired
        timestamp = now_utc()
        state["created_at_utc"] = timestamp
        state["updated_at_utc"] = timestamp
        state["blocks"] = [
            {**block, "status": "planned", "exit_code": None, "last_transition_utc": timestamp}
            for block in desired["blocks"]
        ]
        atomic_write(state_path, state)
    else:
        state = load(state_path)
        validate_state(state, desired)
        changed = False
        for block in state["blocks"]:
            if block["status"] == "running":
                if not readonly:
                    block["status"] = "failed_or_incomplete"
                    block["last_transition_utc"] = now_utc()
                    block["last_transition_detail"] = "resume_observed_previous_running_state"
                    changed = True
        if changed:
            state["updated_at_utc"] = now_utc()
            atomic_write(state_path, state)
    raise SystemExit(0)

state = load(state_path)
if mode == "status":
    block_id = sys.argv[3]
    for block in state.get("blocks", []):
        if block.get("id") == block_id:
            print(block.get("status", ""))
            raise SystemExit(0)
    fail(f"campaign state does not contain block {block_id}")

if mode == "mark":
    block_id, status, exit_code, detail = sys.argv[3:7]
    if status not in VALID_STATUSES:
        fail(f"invalid requested block status {status!r}")
    for block in state.get("blocks", []):
        if block.get("id") == block_id:
            block["status"] = status
            block["exit_code"] = None if exit_code == "none" else int(exit_code)
            block["last_transition_utc"] = now_utc()
            block["last_transition_detail"] = detail
            state["updated_at_utc"] = now_utc()
            atomic_write(state_path, state)
            raise SystemExit(0)
    fail(f"campaign state does not contain block {block_id}")

fail(f"unsupported rebin_fine state operation {mode!r}")
PY
}

rebin_fine_block_id() {
  local year_expr="$1"
  local category_set="$2"
  local index

  for index in "${!rebin_fine_block_ids[@]}"; do
    if [[ "${year_expr}" == "${rebin_fine_plan_year_exprs[index]}" ]] \
      && [[ "${category_set}" == "${rebin_fine_plan_category_sets[index]}" ]]; then
      printf '%s' "${rebin_fine_block_ids[index]}"
      return 0
    fi
  done

  echo "ERROR: unable to resolve rebin_fine block identity for '${year_expr}' / '${category_set}'." >&2
  return 1
}

rebin_fine_outputs_present() {
  local block_id="$1"
  local plan_path="$2"
  local nominal_path
  local nonprompt_path

  IFS=$'\t' read -r _ _ _ _ _ _ nominal_path nonprompt_path < <(
    awk -F '\t' -v block_id="${block_id}" '$1 == block_id {print; exit}' "${plan_path}"
  )
  [[ -n "${nominal_path}" && -n "${nonprompt_path}" && -s "${nominal_path}" && -s "${nonprompt_path}" ]]
}

rebin_fine_any_output_exists() {
  local block_id="$1"
  local plan_path="$2"
  local nominal_path
  local nonprompt_path

  IFS=$'\t' read -r _ _ _ _ _ _ nominal_path nonprompt_path < <(
    awk -F '\t' -v block_id="${block_id}" '$1 == block_id {print; exit}' "${plan_path}"
  )
  [[ -e "${nominal_path}" || -e "${nonprompt_path}" ]]
}

rebin_fine_assert_live_plan() {
  local index
  local var_set_name

  if (( ${#rebin_fine_block_ids[@]} != 6 )); then
    echo "ERROR: rebin_fine state plan must contain exactly six blocks." >&2
    exit 1
  fi

  if (( ${#sr_year_sets[@]} != 2 )) \
    || [[ "${sr_year_sets[0]}" != "2016APV 2016 2017 2018" ]] \
    || [[ "${sr_year_sets[1]}" != "2022 2022EE 2023 2023BPix" ]]; then
    echo "ERROR: live rebin_fine year packing no longer matches the frozen six-block contract." >&2
    exit 1
  fi

  for index in 0 1 2; do
    if [[ "${rebin_fine_category_sets[index]}" != "${rebin_fine_plan_category_sets[index]}" ]] \
      || [[ "${rebin_fine_plan_category_sets[index]}" != "${rebin_fine_plan_category_sets[index + 3]}" ]]; then
      echo "ERROR: live rebin_fine category packing no longer matches the frozen plan." >&2
      exit 1
    fi
    var_set_name="${rebin_fine_category_var_set_names[index]}"
    declare -n rebin_fine_var_set_ref="${var_set_name}"
    if (( ${#rebin_fine_var_set_ref[@]} != 1 )) \
      || [[ "${rebin_fine_var_set_ref[0]}" != "${rebin_fine_plan_var_sets[index]}" ]] \
      || [[ "${rebin_fine_plan_var_sets[index]}" != "${rebin_fine_plan_var_sets[index + 3]}" ]]; then
      echo "ERROR: live rebin_fine histogram packing no longer matches the frozen plan." >&2
      unset -n rebin_fine_var_set_ref
      exit 1
    fi
    unset -n rebin_fine_var_set_ref
  done

  for index in "${!rebin_fine_plan_var_sets[@]}"; do
    if [[ " ${rebin_fine_plan_var_sets[index]} " == *" njets "* ]]; then
      echo "ERROR: rebin_fine must not request njets." >&2
      exit 1
    fi
  done
}

prepare_rebin_fine_campaign() {
  local plan_directory

  rebin_fine_assert_live_plan
  rebin_fine_git_commit=$(git -C /users/apiccine/work/correction-lib/topeft rev-parse HEAD)
  rebin_fine_state_path="${output_dir}/${rebin_fine_state_filename}"

  if [[ "${dry_run}" == "true" ]]; then
    rebin_fine_plan_file=$(mktemp /tmp/rebin_fine_plan.XXXXXX)
  else
    if [[ "${profile_resume}" == "false" ]]; then
      mkdir -- "${output_dir}"
    fi
    plan_directory="${output_dir}"
    rebin_fine_plan_file=$(mktemp "${plan_directory}/.rebin_fine_plan.XXXXXX")
  fi
  write_rebin_fine_plan "${rebin_fine_plan_file}"

  if [[ "${profile_resume}" == "true" ]]; then
    if [[ ! -f "${rebin_fine_state_path}" ]]; then
      echo "ERROR: rebin_fine --resume requires campaign state: ${rebin_fine_state_path}" >&2
      exit 1
    fi
    rebin_fine_state_tool validate \
      "${rebin_fine_state_path}" \
      "${rebin_fine_plan_file}" \
      "${campaign_tag}" \
      "${output_dir}" \
      "${rebin_fine_git_commit}" \
      "${rebin_fine_env_file}" \
      "${rebin_fine_env_file_sha256}" \
      "${ttgamma_sample_role_policy}" \
      "${do_systs}" \
      "${do_np}" \
      "${dry_run}"
  elif [[ "${dry_run}" == "false" ]]; then
    rebin_fine_state_tool initialize \
      "${rebin_fine_state_path}" \
      "${rebin_fine_plan_file}" \
      "${campaign_tag}" \
      "${output_dir}" \
      "${rebin_fine_git_commit}" \
      "${rebin_fine_env_file}" \
      "${rebin_fine_env_file_sha256}" \
      "${ttgamma_sample_role_policy}" \
      "${do_systs}" \
      "${do_np}"
  fi
}

cleanup_rebin_fine_plan() {
  if [[ -n "${rebin_fine_plan_file:-}" && -f "${rebin_fine_plan_file}" ]]; then
    rm -f -- "${rebin_fine_plan_file}"
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
    cmd_ref+=(--do-np)
  fi

  cmd_ref+=(
    -p "${output_dir}"
    --all-analysis
  )

  if [[ "${production_profile}" == "rebin_fine" ]]; then
    cmd_ref+=(--env-file "${rebin_fine_env_file}")
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

  if [[ "${dry_run}" == "false" && "${production_profile}" != "rebin_fine" ]]; then
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
  local rebin_fine_block=""
  local rebin_fine_status=""

  read -r -a years <<< "${year_expr}"
  read -r -a vars <<< "${var_set}"

  cat_tag=$(join_by - "${cats[@]}")
  var_tag=$(join_by - "${vars[@]}")
  pkl_tag="${sr_pkl_base_tag}_${cat_tag}_${var_tag}"

  if [[ "${production_profile}" == "rebin_fine" ]]; then
    rebin_fine_block=$(rebin_fine_block_id "${year_expr}" "${cats[*]}")
    if [[ "${dry_run}" == "true" && "${profile_resume}" == "false" ]]; then
      rebin_fine_status="planned"
    else
      rebin_fine_status=$(rebin_fine_state_tool status "${rebin_fine_state_path}" "${rebin_fine_block}")
    fi

    if [[ "${rebin_fine_status}" == "success" ]]; then
      if rebin_fine_outputs_present "${rebin_fine_block}" "${rebin_fine_plan_file}"; then
        echo "----------------------------------------"
        echo "Skipping validated rebin_fine block: ${rebin_fine_block}"
        echo "Campaign state and both expected artifacts are present."
        echo "----------------------------------------"
        record_block_result \
          "SKIPPED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
          "${pkl_tag}" "0" "0"
        return 0
      fi
      if [[ "${dry_run}" == "false" ]]; then
        rebin_fine_state_tool mark \
          "${rebin_fine_state_path}" "${rebin_fine_block}" \
          "failed_or_incomplete" "none" "success_state_missing_expected_output"
      fi
      echo "ERROR: rebin_fine state marks ${rebin_fine_block} successful, but an expected artifact is missing or empty." >&2
      exit 1
    fi

    if rebin_fine_any_output_exists "${rebin_fine_block}" "${rebin_fine_plan_file}"; then
      echo "ERROR: rebin_fine block ${rebin_fine_block} is ${rebin_fine_status}, but an expected output path already exists. Refusing ambiguous overwrite." >&2
      exit 1
    fi

    if [[ "${dry_run}" == "false" ]]; then
      rebin_fine_state_tool mark \
        "${rebin_fine_state_path}" "${rebin_fine_block}" \
        "running" "none" "child_command_started"
    fi
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
  echo "Dry run: ${dry_run}"
  echo "----------------------------------------"

  if [[ "${dry_run}" == "false" && "${production_profile}" != "rebin_fine" ]]; then
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

  if [[ "${production_profile}" == "rebin_fine" && "${dry_run}" == "true" ]]; then
    record_block_result \
      "DRY_RUN" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo "${year_expr} rebin_fine dry-run resolved for ${cat_tag} / ${var_tag}"
  elif (( exit_code == 0 )) \
    && [[ "${production_profile}" == "rebin_fine" ]] \
    && ! rebin_fine_outputs_present "${rebin_fine_block}" "${rebin_fine_plan_file}"; then
    rebin_fine_state_tool mark \
      "${rebin_fine_state_path}" "${rebin_fine_block}" \
      "failed_or_incomplete" "${exit_code}" "child_exit_zero_missing_expected_output"
    record_block_result \
      "FAILED" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo "ERROR: ${year_expr} SR returned zero for ${cat_tag} / ${var_tag}, but expected rebin_fine artifacts are missing or empty." >&2
  elif (( exit_code == 0 )); then
    if [[ "${production_profile}" == "rebin_fine" ]]; then
      rebin_fine_state_tool mark \
        "${rebin_fine_state_path}" "${rebin_fine_block}" \
        "success" "${exit_code}" "child_exit_zero_expected_outputs_present"
    fi
    record_block_result \
      "SUCCESS" "SR" "${year_expr}" "${cats[*]}" "${vars[*]}" \
      "${pkl_tag}" "${exit_code}" "${duration_seconds}"
    echo "${year_expr} SR done for ${cat_tag} / ${var_tag}"
  else
    if [[ "${production_profile}" == "rebin_fine" ]]; then
      rebin_fine_state_tool mark \
        "${rebin_fine_state_path}" "${rebin_fine_block}" \
        "failed_or_incomplete" "${exit_code}" "child_exit_nonzero"
    fi
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
assert_boolean "${profile_resume}" "profile_resume"

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
if [[ "${production_profile}" == "rebin_fine" ]]; then
  echo "resume: ${profile_resume}"
  echo "env_file: ${rebin_fine_env_file}"
  echo "env_file_sha256: ${rebin_fine_env_file_sha256}"
  echo "environment_policy: explicit_single_archive"
  echo "campaign_state: ${output_dir}/${rebin_fine_state_filename}"
fi
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

if [[ "${production_profile}" == "rebin_fine" ]]; then
  trap cleanup_rebin_fine_plan EXIT
  prepare_rebin_fine_campaign
fi

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
