# BlackPenguin Hermes — Delivery 6 (P08 staged, NOT live cutover)

**IMPORTANT: P07 WAS NOT INSTALLED.** GitHub commit `0ef0c23a` (message mentions P07) contains **zero file modifications** and no workflow runs. This package **re-includes the full P07 code changes** along with the new P08 isolated simulation/SDK preflight lane.

- Extract and upload the archive CONTENTS preserving the repository-relative directories.
- Do NOT upload only the ZIP. No scripts or commands are required BEFORE upload.
- Prefer a branch; merging to main starts the existing DigitalOcean production workflow. New P08 Hermes SDK staging CI builds a container **without deploying it**.
- This release does **not** change live inbound routing, SMS/WhatsApp, Calendar delivery or LangGraph dependencies.
- Run and inspect full GitHub Actions. The existing deployment workflow should require P07 PostgreSQL **14/14 passed, 0 skipped**. The new independent Hermes SDK smoke must pass too.
- Neither P07 completion nor real P08 cutover should be claimed until these independent results are available. Real provider/Calendar E2E and production-worker implementation are still BLOCKED.

Detailed explanation: `docs/hermes-integration/P08_CUTOVER_READINESS.md`.

Recommended commit: `feat(hermes): restore P07 gates and add isolated P08 simulation lane`
