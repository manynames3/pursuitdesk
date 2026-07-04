# Deployment

## Frontend

Cloudflare Pages serves the static files in `frontend/`.

Manual deploy:

```bash
npx wrangler@4 pages deploy frontend \
  --project-name pursuitdesk \
  --branch main \
  --commit-hash "$(git rev-parse --short HEAD)" \
  --commit-dirty=true
```

GitHub Actions can deploy the frontend when these are configured:

- Repository secret: `CLOUDFLARE_API_TOKEN`
- Repository variable: `CLOUDFLARE_ACCOUNT_ID`

## Backend

Build Lambda artifacts:

```bash
./scripts/build_lambda_packages.sh
```

Deploy AWS infrastructure:

```bash
terraform -chdir=infra/terraform apply
```

Database migrations and demo seeding run through the `db_admin` Lambda, documented in the README.

## Validation Before Deploy

```bash
python3 -m py_compile src/proposal_writer_lambda.py src/api_v1_endpoints.py src/db_admin_lambda.py src/gsa_api_ingest.py src/partner_matching.py src/mock_data_seeder.py
node --check frontend/app.js
terraform -chdir=infra/terraform fmt -check
git diff --check
```
