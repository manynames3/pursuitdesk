# ADR 0004: Run Proposal Writer As Async Jobs With DynamoDB TTL

## Status

Accepted

## Context

Proposal drafting can exceed normal HTTP response expectations because it may run Section L/M extraction, source summarization, Bedrock model calls, fallback routing, and compliance post-processing. Users also need proposal history per client and opportunity.

## Decision

Use a dedicated non-VPC Proposal Writer Lambda for Bedrock access. Store job state, draft text, status, errors, timestamps, and tenant/opportunity indexes in an on-demand DynamoDB table with TTL. The frontend submits jobs, polls job endpoints, and renders saved proposal history.

## Consequences

- Long proposal generation does not block the main API Lambda request path.
- DynamoDB on-demand plus TTL keeps history lightweight and bounded.
- Draft text is persisted, but generated PDF/DOCX binaries are created client-side and not stored.
- Job polling adds frontend complexity and requires tenant-aware job filtering.
