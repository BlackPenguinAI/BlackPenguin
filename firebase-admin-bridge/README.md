# Firebase Admin bridge (optional)

This optional keyless Cloud Run service is limited to deleting Firebase
Authentication identities. Appointment email delivery is intentionally outside
the Black Penguin core and no Firestore mail documents are created here.

The DigitalOcean deployment does not require this bridge. When it is not
configured, company deletion can use the existing explicit manual-cleanup
confirmation flow.

Required Cloud Run environment variables when administrative deletion is used:

- `FIREBASE_PROJECT_ID`: the Firebase project configured in Black Penguin.
- `BRIDGE_SHARED_SECRET`: a long random value shared with the API runtime.

The runtime service account needs `roles/firebaseauth.admin`. Requests are
authenticated with the existing timestamped HMAC signature and expire after
five minutes.
