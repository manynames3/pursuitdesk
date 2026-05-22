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
