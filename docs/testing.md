# Testing And Validation

## Current Automated Checks

GitHub Actions runs:

- Python syntax compile for core Lambda modules.
- Frontend JavaScript syntax check with `node --check`.
- Terraform format check.
- Terraform init/validate with backend disabled.
- `git diff --check`.

## Local Commands

```bash
python3 -m py_compile src/proposal_writer_lambda.py src/api_v1_endpoints.py src/db_admin_lambda.py src/gsa_api_ingest.py src/partner_matching.py src/mock_data_seeder.py
node --check frontend/app.js
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
git diff --check
```

## Manual Smoke Checks

- Load the public frontend.
- Confirm live API status.
- Switch client profiles.
- Search/filter opportunities and press Enter to apply filters.
- Select an opportunity and confirm P-win range, evidence, next-best-action guidance, and Go/No-go controls.
- Start a proposal job and confirm the background notification.
- Export a capture brief and proposal PDF/DOCX.

## Gaps

- No committed unit test suite yet.
- No API integration test harness yet.
- No e2e browser test in CI yet.
- Scoring, P-win range logic, Markdown export cleanup, and proposal quality gates should get focused unit tests before production use.
