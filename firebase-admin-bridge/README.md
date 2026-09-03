# Firebase Admin bridge

This small service deletes Firebase Authentication identities without placing a
service-account JSON in Black Penguin. Deploy it to Google Cloud Run with an
attached service account that has `firebaseauth.users.get` and
`firebaseauth.users.delete` permissions.

Required Cloud Run environment variables:

- `FIREBASE_PROJECT_ID`: the same project configured in Black Penguin.
- `BRIDGE_SHARED_SECRET`: a long random value shared with the Black Penguin
  GitHub secret `FIREBASE_ADMIN_BRIDGE_SECRET`.

After deployment, add these GitHub Actions repository secrets:

- `FIREBASE_ADMIN_BRIDGE_URL`: Cloud Run service URL.
- `FIREBASE_ADMIN_BRIDGE_SECRET`: the shared secret above.

The service accepts only short-lived HMAC-signed deletion requests. Configure
Cloud Run ingress and rate limits as narrowly as your deployment permits.

## Example deployment

Replace the uppercase placeholders and run from this directory:

```bash
gcloud iam service-accounts create blackpenguin-firebase-admin \
  --project=FIREBASE_PROJECT_ID

gcloud projects add-iam-policy-binding FIREBASE_PROJECT_ID \
  --member=serviceAccount:blackpenguin-firebase-admin@FIREBASE_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/firebaseauth.admin

gcloud secrets create blackpenguin-firebase-admin-bridge-secret \
  --replication-policy=automatic \
  --project=FIREBASE_PROJECT_ID

openssl rand -hex 32 | gcloud secrets versions add \
  blackpenguin-firebase-admin-bridge-secret --data-file=- \
  --project=FIREBASE_PROJECT_ID

gcloud run deploy blackpenguin-firebase-admin \
  --source=. \
  --region=GCP_REGION \
  --project=FIREBASE_PROJECT_ID \
  --service-account=blackpenguin-firebase-admin@FIREBASE_PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars=FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID \
  --set-secrets=BRIDGE_SHARED_SECRET=blackpenguin-firebase-admin-bridge-secret:latest \
  --allow-unauthenticated
```

Use the same secret value as the GitHub repository secret
`FIREBASE_ADMIN_BRIDGE_SECRET`. Public Cloud Run invocation is required for the
DigitalOcean origin, but every state-changing request is independently
authenticated with a five-minute HMAC signature.

You can retrieve the generated value once for GitHub configuration with:

```bash
gcloud secrets versions access latest \
  --secret=blackpenguin-firebase-admin-bridge-secret \
  --project=FIREBASE_PROJECT_ID
```
