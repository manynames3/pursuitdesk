# ADR 0005: Keep Demo Header Auth Separate From JWT Production Auth

## Status

Accepted

## Context

The public demo needs to be usable without account setup, but the backend is designed around tenant-aware access and role-scoped workflows. Paid production use requires verifiable identity, tenant claims, and stronger enforcement.

## Decision

Keep demo header context (`x-captureos-tenant` and `x-captureos-user`) enabled while `auth_required` is false. Implement JWT/JWKS validation in the API Lambda and optional API Gateway JWT authorizer switches for production.

## Consequences

- Recruiters and evaluators can exercise the public demo without provisioning accounts.
- Production auth can be enabled through Terraform variables without rewriting route handlers.
- Demo headers must not be treated as production security.
- Before charging customers, the API should enforce JWT tenant claims and remove reliance on public demo headers.
