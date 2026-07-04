# Security Model

## Current Public Demo

The public demo uses demo tenant headers so reviewers can exercise the workspace without account setup. This is intentionally not production authentication.

Headers preserved for demo mode:

- `x-captureos-tenant`
- `x-captureos-user`

## Production Auth Path

The API supports JWT/JWKS validation through `src/auth.py` and Terraform variables:

- `auth_required`
- `jwt_issuer`
- `jwt_audience`
- `jwt_jwks_url`
- `enable_api_gateway_jwt_authorizer`
- tenant and role claim names

Before paid use, enable JWT enforcement and remove reliance on public demo headers for tenant selection.

## Network Boundaries

- RDS PostgreSQL is not publicly accessible.
- RDS accepts PostgreSQL only from the Lambda security group.
- VPC-attached API/upsert functions can reach RDS.
- Public ingestion fetchers run outside the VPC for managed Lambda internet egress and invoke private upsert functions.
- No NAT Gateway is provisioned.

## Secrets

Secrets are passed by ARN and read from AWS Secrets Manager when configured:

- SAM.gov API key
- Stripe API key
- Stripe webhook secret

Do not commit `.tfvars`, Terraform state, `.env`, API keys, generated PDFs, or downloaded customer material.

## IAM Approach

The shared Lambda runtime role has scoped permissions for:

- CloudWatch logs through AWS managed Lambda logging policies.
- Invoking in-stack upsert and proposal-writer Lambda functions.
- Reading/writing the DynamoDB Proposal Writer jobs table.
- Reading only configured Secrets Manager ARNs.
- Invoking Bedrock models.

This is appropriate for a demo stack, but a production rollout should split roles by function family for smaller blast radius.

## Audit And Compliance

Workflow mutations are recorded in database audit-style tables, and the UI exposes compliance/control posture. This is not a formal compliance certification.
