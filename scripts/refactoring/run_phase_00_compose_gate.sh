#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

evidence_dir="tmp/phase-00-compose-evidence"
mkdir -p "$evidence_dir"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-skn27_phase00_${GITHUB_RUN_ID:-local}_${GITHUB_RUN_ATTEMPT:-0}}"
compose=(docker compose -f docker-compose.yml -f test/compose/docker-compose.phase-00.yml)
services=(postgres redis clamav neo4j backend agent-worker file-scan-worker)
gate_step="initializing"

write_failure_evidence() {
  "${compose[@]}" ps >"$evidence_dir/compose-ps-final.txt" 2>&1 || true
  "${compose[@]}" logs --no-color >"$evidence_dir/compose-logs.txt" 2>&1 || true
  printf '%s\n' "$gate_step" >"$evidence_dir/failed-step.txt"
}

cleanup() {
  local original_status=$?
  write_failure_evidence
  if ! "${compose[@]}" down -v --remove-orphans >>"$evidence_dir/cleanup.txt" 2>&1; then
    printf '%s\n' "cleanup_failed" >>"$evidence_dir/cleanup.txt"
    exit 1
  fi
  exit "$original_status"
}
trap cleanup EXIT

wait_for_health() {
  local service=$1 timeout_seconds=$2
  local deadline=$((SECONDS + timeout_seconds)) container status
  while (( SECONDS < deadline )); do
    container="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
      printf '%s\n' "$status" >"$evidence_dir/${service}-health.txt"
      if [[ "$status" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

wait_for_running() {
  local service=$1 timeout_seconds=$2
  local deadline=$((SECONDS + timeout_seconds)) container running
  while (( SECONDS < deadline )); do
    container="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container" ]]; then
      running="$(docker inspect --format '{{.State.Running}}' "$container")"
      if [[ "$running" == "true" ]]; then
        printf '%s\n' "$running" >"$evidence_dir/${service}-running.txt"
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

wait_for_http() {
  local path=$1 output=$2 timeout_seconds=$3
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if docker run --rm --network "${COMPOSE_PROJECT_NAME}_default" curlimages/curl:8.10.1 \
      --fail --silent --show-error "http://backend:8000${path}" >"$output"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

gate_step="docker-version"
docker version >"$evidence_dir/docker-version.txt"
docker compose version >"$evidence_dir/docker-compose-version.txt"

gate_step="compose-config"
"${compose[@]}" config --quiet
"${compose[@]}" config >"$evidence_dir/compose-config.yml"

gate_step="compose-up"
"${compose[@]}" up -d --build "${services[@]}"
"${compose[@]}" ps >"$evidence_dir/compose-ps-initial.txt"

gate_step="postgres-health"
wait_for_health postgres 120
gate_step="clamav-health"
wait_for_health clamav 300
gate_step="neo4j-health"
wait_for_health neo4j 180
gate_step="redis-ping"
"${compose[@]}" exec -T redis redis-cli ping >"$evidence_dir/redis-ping.txt"
grep -qx 'PONG' "$evidence_dir/redis-ping.txt"
gate_step="backend-running"
wait_for_running backend 180
gate_step="agent-worker-running"
wait_for_running agent-worker 120
gate_step="file-scan-worker-running"
wait_for_running file-scan-worker 120

gate_step="migration-check"
"${compose[@]}" exec -T backend python backend/manage.py migrate --check >"$evidence_dir/migration-check.txt"
gate_step="backend-live"
wait_for_http /api/health/live/ "$evidence_dir/backend-live.json" 180
gate_step="backend-ready"
wait_for_http /api/health/ready/ "$evidence_dir/backend-ready.json" 180
python3 - "$evidence_dir/backend-ready.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["status"] == "ready"
assert payload["checks"]["database"] == "ready"
assert payload["checks"]["cache"] == "ready"
PY

gate_step="agent-worker-seed"
"${compose[@]}" exec -T backend python scripts/refactoring/phase_00_compose_probe.py seed-agent-work \
  >"$evidence_dir/agent-worker-seed.json"
read -r job_id work_item_id < <(python3 - "$evidence_dir/agent-worker-seed.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload["job_id"], payload["work_item_id"])
PY
)
gate_step="agent-worker-result"
"${compose[@]}" exec -T backend python scripts/refactoring/phase_00_compose_probe.py verify-agent-work \
  --job-id "$job_id" --work-item-id "$work_item_id" --timeout-seconds 120 \
  >"$evidence_dir/agent-worker-result.json"

attachment_id="att_phase00_$(date +%s)_${RANDOM}"
session_id="ses_phase00_$(date +%s)_${RANDOM}"
gate_step="file-scan-upload"
"${compose[@]}" exec -T backend python backend/manage.py smoke_file_scan --phase upload \
  --attachment-id "$attachment_id" --session-id "$session_id" --format json \
  >"$evidence_dir/file-scan-upload.json"
gate_step="file-scan-result"
"${compose[@]}" exec -T backend python scripts/refactoring/phase_00_compose_probe.py verify-file-scan \
  --attachment-id "$attachment_id" --timeout-seconds 180 \
  >"$evidence_dir/file-scan-result.json"

gate_step="compose-final"
"${compose[@]}" ps >"$evidence_dir/compose-ps-final.txt"
python3 - "$evidence_dir/gate-summary.json" <<'PY'
import json
import sys

json.dump(
    {
        "contract_version": "phase_00_compose_gate.v1",
        "status": "pass",
        "database": "ready",
        "cache": "ready",
        "clamav": "ready",
        "neo4j": "ready",
        "backend_live": True,
        "backend_ready": True,
        "agent_worker_consumed": True,
        "file_scan_worker_consumed": True,
        "cleanup_required": True,
    },
    open(sys.argv[1], "w", encoding="utf-8"),
    ensure_ascii=False,
    sort_keys=True,
)
PY
