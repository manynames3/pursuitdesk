locals {
  ingest_alarm_lambda_keys = toset([
    "ingest",
    "upsert",
    "awards_ingest",
    "awards_upsert",
    "subawards_ingest",
    "subawards_upsert",
    "calc_ingest",
    "calc_upsert"
  ])
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = var.enable_cloudwatch_alarms ? local.lambda_runtime_config : {}

  alarm_name          = "${each.value.function_name}-errors"
  alarm_description   = "CaptureOS Lambda ${each.key} reported at least one error in 5 minutes."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.backend[each.key].function_name
  }

  tags = {
    Name = "${each.value.function_name}-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "ingest_lambda_errors" {
  for_each = var.enable_ingest_failure_alarms ? {
    for key, config in local.lambda_runtime_config : key => config
    if contains(tolist(local.ingest_alarm_lambda_keys), key)
  } : {}

  alarm_name          = "${each.value.function_name}-ingest-errors"
  alarm_description   = "CaptureOS ingest Lambda ${each.key} reported at least one error in 5 minutes."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.cloudwatch_alarm_actions
  ok_actions          = var.cloudwatch_alarm_actions

  dimensions = {
    FunctionName = aws_lambda_function.backend[each.key].function_name
  }

  tags = {
    Name = "${each.value.function_name}-ingest-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "api_gateway_5xx" {
  count = var.enable_cloudwatch_alarms ? 1 : 0

  alarm_name          = "${local.name_prefix}-http-api-5xx"
  alarm_description   = "CaptureOS HTTP API returned 5xx responses."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiId = aws_apigatewayv2_api.http.id
    Stage = aws_apigatewayv2_stage.default.name
  }

  tags = {
    Name = "${local.name_prefix}-http-api-5xx"
  }
}
