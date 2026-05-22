data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "demo" {
  cidr_block                       = var.vpc_cidr
  assign_generated_ipv6_cidr_block = true
  enable_dns_hostnames             = true
  enable_dns_support               = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_egress_only_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = {
    Name = "${local.name_prefix}-eigw"
  }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                          = aws_vpc.demo.id
  availability_zone               = data.aws_availability_zones.available.names[count.index]
  cidr_block                      = var.public_subnet_cidrs[count.index]
  ipv6_cidr_block                 = cidrsubnet(aws_vpc.demo.ipv6_cidr_block, 8, count.index)
  assign_ipv6_address_on_creation = true

  # Public IPv4 addresses now carry a direct hourly charge. The subnet is public
  # by route table, but launched resources do not auto-receive public IPv4s.
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-public-${count.index + 1}"
    Tier = "public-no-nat"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.demo.id

  # IPv4 public routing is available for resources that explicitly need it, but
  # no NAT Gateway or Elastic IP is created anywhere in this stack.
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }

  # VPC-attached Lambda functions do not receive public IPv4s. Dual-stack IPv6
  # egress keeps outbound HTTPS possible without a NAT Gateway for IPv6-capable
  # targets such as Cloudflare and AWS dual-stack service endpoints.
  route {
    ipv6_cidr_block        = "::/0"
    egress_only_gateway_id = aws_egress_only_internet_gateway.demo.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-lambda-sg"
  description = "Low-cost demo Lambda SG: no inbound traffic, bounded outbound HTTPS and PostgreSQL."
  vpc_id      = aws_vpc.demo.id

  ingress = []

  egress {
    description = "Allow HTTPS egress; no NAT Gateway is provisioned for IPv4 internet routing."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description      = "Allow no-NAT HTTPS egress over IPv6 from dual-stack Lambda subnets."
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow Lambda functions to reach the private RDS endpoint only inside the demo VPC."
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${local.name_prefix}-lambda-sg"
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS PostgreSQL accepts 5432 only from the backend Lambda security group."
  vpc_id      = aws_vpc.demo.id

  ingress {
    description     = "PostgreSQL ingress is restricted to Lambda ENIs by security group ID."
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress = []

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

resource "aws_db_subnet_group" "postgres" {
  name       = "${local.name_prefix}-postgres-subnets"
  subnet_ids = [for subnet in aws_subnet.public : subnet.id]

  tags = {
    Name = "${local.name_prefix}-postgres-subnets"
  }
}
