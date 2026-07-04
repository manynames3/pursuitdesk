# Tradeoffs

## Low Cost Over Fully Managed Enterprise Stack

The demo avoids NAT Gateway, OpenSearch, Aurora, RDS Proxy, provisioned concurrency, and long log retention. This keeps idle cost low but means the stack has fewer managed scaling and observability conveniences.

## PostgreSQL Plus pgvector Over Separate Search Stores

PostgreSQL handles relational state, JSONB evidence, text search, and vector matching. This is simpler and cheaper for the project stage. A larger production workload may need a dedicated search or analytics store.

## Demo Header Auth Over Mandatory Login

The public demo is easy to evaluate because it does not require account creation. The cost is that it is not production authentication. JWT and API Gateway authorizer paths exist and must be enabled before paid use.

## Client-Side PDF/DOCX Exports

Exports are generated from saved draft text in the browser. This avoids object storage and binary retention decisions, but it limits server-side auditability of generated files.

## AI Drafting With Deterministic Guardrails

Bedrock improves proposal drafting, but output must remain advisory. The app uses structured prompts, source notes, quality checks, fallback models, and deterministic drafts, but a consultant still needs to validate solicitation requirements and claims.

## Manual Backend Deploy Over Full AWS CD

Frontend deployment can run through GitHub Actions. Backend deployment is documented as build packages plus Terraform apply. This is adequate for a work sample and demo, but production should add a gated backend deployment workflow with environment approvals.
