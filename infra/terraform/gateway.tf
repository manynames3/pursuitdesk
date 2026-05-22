resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name_prefix}-http-api"
  protocol_type = "HTTP"

  # HTTP API is the lower-cost API Gateway v2 product. No REST API, REST cache,
  # VPC Link, private API, or PrivateLink endpoint is created.
  cors_configuration {
    allow_credentials = false
    allow_headers     = ["authorization", "content-type", "x-request-id", "x-captureos-tenant", "x-captureos-user"]
    allow_methods     = ["GET", "POST", "OPTIONS"]
    allow_origins     = var.api_cors_allowed_origins
    max_age           = 300
  }

  tags = {
    Name = "${local.name_prefix}-http-api"
  }
}

resource "aws_apigatewayv2_integration" "lambda_proxy" {
  api_id = aws_apigatewayv2_api.http.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.backend["api"].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  count = var.enable_api_gateway_jwt_authorizer ? 1 : 0

  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.name_prefix}-jwt"

  jwt_configuration {
    audience = [var.jwt_audience]
    issuer   = var.jwt_issuer
  }

  lifecycle {
    precondition {
      condition     = var.jwt_issuer != "" && var.jwt_audience != ""
      error_message = "enable_api_gateway_jwt_authorizer requires jwt_issuer and jwt_audience."
    }
  }
}

resource "aws_apigatewayv2_route" "root" {
  api_id = aws_apigatewayv2_api.http.id

  route_key          = "ANY /"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
  authorization_type = var.enable_api_gateway_jwt_authorizer ? "JWT" : "NONE"
  authorizer_id      = var.enable_api_gateway_jwt_authorizer ? aws_apigatewayv2_authorizer.jwt[0].id : null
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id = aws_apigatewayv2_api.http.id

  route_key          = "ANY /{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
  authorization_type = var.enable_api_gateway_jwt_authorizer ? "JWT" : "NONE"
  authorizer_id      = var.enable_api_gateway_jwt_authorizer ? aws_apigatewayv2_authorizer.jwt[0].id : null
}

resource "aws_apigatewayv2_route" "stripe_webhook" {
  api_id = aws_apigatewayv2_api.http.id

  route_key          = "POST /api/v1/billing/webhook"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_route" "health" {
  api_id = aws_apigatewayv2_api.http.id

  route_key          = "GET /api/v1/health"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id = aws_apigatewayv2_api.http.id
  name   = "$default"

  # Auto-deploy removes the need for a separate deployment resource and keeps
  # the demo stack consumption-only. Access logging is intentionally omitted to
  # avoid extra CloudWatch ingestion for low-value demo traffic.
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst_limit
    throttling_rate_limit  = var.api_throttle_rate_limit
  }

  tags = {
    Name = "${local.name_prefix}-default-stage"
  }
}

resource "aws_lambda_permission" "allow_http_api" {
  statement_id  = "AllowExecutionFromHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backend["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
