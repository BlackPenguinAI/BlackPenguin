#!/usr/bin/env bash
# Only GitHub-hosted disposable Linux runners; never use on the production VPS.
set -euo pipefail
mode=${1:?offline or model}
[[ "$mode" == offline || "$mode" == model ]]
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted ]]
[[ "${GITHUB_SHA:-}" =~ ^[a-f0-9]{40}$ ]]
[[ "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ && "${GITHUB_RUN_ATTEMPT:-}" =~ ^[0-9]+$ ]]
[[ -z "${DOCKER_HOST:-}" && -z "${DOCKER_CONTEXT:-}" ]]
[[ "$(docker context show)" == default ]]
base=$(cd "$(dirname "$0")" && pwd)
project="hei06a-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${mode}"
export HEI06A_MODE="$mode" HEI06A_COMMIT="$GITHUB_SHA"
export HEI06A_DB_PASSWORD="$(openssl rand -hex 24)" HEI06A_TOKEN="$(openssl rand -hex 32)"
printf '::add-mask::%s\n' "$HEI06A_DB_PASSWORD" "$HEI06A_TOKEN"
export HEI06A_EVIDENCE_DIR="$GITHUB_WORKSPACE/evidence-hei06a/$mode"
mkdir -p "$HEI06A_EVIDENCE_DIR"; chmod 777 "$HEI06A_EVIDENCE_DIR"
# Do not source a project .env. Compose sees only explicit disposable values.
export HEI06A_MODEL_KEY=test-only
files=(-f "$base/compose.yml")
if [[ "$mode" == model ]]; then
    [[ -n "${HEI06_OPENROUTER_API_KEY:-}" && "$HEI06_OPENROUTER_API_KEY" != test-only ]]
    export HEI06A_MODEL_KEY="$HEI06_OPENROUTER_API_KEY"
    files+=(-f "$base/compose.model.yml")
fi
unset HEI06_OPENROUTER_API_KEY
compose() { docker compose --env-file /dev/null --project-name "$project" "${files[@]}" "$@"; }
cleanup() { compose down --volumes --remove-orphans >/dev/null 2>&1 || true; }
# Fresh project name; never reuse a previously provisioned database or network.
[[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]]
[[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]]
[[ -z "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]]
trap cleanup EXIT
phase() {
    local phase=$1 name="${project}-worker-$1" rc=0 networks
    echo "HEI-06A $mode: $phase"
    # Inspect the actual worker container, not just the Compose declaration.
    compose run -d --no-deps --name "$name" worker --phase "$phase" --output "/evidence/$phase.json" >/dev/null
    networks=$(docker inspect "$name" --format '{{len .NetworkSettings.Networks}}')
    [[ "$networks" == 1 && -z "$(docker port "$name")" ]]
    [[ "$(docker inspect "$name" --format '{{.Config.User}}')" == '10001:10001' ]]
    # The process may already have exited, in which case Networks still
    # contains the configured network but the IP can be empty.
    [[ "$(docker inspect "$name" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')" == "${project}_private" ]]
    rc=$(docker wait "$name")
    docker rm "$name" >/dev/null
    if [[ -f "$HEI06A_EVIDENCE_DIR/$phase.json" ]]; then cat "$HEI06A_EVIDENCE_DIR/$phase.json"; fi
    [[ "$rc" == 0 && -s "$HEI06A_EVIDENCE_DIR/$phase.json" ]]
}
compose up -d --wait hei06a-postgres >/dev/null
[[ "$(docker network inspect "${project}_private" --format '{{.Internal}}')" == true ]]
pg=$(compose ps -q hei06a-postgres)
[[ -n "$pg" && -z "$(docker port "$pg")" ]]
[[ "$(docker inspect "$pg" --format '{{len .NetworkSettings.Networks}}')" == 1 ]]
phase seed
compose up -d bp-hermes >/dev/null
sdk=$(compose ps -q bp-hermes)
[[ -n "$sdk" && -z "$(docker port "$sdk")" ]]
[[ "$(docker inspect "$sdk" --format '{{.Config.User}}')" == '10001:10001' ]]
expected_networks=1; [[ "$mode" == offline ]] || expected_networks=2
[[ "$(docker inspect "$sdk" --format '{{len .NetworkSettings.Networks}}')" == "$expected_networks" ]]
if [[ "$mode" == model ]]; then
    [[ "$(docker network inspect "${project}_model_egress" --format '{{.Internal}}')" == false ]]
    [[ "$(docker network inspect "${project}_model_egress" --format '{{len .Containers}}')" == 1 ]]
fi
phase prepare
started=$(docker inspect "$sdk" --format '{{.State.StartedAt}}')
compose restart bp-hermes >/dev/null
[[ "$sdk" == "$(compose ps -q bp-hermes)" ]]
[[ "$started" != "$(docker inspect "$sdk" --format '{{.State.StartedAt}}')" ]]
phase replay
compose stop bp-hermes >/dev/null
[[ "$(docker inspect "$sdk" --format '{{.State.Running}}')" == false ]]
phase finish
sdk_image=$(docker inspect "$sdk" --format '{{.Image}}')
worker_image=$(docker image inspect "$HEI06A_WORKER_IMAGE" --format '{{.Id}}')
postgres_image=$(docker inspect "$pg" --format '{{.Image}}')
# Do not write a PASS summary before confirming teardown.
compose down --volumes --remove-orphans >/dev/null
[[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]]
[[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]]
[[ -z "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]]
trap - EXIT
python3 - "$HEI06A_EVIDENCE_DIR" "$GITHUB_SHA" "$mode" "$sdk_image" "$worker_image" "$postgres_image" <<'PY'
import json, pathlib, sys
root, sha, mode, sdk_image, worker_image, postgres_image=sys.argv[1:]
p=pathlib.Path(root)
reports={phase:json.loads((p/(phase+'.json')).read_text()) for phase in ('seed','prepare','replay','finish')}
assert all(r['candidate_commit']==sha and r['mode']==mode and r['status']=='PASS'
           and all(r['checks'].values()) and r['production_readiness']=='CLOSED' for r in reports.values())
assert len({reports[x]['draft_hash'] for x in ('prepare','replay','finish')})==1
assert all(reports[x]['runtime_invocations']==1 for x in ('prepare','replay','finish'))
assert reports['finish']['simulated_provider_receipts']==reports['finish']['state_revision']==1
result={'schema':'hei06a-private-runtime-summary/1','candidate_commit':sha,'mode':mode,'status':'PASS',
        'sdk_revision':'b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb',
        'image_ids':{'sdk':sdk_image,'worker':worker_image,'postgres':postgres_image},
        'policy_fingerprint':reports['seed']['policy_fingerprint'],
        'policy_scope':'synthetic_published_read_only_subset',
        'transport':'actual_cross_container_tcp','database':'disposable_postgresql_16',
        'inference':'real_sdk_openrouter' if mode=='model' else 'simulated',
        'checks':{'private_network_internal':True,'no_published_ports':True,'sdk_non_root':True,
                  'worker_single_internal_network':True,'worker_non_root':True,'sdk_restarted':True,
                  'sdk_stopped_before_dispatch':True,'disposable_resources_removed':True},
        'runtime_invocations':1,'simulated_provider_receipts':1,'real_message_provider_calls':0,
        'real_calendar_calls':0,'state_revision':1,'production_readiness':'CLOSED',
        'production_policy_tested':False,'real_provider_acceptance':'NOT_RUN'}
(p/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps(result,sort_keys=True))
PY
