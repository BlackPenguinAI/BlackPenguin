# Active integration validation — 2026-11-06

Base: `e96c8189cfd39f351274d9f2add115ffc59eecf1`.

| Check | Observed result |
| --- | --- |
| Full backend regression, final execution | 1380 passed, 2 skipped, 107.83 seconds |
| Focused active integration + five original audit findings | 25 passed |
| Selected frontend regressions, 19 files | 193 passed |
| Production frontend build | Passed; existing stylesheet budget warnings remain |
| `git diff --check` | Passed |

The two skips are PostgreSQL parallel-writer tests: no disposable
`DIALOGUE_POSTGRES_TEST_URL` was supplied. SQLite is not evidence of production
concurrency correctness. Python dependencies also emit existing deprecation
warnings; they were not hidden from the recorded summary.

Focused tests exercise the real inbound entry point, state store, approved
asset/share services and outbound dispatcher, with mocked inference and
network transport. They cover mixed replies, negative appointment intent,
AND/OR materials, exclusions, photo fallback assent, ambiguous references,
seven catalog alternatives and stable selection after sorting, invalid model
contracts with evidence preservation, durable retry without repeated model
calls/token issuance, approval revocation, manual takeover, kill switch,
opt-out/human controls without model availability, verified booking without
duplicate retry, persistent restrictions/reversal, audited 360 destinations,
and deterministic-ID calendar retry.

No real LLM quality evaluation, SMS/WhatsApp send, Google Calendar write,
OAuth/browser walkthrough or production deployment was performed. See the
activation document before manual live E2E. The older simulator is not the
active inbound engine.

`delivery/` in the differential ZIP contains the actual test/build logs and a
base-commit/SHA-256 manifest. It is evidence, not application code.
