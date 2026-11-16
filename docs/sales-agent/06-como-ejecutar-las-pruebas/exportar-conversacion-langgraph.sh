#!/usr/bin/env bash
# Replace the conversation ID when testing a newly created lead. Read-only.
set -uo pipefail
conversation_id="${1:?Indica el ID de la conversación que probaste}"
diagnostic_run="sales-live-langgraph-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.inspect_commercial_graph \
  --conversation-id "$conversation_id" \
  --limit 30 --output "/tmp/$diagnostic_run.zip" || exit 1
docker cp "bp_api_prod:/tmp/$diagnostic_run.zip" "$HOME/sales-live-langgraph.zip" || exit 1
echo 'Windows PowerShell:'
echo '& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-live-langgraph.zip "$env:USERPROFILE\Downloads\sales-live-langgraph.zip"'
