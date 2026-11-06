# Global Sales rollout and dialogue corrections

Base commit: `f5da5489c843aebe4f449fde6f3913884c92e4c3`.

## Changes

- Published runtime policy accepts explicit `scope: global`. It selects all
  current/future Companies, Projects and Leads without storing allowlists.
  Existing policies default to `cohort`; empty filters do not silently enable
  global operation. Global plus any filter is rejected as contradictory.
- AI Settings adds a Global/Cohort selector. Selecting Global clears and hides
  filters. Publication is still required. Scope never replaces tenant checks,
  approved-project/resource checks, consent or manual control.
- GitHub Actions forwards repository variable `SALES_DIALOGUE_RUNTIME_ENABLED`
  to SSH and validates exact `true`/`false` before touching deployment state.
  It persists the flag into the generated common API/worker environment on
  every deploy. Absent variable defaults to false; no automatic activation.
- Exact opt-out controls are processed even if the active chat is already
  paused, without invoking a model or depending on sales-readiness permission.
  Repeated handling retains the existing durable run/send rather than sending
  another acknowledgement. Ordinary paused conversations remain paused.
- Approved material tasks resumed by the read loop can reach the share adapter
  even when they originated in an earlier message. Current exclusions and
  fresh sharing permissions still gate them; discovery is not delivery.
- Explicit clock-time appointment references resolve only to a unique current,
  unexpired, future offered slot in the Project timezone. Two offered dates with
  the same time remain ambiguous. The normal booking service still revalidates
  location, eligible Sales users, availability and conflicts.

## Activation after applying the differential

1. In GitHub repository Settings → Secrets and variables → Actions → Variables,
   add/update the **repository variable** `SALES_DIALOGUE_RUNTIME_ENABLED` with
   value `true` (lowercase). This is a non-secret switch, not a model credential.
2. Commit/push this patch, including `.github/`, and wait for the entire
   production deployment to succeed. Setting the repository variable alone
   does not change already-running containers.
3. In `/admin/ai-settings` → Sales Agent, choose **Active · structured engine**
   and **Global · all Companies and Projects**. Save and **publish**.
   No Company/Project/Lead IDs are needed or allowed in Global scope.
4. Verify effective settings on API and worker and a new eligible live turn's
   `sales-active/1.0` trace in `/monitor`. The historical simulator still uses
   its separate executor; use the ordinary live SMS/WhatsApp path for manual E2E.

To stop new active execution immediately, publish Disabled in AI Settings.
To persist the server kill switch as false, set the repository variable to
`false` and redeploy. This does not undo already-confirmed bookings/messages.
Prior active events do not silently replay through legacy on rollback.

No production configuration, credential, prompt publication, real messaging,
calendar event or deployment was changed during development of this patch.
No migration is introduced. Existing dialogue migrations must remain applied.

## Validation boundaries

| Check | Observed result |
| --- | --- |
| Final complete backend suite | 1402 passed, 2 skipped; 96.14 seconds |
| Focused global/active/original-audit regressions | 42 passed |
| Frontend regression set, 19 files | 194 passed |
| Production frontend build | Passed; existing stylesheet budget warnings remain |
| YAML/Bash and six deployment-flag cases | Passed |
| Git whitespace check | Passed |

Regression logs are included under `delivery/`. Tests use scripted inference,
SQLite and mocked provider transports; passing tests do not certify arbitrary
LLM interpretation, Google OAuth, Meta or real SMS/WhatsApp delivery. Two
PostgreSQL concurrency tests require a disposable database and remain skipped.
Docker is not available here; workflow YAML/Bash and flag forwarding/validation
were checked without running production commands. Real image execution and
deployment health must be confirmed in GitHub Actions.
