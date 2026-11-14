#!/usr/bin/env bash
set -Eeuo pipefail
# Run on the Docker host after deployment. Only global configuration is read;
# all synthetic company/project/lead/conversation writes are in private SQLite.
diagnostic_run="sales-needs-discovery-$(date -u +%Y%m%dT%H%M%SZ)"
set +e
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite needs-discovery --max-calls 112 --max-turns 3 \
  --output "/tmp/$diagnostic_run"
result=$?
set -e
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/$diagnostic_run.zip"
printf '\nEvidence: %s\n' "$HOME/$diagnostic_run.zip"
exit "$result"
