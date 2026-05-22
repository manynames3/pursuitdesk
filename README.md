# GovCon CaptureOS

GovCon CaptureOS is an AI-assisted federal market intelligence demo stack for opportunity discovery, entity resolution, capture scoring, subcontractor graph analysis, and CALC+ labor-rate benchmarking.

## Repository Layout

- `src/`: Python ingestion, entity resolution, presentation API, and partner matching modules.
- `migrations/`: PostgreSQL migrations for `pgvector`, capture tables, and CALC+ labor rates.
- `infra/terraform/`: low-cost AWS demo infrastructure with RDS PostgreSQL, Lambda, and API Gateway v2 HTTP API.
- `frontend/`: static Cloudflare Pages dashboard.

## Cloudflare Pages

Live demo:

- Frontend: https://govcon-captureos.pages.dev/
- Backend API: https://n2qx0wcyg8.execute-api.us-east-1.amazonaws.com

Use these Git integration settings for the frontend:

- Production branch: `main`
- Root directory: `frontend`
- Build command: leave blank
- Build output directory: `.`

The dashboard reads its backend base URL from `frontend/config.js`. It falls back to local demo data if the API is unavailable.

GitHub Actions will deploy `frontend/` to Cloudflare Pages when `CLOUDFLARE_API_TOKEN` is set as a repository secret. `CLOUDFLARE_ACCOUNT_ID` is already safe to keep as a repository variable.

## Lambda Packaging

Build deployable AWS Lambda artifacts before running Terraform:

```bash
./scripts/build_lambda_packages.sh
```

The script creates ARM64 Python 3.12-compatible zip files under `dist/` for the API, ingestion, entity resolver, and one-shot database admin Lambda.

Initialize or refresh the demo database after Terraform has deployed the Lambda functions:

```bash
aws lambda invoke \
  --function-name govcon-captureos-demo-db_admin \
  --cli-binary-format raw-in-base64-out \
  --payload '{"action":"migrate_and_seed","reset":true}' \
  /tmp/captureos-db-admin-response.json
```

## Paid-MVP Surfaces

The live demo now exposes the buyer-facing capture workspace layer:

- Source-backed evidence for SAM.gov opportunities, USAspending awards, FSRS subawards, and CALC+ labor rates.
- Customer-specific scoring with market baseline P-win, company-adjusted P-win, fit factors, contract vehicles, clearances, and eligibility posture.
- Capture workflow state for go/no-go, stage, owner, priority, notes, and markdown capture brief export.
- Data freshness watermarks by source system.
- Tenant, user, RBAC, watchlist, and audit-event tables for production auth integration.

The deployed demo uses `demo_header_context` so the public Cloudflare page can be exercised without a login. Before charging real customers, put API Gateway behind Cognito, Cloudflare Access, or another verified JWT provider and enforce tenant claims instead of default headers.

## Production Hardening Switches

Set these Terraform variables when moving from demo mode to paid users:

- `auth_required = true`
- `jwt_issuer`, `jwt_audience`, `jwt_jwks_url`
- `enable_api_gateway_jwt_authorizer = true` when issuer/audience are stable
- `sam_api_key_secret_arn` and `enable_gsa_ingest_schedule = true`
- `stripe_api_key_secret_arn`, `stripe_webhook_secret_arn`, and `stripe_price_id`
- `enable_cloudwatch_alarms = true` if the small CloudWatch alarm cost is acceptable

The SAM.gov scheduler uses EventBridge Scheduler and invokes the public `ingest` Lambda, which runs outside the VPC for managed internet egress. That Lambda fetches SAM.gov and invokes the VPC-attached `upsert` Lambda, which writes to PostgreSQL. This keeps RDS private without adding a NAT Gateway.

Auth is enforced in the API Lambda through JWKS validation and can also be enforced at API Gateway. Billing checkout uses Stripe Checkout when secrets are configured; Stripe webhooks verify `Stripe-Signature` when a webhook signing secret is present. Customer onboarding imports past performance into `capture.customer_past_performance` and refreshes the scoring profile rollup.

## Live SAM.gov Ingestion

SAM.gov requires a public API key for the Opportunities API. Keep that key out of source control and Terraform state:

```bash
export SAM_API_KEY="..."
./scripts/enable_live_sam_ingest.sh
```

The script creates or updates an AWS Secrets Manager secret, writes the secret ARN to the ignored `infra/terraform/live_ingest.auto.tfvars` file, enables the EventBridge Scheduler job, and runs a one-time 30-day active-opportunity backfill. The scheduled path uses a no-NAT split: public fetch Lambda -> private VPC upsert Lambda.

You can run a manual bridge backfill through the same private upsert path:

```bash
export SAM_API_KEY="..."
./scripts/backfill_sam_opportunities.py --days 30 --max-pages 5
unset SAM_API_KEY
```

Override these optional knobs when needed:

```bash
GSA_INGEST_SCHEDULE_EXPRESSION="rate(12 hours)" \
GSA_BACKFILL_DAYS=60 \
GSA_BACKFILL_MAX_PAGES=20 \
./scripts/enable_live_sam_ingest.sh
```
