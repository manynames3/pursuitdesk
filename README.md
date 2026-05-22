# GovCon CaptureOS

GovCon CaptureOS is an AI-assisted federal market intelligence demo stack for opportunity discovery, entity resolution, capture scoring, subcontractor graph analysis, and CALC+ labor-rate benchmarking.

## Repository Layout

- `src/`: Python ingestion, entity resolution, presentation API, and partner matching modules.
- `migrations/`: PostgreSQL migrations for `pgvector`, capture tables, and CALC+ labor rates.
- `infra/terraform/`: low-cost AWS demo infrastructure with RDS PostgreSQL, Lambda, and API Gateway v2 HTTP API.
- `frontend/`: static Cloudflare Pages dashboard.

## Cloudflare Pages

Use these Git integration settings for the frontend:

- Production branch: `main`
- Root directory: `frontend`
- Build command: leave blank
- Build output directory: `.`

The dashboard can run before the AWS API is live because it falls back to local demo data. When the API Gateway endpoint is ready, set `window.CAPTUREOS_API_BASE_URL` in the Pages project or add a small runtime config script before `app.js`.
