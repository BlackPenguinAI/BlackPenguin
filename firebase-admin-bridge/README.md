# Firebase Admin bridge

This service deletes Firebase Authentication identities and creates trusted
Trigger Email documents without placing a service-account JSON or SMTP password
in Black Penguin. Its Cloud Run service account needs Firebase Authentication
administration plus `roles/datastore.user` on the Firebase project.

Required Cloud Run environment variables:

- `FIREBASE_PROJECT_ID`: the same project configured in Black Penguin.
- `BRIDGE_SHARED_SECRET`: a long random value shared with the Black Penguin
  GitHub secret `FIREBASE_ADMIN_BRIDGE_SECRET`.
- `FIRESTORE_MAIL_COLLECTION`: the collection watched by Trigger Email from
  Firestore (default: `mail`).

After deployment, add these GitHub Actions repository secrets:

- `FIREBASE_ADMIN_BRIDGE_URL`: Cloud Run service URL.
- `FIREBASE_ADMIN_BRIDGE_SECRET`: the shared secret above.

The service accepts only short-lived HMAC-signed deletion requests. Configure
Cloud Run ingress and rate limits as narrowly as your deployment permits.

## Automated deployment

The repository workflow `.github/workflows/deploy-firebase-admin-bridge.yml`
deploys this directory whenever it changes on `main`. It authenticates to
Google Cloud with Workload Identity Federation, so no service-account JSON is
stored in GitHub.

Configure these GitHub Actions secrets once:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: full Workload Identity Provider resource.
- `GCP_DEPLOY_SERVICE_ACCOUNT`: deployer service-account email.
- `FIREBASE_ADMIN_BRIDGE_URL`: stable Cloud Run service URL consumed by the API.
- `FIREBASE_ADMIN_BRIDGE_SECRET`: the same HMAC value exposed to Cloud Run from
  `blackpenguin-firebase-admin-bridge-secret`.

The deployer identity needs permission to deploy Cloud Run from source and to
act as `blackpenguin-firebase-admin@blackpenguinai.iam.gserviceaccount.com`.
The runtime identity keeps `roles/firebaseauth.admin`, `roles/datastore.user`,
and access to the bridge secret. The main DigitalOcean workflow validates that
the URL and HMAC secret are non-empty before it recreates production.

## Example deployment

Replace the uppercase placeholders and run from this directory:

```bash
gcloud iam service-accounts create blackpenguin-firebase-admin \
  --project=FIREBASE_PROJECT_ID

gcloud projects add-iam-policy-binding FIREBASE_PROJECT_ID \
  --member=serviceAccount:blackpenguin-firebase-admin@FIREBASE_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/firebaseauth.admin

gcloud projects add-iam-policy-binding FIREBASE_PROJECT_ID \
  --member=serviceAccount:blackpenguin-firebase-admin@FIREBASE_PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/datastore.user

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
  --set-env-vars=FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID,FIRESTORE_MAIL_COLLECTION=mail \
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

## Trigger Email from Firestore

Install Firebase's official **Trigger Email from Firestore** extension in the
same project. Configure its collection as `mail`, set the corporate address as
the default FROM address, choose SMTP username/password authentication, and put
the Google Workspace/Gmail App Password in the extension's secret field. The
App Password must never be copied into Black Penguin or GitHub.

Use `smtp.gmail.com` with TLS (port 465 or 587, according to the extension
wizard). Restrict Firestore client rules so browsers cannot create mail
documents; only this bridge writes them. Delivery results are read from the
extension's `delivery.state` field. A Firestore TTL policy on
`delivery.expireAt` is recommended for automatic cleanup.
