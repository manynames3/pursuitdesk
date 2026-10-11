locals {
  lambda_base_environment = {
    AWS_USE_DUALSTACK_ENDPOINT   = "true"
    APP_PUBLIC_URL               = var.app_public_url
    BEDROCK_EMBEDDING_MODEL_ID   = var.bedrock_embedding_model_id
    AUTH_REQUIRED                = tostring(var.auth_required)
    BEDROCK_MODEL_ID             = var.bedrock_model_id
    DATABASE_HOST                = var.database_host
    DATABASE_NAME                = var.database_name
    DATABASE_PASSWORD            = var.database_password
    DATABASE_PORT                = tostring(var.database_port)
    DATABASE_URL                 = var.database_url
    DATABASE_USER                = var.database_user
    PGVECTOR_SCHEMA              = "capture"
    PROPOSAL_JOBS_TABLE          = aws_dynamodb_table.proposal_writer_jobs.name
    PROPOSAL_JOB_TTL_SECONDS     = tostring(var.proposal_job_ttl_seconds)
    JWT_AUDIENCE                 = var.jwt_audience
    JWT_ISSUER                   = var.jwt_issuer
    JWT_JWKS_URL                 = var.jwt_jwks_url
    JWT_ROLE_CLAIM               = var.jwt_role_claim
    JWT_TENANT_CLAIM             = var.jwt_tenant_claim
    SAM_API_KEY_SECRET_ARN       = var.sam_api_key_secret_arn
    STRIPE_API_KEY_SECRET_ARN    = var.stripe_api_key_secret_arn
    STRIPE_PRICE_ID              = var.stripe_price_id
    STRIPE_WEBHOOK_SECRET_ARN    = var.stripe_webhook_secret_arn
    PROPOSAL_ESCALATION_MODEL_ID = var.proposal_escalation_model_id
    PROPOSAL_FALLBACK_MODEL_ID   = var.proposal_fallback_model_id
    PROPOSAL_HELPER_MODEL_ID     = var.proposal_helper_model_id
    PROPOSAL_WRITER_MODEL_ID     = var.proposal_writer_model_id
    PROPOSAL_WRITER_PROVIDER     = var.proposal_writer_provider
    SAM_EMBEDDING_PROVIDER       = var.sam_embedding_provider
    VECTOR_STORE                 = "pgvector"
  }

  lambda_runtime_config = {
    for name, fn in var.lambda_functions : name => {
      function_name        = "${local.name_prefix}-${name}"
      package_path         = fn.package_path
      source_code_hash     = fn.source_code_hash != null ? fn.source_code_hash : try(filebase64sha256(fn.package_path), null)
      handler              = fn.handler
      runtime              = fn.runtime
      memory_size          = fn.memory_size
      timeout              = fn.timeout
      reserved_concurrency = fn.reserved_concurrency
      vpc_enabled          = fn.vpc_enabled
      environment          = merge(local.lambda_base_environment, fn.environment)
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.lambda_runtime_config

  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = var.lambda_log_retention_days

  tags = {
    Name = "${each.value.function_name}-logs"
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${local.name_prefix}-lambda-exec"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  count = local.create_lambda_vpc ? 1 : 0

  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_runtime" {
  name = "${local.name_prefix}-lambda-runtime"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "InvokeBedrockModels"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      },
      {
        Sid    = "InvokeCaptureOsLambdas"
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-upsert",
          "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-awards_upsert",
          "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-subawards_upsert",
          "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-calc_upsert",
          "arn:aws:lambda:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-proposal_writer"
        ]
      },
      {
        Sid    = "ReadWriteProposalWriterJobs"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.proposal_writer_jobs.arn,
          "${aws_dynamodb_table.proposal_writer_jobs.arn}/index/*"
        ]
      }
      ],
      length(compact([var.sam_api_key_secret_arn, var.stripe_api_key_secret_arn, var.stripe_webhook_secret_arn])) > 0 ? [
        {
          Sid    = "ReadConfiguredSecrets"
          Effect = "Allow"
          Action = [
            "secretsmanager:GetSecretValue"
          ]
          Resource = compact([
            var.sam_api_key_secret_arn,
            var.stripe_api_key_secret_arn,
            var.stripe_webhook_secret_arn
          ])
        }
    ] : [])
  })
}

resource "aws_lambda_function" "backend" {
  for_each = local.lambda_runtime_config

  function_name = each.value.function_name
  description   = "GovCon CaptureOS ${each.key} Lambda for the low-cost demo stack."
  role          = aws_iam_role.lambda_exec.arn
  handler       = each.value.handler
  runtime       = each.value.runtime
  architectures = ["arm64"]

  filename         = each.value.package_path
  source_code_hash = each.value.source_code_hash
  layers           = var.lambda_layer_arns

  # 128/256 MB keeps compute cost low under per-millisecond billing. No
  # provisioned concurrency is declared, and request volume is capped at HTTP API.
  memory_size = each.value.memory_size
  timeout     = each.value.timeout

  reserved_concurrent_executions = each.value.reserved_concurrency

  # Neon-backed functions default to public Lambda networking so they can reach
  # external PostgreSQL, AWS APIs, and public data APIs without NAT Gateway cost.
  # vpc_enabled remains available for future private integrations.
  dynamic "vpc_config" {
    for_each = each.value.vpc_enabled ? [1] : []
    content {
      subnet_ids                  = aws_subnet.public[*].id
      security_group_ids          = aws_security_group.lambda[*].id
      ipv6_allowed_for_dual_stack = true
    }
  }

  environment {
    variables = each.value.environment
  }

  # X-Ray active tracing is useful later, but it adds metered telemetry cost.
  tracing_config {
    mode = "PassThrough"
  }

  ephemeral_storage {
    size = 512
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_runtime,
    aws_iam_role_policy_attachment.lambda_basic_logs,
    aws_iam_role_policy_attachment.lambda_vpc_access
  ]

  tags = {
    Name = each.value.function_name
  }
}
