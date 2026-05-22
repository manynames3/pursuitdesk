#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform"
SECRET_NAME="${SAM_SECRET_NAME:-govcon-captureos-demo-sam-api-key}"
AWS_REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
SCHEDULE_EXPRESSION="${GSA_INGEST_SCHEDULE_EXPRESSION:-rate(6 hours)}"
LOOKBACK_DAYS="${GSA_INGEST_LOOKBACK_DAYS:-1}"
MAX_PAGES="${GSA_INGEST_MAX_PAGES:-2}"
BACKFILL_DAYS="${GSA_BACKFILL_DAYS:-30}"
BACKFILL_MAX_PAGES="${GSA_BACKFILL_MAX_PAGES:-10}"

if [[ -z "${SAM_API_KEY:-}" && -t 0 ]]; then
  printf "SAM.gov API key: " >&2
  stty -echo
  IFS= read -r SAM_API_KEY
  stty echo
  printf "\n" >&2
  export SAM_API_KEY
fi

if [[ -z "${SAM_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
SAM_API_KEY is required.

Run the script from an interactive terminal and paste your key at the prompt, or export it first:
  export SAM_API_KEY='...'

The key will be stored in AWS Secrets Manager and will not be written to Terraform state.
EOF
  exit 64
fi

SECRET_PAYLOAD="$(python3 -c 'import json, os; print(json.dumps({"SAM_API_KEY": os.environ["SAM_API_KEY"]}))')"

if aws secretsmanager describe-secret --region "$AWS_REGION" --secret-id "$SECRET_NAME" >/tmp/captureos-sam-secret.json 2>/dev/null; then
  SECRET_ARN="$(python3 - <<'PY'
import json
with open('/tmp/captureos-sam-secret.json', 'r', encoding='utf-8') as handle:
    print(json.load(handle)['ARN'])
PY
)"
  aws secretsmanager put-secret-value \
    --region "$AWS_REGION" \
    --secret-id "$SECRET_NAME" \
    --secret-string "$SECRET_PAYLOAD" >/dev/null
else
  SECRET_ARN="$(aws secretsmanager create-secret \
    --region "$AWS_REGION" \
    --name "$SECRET_NAME" \
    --description "SAM.gov public API key for GovCon CaptureOS live opportunity ingestion." \
    --secret-string "$SECRET_PAYLOAD" \
    --query ARN \
    --output text)"
fi

cat >"$TF_DIR/live_ingest.auto.tfvars" <<EOF
sam_api_key_secret_arn = "$SECRET_ARN"
enable_gsa_ingest_schedule = true
gsa_ingest_schedule_expression = "$SCHEDULE_EXPRESSION"
gsa_ingest_lookback_days = $LOOKBACK_DAYS
gsa_ingest_max_pages = $MAX_PAGES
EOF

terraform -chdir="$TF_DIR" apply -auto-approve

INGEST_FUNCTION="$(terraform -chdir="$TF_DIR" output -json lambda_function_names | python3 -c 'import json, sys; print(json.load(sys.stdin)["ingest"])')"

cat >/tmp/captureos-sam-backfill-event.json <<EOF
{
  "source": "manual.backfill",
  "dataset": "sam_opportunities",
  "lookback_days": $BACKFILL_DAYS,
  "max_pages": $BACKFILL_MAX_PAGES,
  "ptype": ["o", "k", "p", "r"],
  "status": "active",
  "direct_db_upsert": true
}
EOF

aws lambda invoke \
  --region "$AWS_REGION" \
  --function-name "$INGEST_FUNCTION" \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/captureos-sam-backfill-event.json \
  /tmp/captureos-sam-backfill-response.json >/dev/null

cat /tmp/captureos-sam-backfill-response.json
printf '\nLive SAM.gov ingestion is enabled. Secret ARN is stored in %s/live_ingest.auto.tfvars.\n' "$TF_DIR"
