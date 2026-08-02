#!/usr/bin/env bash
set -euo pipefail

readonly ssm_timeout_seconds=1500
readonly polling_timeout_seconds=1680
readonly poll_seconds=10

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Required environment variable $name is empty." >&2
    exit 64
  fi
}

for name in AWS_DEFAULT_REGION PILOT_INSTANCE_ID BACKEND_REPOSITORY_URL FRONTEND_REPOSITORY_URL CODEBUILD_RESOLVED_SOURCE_VERSION; do
  require_env "$name"
done

IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:12}"
[[ "$IMAGE_TAG" =~ ^[0-9a-f]{12}$ ]] || {
  echo "Resolved source version must begin with a lowercase 12-character Git SHA." >&2
  exit 64
}
[[ "$PILOT_INSTANCE_ID" =~ ^i-[0-9a-f]{8,17}$ ]] || {
  echo "PILOT_INSTANCE_ID must be an EC2 instance ID." >&2
  exit 64
}

readonly ecr_repository_pattern='^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9][a-z0-9/_-]*$'
[[ "$BACKEND_REPOSITORY_URL" =~ $ecr_repository_pattern ]] || {
  echo "BACKEND_REPOSITORY_URL must be a private ECR repository URI." >&2
  exit 64
}
[[ "$FRONTEND_REPOSITORY_URL" =~ $ecr_repository_pattern ]] || {
  echo "FRONTEND_REPOSITORY_URL must be a private ECR repository URI." >&2
  exit 64
}

request_path="$(mktemp)"
cleanup() {
  rm -f "$request_path"
}
trap cleanup EXIT

remote_script=$(cat <<'REMOTE_SCRIPT'
set -euo pipefail

exec 8>/var/lock/skn27-pilot-maintenance.lock
flock -w 60 8 || {
  echo 'Another pilot maintenance workflow is running.' >&2
  exit 75
}

release_dir="$(readlink -f /opt/skn27-pilot/current 2>/dev/null || true)"
[[ -n "$release_dir" && -d "$release_dir" && ! -L "$release_dir" ]] || {
  echo 'Current Pilot release directory is unavailable.' >&2
  exit 78
}
cd "$release_dir"

previous_tag="$(sed -n 's/^RELEASE_TAG=//p' .compose.env)"
[[ "$previous_tag" =~ ^[0-9a-f]{12}$ ]] || {
  echo 'Current release tag is not an immutable twelve-character Git SHA.' >&2
  exit 78
}

target_tag='__IMAGE_TAG__'
[[ "$target_tag" != "$previous_tag" ]] || {
  echo 'Target release already matches the current release.' >&2
  exit 78
}
readonly release_image_retention_count=3
readonly release_reserved_free_bytes=$((5 * 1024 * 1024 * 1024))
registry='__BACKEND_REGISTRY__'
backend_repository='__BACKEND_REPOSITORY__'
frontend_repository='__FRONTEND_REPOSITORY__'
app_domain="$(sed -n 's/^APP_DOMAIN=//p' .edge.env)"
[[ -n "$app_domain" ]] || {
  echo 'Current release does not define APP_DOMAIN.' >&2
  exit 78
}

compose=(docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml)
frontend_image_ref="$frontend_repository:$target_tag"
rollback_frontend_image_ref="$frontend_repository:$previous_tag"
seed_source_file='/opt/skn27-pilot/state/legal-operational-evidence-source.env'
[[ -f "$seed_source_file" ]] || {
  echo 'Verified seed source descriptor is unavailable.' >&2
  exit 78
}

declare -A seed_source=()
while IFS='=' read -r key value; do
  case "$key" in
    RAG_SEED_S3_URI|RAG_SEED_MANIFEST_RELATIVE_PATH|RAG_SEED_MANIFEST_SHA256)
      [[ -z "${seed_source[$key]+x}" ]] || {
        echo 'Seed source descriptor contains a duplicate key.' >&2
        exit 78
      }
      seed_source["$key"]="$value"
      ;;
    *)
      echo 'Seed source descriptor contains an unsupported key.' >&2
      exit 78
      ;;
  esac
done < "$seed_source_file"
[[ "${#seed_source[@]}" -eq 3 ]]
rag_seed_s3_uri="${seed_source[RAG_SEED_S3_URI]}"
manifest_relative_path="${seed_source[RAG_SEED_MANIFEST_RELATIVE_PATH]}"
manifest_sha256="${seed_source[RAG_SEED_MANIFEST_SHA256]}"
[[ "$rag_seed_s3_uri" =~ ^s3://[a-zA-Z0-9.-]+/_rag-seed/[a-zA-Z0-9._/-]+/$ ]]
[[ "$manifest_relative_path" =~ ^[A-Za-z0-9._-]+\.json$ ]]
[[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ "$rag_seed_s3_uri" != *"/../"* ]]

legal_dataset_version="$(sed -n 's/^LEGAL_DATASET_VERSION=//p' .runtime.env)"
legal_dataset_verified_at="$(sed -n 's/^LEGAL_DATASET_VERIFIED_AT=//p' .runtime.env)"
legal_max_age_hours="$(sed -n 's/^OPERATIONAL_LEGAL_MAX_AGE_HOURS=//p' .runtime.env)"
[[ -n "$legal_dataset_version" && -n "$legal_dataset_verified_at" && -n "$legal_max_age_hours" ]]
mapfile -t PRECEDENT_SEED_LINES < <(grep '^PRECEDENT_NEWPLUSPLUS_SEED_VERSION=' .runtime.env)
[[ ${#PRECEDENT_SEED_LINES[@]} -eq 1 ]] || {
  echo 'Runtime environment must contain exactly one verified precedent seed version.' >&2
  exit 78
}
PRECEDENT_NEWPLUSPLUS_SEED_VERSION="${PRECEDENT_SEED_LINES[0]#*=}"
[[ "$PRECEDENT_NEWPLUSPLUS_SEED_VERSION" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo 'Runtime precedent seed version is invalid.' >&2
  exit 78
}

release_evidence_dir="$release_dir/operational-evidence"
release_evidence_file="$release_evidence_dir/run_summary.json"
release_evidence_tmp="$release_evidence_dir/.run_summary.json.app-release.tmp"
release_evidence_backup="$release_evidence_dir/.run_summary.json.app-release.backup.$$"
shared_evidence_dir='/opt/skn27-pilot/operational-evidence'
shared_evidence_file="$shared_evidence_dir/run_summary.json"
candidate_evidence_tmp="$shared_evidence_dir/.run_summary.json.app-release.tmp"
shared_evidence_backup="$shared_evidence_dir/.run_summary.json.app-release.backup.$$"
candidate_dir="/opt/skn27-pilot/app-release-evidence/$target_tag"
candidate_evidence_file="$candidate_dir/run_summary.json"
rag_dir="/opt/skn27-pilot/app-release-rag/$manifest_sha256"

install -d -m 0755 "$release_evidence_dir"
install -d -m 0755 "$shared_evidence_dir"
release_evidence_existed=0
if [[ -f "$release_evidence_file" ]]; then
  install -m 0444 "$release_evidence_file" "$release_evidence_backup"
  release_evidence_existed=1
fi
shared_evidence_existed=0
if [[ -f "$shared_evidence_file" ]]; then
  install -m 0444 "$shared_evidence_file" "$shared_evidence_backup"
  shared_evidence_existed=1
fi

restore_previous_evidence() {
  if (( release_evidence_existed )); then
    install -m 0444 "$release_evidence_backup" "$release_evidence_tmp"
    mv -f "$release_evidence_tmp" "$release_evidence_file"
  else
    rm -f "$release_evidence_file" "$release_evidence_tmp"
  fi
  if (( shared_evidence_existed )); then
    install -m 0444 "$shared_evidence_backup" "$candidate_evidence_tmp"
    mv -f "$candidate_evidence_tmp" "$shared_evidence_file"
  else
    rm -f "$shared_evidence_file" "$candidate_evidence_tmp"
  fi
}

cleanup_seed_and_evidence() {
  rm -rf -- "$rag_dir" "$candidate_dir"
  rm -f "$release_evidence_backup" "$shared_evidence_backup"
}

cleanup_release_images() {
  local repository image_ref tag protected_tag
  local protected retained
  local -a protected_tags

  for repository in "$backend_repository" "$frontend_repository"; do
    protected_tags=("$previous_tag" "$target_tag")
    retained=0
    while IFS= read -r tag; do
      [[ "$tag" =~ ^[0-9a-f]{12}$ ]] || continue
      protected_tags+=("$tag")
      retained=$((retained + 1))
      if (( retained >= release_image_retention_count )); then
        break
      fi
    done < <(docker images "$repository" --format '{{.Tag}}')

    while IFS= read -r image_ref; do
      [[ -n "$image_ref" ]] || continue
      tag="${image_ref##*:}"
      if [[ ! "$tag" =~ ^[0-9a-f]{12}$ && ! "$tag" =~ ^pipeline-rollback-[0-9a-f]{12}$ ]]; then
        continue
      fi
      protected=0
      for protected_tag in "${protected_tags[@]}"; do
        if [[ "$tag" == "$protected_tag" ]]; then
          protected=1
          break
        fi
      done
      if (( protected )); then
        continue
      fi
      if docker image rm "$image_ref"; then
        echo "Removed stale release image $image_ref."
      else
        echo "Retained release image $image_ref because Docker reports it is in use." >&2
      fi
    done < <(docker images "$repository" --format '{{.Repository}}:{{.Tag}}')
  done
}

require_release_disk_headroom() {
  local rag_seed_location rag_seed_bucket rag_seed_prefix
  local seed_size_bytes available_bytes required_free_bytes

  rag_seed_location="${rag_seed_s3_uri#s3://}"
  rag_seed_bucket="${rag_seed_location%%/*}"
  rag_seed_prefix="${rag_seed_location#*/}"
  seed_size_bytes="$(aws s3api list-objects-v2 \
    --bucket "$rag_seed_bucket" \
    --prefix "$rag_seed_prefix" \
    --region '__AWS_REGION__' \
    --query 'sum(Contents[].Size)' \
    --output text)"
  [[ "$seed_size_bytes" =~ ^[1-9][0-9]*$ ]] || {
    echo 'Unable to determine a positive RAG seed size.' >&2
    return 70
  }
  available_bytes="$(df -B1 --output=avail "$release_dir" | tail -n 1 | tr -d '[:space:]')"
  [[ "$available_bytes" =~ ^[0-9]+$ ]] || {
    echo 'Unable to determine available release disk space.' >&2
    return 70
  }
  required_free_bytes=$((seed_size_bytes + release_reserved_free_bytes))
  if (( available_bytes < required_free_bytes )); then
    printf 'Insufficient disk space for app release: available=%s required=%s seed=%s reserve=%s bytes.\n' \
      "$available_bytes" "$required_free_bytes" "$seed_size_bytes" "$release_reserved_free_bytes" >&2
    return 70
  fi
  printf 'Release disk preflight passed: available=%s required=%s bytes.\n' \
    "$available_bytes" "$required_free_bytes"
}

snapshot_rollback_image() {
  local service="$1"
  local repository="$2"
  local container_id
  local image_id

  container_id="$("${compose[@]}" ps -q "$service")"
  [[ -n "$container_id" ]] || {
    echo "Current $service container is unavailable for rollback snapshot." >&2
    exit 78
  }
  image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
  [[ -n "$image_id" ]] || {
    echo "Current $service image ID is unavailable for rollback snapshot." >&2
    exit 78
  }
  docker tag "$image_id" "$repository:$previous_tag"
}

snapshot_rollback_image backend "$backend_repository"
snapshot_rollback_image frontend "$frontend_repository"

restore_tag() {
  sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$previous_tag/" .compose.env
}

remove_runtime_services() {
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" rm -sf backend frontend agent-worker file-scan-worker ops-monitor >/dev/null 2>&1
}

start_frontend_backend() {
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend >/dev/null 2>&1
}

start_workers() {
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor >/dev/null 2>&1
}

record_rollback_step() {
  local step="$1"
  shift
  if ! "$@"; then
    rollback_failures+=("$step")
    echo "Rollback step failed: $step" >&2
  fi
}

rollback_app_release() {
  local status=$?
  local rollback_failures=()
  trap - ERR
  record_rollback_step restore_tag restore_tag
  record_rollback_step restore_previous_evidence restore_previous_evidence
  record_rollback_step remove_runtime_services remove_runtime_services
  record_rollback_step start_frontend_backend start_frontend_backend
  record_rollback_step start_workers start_workers
  record_rollback_step cleanup_seed_and_evidence cleanup_seed_and_evidence
  if (( ${#rollback_failures[@]} == 0 )); then
    echo "ROLLBACK_STATUS=complete" >&2
  else
    printf 'ROLLBACK_STATUS=incomplete steps=%s\n' "${rollback_failures[*]}" >&2
  fi
  exit "$status"
}

trap rollback_app_release ERR

cleanup_release_images
aws ecr get-login-password --region '__AWS_REGION__' | docker login --username AWS --password-stdin "$registry"
RELEASE_TAG="$target_tag" FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" pull backend frontend agent-worker file-scan-worker ops-monitor
require_release_disk_headroom
PILOT_BACKEND_IP="${PILOT_MIGRATION_CHECK_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" "${compose[@]}" run --rm --no-deps backend python backend/manage.py migrate --check
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" "${compose[@]}" run --rm --no-deps backend python backend/manage.py verify_precedent_newplusplus_seed --expected-seed-version "$PRECEDENT_NEWPLUSPLUS_SEED_VERSION" --format json
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" "${compose[@]}" run --rm --no-deps backend python backend/manage.py verify_pgvector_rag_readiness --format json

test ! -e "$rag_dir" && test ! -L "$rag_dir"
test ! -e "$candidate_dir" && test ! -L "$candidate_dir"
install -d -m 0700 "$rag_dir"
install -d -m 0755 "$candidate_dir"
aws s3 cp "$rag_seed_s3_uri" "$rag_dir/" --region '__AWS_REGION__' --recursive --only-show-errors
test -f "$rag_dir/$manifest_relative_path"
printf '%s  %s\n' "$manifest_sha256" "$rag_dir/$manifest_relative_path" | sha256sum -c -
find "$rag_dir" -type d -exec chmod 0555 {} +
find "$rag_dir" -type f -exec chmod 0444 {} +

PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" run --rm --no-deps -v "$rag_dir:/run/production-rag-seed:ro" backend python backend/manage.py verify_production_rag_seed_manifest --manifest "/run/production-rag-seed/$manifest_relative_path" --format json
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" run --rm --no-deps -v "$rag_dir:/run/production-rag-seed:ro" backend python backend/manage.py build_legal_operational_evidence --manifest "/run/production-rag-seed/$manifest_relative_path" --dataset-version "$legal_dataset_version" --release-version "$target_tag" --verified-at "$legal_dataset_verified_at" > "$candidate_evidence_file"
PILOT_BACKEND_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" run --rm --no-deps -v "$candidate_dir:/run/candidate-evidence:ro" backend python -m etl.legal.validate_run_summary --summary /run/candidate-evidence/run_summary.json --max-age-hours "$legal_max_age_hours" --expected-dataset-version "$legal_dataset_version" --expected-release-version "$target_tag"
chmod 0444 "$candidate_evidence_file"

FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" rm -sf backend frontend agent-worker file-scan-worker ops-monitor
sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$target_tag/" .compose.env
FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend

for path in /api/health/live/ /api/health/ready/; do
  curl --fail --silent --show-error --retry 10 --retry-delay 6 --resolve "$app_domain:443:127.0.0.1" "https://$app_domain$path" >/dev/null
done

install -m 0444 "$candidate_evidence_file" "$release_evidence_tmp"
mv -f "$release_evidence_tmp" "$release_evidence_file"
install -m 0444 "$candidate_evidence_file" "$candidate_evidence_tmp"
mv -f "$candidate_evidence_tmp" "$shared_evidence_file"
FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor
PILOT_OPS_MONITOR_IP="${PILOT_ONE_OFF_CONTAINER_IP:-172.31.0.11}" FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" run --rm --no-deps ops-monitor python backend/manage.py observe_operational_health --once --gate-mode transaction

trap - ERR
cleanup_seed_and_evidence
echo "App release completed for $target_tag."
REMOTE_SCRIPT
)

remote_script="${remote_script//__IMAGE_TAG__/$IMAGE_TAG}"
remote_script="${remote_script//__BACKEND_REGISTRY__/${BACKEND_REPOSITORY_URL%%/*}}"
remote_script="${remote_script//__BACKEND_REPOSITORY__/$BACKEND_REPOSITORY_URL}"
remote_script="${remote_script//__FRONTEND_REPOSITORY__/$FRONTEND_REPOSITORY_URL}"
remote_script="${remote_script//__AWS_REGION__/$AWS_DEFAULT_REGION}"

python3 - "$request_path" "$PILOT_INSTANCE_ID" "$remote_script" "$ssm_timeout_seconds" <<'PY'
import json
import sys

request_path, instance_id, command, ssm_timeout_seconds = sys.argv[1:]
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance_id],
            "Comment": "Release immutable Pilot app images",
            "TimeoutSeconds": int(ssm_timeout_seconds),
            "Parameters": {"commands": [command]},
        },
        handle,
    )
PY

command_id="$(aws ssm send-command \
  --region "$AWS_DEFAULT_REGION" \
  --cli-input-json "file://$request_path" \
  --query "Command.CommandId" \
  --output text \
  --no-cli-pager)"

deadline=$((SECONDS + polling_timeout_seconds))
while (( SECONDS < deadline )); do
  status="$(aws ssm get-command-invocation \
    --region "$AWS_DEFAULT_REGION" \
    --command-id "$command_id" \
    --instance-id "$PILOT_INSTANCE_ID" \
    --query "Status" \
    --output text \
    --no-cli-pager 2>/dev/null || true)"
  case "$status" in
    Success)
      echo "Pilot app release SSM command completed successfully."
      exit 0
      ;;
    Failed|Cancelled|TimedOut)
      echo "Pilot app release SSM command finished with status $status." >&2
      aws ssm get-command-invocation \
        --region "$AWS_DEFAULT_REGION" \
        --command-id "$command_id" \
        --instance-id "$PILOT_INSTANCE_ID" \
        --query '{StandardOutputContent:StandardOutputContent,StandardErrorContent:StandardErrorContent}' \
        --output json \
        --no-cli-pager >&2 || true
      exit 1
      ;;
  esac
  sleep "$poll_seconds"
done

echo "SSM command exceeded ${polling_timeout_seconds} seconds." >&2
aws ssm get-command-invocation \
  --region "$AWS_DEFAULT_REGION" \
  --command-id "$command_id" \
  --instance-id "$PILOT_INSTANCE_ID" \
  --query '{Status:Status,StandardOutputContent:StandardOutputContent,StandardErrorContent:StandardErrorContent}' \
  --output json \
  --no-cli-pager >&2 || true

if aws ssm cancel-command \
  --region "$AWS_DEFAULT_REGION" \
  --command-id "$command_id" \
  --no-cli-pager >/dev/null; then
  echo "SSM_CANCEL_STATUS=complete" >&2
else
  echo "SSM_CANCEL_STATUS=incomplete" >&2
fi
exit 1
