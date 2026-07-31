#!/usr/bin/env bash
set -euo pipefail

readonly timeout_seconds=900
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
[[ -n "$release_dir" && -d "$release_dir" ]] || {
  echo 'Current Pilot release directory is unavailable.' >&2
  exit 78
}
cd "$release_dir"

previous_tag="$(sed -n 's/^RELEASE_TAG=//p' .compose.env)"
[[ -n "$previous_tag" ]] || {
  echo 'Current release does not define RELEASE_TAG.' >&2
  exit 78
}

target_tag='__IMAGE_TAG__'
registry='__BACKEND_REGISTRY__'
backend_repository='__BACKEND_REPOSITORY__'
frontend_repository='__FRONTEND_REPOSITORY__'
app_domain="$(sed -n 's/^APP_DOMAIN=//p' .edge.env)"
[[ -n "$app_domain" ]] || {
  echo 'Current release does not define APP_DOMAIN.' >&2
  exit 78
}

compose=(docker compose --project-name skn27-pilot --env-file .compose.env --env-file .production-compose.env -f docker-compose.pilot.yml)
rollback_tag="pipeline-rollback-${target_tag}"
frontend_image_ref="$frontend_repository:$target_tag"
rollback_frontend_image_ref="$frontend_repository:$rollback_tag"

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
  docker tag "$image_id" "$repository:$rollback_tag"
}

snapshot_rollback_image backend "$backend_repository"
snapshot_rollback_image frontend "$frontend_repository"

restore_tag() {
  sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$rollback_tag/" .compose.env
}

rollback_app_release() {
  local status=$?
  trap - ERR
  restore_tag
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" rm -sf backend frontend agent-worker file-scan-worker ops-monitor >/dev/null 2>&1 || true
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend >/dev/null 2>&1 || true
  FRONTEND_IMAGE_REF="$rollback_frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor >/dev/null 2>&1 || true
  exit "$status"
}

trap rollback_app_release ERR

PILOT_BACKEND_IP="${PILOT_MIGRATION_CHECK_IP:-172.31.0.11}" RELEASE_TAG="$target_tag" "${compose[@]}" run --rm --no-deps backend python backend/manage.py migrate --check
aws ecr get-login-password --region '__AWS_REGION__' | docker login --username AWS --password-stdin "$registry"
sed -i "s/^RELEASE_TAG=.*/RELEASE_TAG=$target_tag/" .compose.env
FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" pull backend frontend agent-worker file-scan-worker ops-monitor
FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" rm -sf backend frontend agent-worker file-scan-worker ops-monitor
FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps backend frontend

for path in /api/health/live/ /api/health/ready/; do
  curl --fail --silent --show-error --retry 10 --retry-delay 6 --resolve "$app_domain:443:127.0.0.1" "https://$app_domain$path" >/dev/null
done

FRONTEND_IMAGE_REF="$frontend_image_ref" "${compose[@]}" up -d --no-deps agent-worker file-scan-worker ops-monitor

trap - ERR
echo "App release completed for $target_tag."
REMOTE_SCRIPT
)

remote_script="${remote_script//__IMAGE_TAG__/$IMAGE_TAG}"
remote_script="${remote_script//__BACKEND_REGISTRY__/${BACKEND_REPOSITORY_URL%%/*}}"
remote_script="${remote_script//__BACKEND_REPOSITORY__/$BACKEND_REPOSITORY_URL}"
remote_script="${remote_script//__FRONTEND_REPOSITORY__/$FRONTEND_REPOSITORY_URL}"
remote_script="${remote_script//__AWS_REGION__/$AWS_DEFAULT_REGION}"

python3 - "$request_path" "$PILOT_INSTANCE_ID" "$remote_script" <<'PY'
import json
import sys

request_path, instance_id, command = sys.argv[1:]
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "DocumentName": "AWS-RunShellScript",
            "InstanceIds": [instance_id],
            "Comment": "Release immutable Pilot app images",
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

deadline=$((SECONDS + timeout_seconds))
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

aws ssm cancel-command \
  --region "$AWS_DEFAULT_REGION" \
  --command-id "$command_id" \
  --no-cli-pager >/dev/null
echo "Pilot app release SSM command exceeded $timeout_seconds seconds." >&2
exit 1
