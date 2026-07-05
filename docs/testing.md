# Testing And Validation

PursuitDesk has lightweight automated validation plus focused unit tests for the riskiest recent product logic. It is not yet a full production test suite.

## Current Automated Checks

GitHub Actions runs:

- Python syntax compile for core Lambda modules.
- Python unit tests for P-win range, confidence shrinkage, capture-fit display mode, structural-only caps, proposal source context, and API route contracts.
- Frontend JavaScript syntax check with `node --check`.
- Frontend formatting tests for proposal Markdown table cleanup and PDF-safe text normalization.
- Playwright consultant-workflow smoke test against the static frontend.
- Terraform format check.
- Terraform init/validate with backend disabled.
- `git diff --check`.

## Local Commands

```bash
python3 -m py_compile src/proposal_writer_lambda.py src/api_v1_endpoints.py src/db_admin_lambda.py src/gsa_api_ingest.py src/partner_matching.py src/mock_data_seeder.py
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -p 'test_*.py'
node --check frontend/app.js
node --test tests/*.test.mjs
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
git diff --check
```

## Manual Smoke Checks

- Load the public frontend.
- Confirm live API status.
- Switch client profiles.
- Confirm the advisor workflow cue reflects client, pipeline, decision, and proposal state.
- Search/filter opportunities, press Enter to apply filters, and use Clear filters from the empty state.
- Select an opportunity and confirm P-win range, evidence, next-best-action guidance, and Go/No-go controls.
- Start a proposal job and confirm the background notification.
- Export a capture brief and proposal PDF/DOCX.

## Gaps

- Authenticated tenant e2e coverage should be added after production JWT/account access is enabled.
- Proposal quality gates should get deeper regression tests before production use.
