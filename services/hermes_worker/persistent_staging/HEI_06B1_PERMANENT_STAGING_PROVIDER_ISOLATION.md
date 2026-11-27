# HEI-06B.1 — Permanent Staging & Provider Isolation

**Certified baseline:** `893ecc290fc4e51ee54d818af23f0728a28011b7` (HEI-06A.2b.3, runs #10 and #11). **Status of this differential:** implementation and local tests complete; Docker CI and permanent-server deployment not yet executed. Production readiness remains **CLOSED**.

## 1. Scope and architecture

The permanent runtime reuses the certified A.2 infrastructure, `continuous.compose.yml`, `continuous.Dockerfile`, verified build-time overlay, native worker and simulated dispatcher. The optional model overlay attaches only the SDK to an additional egress network. The API and PostgreSQL remain on the internal network; the frontend binds `127.0.0.1:18082` for an SSH tunnel. The global engine selector and production build files are untouched.

The new HTTPS receiver is a **different Compose project** with its own network, certificate and journal. It does not share a network with BlackPenguin, have a DB connection, know a Hermes token, or have a Telnyx send key. It accepts only signed `message.received` SMS v2 events within a fixed test profile, organization, destination number and explicit list of consenting test senders. It returns 200 only after a durable, idempotent evidence write; it never forwards a body to BlackPenguin or sends a message.

```
Operator -> SSH tunnel -> localhost:18082 -> Angular -> BP API + continuous worker
                                                     |-> PostgreSQL staging
                                                     |-> private Hermes SDK -> OpenRouter (optional)
                                                     |-> simulated dispatcher only

Telnyx -> public HTTPS:443 -> separate quarantine receiver -> private SQLite evidence
                               NO route to BP, NO job creation, NO SMS reply
```

This is deliberately a provider quarantine, not yet a real conversational ingress. The A.2b.3 runtime still admits two predefined synthetic turns and a revocation case. No free-text lead conversation, SMS delivery callback, WhatsApp, media, booking, real Calendar call, or automatic cutover is implemented by B.1. The journal is not a replay queue and intentionally cannot reconstruct the inbound SMS. B.2 must replace the quarantine boundary with a separately reviewed, durable native ingress and recipient-scoped transport.

The split preserves the demo's responsibilities: Hermes interprets and reasons; BlackPenguin owns transport, permissions, domain data, effects and persistence. No change to prompts, commercial rules, tool schemas or LangGraph.

## 2. Upload and CI (do this first)

1. Unzip the Upload Ready archive at repository root and upload all files preserving paths. Replace `.github/workflows/hermes-hei06a2-persistent-staging.yml` at the exact same path. Do not create a duplicate YAML workflow. The hidden `.dockerignore` under `provider_isolation/` is part of the build context; ensure it is included.
2. Commit: `test(hermes): add permanent staging provisioning and isolated signed provider ingress`.
3. Wait for the existing automatic HEI-06 isolated regression. The production deploy may not trigger (only staging files changed).
4. In **Hermes HEI-06A.2 persistent staging foundation**, select only `run_provider_isolation`. Leave `run_scoped`, `run_live_worker`, `run_continuous`, and `run_openrouter` unchecked for this lane. No new GitHub secrets or provider accounts are needed in CI. The canonical workflow retains all earlier inputs and tests.
5. Inspect `provider-isolation.json` inside the existing `hei06a2-foundation-<sha>` artifact. Expected: `status: PASS`, five acceptance checks true (network/no credentials, signed HTTPS negatives, durable quarantine, stop, cleanup), `quarantined_unique_events: 1`, and `actual_telnyx_delivery: NOT_RUN`, `permanent_server_deployment: NOT_RUN`. `summary.json` should show `provider_isolation: PASS`.

The hosted-CI test creates a throwaway signing key and self-signed certificate with SAN localhost/127.0.0.1, exposes the receiver only at `127.0.0.1:18443`, sends locally signed synthetic events, verifies certificate trust using that fixture, tests signature tampering/expiry/unauthorized sender, restarts the container, verifies idempotence and stops it. The test inspects network membership, UID/GID configuration and absence of private application credentials. It does not test public DNS or Telnyx delivery. The existing A.2 foundation is also checked in the same run. On failure share only the sanitized `provider-isolation.json` and startup evidence, not raw provider config or environment dumps.

Local validation for this differential: 20 new tests passed (real OpenSSL Ed25519 signatures, local HTTPS, journal persistence, authorization and topology checks); assembled staging suite ran 104 tests, 103 passed and one skipped because it needs the complete backend. Docker is not available locally; no claim of Docker or server acceptance is made. Image tags are not digest-pinned; pin and scan images before a broader exposure. The receiver is a bounded-concurrency Python HTTPS service for a restricted test environment, not a general public production edge.

## 3. Permanent host prerequisites (after CI passes)

Use a **new dedicated Linux staging host**, not the current DigitalOcean production droplet, with Docker Engine and Compose v2, Git, Python 3, OpenSSL and adequate disk/RAM for the existing images. Docker access is equivalent to host root. Use a dedicated checkout of the private repository, with a reviewed SSH deploy key or other authorized read-only Git access. Do not copy production `.env`, database backups, Telnyx keys or calendar credentials. No existing unrelated containers may be present; the tool rejects them. This does not independently prove host identity, so operator verification of the droplet is mandatory. Host package installation, DNS, firewall and CA certificate issuance remain manual.

Before enabling public access:

- Reserve a separate staging FQDN, e.g. `hermes-staging.<your-domain>`, with an A record to the new host. Do not modify the production domain. The included binding is IPv4 only.
- Use the cloud firewall to restrict SSH to the operator and inbound TCP 443 to the verified current Telnyx webhook source ranges plus the operator for testing. Confirm ranges in Telnyx documentation/support; do not blindly trust a copied IP range. Do not rely solely on UFW for Docker-published ports. No inbound 5432, 8000, 8080, 18082 or 18443.
- Obtain a trusted full-chain TLS certificate and key for the staging FQDN (e.g. DNS validation). Self-signed certificates are for CI/loopback only. Set a renewal schedule and restart the receiver after replacing certificate files; automated certificate issuance/renewal is not included. Ensure host UTC clock synchronization.
- Prepare a dedicated Telnyx test account or isolated messaging profile, SMS-capable dedicated number and consenting tester numbers. Do not repoint a production profile or use actual leads. If available, use an independent Telnyx organization. B.1 needs only the public webhook verification key, profile/organization IDs and numbers. Do not supply a Telnyx API send key.

## 4. Provision the certified continuous runtime

Run from the new host's dedicated clean checkout at the exact uploaded, CI-approved commit (not from the production machine):

```bash
cd ~/BlackPenguin-staging
# Verify the uploaded candidate SHA and successful CI first.
git rev-parse HEAD
git status --short
TOOL=services/hermes_worker/persistent_staging/permanent.py
STATE="$HOME/bp-hei06b1-state"
python3 "$TOOL" init "$STATE" --confirm-dedicated-host
```

`init` creates new 256-bit staging secrets in an external directory (0700, env file 0600). It must run once per installation. The database marker binds the candidate SHA and instance; automatic upgrade/reuse with a new SHA is intentionally denied. Back up data and create a reviewed migration or fresh isolated instance for later releases. Do not edit the marker to bypass it.

For the real Hermes model, store a **dedicated** OpenRouter key in `$STATE/openrouter.key` owned by your user with mode 0600. Example: `umask 077; nano "$STATE/openrouter.key"; chmod 600 "$STATE/openrouter.key"`. Never paste the key into Git, a chat, a shell argument, screenshots or CI logs. Use an independently budget-limited key.

```bash
python3 "$TOOL" up "$STATE" --confirm-dedicated-host --model
python3 "$TOOL" status "$STATE"
```

If a real model is not required, omit `--model` at the initial `up`. The mode is persisted and cannot be switched by rerunning `up` with a different flag. `up` first uses the certified original foundation and administrative probe to publish a synthetic policy, then builds and starts the derived images and verifies the resulting topology. On subsequent starts it keeps PostgreSQL data and does not rerun the closed foundation probe. Do not run `up` while a turn is in flight: stop and reconcile any uncertain work first. This is manual provisioning, not a deployment action in the CI runner.

Access the UI via SSH from your computer:

```bash
ssh -N -L 18082:127.0.0.1:18082 <operator>@<staging-host>
```

Open `http://127.0.0.1:18082/login`. Use `staging-admin@example.invalid` and the dedicated `STAGE_ADMIN_PASSWORD` stored in the local state file (consult it privately). The UI is not publicly exposed. The existing test-only grant endpoints remain restricted to the predefined synthetic fixtures; do not invoke them to test a real SMS.

The OpenRouter key is provided only to the SDK container, not the API or receiver. Docker administrators can inspect container environment values, so host access must be limited. SDK model egress uses a separate bridge network, **not a destination-level allowlist**. The receiver also uses a distinct bridge network (not a network-enforced outbound-deny sandbox). No receiver code initiates outbound provider calls and there are no application credentials inside it. If host-level egress restriction is required, enforce and verify it on the dedicated host before exposure.

## 5. Configure the receiver (no production credentials)

Create the provider directory and private journal. Copy and edit the policy template in a private file outside the repo. Fill `public_key_base64` with the raw 32-byte Ed25519 public key encoded as base64 (not an API token or PEM); fill the UUIDs and E.164 numbers from the dedicated test profile. Generate `fingerprint_key_hex` using `openssl rand -hex 32` locally. Up to five test senders are allowed. Do not include other fields or real customer numbers.

```bash
umask 077
mkdir -m 700 "$STATE/provider"
cp services/hermes_worker/persistent_staging/provider_isolation/policy.example.json "$STATE/policy-draft.json"
nano "$STATE/policy-draft.json"
sudo install -o 10001 -g 10001 -m 0400 "$STATE/policy-draft.json" "$STATE/provider/policy.json"
sudo install -o 10001 -g 10001 -m 0400 /path/to/fullchain.pem "$STATE/provider/fullchain.pem"
sudo install -o 10001 -g 10001 -m 0400 /path/to/privkey.pem "$STATE/provider/privkey.pem"
sudo install -d -o 10001 -g 10001 -m 0700 "$STATE/provider/journal"
```

Use actual certificate paths instead of placeholders. Files are copied rather than symlinked so the container gets the intended files only. Only the receiver's configuration and TLS material are mounted in the receiver; the journal is private to UID/GID 10001. Back up the HMAC key and journal together if retaining evidence. Changing the allowlist, identity, public key or HMAC key invalidates the current journal binding; use a new reviewed journal after archiving the old one. Certificate renewal alone does not invalidate the journal.

Start with a local binding, then verify:

```bash
python3 "$TOOL" webhook-up "$STATE" --confirm-dedicated-host
python3 "$TOOL" verify "$STATE" --confirm-dedicated-host
python3 "$TOOL" stats "$STATE"
```

The loopback receiver uses 18443 and rejects any unauthenticated event. A TLS certificate issued for the staging domain can be tested with `curl --resolve <staging-fqdn>:18443:127.0.0.1 https://<staging-fqdn>:18443/` (expect HTTP 404, with valid TLS; don't use `-k`). The Docker healthcheck intentionally verifies local readiness only, not public CA trust.

Only after firewall, DNS and valid certificate are verified, explicitly start the public endpoint:

```bash
python3 "$TOOL" webhook-up "$STATE" --confirm-dedicated-host --public
python3 "$TOOL" verify "$STATE" --confirm-dedicated-host --public
```

From an authorized external machine check:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://<staging-fqdn>/
# Expect 404, without certificate errors.
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Content-Type: application/json' --data '{}' \
  https://<staging-fqdn>/webhooks/telnyx/messaging
# Expect 401, without signature.
```

No public path proxies to the core application. Verify that the production host/domain/profile remain unchanged.

## 6. Optional real inbound quarantine smoke (operator-controlled)

Only after CI, provisioning, TLS and firewall checks pass, configure the **dedicated test messaging profile only**, API webhook v2, pointing at `https://<staging-fqdn>/webhooks/telnyx/messaging`. Ensure its failover URL is unset or exclusively a safe test endpoint, never production. Send exactly one manual test SMS from an authorized consenting number to the dedicated number (carrier/number charges may apply). Check portal delivery and `python3 "$TOOL" stats "$STATE"`: `quarantined_unique_events` should increase by one. A retry of the same event ID with unchanged business content returns 200 `duplicate`; an altered content collision returns 409. No response SMS, AgentRun, commercial job, meeting or lead change should be generated by this receiver. Outbound callbacks, MMS and WhatsApp are denied in B.1. Do not test with a live buyer, and do not treat this smoke as B.2 end-to-end acceptance.

Provider documentation used to align signature and payload contract:
- https://support.telnyx.com/en/articles/4334722-how-to-leverage-webhooks
- https://support-v2.telnyx.com/en/articles/4334722-how-to-leverage-webhooks

Signature: verify Ed25519 over exact timestamp + `|` + raw body. Timestamp window ±300 seconds. Profile ID, organization ID, event and direction, SMS type, single destination and sender allowlist are checked. Only UUID-derived HMAC event identity, HMAC content fingerprint and acceptance time are stored. Retry envelope metadata is deliberately excluded from the content fingerprint. No raw phone number, SMS, media, token or public provider event ID is persisted in the journal. It is still sensitive operational metadata; keep private and set a retention policy. Limit: 1,000 unique events, 32 KiB payload, 1,600-character text, 16 concurrent handler slots. Full journals fail closed; no automatic pruning that could make old duplicates eligible again. This is not a DDoS protection service. Malformed/unsigned requests can be dropped or rejected. The journal's event-id deduplication is not a full commercial message/receipt ledger; B.2 must independently deduplicate provider message ID and receipt transitions.

## 7. Stop, recovery and rollback

```bash
# Immediately stop the public receiver and preserve its journal.
python3 "$TOOL" webhook-stop "$STATE"
# Emergency stop of receiver, UI, API worker and SDK, retaining databases.
python3 "$TOOL" stop "$STATE"
```

Also remove/disable the dedicated Telnyx webhook configuration when stopping a public test, to prevent retry traffic. Never change the production profile. A stop is not cancellation of an already in-flight provider operation (B.1 has no real provider sends). PostgreSQL remains running; no volume deletion is performed. Backups and restore should be tested before B.2; neither automated backup nor cross-version upgrade is implemented here. To restart the exact candidate, use the same mode and private state, and explicitly start the receiver again if required. Do not automatically resume uncertain commercial jobs. The existing authorization revocation endpoints can revoke a granted synthetic capability; the infrastructure stop is a separate emergency boundary.

## 8. What remains

- CI acceptance of the Docker quarantine and all core regression checks.
- Permanent staging host, DNS, TLS, firewall, key and provider profile configuration, and real inbound smoke remain operator actions. No provider credentials, host or DNS changes are made by this package.
- HEI-06B.2: Native authenticated inbound mapping to real `SalesInboundJob`, arbitrary *authorized test* message scope, consent/opt-out, protected real SMS egress, durable outbox and callback correlation, retry/uncertain-send reconciliation and revocation. Real provider sends are deliberately disabled until this is reviewed and tested.
- HEI-06B.3: WhatsApp and media; HEI-06C: Calendar and operational acceptance; HEI-07: separate production authorization and rollback. Production remains CLOSED.
