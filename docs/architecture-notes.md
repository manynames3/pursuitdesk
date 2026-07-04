# AWS Architecture Notes

The main diagram is generated from [`architecture_aws.py`](architecture_aws.py) with the
[Mingrammer Diagrams](https://diagrams.mingrammer.com/) package and Graphviz. It reflects the
repository's Terraform defaults and application integrations as of the current commit.

## What the diagram shows

### Request flow

1. A GovCon advisor opens the static HTML/CSS/JavaScript frontend on Cloudflare Pages.
2. The browser calls the API Gateway v2 HTTP API over HTTPS.
3. API routes run on the VPC-attached FastAPI/Mangum Lambda and read or write private RDS
   PostgreSQL 15 with `pgvector`.
4. Proposal Writer routes use a non-VPC Lambda. It records asynchronous jobs and draft history
   in DynamoDB, invokes Amazon Bedrock, and exposes polling endpoints through API Gateway.
5. Stripe checkout and webhook handling are implemented, but require configured Stripe secrets
   and a price ID. The public demo does not enable paid billing by default.

### Data ingestion

EventBridge Scheduler jobs can trigger non-VPC fetch Lambdas for SAM.gov, USAspending/FSRS, and
GSA CALC+. The fetch functions invoke VPC-attached upsert functions, which normalize records and
write to RDS. This split gives public data fetches managed Lambda internet access without a NAT
Gateway while keeping the database private. All schedules are optional and default to disabled.

### Deployment

- The committed GitHub Actions workflow deploys only `frontend/` to Cloudflare Pages with
  Wrangler when Cloudflare credentials are configured.
- Lambda zip files are built by `scripts/build_lambda_packages.sh`.
- Terraform provisions the AWS stack. The repository documents Terraform apply as a manual
  deployment step; it does not contain an AWS deployment workflow.
- Database migrations and demo seed data run through the `db_admin` Lambda.

### Security and observability

- RDS has no public endpoint. Its security group accepts PostgreSQL only from the Lambda security
  group, and storage encryption is enabled.
- API Gateway and application-level JWT/JWKS validation are implemented but disabled by default.
  Demo tenant headers are used when authentication is not required. No specific identity provider
  is assumed by the diagram.
- IAM grants the shared Lambda runtime role access to the specific in-stack Lambda and DynamoDB
  resources, plus Bedrock model invocation. Secrets Manager access is limited to configured ARNs.
- Each Lambda has a CloudWatch log group with seven-day default retention. Lambda error and API
  Gateway 5xx alarms are supported but disabled by default.

### Cost controls

The Terraform deliberately uses API Gateway HTTP API, ARM64 Lambdas with 128/256 MB memory,
single-AZ `db.t4g.micro` RDS with fixed 20 GB storage, DynamoDB on-demand billing with TTL, bounded
API throttles and ingest page counts, short log retention, and no NAT Gateway, RDS Proxy, Aurora,
OpenSearch, provisioned concurrency, or X-Ray active tracing.

## Evidence and exclusions

AWS services shown in the diagram are declared in `infra/terraform/` or called by the application.
Cloudflare Pages, GitHub Actions, Stripe, and the public procurement APIs are external services.
Secrets Manager entries are referenced by ARN rather than provisioned by Terraform; the SAM.gov
enablement script can create its secret. Scheduled ingestion, JWT enforcement, Stripe billing, and
CloudWatch alarms are explicitly marked optional because their Terraform defaults are off or blank.

The repository contains optional SQS code paths but no SQS Terraform resource, so SQS is not shown.
It also does not provision Cognito, S3, CloudFront, WAF, SNS, or an AWS CI/CD service. The existing
Mermaid diagram in [`architecture.md`](architecture.md) remains a simpler logical-flow companion;
the generated AWS-icon diagram is the primary visual.

## Render the diagram

Graphviz provides the `dot` executable used by the Python package:

```bash
# macOS
brew install graphviz

# Ubuntu/Debian
sudo apt-get install graphviz
```

From the repository root, install the diagram dependency and render both outputs:

```bash
python3 -m pip install -r docs/requirements.txt
python3 docs/architecture_aws.py
```

The command writes `docs/architecture_aws.png` and a self-contained
`docs/architecture_aws.svg` with its service icons embedded.
