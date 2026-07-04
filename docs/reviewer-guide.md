# Reviewer Guide

This guide is for a busy technical reviewer who wants to understand what PursuitDesk proves without reading every file.

## What To Look At First

1. `README.md` for the product summary, stack, evidence matrix, validation commands, limitations, and hardening switches.
2. `docs/architecture.md` and `docs/architecture-notes.md` for the runtime model, C4-style diagram, AWS diagram evidence, and exclusions.
3. `infra/terraform/` for the AWS shape: API Gateway HTTP API, Lambda, RDS PostgreSQL, DynamoDB proposal jobs, IAM, EventBridge schedules, and optional alarms.
4. `src/api_v1_endpoints.py`, `src/proposal_writer_lambda.py`, and `src/auth.py` for backend workflow, async proposal jobs, Bedrock routing, and JWT/demo-auth separation.
5. `frontend/` for the consultant workspace, pipeline, decision room, background proposal notifications, proposal history, and client-side PDF/DOCX exports.

## What This Project Proves

- Can design and ship a low-idle-cost AWS serverless application.
- Can model a real business workflow rather than only displaying data.
- Can wire live public data sources into tenant-aware scoring and evidence surfaces.
- Can use Bedrock models pragmatically: Nova Lite for cheaper helper tasks, Claude Haiku for faster drafts, Claude Sonnet escalation for quality, and deterministic fallbacks.
- Can document tradeoffs, security boundaries, cost controls, observability, deployment, teardown, and known gaps honestly.

## Strongest Engineering Decisions

- Static frontend on Cloudflare Pages plus API Gateway HTTP API and Lambda keeps the public demo inexpensive.
- RDS PostgreSQL with `pgvector` keeps relational workflow state, source evidence, search, and semantic matching in one store.
- Public ingest Lambdas call public APIs outside the VPC, then invoke private upsert Lambdas that write to RDS, avoiding NAT Gateway cost.
- Proposal Writer runs as async DynamoDB-backed jobs so slow Bedrock calls do not block the user.
- Demo header auth is explicitly separated from JWT-ready production auth.

## Demo-Only Or Incomplete

- The public demo does not enforce production authentication.
- Stripe billing plumbing exists, but production billing is not activated.
- Some client profiles, past performance, reminders, and workflow examples are seeded or imported baseline data.
- Source document/SOW extraction exists as an improvement path; proposal drafts still require human validation against solicitation documents.
- Test coverage is currently validation-heavy, not a full unit/integration/e2e suite.

## How To Inspect Or Run

Use the validation commands in `README.md` and `docs/testing.md`. For live inspection, open the public demo and use the demo client profiles; API smoke examples are documented in `docs/runbook.md`.
