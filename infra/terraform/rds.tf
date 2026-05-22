resource "random_password" "db_master" {
  length  = 24
  special = false
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = var.postgres_engine_version

  # Free-tier eligible for Amazon RDS PostgreSQL Single-AZ in qualifying accounts
  # and small enough for demo traffic. No Aurora capacity floor is provisioned.
  instance_class = "db.t4g.micro"
  multi_az       = false

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_master.result

  # RDS free tier includes 20 GB of general purpose SSD storage. Autoscaling is
  # explicitly disabled so the demo cannot silently grow into billable storage.
  allocated_storage     = 20
  max_allocated_storage = 0
  storage_type          = "gp2"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # The DB sits in subnets that have an internet gateway route, but RDS receives
  # no public endpoint. Only the Lambda SG rule above can reach port 5432.
  publicly_accessible = false

  # Disable idle flat-rate add-ons. CloudWatch log exports, Performance Insights,
  # Enhanced Monitoring, read replicas, RDS Proxy, and Aurora are intentionally absent.
  performance_insights_enabled    = false
  monitoring_interval             = 0
  enabled_cloudwatch_logs_exports = []

  # A short retention window keeps demo recovery possible without building up
  # long-lived snapshots. Final snapshots are skipped to avoid teardown costs.
  backup_retention_period  = 1
  backup_window            = "08:00-08:30"
  maintenance_window       = "sun:09:00-sun:09:30"
  copy_tags_to_snapshot    = false
  skip_final_snapshot      = true
  delete_automated_backups = true
  deletion_protection      = false

  auto_minor_version_upgrade = true
  apply_immediately          = true

  tags = {
    Name        = "${local.name_prefix}-postgres"
    VectorStore = "pgvector"
  }
}
