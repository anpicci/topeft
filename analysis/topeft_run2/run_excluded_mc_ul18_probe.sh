#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --run {run2|run3} --block {a|d} --campaign-tag TAG --output-root PATH --manager-name NAME --port PORT --wq-staging-base PATH --wq-quota-root PATH --wq-free-warning-bytes N --wq-min-free-bytes N --wq-poll-seconds N --env-file PATH (--dry-run | --execute)" >&2
}

run=""
block=""
campaign_tag=""
output_root=""
manager_name=""
port=""
wq_staging_base=""
wq_quota_root=""
wq_free_warning_bytes=""
wq_min_free_bytes=""
wq_poll_seconds=""
env_file=""
dry_run=false
execute=false

while (($#)); do
  case "$1" in
    --run) run="${2:-}"; shift 2 ;;
    --block) block="${2:-}"; shift 2 ;;
    --campaign-tag) campaign_tag="${2:-}"; shift 2 ;;
    --output-root) output_root="${2:-}"; shift 2 ;;
    --manager-name) manager_name="${2:-}"; shift 2 ;;
    --port) port="${2:-}"; shift 2 ;;
    --wq-staging-base) wq_staging_base="${2:-}"; shift 2 ;;
    --wq-quota-root) wq_quota_root="${2:-}"; shift 2 ;;
    --wq-free-warning-bytes) wq_free_warning_bytes="${2:-}"; shift 2 ;;
    --wq-min-free-bytes) wq_min_free_bytes="${2:-}"; shift 2 ;;
    --wq-poll-seconds) wq_poll_seconds="${2:-}"; shift 2 ;;
    --env-file) env_file="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    --execute) execute=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ -z "$run" || -z "$block" || -z "$campaign_tag" ||
      -z "$output_root" || -z "$manager_name" || -z "$port" ||
      -z "$wq_staging_base" || -z "$wq_quota_root" ||
      -z "$wq_free_warning_bytes" || -z "$wq_min_free_bytes" ||
      -z "$wq_poll_seconds" || -z "$env_file" ]]; then
  usage
  exit 2
fi
if [[ "$dry_run" == "$execute" ]]; then
  echo "Specify exactly one of --dry-run and --execute." >&2
  exit 2
fi
if [[ "$run" != "run2" && "$run" != "run3" ]]; then
  echo "Run must be run2 or run3." >&2
  exit 2
fi
if [[ "$block" != "a" && "$block" != "d" ]]; then
  echo "Block must be a or d." >&2
  exit 2
fi
if [[ ! "$campaign_tag" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Campaign tag must contain only letters, digits, underscores, or hyphens." >&2
  exit 2
fi
if [[ ! "$manager_name" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Manager name must contain only letters, digits, underscores, or hyphens." >&2
  exit 2
fi
user_lower="${USER:-}"
user_lower="${user_lower,,}"
manager_lower="${manager_name,,}"
if [[ "$manager_lower" != *excludedmc* || "$manager_lower" != *"$run"* ||
      "$manager_lower" != *"block-$block"* ]]; then
  echo "Manager name must identify excludedmc, $run, and block-$block." >&2
  exit 2
fi
if [[ -n "$user_lower" && "$manager_lower" == *"$user_lower"* ]]; then
  echo "Manager name must not include the user name." >&2
  exit 2
fi
if [[ "$output_root" != /* || "$wq_staging_base" != /* ||
      "$wq_quota_root" != /* || "$env_file" != /* ]]; then
  echo "Output, staging, quota, and environment paths must be absolute." >&2
  exit 2
fi
if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  echo "Port must be an integer from 1 through 65535." >&2
  exit 2
fi
for amount in "$wq_free_warning_bytes" "$wq_min_free_bytes"; do
  if [[ ! "$amount" =~ ^[0-9]+$ ]] || ((amount < 1)); then
    echo "Work Queue free-space thresholds must be positive integers." >&2
    exit 2
  fi
done
if [[ ! "$wq_poll_seconds" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Work Queue poll seconds must be a nonnegative number." >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cfg_path="$script_dir/../../input_samples/cfgs/excluded_mc_${run}_sr_probe.cfg"
runner="$script_dir/fullR3_run_excluded_mc_ul18.sh"
output_dir="$output_root/$run"
outname="excluded_mc_${run}_block_${block}_njets"
output_pkl="$output_dir/$outname.pkl.gz"
log_dir="$output_dir/work_queue_logs/$outname/source_native"

case "$block" in
  a) category_groups=(2l 2los_1tau) ;;
  d) category_groups=(3l_onZ_tau) ;;
esac

if [[ ! -f "$cfg_path" ]]; then
  echo "Excluded-MC CFG is absent: $cfg_path" >&2
  exit 2
fi
if [[ "$execute" == true ]]; then
  if [[ -e "$output_pkl" || -L "$output_pkl" ||
        -e "$output_pkl.metadata.json" || -L "$output_pkl.metadata.json" ]]; then
    echo "Refusing to overwrite an existing output or sidecar: $output_pkl" >&2
    exit 2
  fi
  if [[ ! -f "$env_file" ]]; then
    echo "Prebuilt environment archive is absent: $env_file" >&2
    exit 2
  fi
fi

command=(
  "$runner"
  -y "$run"
  --sr
  --hist-vars njets
  --output-name "$outname"
  -s 50000
  --cfg-override "$cfg_path"
  --sample-universe-wrapper fullR3_run_excluded_mc_ul18.sh
  -p "$output_dir"
  -t "$campaign_tag"
  --all-analysis
  --category-groups "${category_groups[@]}"
  --sumw2-family njets
  --wq-manager-name "$manager_name"
  --wq-processing-cores 1
  --wq-accumulating-memory-mb 32000
  --wq-accumulating-cores 2
  --np-postprocess=skip
  -x work_queue
  --port "$port"
  --wq-guard
  --wq-filepath "$wq_staging_base"
  --wq-invocation-id "${campaign_tag}_${run}_block_${block}"
  --wq-quota-root "$wq_quota_root"
  --wq-free-warning-bytes "$wq_free_warning_bytes"
  --wq-min-free-bytes "$wq_min_free_bytes"
  --wq-poll-seconds "$wq_poll_seconds"
  --wq-log-dir "$log_dir"
  --env-file "$env_file"
)
if [[ "$dry_run" == true ]]; then
  command+=(--dry-run)
fi
printf 'EXCLUDED_MC_RUN %s\n' "$run"
printf 'EXCLUDED_MC_BLOCK %s\n' "$block"
printf 'EXCLUDED_MC_CATEGORIES %s\n' "${category_groups[*]}"
printf 'EXCLUDED_MC_OUTPUT %s\n' "$output_pkl"
printf 'EXCLUDED_MC_MANAGER_PENDING %s\n' "$manager_name"
printf 'EXCLUDED_MC_SUMW2_POLICY full_custom:variables=njets:all-active-datasets\n'
cd "$script_dir"
"${command[@]}"
