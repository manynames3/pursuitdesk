# Architecture Decision Records

These ADRs document the main architectural choices behind PursuitDesk.

- [ADR 0001: Use Cloudflare Pages And AWS Serverless For The Public Demo](0001-cloudflare-pages-aws-serverless.md)
- [ADR 0002: Use PostgreSQL With pgvector As The Primary Data Store](0002-postgres-pgvector-primary-store.md)
- [ADR 0003: Use Public Lambda Networking For Ingestion To Avoid NAT](0003-no-nat-ingestion-split.md)
- [ADR 0004: Run Proposal Writer As Async Jobs With DynamoDB TTL](0004-async-proposal-writer-jobs.md)
- [ADR 0005: Keep Demo Header Auth Separate From JWT Production Auth](0005-demo-header-auth-jwt-production.md)
