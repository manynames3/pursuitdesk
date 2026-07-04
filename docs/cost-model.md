# Cost Model

PursuitDesk is designed to stay inexpensive while still demonstrating production-style cloud architecture.

## Cost Controls

- Cloudflare Pages static frontend.
- API Gateway v2 HTTP API instead of REST API.
- ARM64 Lambda functions with 128 MB or 256 MB memory.
- No provisioned concurrency.
- Single-AZ `db.t4g.micro` RDS PostgreSQL with fixed storage.
- DynamoDB on-demand table for proposal jobs with TTL.
- EventBridge schedules are optional and bounded by page/record limits.
- Short CloudWatch log retention.
- No NAT Gateway.
- No OpenSearch.
- No Aurora Serverless.
- No RDS Proxy.
- No X-Ray active tracing by default.

## Intentional Tradeoff

The stack pays for a small RDS instance to keep relational state, source evidence, and pgvector matching in one database. That is simpler and more credible for this domain than stitching together separate vector/search stores for the demo.

## Cost Risks To Watch

- Bedrock proposal jobs can dominate variable cost if prompts, retries, or draft lengths are not bounded.
- RDS is fixed-cost while running.
- CloudWatch logs can grow if retention is increased or verbose logs are enabled.
- Scheduled ingestion should stay bounded and monitored.
