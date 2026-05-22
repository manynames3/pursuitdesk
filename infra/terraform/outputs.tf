output "http_api_endpoint" {
  description = "API Gateway v2 HTTP API invoke URL for the demo dashboard backend."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "rds_endpoint" {
  description = "Private RDS PostgreSQL endpoint reachable from Lambda security group only."
  value       = aws_db_instance.postgres.address
}

output "rds_port" {
  description = "PostgreSQL listener port."
  value       = aws_db_instance.postgres.port
}

output "lambda_security_group_id" {
  description = "Security group attached to all backend Lambda functions."
  value       = aws_security_group.lambda.id
}

output "rds_security_group_id" {
  description = "Security group restricting RDS ingress to Lambda only."
  value       = aws_security_group.rds.id
}

output "lambda_function_names" {
  description = "Provisioned backend Lambda functions."
  value       = { for name, fn in aws_lambda_function.backend : name => fn.function_name }
}
