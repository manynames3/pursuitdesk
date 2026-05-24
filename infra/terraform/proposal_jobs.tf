resource "aws_dynamodb_table" "proposal_writer_jobs" {
  name         = "${local.name_prefix}-proposal-writer-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "tenant_slug"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "tenant-created-at-index"
    hash_key        = "tenant_slug"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Name = "${local.name_prefix}-proposal-writer-jobs"
  }
}
