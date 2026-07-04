# Runbook

## Routine Checks

- Open the frontend at `https://pursuitdesk.pages.dev/`.
- Confirm the API status pill changes to `Live API`.
- Select a client profile and confirm active opportunities load.
- Select an opportunity and confirm P-win range, evidence, decision guidance, and proposal history render.
- Submit a Proposal Writer job and confirm the background notification appears when the draft is ready.

## API Smoke Checks

```bash
curl -sS https://n2qx0wcyg8.execute-api.us-east-1.amazonaws.com/api/v1/customer-teams \
  | python3 -m json.tool

curl -sS 'https://n2qx0wcyg8.execute-api.us-east-1.amazonaws.com/api/v1/opportunities/active?limit=2' \
  -H 'x-captureos-tenant: demo-growth' \
  -H 'x-captureos-user: capture.lead@example.com' \
  | python3 -m json.tool

curl -sS 'https://n2qx0wcyg8.execute-api.us-east-1.amazonaws.com/api/v1/proposal-writer/jobs?limit=5' \
  -H 'x-captureos-tenant: demo-growth' \
  -H 'x-captureos-user: capture.lead@example.com' \
  | python3 -m json.tool
```

## Common Failure Modes

- **Frontend shows offline mode:** verify `frontend/config.js`, API Gateway availability, and CORS settings.
- **No active opportunities:** check SAM.gov ingestion status, filters, and source freshness rows.
- **Proposal job is slow:** review Proposal Writer Lambda logs and Bedrock model access. Jobs are async, so users can continue working while polling continues.
- **Proposal job fails:** inspect DynamoDB job error fields, Proposal Writer Lambda logs, and Bedrock permission/model availability.
- **Database errors:** inspect API Lambda logs and RDS reachability from the Lambda security group.

## Rollback / Recovery

- Frontend: redeploy a known-good Cloudflare Pages deployment or run the Wrangler deploy command from a previous commit.
- Backend: revert code/Terraform changes, rebuild Lambda packages, and run `terraform apply`.
- Database: migrations are forward-only in this repo. Restore from RDS backups/snapshots for destructive mistakes.
