# Black Penguin — Twilio + Telnyx update

Base commit: `81d2fd4075704a795b5e20e30a790a4435f74822`

1. Copy the included folders over the repository root, preserving paths.
2. Delete every path listed in `DELETE_FILES.txt`.
3. Run `cd backend && alembic upgrade head` before restarting the API and worker.
4. Build and deploy the API, worker and frontend using the existing workflow.
5. In `/admin/messaging-settings`, save and verify Telnyx before enabling it or selecting it as default.
6. In the Telnyx Messaging Profile configure:
   `https://blackpenguin.ai/api/v1/webhooks/telnyx/messaging`

The migration is forward-only and keeps historical appointment-email columns
and tables dormant. Do not run an Alembic downgrade in production.

Validated locally:

- Backend: 306 tests passed.
- Frontend production build: passed.
- Updated frontend specs: 4 tests passed.
- The repository-wide Angular test target still contains pre-existing broken
  scaffold specs unrelated to this change; the production build is clean.
