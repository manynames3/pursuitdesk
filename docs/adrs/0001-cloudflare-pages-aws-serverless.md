# ADR 0001: Use Cloudflare Pages And AWS Serverless For The Public Demo

## Status

Accepted

## Context

PursuitDesk needs a public demo that is inexpensive to keep online, easy to deploy, and credible enough to show real workflows: client intake, opportunity review, capture analysis, proposal generation, and exports. The app does not need a long-running application server for the frontend or steady compute capacity for backend traffic.

## Decision

Serve the frontend as static assets on Cloudflare Pages. Expose backend routes through API Gateway v2 HTTP API and AWS Lambda functions packaged for Python 3.12 on ARM64.

## Consequences

- Idle cost stays low because frontend hosting is static and backend compute is request-driven.
- API Gateway HTTP API is cheaper and simpler than REST API for this routing model.
- Lambda packaging and cold-start behavior must be managed directly.
- Long-running operations need async patterns rather than blocking a request path.
