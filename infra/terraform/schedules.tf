locals {
  scheduler_enabled = var.enable_gsa_ingest_schedule || var.enable_sam_enrichment_schedule || var.enable_usaspending_awards_schedule || var.enable_usaspending_subawards_schedule || var.enable_gsa_calc_schedule
}

resource "aws_iam_role" "scheduler_invoke_lambda" {
  count = local.scheduler_enabled ? 1 : 0

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
  count = local.scheduler_enabled ? 1 : 0

  name = "${local.name_prefix}-scheduler-invoke-lambda"
  role = aws_iam_role.scheduler_invoke_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = compact([
          var.enable_gsa_ingest_schedule ? aws_lambda_function.backend["ingest"].arn : "",
          var.enable_sam_enrichment_schedule ? aws_lambda_function.backend["upsert"].arn : "",
          var.enable_usaspending_awards_schedule ? aws_lambda_function.backend["awards_ingest"].arn : "",
          var.enable_usaspending_subawards_schedule ? aws_lambda_function.backend["subawards_ingest"].arn : "",
          var.enable_gsa_calc_schedule ? aws_lambda_function.backend["calc_ingest"].arn : ""
        ])
      }
    ]
  })
}

resource "aws_scheduler_schedule" "sam_opportunities_enrichment" {
  count = var.enable_sam_enrichment_schedule ? 1 : 0

  name        = "${local.name_prefix}-sam-opportunities-enrichment"
  description = "Low-cost scheduled SAM.gov opportunity SOW extraction and pgvector enrichment for CaptureOS."
  group_name  = "default"

  schedule_expression          = var.sam_enrichment_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 15
  }

  target {
    arn      = aws_lambda_function.backend["upsert"].arn
    role_arn = aws_iam_role.scheduler_invoke_lambda[0].arn
    input = jsonencode({
      source                    = "aws.scheduler"
      dataset                   = "sam_opportunity_enrichment"
      mode                      = "enrich_sam_opportunity_embeddings"
      limit                     = var.sam_enrichment_batch_limit
      fetch_documents           = var.sam_enrichment_fetch_documents
      documents_per_opportunity = 1
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 1
    }
  }
}

resource "aws_scheduler_schedule" "usaspending_awards_ingest" {
  count = var.enable_usaspending_awards_schedule ? 1 : 0

  name        = "${local.name_prefix}-usaspending-awards-ingest"
  description = "Low-cost scheduled USAspending contract award ingestion for CaptureOS incumbent and recompete signals."
  group_name  = "default"

  schedule_expression          = var.usaspending_awards_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30
  }

  target {
    arn      = aws_lambda_function.backend["awards_ingest"].arn
    role_arn = aws_iam_role.scheduler_invoke_lambda[0].arn
    input = jsonencode({
      source             = "aws.scheduler"
      dataset            = "usaspending_contract_awards"
      lookback_days      = var.usaspending_awards_lookback_days
      max_pages          = var.usaspending_awards_max_pages
      upsert_lambda_name = aws_lambda_function.backend["awards_upsert"].function_name
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 1
    }
  }
}

resource "aws_scheduler_schedule" "usaspending_subawards_ingest" {
  count = var.enable_usaspending_subawards_schedule ? 1 : 0

  name        = "${local.name_prefix}-usaspending-subawards-ingest"
  description = "Low-cost scheduled FSRS-derived subaward ingestion through USAspending for CaptureOS partner and supply-chain signals."
  group_name  = "default"

  schedule_expression          = var.usaspending_subawards_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30
  }

  target {
    arn      = aws_lambda_function.backend["subawards_ingest"].arn
    role_arn = aws_iam_role.scheduler_invoke_lambda[0].arn
    input = jsonencode({
      source             = "aws.scheduler"
      dataset            = "fsrs_subawards"
      lookback_days      = var.usaspending_subawards_lookback_days
      max_pages          = var.usaspending_subawards_max_pages
      upsert_lambda_name = aws_lambda_function.backend["subawards_upsert"].function_name
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 1
    }
  }
}

resource "aws_scheduler_schedule" "gsa_calc_ingest" {
  count = var.enable_gsa_calc_schedule ? 1 : 0

  name        = "${local.name_prefix}-gsa-calc-ingest"
  description = "Low-cost scheduled GSA CALC+ labor ceiling-rate benchmark ingestion for CaptureOS pricing support."
  group_name  = "default"

  schedule_expression          = var.gsa_calc_schedule_expression
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30
  }

  target {
    arn      = aws_lambda_function.backend["calc_ingest"].arn
    role_arn = aws_iam_role.scheduler_invoke_lambda[0].arn
    input = jsonencode({
      source             = "aws.scheduler"
      dataset            = "gsa_calc_labor_rates"
      keywords           = var.gsa_calc_keywords
      max_pages          = var.gsa_calc_max_pages
      page_size          = var.gsa_calc_page_size
      upsert_lambda_name = aws_lambda_function.backend["calc_upsert"].function_name
    })

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 1
    }
  }
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
      source             = "aws.scheduler"
      dataset            = "sam_opportunities"
      lookback_days      = var.gsa_ingest_lookback_days
      max_pages          = var.gsa_ingest_max_pages
      ptype              = ["o", "k", "p", "r"]
      status             = "active"
      direct_db_upsert   = false
      upsert_lambda_name = aws_lambda_function.backend["upsert"].function_name
      upsert_chunk_size  = 100
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
