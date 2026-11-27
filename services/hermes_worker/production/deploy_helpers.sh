# Sourced by the canonical deploy.yml AFTER checkout of the candidate revision.
# Never execute this file independently. The existing deploy trap owns rollback.
# No provider operations, production DDL or automatic engine selection here.
HERMES_NETWORK=bp-hermes-private
HERMES_LABEL=com.blackpenguin.hermes-pilot
HERMES_IMAGE="blackpenguin-hermes:${DEPLOY_SHA}"
HERMES_CANDIDATE="bp-hermes-candidate-${DEPLOY_SHA:0:12}"
HERMES_PREVIOUS="bp-hermes-previous-${DEPLOY_SHA:0:12}"
HERMES_PREVIOUS_MOVED=false
HERMES_PREVIOUS_STOPPED=false
HERMES_CANDIDATE_CREATED=false
HERMES_NEW_ACTIVE=false
HERMES_ROLLING_BACK=false
HERMES_PREVIOUS_API_PILOT=false
HERMES_TMP="$(mktemp -d "$HOME/.bp-hermes-deploy.XXXXXXXX")"
chmod 700 "$HERMES_TMP"
HERMES_API_ENV="$HERMES_TMP/api.env"
HERMES_SDK_ENV="$HERMES_TMP/sdk.env"
HERMES_PREV_API_ENV="$HERMES_TMP/previous-api.env"
HERMES_PREV_BASE_ENV="$HERMES_TMP/previous-backend.env"
HERMES_HAD_BASE_ENV=false
HERMES_PREVIOUS_EXISTS=false

hermes_exists() { docker container inspect "$1" >/dev/null 2>&1; }
hermes_owned() { [ "$(docker inspect --format '{{index .Config.Labels "com.blackpenguin.hermes-pilot"}}' "$1" 2>/dev/null || true)" = 'true' ]; }
hermes_remove_owned() {
  if hermes_exists "$1"; then
    hermes_owned "$1" || { echo 'Refusing to remove an unrelated container.'; return 1; }
    docker rm -f "$1" >/dev/null
  fi
}
hermes_selected_langgraph() {
  docker exec bp_api_prod python -c 'import app.db.base; from app.db.postgres import SessionLocal; from app.modules.hermes_sales_core.staff_models import HermesGlobalSettings; from app.modules.hermes_sales_core.engine_selection import read_engine; db=SessionLocal(); row=db.get(HermesGlobalSettings,"global"); assert read_engine(row.configuration if row else None)=="langgraph", "Select LangGraph in Sales Agent before deployment"; db.close(); print("sales_selector=langgraph")'
}

hermes_preflight() {
  case "${HERMES_RELEASE_MODE:-closed}" in closed|pilot) ;; *) echo 'Only closed or pilot is supported.'; return 1;; esac
  # Save prior env privately before the existing deploy rewrites it.
  if [ -f backend/.env ]; then cp backend/.env "$HERMES_PREV_BASE_ENV"; chmod 600 "$HERMES_PREV_BASE_ENV"; HERMES_HAD_BASE_ENV=true; fi
  if hermes_exists bp-hermes; then
    hermes_owned bp-hermes || { echo 'Existing bp-hermes is not owned by this deployment.'; return 1; }
    HERMES_PREVIOUS_EXISTS=true
  fi
  if [ "$HERMES_PREVIOUS_EXISTS" = true ] || [ "${HERMES_RELEASE_MODE:-closed}" = pilot ]; then
    hermes_selected_langgraph
  fi
  # Preserve only prior pilot variables. No Docker environment is printed.
  if hermes_exists bp_api_prod; then
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' bp_api_prod | \
      awk '/^HERMES_(RELEASE_MODE|RELEASE_SHA|RUNTIME_ROLE|INTERNAL_TOKEN|PILOT_SCOPES|PILOT_UNTIL)=/' > "$HERMES_PREV_API_ENV"
    chmod 600 "$HERMES_PREV_API_ENV"
    if grep -qx 'HERMES_RELEASE_MODE=pilot' "$HERMES_PREV_API_ENV"; then HERMES_PREVIOUS_API_PILOT=true; fi
    if [ "$HERMES_PREVIOUS_API_PILOT" = true ]; then
      hermes_selected_langgraph
      [ "$HERMES_PREVIOUS_EXISTS" = true ] || { echo 'Previous pilot SDK is missing; reconcile before deployment.'; return 1; }
    fi
  fi
  [ "${HERMES_RELEASE_MODE:-closed}" = pilot ] || return 0
  # Conservative initial resource floor; no changes to production if insufficient.
  [ "$(nproc)" -ge 2 ] || { echo 'Pilot requires at least 2 host vCPU.'; return 1; }
  [ "$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)" -ge 2097152 ] || { echo 'Pilot preflight requires 2 GiB currently available RAM.'; return 1; }
  local docker_root
  docker_root="$(docker info --format '{{.DockerRootDir}}')"
  [ "$(df -Pk "$docker_root" | awk 'NR==2{print $4}')" -ge 6291456 ] || { echo 'Pilot preflight requires 6 GiB free in Docker storage.'; return 1; }
  ! hermes_exists "$HERMES_CANDIDATE" && ! hermes_exists "$HERMES_PREVIOUS" || { echo 'Previous interrupted pilot deployment requires operator review.'; return 1; }
  # Values are transported as envs, never interpolated as shell code. Reject
  # newline injection in docker env-file. The candidate Python validates IDs.
  for name in HERMES_INTERNAL_TOKEN HERMES_PILOT_SCOPES HERMES_PILOT_UNTIL; do
    local value="${!name:-}"
    [ -n "$value" ] && [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || { echo "Missing or multiline $name."; return 1; }
  done
  [[ "$HERMES_INTERNAL_TOKEN" =~ ^[0-9a-f]{64}$ ]] || { echo 'HERMES_INTERNAL_TOKEN must be 64 lowercase hex characters.'; return 1; }
  [ -n "${HERMES_MODEL_KEY:-}" ] && [[ "$HERMES_MODEL_KEY" != *$'\n'* && "$HERMES_MODEL_KEY" != *$'\r'* ]] || { echo 'Missing Hermes OpenRouter key.'; return 1; }
  [ -n "${DB_URL:-}" ] && [[ "$DB_URL" != *$'\n'* && "$DB_URL" != *$'\r'* ]] || { echo 'Invalid database connection configuration.'; return 1; }
  umask 077
  {
    printf 'HERMES_RELEASE_MODE=pilot\nHERMES_RELEASE_SHA=%s\nHERMES_RUNTIME_ROLE=api\n' "$DEPLOY_SHA"
    printf 'HERMES_INTERNAL_TOKEN=%s\nHERMES_PILOT_SCOPES=%s\nHERMES_PILOT_UNTIL=%s\n' "$HERMES_INTERNAL_TOKEN" "$HERMES_PILOT_SCOPES" "$HERMES_PILOT_UNTIL"
  } > "$HERMES_API_ENV"
  {
    printf 'ENVIRONMENT=production\nAPP_COMMIT_SHA=%s\n' "$DEPLOY_SHA"
    sed 's/^HERMES_RUNTIME_ROLE=api$/HERMES_RUNTIME_ROLE=sdk/' "$HERMES_API_ENV"
    printf 'DATABASE_URL=%s\nOPENROUTER_API_KEY=%s\n' "$DB_URL" "$HERMES_MODEL_KEY"
    # The private SDK imports Settings, not the public API/auth/onboarding app.
    printf 'SECRET_KEY=private-sdk-not-a-public-auth-service\nFIRST_SUPERADMIN_EMAIL=sdk@example.invalid\nFIRST_SUPERADMIN_PASSWORD=unused-private-sdk\nMETA_ACCESS_TOKEN=unused-private-sdk\nACCESS_TOKEN_EXPIRE_MINUTES=1\nSEED_MINTO_DEMO=false\nPROJECT_UPLOAD_ROOT=/tmp/bp-hermes-uploads\n'
  } > "$HERMES_SDK_ENV"
}

hermes_prepare_candidate() {
  [ "${HERMES_RELEASE_MODE:-closed}" = pilot ] || return 0
  test "$(image_revision "$HERMES_IMAGE")" = "$DEPLOY_SHA"
  if docker network inspect "$HERMES_NETWORK" >/dev/null 2>&1; then
    test "$(docker network inspect --format '{{index .Labels "com.blackpenguin.hermes-pilot"}}' "$HERMES_NETWORK")" = true
    # Reject unknown peers on the dedicated network; don't disconnect them.
    docker network inspect --format '{{range .Containers}}{{println .Name}}{{end}}' "$HERMES_NETWORK" | \
      awk 'NF && $0!="bp_api_prod" && $0!="bp-hermes" {bad=1} END {exit bad}'
  else
    docker network create --driver bridge --label "$HERMES_LABEL=true" "$HERMES_NETWORK" >/dev/null
  fi
  docker run -d --name "$HERMES_CANDIDATE" --label "$HERMES_LABEL=true" \
    --network "$HERMES_NETWORK" --env-file "$HERMES_SDK_ENV" --restart no \
    --memory 1536m --cpus 1.0 --pids-limit 256 --cap-drop ALL --security-opt no-new-privileges:true \
    --entrypoint python "$HERMES_IMAGE" -m uvicorn app.modules.hermes_sales_core.sdk_service:app --host 0.0.0.0 --port 8080 --workers 1 >/dev/null
  HERMES_CANDIDATE_CREATED=true
  local ok=false attempt
  for attempt in $(seq 1 30); do
    if docker exec "$HERMES_CANDIDATE" python -c 'import os,httpx; r=httpx.get("http://127.0.0.1:8080/internal/readiness",headers={"Authorization":"Bearer "+os.environ["HERMES_INTERNAL_TOKEN"]},timeout=3,trust_env=False); assert r.status_code==200 and r.json()["release"]==os.environ["APP_COMMIT_SHA"]' >/dev/null 2>&1; then ok=true; break; fi
    sleep 2
  done
  [ "$ok" = true ] || { echo 'Candidate SDK failed private readiness; existing production remains unchanged.'; return 1; }
  # This imports the existing domain models and performs SELECT-only checks.
  # Don't expose SQL/phone values if validation fails.
  docker exec "$HERMES_CANDIDATE" python -c 'from app.modules.hermes_sales_core.production_release import validate_deployment_targets; print("authorized_test_opportunities="+str(validate_deployment_targets()))' 2>/dev/null || { echo 'Pilot test opportunity validation failed; verify consent, test flag, route, approved project and IDs.'; return 1; }
  test "$(docker inspect --format '{{len .HostConfig.PortBindings}}' "$HERMES_CANDIDATE")" = 0
}

hermes_activate() {
  [ "${HERMES_RELEASE_MODE:-closed}" = pilot ] || return 0
  if [ "$HERMES_PREVIOUS_EXISTS" = true ]; then
    docker stop bp-hermes >/dev/null
    HERMES_PREVIOUS_STOPPED=true
    docker rename bp-hermes "$HERMES_PREVIOUS"
    HERMES_PREVIOUS_MOVED=true
    docker network disconnect "$HERMES_NETWORK" "$HERMES_PREVIOUS" >/dev/null
  fi
  docker network disconnect "$HERMES_NETWORK" "$HERMES_CANDIDATE"
  docker rename "$HERMES_CANDIDATE" bp-hermes
  HERMES_CANDIDATE_CREATED=false
  HERMES_NEW_ACTIVE=true
  docker network connect --alias bp-hermes "$HERMES_NETWORK" bp-hermes
  docker update --restart always bp-hermes >/dev/null
}

hermes_api_arguments() {
  HERMES_API_ARGS=()
  if [ "$HERMES_ROLLING_BACK" = true ]; then
    if [ "$HERMES_PREVIOUS_API_PILOT" = true ]; then HERMES_API_ARGS=(--env-file "$HERMES_PREV_API_ENV"); fi
  elif [ "${HERMES_RELEASE_MODE:-closed}" = pilot ]; then
    HERMES_API_ARGS=(--env-file "$HERMES_API_ENV")
  fi
}

hermes_connect_api() {
  if { [ "$HERMES_ROLLING_BACK" = true ] && [ "$HERMES_PREVIOUS_API_PILOT" = true ]; } || \
     { [ "$HERMES_ROLLING_BACK" != true ] && [ "${HERMES_RELEASE_MODE:-closed}" = pilot ]; }; then
    docker network connect "$HERMES_NETWORK" bp_api_prod
  fi
}

hermes_verify_api() {
  [ "${HERMES_RELEASE_MODE:-closed}" = pilot ] || return 0
  docker exec bp_api_prod python -c 'from app.modules.hermes_sales_core.production_release import ready; assert ready(), "Private Hermes readiness not confirmed"; print("hermes_pilot_transport=ready")'
  hermes_selected_langgraph
  test "$(docker inspect --format '{{len .HostConfig.PortBindings}}' bp-hermes)" = 0
  echo 'Hermes transport ready for scoped pilot. No automatic selection; real provider acceptance NOT_RUN.'
}

hermes_restore() {
  HERMES_ROLLING_BACK=true
  if [ "$HERMES_HAD_BASE_ENV" = true ]; then cp "$HERMES_PREV_BASE_ENV" backend/.env; chmod 600 backend/.env; fi
  if [ "$HERMES_NEW_ACTIVE" = true ]; then hermes_remove_owned bp-hermes || return 1; fi
  if [ "$HERMES_PREVIOUS_MOVED" = true ]; then
    docker rename "$HERMES_PREVIOUS" bp-hermes || return 1
    # The old container may have been disconnected before failure.
    if ! docker inspect --format '{{json .NetworkSettings.Networks}}' bp-hermes | grep -q '"bp-hermes-private"'; then
      docker network connect --alias bp-hermes "$HERMES_NETWORK" bp-hermes || return 1
    fi
    docker start bp-hermes >/dev/null || return 1
  elif [ "$HERMES_PREVIOUS_STOPPED" = true ] && hermes_exists bp-hermes; then
    docker start bp-hermes >/dev/null || return 1
  fi
  if [ "$HERMES_CANDIDATE_CREATED" = true ]; then hermes_remove_owned "$HERMES_CANDIDATE" || return 1; fi
}

hermes_finish() {
  # Only the owned previous SDK is removed, after all production health checks.
  if [ "$HERMES_PREVIOUS_MOVED" = true ]; then hermes_remove_owned "$HERMES_PREVIOUS"; fi
  if [ "${HERMES_RELEASE_MODE:-closed}" = closed ] && [ "$HERMES_PREVIOUS_EXISTS" = true ]; then hermes_remove_owned bp-hermes; fi
  rm -f "$HERMES_API_ENV" "$HERMES_SDK_ENV" "$HERMES_PREV_API_ENV" "$HERMES_PREV_BASE_ENV"
  rmdir "$HERMES_TMP" 2>/dev/null || true
}
