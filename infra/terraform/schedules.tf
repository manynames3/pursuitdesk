resource "aws_iam_role" "scheduler_invoke_lambda" {
  count = var.enable_gsa_ingest_schedule ? 1 : 0

  name = "${local.name_prefix}-scheduler-invoke"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name = "${local.name_prefix}-scheduler-invoke"
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  count = var.enable_gsa_ingest_schedule ? 1 : 0

  name = "${local.name_prefix}-scheduler-invoke-lambda"
  role = aws_iam_role.scheduler_invoke_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.backend["ingest"].arn
      }
    ]
  })
}

resource "aws_scheduler_schedule" "sam_opportunities_ingest" {
  count = var.enable_gsa_ingest_schedule ? 1 : 0

  name        = "${local.name_prefix}-sam-opportunities-ingest"
  description = "Low-cost scheduled SAM.gov opportunity ingestion for CaptureOS."
  group_name  = "default"

  schedule_expression          = var.gsa_ingest_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 15
  }

  target {
    arn      = aws_lambda_function.backend["ingest"].arn
    role_arn = aws_iam_role.scheduler_invoke_lambda[0].arn
    input = jsonencode({
      source           = "aws.scheduler"
      dataset          = "sam_opportunities"
      lookback_days    = var.gsa_ingest_lookback_days
      max_pages        = var.gsa_ingest_max_pages
      ptype            = ["o", "k", "p", "r"]
      status           = "active"
      direct_db_upsert = true
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  lifecycle {
    precondition {
      condition     = var.sam_api_key_secret_arn != ""
      error_message = "enable_gsa_ingest_schedule requires sam_api_key_secret_arn so the scheduled Lambda can call SAM.gov."
    }
  }
}
