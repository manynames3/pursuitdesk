# Observability

## Implemented

- CloudWatch log groups are created for each Lambda.
- Default log retention is seven days to limit storage cost.
- Optional Lambda error alarms and API Gateway 5xx alarms are defined in Terraform.
- Ingest watermarks and freshness rows are surfaced in the application.
- The workspace includes monitoring/alert cards for live source health.
- Proposal Writer jobs persist status, timestamps, and error messages in DynamoDB.

## Operational Checks

- Review Lambda logs for API, ingest, upsert, and Proposal Writer failures.
- Review API Gateway metrics for 5xx responses.
- Check source freshness rows when live opportunity counts look stale.
- Check DynamoDB job records when proposal generation appears stuck.

## Not Yet Implemented

- X-Ray active tracing is intentionally disabled to avoid demo telemetry cost.
- No centralized dashboard JSON is committed.
- No synthetic browser monitor is configured.
- No pager or incident routing target is configured; alarm actions are optional Terraform input.
