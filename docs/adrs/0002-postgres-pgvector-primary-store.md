# ADR 0002: Use PostgreSQL With pgvector As The Primary Data Store

## Status

Accepted

## Context

The app needs relational tenant data, opportunity records, workflow state, evidence, audit-style operational tables, and semantic matching over SOW text. A separate search/vector system would add cost and operational complexity for the demo and early paid-MVP stage.

## Decision

Use Amazon RDS PostgreSQL 15 as the primary store with the `capture` schema, JSONB source payloads, generated text-search columns, `pg_trgm`, and `pgvector` HNSW indexes for SOW embeddings.

## Consequences

- Relational records, source evidence, and vector similarity stay in one database.
- The team avoids OpenSearch, a separate vector database, and extra sync pipelines.
- RDS is not serverless, so the instance class and storage are intentionally small.
- Heavier search workloads may require a later dedicated search or analytics store.
