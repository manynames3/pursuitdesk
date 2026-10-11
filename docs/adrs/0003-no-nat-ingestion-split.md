# ADR 0003: Use Public Lambda Networking For Ingestion To Avoid NAT

## Status

Accepted

## Context

The system ingests public procurement data from SAM.gov, USAspending/FSRS, and GSA CALC+. The database is now externalized to Neon Postgres, and a NAT Gateway would add fixed monthly cost that is disproportionate for a public demo.

## Decision

Run public API fetches and database upserts in non-VPC Lambda functions with managed internet egress. Fetch Lambdas may still invoke upsert/enrichment Lambdas for batching and separation of concerns, but the upsert functions write to Neon over the external PostgreSQL connection string. Use EventBridge Scheduler for bounded recurring runs.

## Consequences

- The AWS stack avoids NAT Gateway and Lambda ENI overhead.
- Ingestion code has a clear separation between external fetch and internal persistence.
- Some operations require Lambda-to-Lambda invocation and explicit payload sizing/batching.
- Neon credentials must be supplied through ignored tfvars or secret-management workflows, never committed to Terraform source.
