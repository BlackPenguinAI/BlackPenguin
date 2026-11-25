# BP-HERMES-P01: local test results

Command (against the exact P01 new-file tree):

```bash
PYTHONPATH=backend python -m pytest -q backend/tests/test_bp_hermes_p01.py backend/tests/test_bp_hermes_p01_policies.py
```

Local test environment: Python 3.13, pytest 9.0.2.

Results at package creation: **30 passed** (offline tests).

Verified:
- Toolset is exactly 15 registered names; effect-capable methods are blocked.
- Original AIAgent constructor argument contract, tool allowlist and history
  passing, with a **fake SDK implementation** (NOT a real OpenRouter test).
- Rejects invalid runtime settings, missing secret and mismatched tenant scope.
- Read tools receive the expected scoped IDs; no database/provider involved.
- Repeated identical failed tool requests are de-duplicated within a turn.
- Visible options `2`, `Option 2`, `the second option`, `la segunda` select the
  second *day* instead of a stale property; exact offered hours remain unbooked.
- Permanent budget cap vs temporary property search is kept separate.
- Soft budget targets are not promoted to hard maximums.
- Relevant property focus, ambiguous follow-ups and material choice selection.

Not verified:
- No actual Nous Research Hermes SDK installation/import/LLM call.
- No BlackPenguin FastAPI full test suite, Angular build, or SQL migration.
- No live Telnyx/Twilio, Google Calendar, DigitalOcean, or OpenRouter call.
- No production or end-to-end multi-process performance claims.

**Release gate:** P01 is code foundation only, not a production-enabled agent.
