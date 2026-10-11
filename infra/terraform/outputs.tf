output "http_api_endpoint" {
  description = "API Gateway v2 HTTP API invoke URL for the demo dashboard backend."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "database_host" {
  description = "External PostgreSQL host configured for the Lambda functions."
  value       = var.database_host
}

output "database_port" {
  description = "External PostgreSQL listener port configured for the Lambda functions."
  value       = var.database_port
}

output "lambda_security_group_id" {
  description = "Security group attached to VPC-enabled Lambda functions, or null when all Lambdas use public networking."
  value       = try(aws_security_group.lambda[0].id, null)
}

output "lambda_function_names" {
  description = "Provisioned backend Lambda functions."
  value       = { for name, fn in aws_lambda_function.backend : name => fn.function_name }
}

output "lambda_vpc_enabled_functions" {
  description = "Lambda functions that opted into VPC networking."
  value       = keys(local.vpc_enabled_lambda_functions)
}
