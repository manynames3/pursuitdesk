resource "aws_dynamodb_table" "proposal_writer_jobs" {
  name         = "${local.name_prefix}-proposal-writer-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "${local.name_prefix}-proposal-writer-jobs"
  }
}
