# ADR 0003: Split Public Ingestion From Private Upsert To Avoid NAT

## Status

Accepted

## Context

The system ingests public procurement data from SAM.gov, USAspending/FSRS, and GSA CALC+. The database should stay private, but a NAT Gateway would add fixed monthly cost that is disproportionate for a public demo.

## Decision

Run public API fetches in non-VPC Lambda functions with managed internet egress. Have those functions invoke VPC-attached upsert/enrichment Lambdas that can write to private RDS. Use EventBridge Scheduler for bounded recurring runs.

## Consequences

- The database stays private without paying for NAT Gateway.
- Ingestion code has a clear separation between external fetch and internal persistence.
- Some operations require Lambda-to-Lambda invocation and explicit payload sizing/batching.
- VPC-attached functions still need careful egress choices for any external calls.
